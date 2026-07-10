from markupsafe import Markup
from odoo import models, fields, api, tools
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_round, float_is_zero


class ReemaWoBatchEntry(models.Model):
    _name = 'reema.wo.batch.entry'
    _description = 'Work Order Batch Progress Entry'
    _order = 'date desc'

    name = fields.Char(string='Reference', readonly=True, copy=False, default='New')
    workorder_id = fields.Many2one('mrp.workorder', string='Work Order',
                                   required=True, ondelete='cascade')
    reema_po_id = fields.Many2one('reema.production.order', string='Production Order',
                                  compute='_compute_reema_po_id', store=True)
    mo_id = fields.Many2one(related='workorder_id.production_id',
                            string='Manufacturing Order', store=True)
    process_name = fields.Char(related='workorder_id.name', string='Process', store=True)
    workforce_type = fields.Selection(
        related='workorder_id.workcenter_id.workforce_type', store=True, readonly=True
    )
    contractor_id = fields.Many2one('res.partner', string='Contractor',
                                    required=False, domain=[('supplier_rank', '>', 0)])
    date = fields.Datetime(string='Date', default=fields.Datetime.now, readonly=True)
    qty = fields.Float(string='Qty Completed', required=True)
    notes = fields.Char(string='Notes')
    sfg_move_id = fields.Many2one('stock.move', string='Stock Move', readonly=True)
    logged_by = fields.Many2one('res.users', string='Logged By',
                                default=lambda self: self.env.uid, readonly=True)
    qty_balls = fields.Float(string='Balls Equivalent', compute='_compute_qty_balls', store=True)
    piece_rate_id = fields.Many2one('reema.piece.rate', string='Piece Rate')
    piece_rate_value = fields.Float(related='piece_rate_id.rate', string='Rate (PKR)', digits=(10, 2))
    amount_earned = fields.Float(string='Amount (PKR)', compute='_compute_amount_earned', store=True, digits=(10, 2))
    is_billed = fields.Boolean(string='Billed', default=False, readonly=True, copy=False)
    bill_id = fields.Many2one('account.move', string='Bill', readonly=True, copy=False)
    payment_excluded = fields.Boolean(string='Excluded from Payment',
                                      default=False, readonly=True, copy=False)
    exclusion_reason = fields.Char(string='Exclusion Reason')
    original_contractor_id = fields.Many2one(
        'res.partner', string='Original Contractor',
        help='ILO-only: contractor who ultimately gets production credit/deduction. '
             'May differ from Contractor when this entry logs a repair return '
             'physically brought back by a different contractor.',
    )
    ilo_dispatch_type = fields.Selection(
        [('stitching', 'Stitching'), ('repair', 'Repair')],
        string='ILO Flow Type',
    )
    is_initial_qc_entry = fields.Boolean(compute='_compute_qc_summary')
    qc_received_qty = fields.Integer(
        string='Pending Inspection', compute='_compute_qc_summary',
        help='ILO Initial QC only: total balls ever logged in at Ball Receive for '
             'this contractor on this MO.',
    )
    qc_pass_qty = fields.Integer(
        string='Pass Qty', compute='_compute_qc_summary',
        help='ILO Initial QC only: total balls passed at Initial QC for this '
             'contractor on this MO, across all QC decisions.',
    )
    qc_repair_qty = fields.Integer(
        string='Fail Qty (Repair)', compute='_compute_qc_summary',
        help='ILO Initial QC only: total balls sent to repair for this contractor on this MO.',
    )
    qc_repair_defect_types = fields.Char(
        string='Repair Defect Type', compute='_compute_qc_summary',
        help='ILO Initial QC only: defect reason(s) recorded on the repair dispatch(es).',
    )
    qc_repair_contractor_ids = fields.Many2many(
        'res.partner', compute='_compute_qc_summary', string='Repair Contractor',
        help='ILO Initial QC only: who repair work for this contractor on this MO was issued to.',
    )
    qc_scrap_qty = fields.Integer(
        string='Scrap / Write-off Qty', compute='_compute_qc_summary',
        help='ILO Initial QC only: total balls scrapped for this contractor on this MO.',
    )
    qc_scrap_defect_types = fields.Char(
        string='Scrap / Write-off Reason', compute='_compute_qc_summary',
        help='ILO Initial QC only: defect reason(s) recorded on the scrap record(s).',
    )
    # Per-decision outcome — unlike qc_repair_qty/qc_scrap_qty above (running MO/
    # contractor totals, same figure repeated on every historical entry), these
    # are scoped to the exact repair dispatch / scrap record from the SAME
    # Initial QC wizard submission as this entry. Matched live at read time by
    # create_date (records created in the same action_confirm() call share the
    # same transaction timestamp down to the microsecond) plus contractor, OR
    # by the explicit batch_entry_id link the wizard now sets going forward —
    # no backfill/migration needed, this works for entries logged before that
    # link existed too since it's a plain search, not a stored value.
    entry_repair_qty = fields.Integer(string='Repair Qty (this entry)', compute='_compute_entry_qc_outcome')
    entry_repair_defect_types = fields.Char(string='Repair Reason (this entry)', compute='_compute_entry_qc_outcome')
    entry_scrap_qty = fields.Integer(string='Scrap Qty (this entry)', compute='_compute_entry_qc_outcome')
    entry_scrap_defect_types = fields.Char(string='Scrap Reason (this entry)', compute='_compute_entry_qc_outcome')

    def _compute_entry_qc_outcome(self):
        Dispatch = self.env['reema.ilo.dispatch']
        Scrap = self.env['reema.ilo.qc.scrap']
        defect_labels = dict(Dispatch._fields['defect_type'].selection)
        for entry in self:
            if not entry.workorder_id.workcenter_id.is_initial_qc or not entry.contractor_id:
                entry.entry_repair_qty = 0
                entry.entry_repair_defect_types = False
                entry.entry_scrap_qty = 0
                entry.entry_scrap_defect_types = False
                continue
            repairs = Dispatch.search([
                ('dispatch_type', '=', 'repair'), ('repair_source', '=', 'initial_qc'),
                '|', ('batch_entry_id', '=', entry.id),
                '&', ('original_contractor_id', '=', entry.contractor_id.id),
                     ('create_date', '=', entry.create_date),
            ])
            entry.entry_repair_qty = sum(repairs.mapped('qty_balls'))
            entry.entry_repair_defect_types = ', '.join(sorted({
                defect_labels.get(d, d) for d in repairs.mapped('defect_type') if d
            }))
            scraps = Scrap.search([
                '|', ('batch_entry_id', '=', entry.id),
                '&', ('workorder_id', '=', entry.workorder_id.id),
                '&', ('contractor_id', '=', entry.contractor_id.id),
                     ('create_date', '=', entry.create_date),
            ])
            entry.entry_scrap_qty = sum(scraps.mapped('qty'))
            entry.entry_scrap_defect_types = ', '.join(sorted({
                defect_labels.get(d, d) for d in scraps.mapped('defect_type') if d
            }))

    def _compute_qc_summary(self):
        Dispatch = self.env['reema.ilo.dispatch']
        Scrap = self.env['reema.ilo.qc.scrap']
        BatchEntry = self.env['reema.wo.batch.entry']
        defect_labels = dict(Scrap._fields['defect_type'].selection)
        for entry in self:
            wc = entry.workorder_id.workcenter_id
            if not wc.is_initial_qc or not entry.mo_id or not entry.contractor_id:
                entry.is_initial_qc_entry = False
                entry.qc_received_qty = 0
                entry.qc_pass_qty = 0
                entry.qc_repair_qty = 0
                entry.qc_scrap_qty = 0
                entry.qc_repair_contractor_ids = False
                entry.qc_repair_defect_types = False
                entry.qc_scrap_defect_types = False
                continue
            entry.is_initial_qc_entry = True
            mo_id = entry.mo_id.id
            contractor_id = entry.contractor_id.id
            entry.qc_received_qty = sum(BatchEntry.search([
                ('workorder_id.production_id', '=', mo_id),
                ('workorder_id.workcenter_id.is_ball_receive_point', '=', True),
                ('original_contractor_id', '=', contractor_id),
            ]).mapped('qty'))
            entry.qc_pass_qty = sum(BatchEntry.search([
                ('workorder_id.production_id', '=', mo_id),
                ('workorder_id.workcenter_id.is_initial_qc', '=', True),
                ('contractor_id', '=', contractor_id),
            ]).mapped('qty'))
            repair_dispatches = Dispatch.search([
                ('mo_id', '=', mo_id), ('dispatch_type', '=', 'repair'),
                ('original_contractor_id', '=', contractor_id),
            ])
            entry.qc_repair_qty = sum(repair_dispatches.mapped('qty_balls'))
            entry.qc_repair_contractor_ids = repair_dispatches.mapped('contractor_id')
            entry.qc_repair_defect_types = ', '.join(sorted({
                defect_labels.get(d, d) for d in repair_dispatches.mapped('defect_type') if d
            }))
            scrap_records = Scrap.search([
                ('mo_id', '=', mo_id), ('contractor_id', '=', contractor_id),
            ])
            entry.qc_scrap_qty = sum(scrap_records.mapped('qty'))
            entry.qc_scrap_defect_types = ', '.join(sorted({
                defect_labels.get(d, d) for d in scrap_records.mapped('defect_type') if d
            }))

    @api.depends('workorder_id.production_id')
    def _compute_reema_po_id(self):
        POLine = self.env['reema.production.order.line']
        for entry in self:
            mo = entry.workorder_id.production_id
            if mo:
                line = POLine.search([('mo_id', '=', mo.id)], limit=1)
                entry.reema_po_id = line.order_id
            else:
                entry.reema_po_id = False

    @api.depends('qty', 'workorder_id.operation_id.balls_per_unit',
                 'workorder_id.workcenter_id.hall_unit')
    def _compute_qty_balls(self):
        for entry in self:
            wo = entry.workorder_id
            entry.qty_balls = wo._units_to_balls(entry.qty) if wo else entry.qty

    def _impressions_per_ball(self):
        """Impressions/Ball for this batch — a design-level constant read from the
        BOM, applied only at the printing work center. 0 otherwise."""
        wo = self.workorder_id
        if wo.workcenter_id.is_printing and wo.production_id.bom_id:
            return wo.production_id.bom_id.impressions_per_ball or 0.0
        return 0.0

    def _calc_amount(self):
        if self.payment_excluded:
            return 0.0
        rate = self.piece_rate_id.rate or 0.0
        wc = self.workorder_id.workcenter_id
        if (wc.pay_basis or 'ball') == 'ball':
            return rate * self.qty_balls
        ipu = self._impressions_per_ball()
        if ipu:
            return rate * self.qty_balls * ipu
        return rate * self.qty

    @api.depends(
        'piece_rate_id.rate', 'qty', 'qty_balls', 'payment_excluded',
        'workorder_id.workcenter_id.pay_basis',
        'workorder_id.workcenter_id.is_printing',
        'workorder_id.production_id.bom_id.impressions_per_ball',
    )
    def _compute_amount_earned(self):
        for entry in self:
            entry.amount_earned = entry._calc_amount()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('reema.production.batch') or 'New'
        records = super().create(vals_list)
        for entry in records:
            entry._create_sfg_move()
            entry._backflush_components()
            # First batch logged on this WO → auto-release so the next hall's
            # Start button becomes available without any manual action.
            if not entry.workorder_id.batch_released:
                entry.workorder_id.batch_released = True
        records.mapped('workorder_id.production_id')._sync_packing_qty()
        for entry in records:
            contractor_part = f', Contractor: {entry.contractor_id.name}' if entry.contractor_id else ''
            entry.workorder_id.production_id._message_log(
                body=Markup(
                    f'Batch logged — <b>{entry.workorder_id.workcenter_id.name}</b>: '
                    f'Qty {entry.qty}, Balls {entry.qty_balls:.2f}{contractor_part} '
                    f'(ref: {entry.name}, by {self.env.user.name})'
                ),
            )
        return records

    def unlink(self):
        if not (self.env.user.has_group('reema_mrp.group_reema_supervisor')
                or self.env.user.has_group('base.group_system')):
            raise UserError('Only supervisors can delete batch entries.')
        for entry in self:
            if entry.is_billed:
                raise UserError(
                    f'Cannot delete "{entry.name}" — it has already been billed. '
                    'Remove it from the bill first.'
                )
            entry._reverse_stock_moves()
            entry.workorder_id.production_id._message_log(
                body=Markup(
                    f'<b>Batch entry deleted:</b> {entry.name}<br/>'
                    f'Hall: {entry.workorder_id.workcenter_id.name}<br/>'
                    f'Qty: {entry.qty} — Balls: {entry.qty_balls:.2f}<br/>'
                    f'Deleted by: {self.env.user.name}'
                ),
            )
        wos = self.mapped('workorder_id')
        productions = self.mapped('workorder_id.production_id')
        res = super().unlink()
        for wo in wos:
            if not wo.batch_entry_ids:
                wo.batch_released = False

        for wo in wos:
            if wo.state not in ('done', 'progress'):
                continue
            open_logs = self.env['mrp.workcenter.productivity'].search([
                ('workorder_id', '=', wo.id),
                ('date_end', '=', False),
            ])
            for log in open_logs:
                log.date_end = log.date_start
            # date_start/date_finished are computed from leave_id (the Gantt/capacity
            # planning record) — if this WO was ever planned, that leave still exists.
            # Raw-SQL-ing date_finished to NULL below without clearing leave_id first
            # leaves date_finished and leave_id.date_to out of sync, which later trips
            # Odoo's own "cannot unplan a single Work Order" guard the next time
            # anything recomputes these fields. Go through the ORM here so the leave
            # is actually cleared (and its now-orphaned record removed).
            if wo.leave_id:
                leave = wo.leave_id
                wo.leave_id = False
                leave.unlink()
            if not wo.batch_entry_ids:
                self.env.cr.execute(
                    "UPDATE mrp_workorder SET state='pending', qty_produced=0, date_finished=NULL WHERE id=%s",
                    [wo.id]
                )
                wo.invalidate_recordset()
                wo._compute_state()
            else:
                self.env.cr.execute(
                    "UPDATE mrp_workorder SET state='progress', qty_produced=0, date_finished=NULL WHERE id=%s AND state='done'",
                    [wo.id]
                )
                wo.invalidate_recordset()

        for mo in productions:
            mo.invalidate_recordset(['state'])
            mo._compute_state()

        productions._sync_packing_qty()
        return res

    def _reverse_stock_moves(self):
        if self.sfg_move_id and self.sfg_move_id.state == 'done':
            sfg = self.sfg_move_id
            ret = self.env['stock.move'].create({
                'name': f'Return SFG: {sfg.product_id.display_name}',
                'product_id': sfg.product_id.id,
                'product_uom': sfg.product_uom.id,
                'product_uom_qty': sfg.product_uom_qty,
                'location_id': sfg.location_dest_id.id,
                'location_dest_id': sfg.location_id.id,
                'origin': f'Return: {sfg.origin}',
                'company_id': sfg.company_id.id,
                'origin_returned_move_id': sfg.id,
            })
            ret._action_confirm()
            ret.quantity = ret.product_uom_qty
            ret._action_done()

        backflush_origin = f'{self.mo_id.name} / {self.workorder_id.name} / {self.name}'
        backflush_moves = self.env['stock.move'].search([
            ('origin', '=', backflush_origin),
            ('state', '=', 'done'),
        ])
        for move in backflush_moves:
            ret = self.env['stock.move'].create({
                'name': f'Return: {move.product_id.display_name}',
                'product_id': move.product_id.id,
                'product_uom': move.product_uom.id,
                'product_uom_qty': move.product_uom_qty,
                'location_id': move.location_dest_id.id,
                'location_dest_id': move.location_id.id,
                'origin': f'Return: {move.origin}',
                'company_id': move.company_id.id,
                'origin_returned_move_id': move.id,
            })
            ret._action_confirm()
            ret.quantity = ret.product_uom_qty
            ret._action_done()

    def action_supervisor_delete(self):
        self.unlink()

    def action_exclude_from_payment(self):
        billed = self.filtered('is_billed')
        if billed:
            raise UserError(
                'The following entries are already billed and cannot be excluded here.\n'
                'Remove them from their bill first.\n\n'
                + '\n'.join(billed.mapped('name'))
            )
        self.write({'payment_excluded': True})

    def action_include_in_payment(self):
        if not self.env.user.has_group('base.group_system'):
            raise UserError('Only an administrator can re-include an entry in payment.')
        self.write({'payment_excluded': False})

    def action_create_contractor_bill(self):
        missing_contractor = self.filtered(lambda e: not e.contractor_id)
        if missing_contractor:
            raise UserError(
                'The following entries have no contractor assigned:\n'
                + '\n'.join(missing_contractor.mapped('name'))
            )

        already_billed = self.filtered('is_billed')
        if already_billed:
            raise UserError(
                'The following entries are already billed:\n'
                + '\n'.join(already_billed.mapped('name'))
            )

        excluded = self.filtered('payment_excluded')
        if excluded:
            raise UserError(
                'The following entries are excluded from payment and cannot be billed.\n'
                'Re-include them in payment first if they should be paid:\n\n'
                + '\n'.join(excluded.mapped('name'))
            )

        contractors = self.mapped('contractor_id')
        if len(contractors) > 1:
            raise UserError(
                'All selected entries must belong to the same contractor.\n'
                'Please filter by contractor before creating a bill.\n\n'
                'Selected contractors: ' + ', '.join(contractors.mapped('name'))
            )

        workcenters = self.mapped('workorder_id.workcenter_id')
        if len(workcenters) > 1:
            raise UserError(
                'All selected entries must belong to the same process.\n'
                'Selected processes: ' + ', '.join(workcenters.mapped('name'))
            )

        for entry in self.filtered(lambda e: not e.piece_rate_id):
            rate = entry.workorder_id.operation_id.piece_rate_id
            if rate:
                entry.piece_rate_id = rate

        missing_rate = self.filtered(lambda e: not e.piece_rate_id)
        if missing_rate:
            raise UserError(
                'The following entries have no piece rate assigned:\n'
                + '\n'.join(missing_rate.mapped('name'))
                + '\n\nAssign a piece rate in the BOM before billing.'
            )

        missing_account = self.filtered(lambda e: not e.workorder_id.workcenter_id.expense_account_id)
        if missing_account:
            wc_names = ', '.join(missing_account.mapped('workorder_id.workcenter_id.name'))
            raise UserError(
                f'The following work centers have no Labor Expense Account configured: {wc_names}\n\n'
                'Go to Manufacturing → Configuration → Work Centers and set the account.'
            )

        contractor = contractors
        if not contractor.is_contractor:
            contractor.is_contractor = True

        lines = []
        for entry in self.sorted('name'):
            wc = entry.workorder_id.workcenter_id
            pay_basis = wc.pay_basis or 'ball'
            ipu = entry._impressions_per_ball()
            rate = entry.piece_rate_id.rate or 0.0
            if pay_basis == 'ball':
                bill_qty = entry.qty_balls
            elif ipu:
                bill_qty = entry.qty_balls * ipu
            else:
                bill_qty = entry.qty
            line_vals = {
                'name': f'{entry.name} — {entry.process_name}',
                'quantity': bill_qty,
                'price_unit': rate,
                'account_id': wc.expense_account_id.id,
                'reema_batch_entry_id': entry.id,
            }
            if wc.is_printing:
                line_vals['reema_balls_qty'] = entry.qty_balls
                line_vals['reema_impressions_per_ball'] = ipu
            lines.append((0, 0, line_vals))

        # Deductions against this contractor (ILO repair charges + Final QC scrap
        # material cost) — surfaced as lines on the bill itself, per production's
        # requirement that these are impossible to miss at billing time rather than
        # something to remember to check separately. Repair charges are fully
        # computed already (qty x rate); scrap lines carry the qty/type but the
        # amount is left for the preparer to type in — there's no stored cost figure.
        pending_deductions = self.env['reema.ilo.contractor.deduction'].search([
            ('original_contractor_id', '=', contractor.id),
            ('state', '=', 'pending'),
        ])
        for ded in pending_deductions.sorted('date'):
            if ded.deduction_type == 'repair':
                line_name = f'{ded.name} — ILO Repair Charge ({ded.qty} balls @ {ded.rate:.2f})'
                price_unit = ded.rate
            else:
                ball_type = ded.construction_type.upper() if ded.construction_type else ''
                line_name = f'{ded.name} — Scrap Material Cost ({ded.qty} balls, {ball_type}) — enter cost'
                price_unit = 0.0
            lines.append((0, 0, {
                'name': line_name,
                'quantity': -ded.qty,
                'price_unit': price_unit,
                'account_id': workcenters.expense_account_id.id,
            }))

        # Contractor-hall production scrap (e.g. Printing) — same "enter cost
        # manually" pattern as the ILO scrap line above, sourced from
        # reema.production.scrap instead of the ILO-specific deduction model.
        # Employee-hall scrap (Shaping) never has contractor_id set, so it
        # never surfaces here — it isn't charged to anyone.
        pending_scrap = self.env['reema.production.scrap'].search([
            ('contractor_id', '=', contractor.id),
            ('is_billed', '=', False),
        ])
        for scrap in pending_scrap.sorted('date'):
            reason_label = scrap.reason_id.name
            unit_label = f'{scrap.workcenter_id.hall_unit or "unit"}s'
            line_name = f'{scrap.name} — Scrap Material Cost ({scrap.qty} {unit_label}, {reason_label}) — enter cost'
            lines.append((0, 0, {
                'name': line_name,
                'quantity': -scrap.qty,
                'price_unit': 0.0,
                'account_id': workcenters.expense_account_id.id,
            }))

        # Append to existing draft bill for this contractor if one exists
        existing_bill = self.env['account.move'].search([
            ('move_type', '=', 'in_invoice'),
            ('state', '=', 'draft'),
            ('partner_id', '=', contractor.id),
            ('batch_entry_ids', '!=', False),
        ], limit=1)

        if existing_bill:
            existing_bill.write({'invoice_line_ids': lines})
            move = existing_bill
        else:
            journal = self.env['account.journal'].search([('type', '=', 'purchase')], limit=1)
            if not journal:
                raise UserError('No purchase journal found. Please configure a purchase journal in Accounting.')
            move = self.env['account.move'].create({
                'move_type': 'in_invoice',
                'partner_id': contractor.id,
                'journal_id': journal.id,
                'invoice_date': fields.Date.today(),
                'invoice_line_ids': lines,
            })
            move._set_next_sequence()

        self.write({'is_billed': True, 'bill_id': move.id})
        pending_deductions.write({'state': 'applied', 'bill_id': move.id})
        pending_scrap.write({'is_billed': True, 'bill_id': move.id})

        try:
            view_id = self.env.ref('reema_accounting.view_contractor_bill_form').id
        except Exception:
            view_id = False

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': move.id,
            'view_mode': 'form',
            'views': [(view_id, 'form')],
            'target': 'current',
        }

    def _backflush_components(self):
        wo = self.workorder_id
        mo = wo.production_id
        if not mo.bom_id or not wo.operation_id:
            return
        bom_lines = mo.bom_id.bom_line_ids.filtered(
            lambda l: l.operation_id == wo.operation_id
        )
        if not bom_lines:
            return
        source_loc = wo.workcenter_id.location_id
        if not source_loc:
            return
        prod_loc = self.env['stock.location'].search(
            [('usage', '=', 'production')], limit=1
        )
        if not prod_loc:
            return
        for line in bom_lines:
            rounding = line.product_uom_id.rounding
            consumed_qty = float_round(
                self.qty_balls * line.product_qty, precision_rounding=rounding
            )
            if float_is_zero(consumed_qty, precision_rounding=rounding):
                continue
            move = self.env['stock.move'].create({
                'name': f'Backflush: {line.product_id.display_name}',
                'product_id': line.product_id.id,
                'product_uom': line.product_uom_id.id,
                'product_uom_qty': consumed_qty,
                'location_id': source_loc.id,
                'location_dest_id': prod_loc.id,
                'origin': f'{mo.name} / {wo.name} / {self.name}',
                'reema_batch_entry_id': self.id,
                'company_id': wo.company_id.id,
            })
            move._action_confirm()
            move.quantity = consumed_qty
            move._action_done()

    def _create_sfg_move(self):
        wo = self.workorder_id
        wc = wo.workcenter_id
        if not wc.sfg_product_id or not wc.location_id:
            return
        if not self.qty:
            return
        rounding = wc.sfg_product_id.uom_id.rounding
        qty = float_round(self.qty, precision_rounding=rounding)
        if float_is_zero(qty, precision_rounding=rounding):
            return
        production_loc = self.env['stock.location'].search([('usage', '=', 'production')], limit=1)
        if not production_loc:
            raise UserError('No production location found. Please configure a location with usage "Production".')
        move = self.env['stock.move'].create({
            'name': f'SFG Batch: {wc.sfg_product_id.name}',
            'product_id': wc.sfg_product_id.id,
            'product_uom': wc.sfg_product_id.uom_id.id,
            'product_uom_qty': qty,
            'location_id': production_loc.id,
            'location_dest_id': wc.location_id.id,
            'origin': f'{wo.production_id.name} / {wo.name}',
            'company_id': wo.company_id.id,
        })
        move._action_confirm()
        move.quantity = qty
        move._action_done()
        self.sfg_move_id = move


class ReemaScrapReason(models.Model):
    """Configurable scrap-cause list, scoped per hall — a Many2one (not a
    Selection) specifically so the dropdown can be domain-filtered to only
    the reasons relevant at whichever hall is being logged, instead of every
    hall's causes mixed into one shared list. Add new reasons here as new
    halls get scrap logging enabled; no code change needed."""
    _name = 'reema.scrap.reason'
    _description = 'Production Scrap Reason'
    _order = 'name'

    name = fields.Char(required=True)
    workcenter_ids = fields.Many2many(
        'mrp.workcenter', string='Applicable Halls',
        help='Which halls this reason can be selected at when logging scrap. '
             'Leave empty to allow it at any hall (e.g. a generic "Other").',
    )
    active = fields.Boolean(default=True)


class ReemaProductionScrap(models.Model):
    _name = 'reema.production.scrap'
    _description = 'Production Scrap (Shop Floor)'
    _order = 'date desc'

    name = fields.Char(string='Reference', readonly=True, copy=False, default='New')
    workorder_id = fields.Many2one('mrp.workorder', string='Work Order',
                                   required=True, ondelete='cascade')
    mo_id = fields.Many2one('mrp.production', related='workorder_id.production_id',
                            string='MO', store=True)
    workcenter_id = fields.Many2one('mrp.workcenter', related='workorder_id.workcenter_id',
                                    string='Hall', store=True)
    batch_entry_id = fields.Many2one('reema.wo.batch.entry', string='Batch Entry',
                                     ondelete='set null',
                                     help='The batch-logging session this scrap was recorded during, if any.')
    # Whoever was logging the batch at a contractor-staffed hall when this
    # scrap happened — blank at employee halls (e.g. Shaping), where scrap
    # is never charged to anyone. Set from the same contractor already
    # selected for the batch-log session, not chosen separately.
    contractor_id = fields.Many2one('res.partner', string='Contractor')
    qty = fields.Integer(string='Qty Scrapped', required=True)
    # Balls-equivalent of qty, in this hall's logging unit — same conversion
    # reema.wo.batch.entry.qty_balls uses. A scrapped unit still consumed one
    # unit that arrived from the previous hall, so this has to feed into that
    # hall's own predecessor-availability cap (see action_confirm below) —
    # without it, repeated scrap entries let a WO silently over-consume more
    # than the previous hall actually produced.
    qty_balls = fields.Float(string='Balls Equivalent', compute='_compute_qty_balls', store=True)
    reason_id = fields.Many2one('reema.scrap.reason', string='Reason', required=True)
    notes = fields.Char(string='Notes')
    date = fields.Datetime(string='Date', default=fields.Datetime.now)
    recorded_by = fields.Many2one('res.users', string='Recorded By',
                                  default=lambda self: self.env.user)
    # Contractor-hall scrap only — the material-cost penalty charged against
    # contractor_id, entered manually when the bill is prepared (there's no
    # stored cost figure to compute this from, same as the ILO scrap
    # deduction pattern). Employee-hall scrap (Shaping) never gets billed,
    # so these stay at their defaults for those records.
    amount = fields.Float(string='Amount (PKR)', digits=(10, 2))
    is_billed = fields.Boolean(string='Billed', default=False)
    bill_id = fields.Many2one('account.move', string='Bill', readonly=True, copy=False)

    _sql_constraints = [
        ('qty_positive', 'CHECK(qty > 0)', 'Scrapped quantity must be greater than zero.'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('reema.production.scrap') or 'New'
        return super().create(vals_list)

    @api.depends('qty', 'workorder_id')
    def _compute_qty_balls(self):
        for rec in self:
            rec.qty_balls = rec.workorder_id._units_to_balls(rec.qty) if rec.workorder_id else 0.0


class ReemaScrapReport(models.Model):
    """Combined, read-only feed of every scrap/write-off event across the
    factory — ILO Initial QC scrap (reema.ilo.qc.scrap) and general shop-floor
    scrap (reema.production.scrap) — so the total can be seen in one place
    without merging the two source models, which have different accountability
    rules (ILO scrap charges a contractor; production scrap doesn't)."""
    _name = 'reema.scrap.report'
    _description = 'Scrap Report (All Sources)'
    _auto = False
    _order = 'date desc'

    date = fields.Datetime(string='Date', readonly=True)
    mo_id = fields.Many2one('mrp.production', string='Manufacturing Order', readonly=True)
    workorder_id = fields.Many2one('mrp.workorder', string='Work Order', readonly=True)
    workcenter_id = fields.Many2one('mrp.workcenter', string='Hall', readonly=True)
    source = fields.Selection(
        [('ilo_qc', 'ILO QC'), ('production', 'Production Floor')],
        string='Source', readonly=True,
    )
    contractor_id = fields.Many2one(
        'res.partner', string='Charged To', readonly=True,
        help='Contractor this scrap is chargeable against, if any — blank for '
             'employee-hall scrap (e.g. Shaping), which is never charged to anyone.',
    )
    qty = fields.Integer(string='Qty Scrapped', readonly=True)
    reason = fields.Char(string='Reason', readonly=True)
    notes = fields.Char(string='Notes', readonly=True)
    recorded_by = fields.Many2one('res.users', string='Recorded By', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW reema_scrap_report AS (
                SELECT row_number() OVER (ORDER BY combined.date DESC) AS id,
                       combined.date,
                       combined.mo_id,
                       combined.workorder_id,
                       combined.workcenter_id,
                       combined.source,
                       combined.contractor_id,
                       combined.qty,
                       combined.reason,
                       combined.notes,
                       combined.recorded_by
                FROM (
                    SELECT
                        s.date::timestamp      AS date,
                        s.mo_id                AS mo_id,
                        s.workorder_id         AS workorder_id,
                        wo.workcenter_id       AS workcenter_id,
                        'ilo_qc'                AS source,
                        s.contractor_id         AS contractor_id,
                        s.qty                   AS qty,
                        CASE s.defect_type
                            WHEN 'bad_stitching' THEN 'Bad Stitching'
                            WHEN 'missing_panel' THEN 'Missing Panel'
                            WHEN 'missing_bladder' THEN 'Missing Bladder'
                            WHEN 'other' THEN 'Other'
                            ELSE s.defect_type
                        END                     AS reason,
                        s.notes                 AS notes,
                        s.recorded_by           AS recorded_by
                    FROM reema_ilo_qc_scrap s
                    JOIN mrp_workorder wo ON wo.id = s.workorder_id

                    UNION ALL

                    SELECT
                        p.date                  AS date,
                        p.mo_id                 AS mo_id,
                        p.workorder_id          AS workorder_id,
                        p.workcenter_id         AS workcenter_id,
                        'production'             AS source,
                        p.contractor_id          AS contractor_id,
                        p.qty                    AS qty,
                        r.name                   AS reason,
                        p.notes                  AS notes,
                        p.recorded_by            AS recorded_by
                    FROM reema_production_scrap p
                    LEFT JOIN reema_scrap_reason r ON r.id = p.reason_id
                ) combined
            )
        """)


class ReemaBatchEntryWizard(models.TransientModel):
    _name = 'reema.batch.entry.wizard'
    _description = 'Log Batch Progress'

    workorder_id = fields.Many2one('mrp.workorder', string='Work Order',
                                   required=True, readonly=True)
    workorder_name = fields.Char(related='workorder_id.name', string='Work Order', readonly=True)
    workcenter_name = fields.Char(related='workorder_id.workcenter_id.name',
                                  string='Hall', readonly=True)
    workcenter_id = fields.Many2one(related='workorder_id.workcenter_id', readonly=True)
    workforce_type = fields.Selection(
        related='workorder_id.workcenter_id.workforce_type', readonly=True
    )
    hall_qty = fields.Float(related='workorder_id.hall_qty',
                            string='Target', readonly=True)
    qty_batch_completed = fields.Float(related='workorder_id.qty_batch_completed',
                                       string='Completed So Far', readonly=True)
    # Restrict contractor dropdown to only those assigned to this work order
    available_contractor_ids = fields.Many2many(related='workorder_id.contractor_ids',
                                                string='Assigned Contractors')
    contractor_id = fields.Many2one('res.partner', string='Contractor', required=False,
                                    domain="[('id', 'in', available_contractor_ids)]")
    qty = fields.Float(string='Qty Completed Now', required=True)
    # Logging unit drives which fields the modal shows (sheet/panel/ball).
    hall_unit = fields.Selection(
        related='workorder_id.workcenter_id.hall_unit', readonly=True)
    panels_per_ball = fields.Integer(
        string='Panels per Ball', compute='_compute_panels_per_ball')
    # Panel halls only: balls equivalent, kept in sync with qty (panels) both ways.
    qty_balls_input = fields.Float(string='Balls Completed')
    notes = fields.Char(string='Notes')
    qty_warning = fields.Char(string='Quantity Warning', compute='_compute_qty_warning')
    scrap_enabled = fields.Boolean(related='workorder_id.workcenter_id.scrap_enabled', readonly=True)
    qty_scrap = fields.Integer(string='Scrapped Qty')
    scrap_reason_id = fields.Many2one(
        'reema.scrap.reason', string='Scrap Reason',
        domain="['|', ('workcenter_ids', '=', False), ('workcenter_ids', 'in', [workcenter_id])]",
    )

    @api.depends('workorder_id')
    def _compute_panels_per_ball(self):
        for wiz in self:
            wiz.panels_per_ball = wiz.workorder_id._get_total_panels() if wiz.workorder_id else 0

    @api.onchange('qty')
    def _onchange_qty_to_balls(self):
        if self.hall_unit == 'panel' and self.panels_per_ball:
            self.qty_balls_input = self.qty / self.panels_per_ball

    @api.onchange('qty_balls_input')
    def _onchange_balls_to_qty(self):
        if self.hall_unit == 'panel' and self.panels_per_ball:
            self.qty = self.qty_balls_input * self.panels_per_ball

    @api.depends('qty', 'workorder_id.qty_batch_completed', 'workorder_id.hall_qty')
    def _compute_qty_warning(self):
        for wiz in self:
            if wiz.qty > 0 and (wiz.workorder_id.qty_batch_completed + wiz.qty) > wiz.workorder_id.hall_qty:
                total = wiz.workorder_id.qty_batch_completed + wiz.qty
                wiz.qty_warning = (
                    f"Total will be {total:.1f}, exceeding the target of {wiz.workorder_id.hall_qty:.1f}."
                )
            else:
                wiz.qty_warning = False
    piece_rate_id = fields.Many2one(
        related='workorder_id.operation_id.piece_rate_id',
        string='Piece Rate',
        readonly=True,
    )
    piece_rate_value = fields.Float(
        related='workorder_id.operation_id.piece_rate_id.rate',
        string='Rate (PKR)',
        readonly=True,
        digits=(10, 2),
    )

    def action_confirm(self):
        self.ensure_one()
        wo = self.workorder_id
        if self.qty <= 0 and self.qty_scrap <= 0:
            raise UserError('Enter a completed quantity or a scrapped quantity before confirming.')
        if self.qty_scrap > 0 and not self.scrap_reason_id:
            raise UserError('Select a reason for the scrapped quantity.')
        # Panel halls convert qty → balls by dividing by panels-per-ball (from the
        # product's sampling blueprint). Without it, balls/consumption would be wrong.
        if wo.workcenter_id.hall_unit == 'panel' and not wo._get_total_panels():
            raise UserError(
                f'{wo.workcenter_id.name} is a panel-based hall, but this product\'s '
                'sampling blueprint has no panel count set.\n\n'
                'Add the cutting knives / panel count on the blueprint before logging here.'
            )
        # Cap: cannot log more than what has physically arrived from the previous hall.
        # Comparison is normalized to balls so different hall units (sheets vs panels) work correctly.
        # Scrapped units also consumed a unit that arrived from the previous hall, so they
        # count toward "already processed here" alongside good output — both for this
        # submission (total_logged) and for everything already logged at this hall before
        # it (qty_scrap_balls), otherwise a previously-scrapped unit is silently forgotten
        # and lets this WO over-consume beyond what the previous hall actually produced.
        total_logged = self.qty + self.qty_scrap
        for pred in wo.blocked_by_workorder_ids:
            if pred.state in ('done', 'cancel'):
                continue
            self_balls = wo._units_to_balls(total_logged)
            already_processed = wo.qty_balls_completed + wo.qty_scrap_balls
            available_balls = pred.qty_balls_completed - already_processed
            available_units = wo._balls_to_units(available_balls)
            if self_balls > available_balls + 0.001:
                uom_label = 'units'
                raise UserError(
                    f'Cannot log {total_logged:.1f} {uom_label}.\n\n'
                    f'{pred.workcenter_id.name} has completed '
                    f'{pred.qty_balls_completed:.1f} balls equivalent.\n\n'
                    f'{already_processed:.1f} balls equivalent already processed here '
                    f'(including scrap).\n\n'
                    f'Maximum you can log now: {available_units:.1f} {uom_label}.'
                )
        # Block logging if BOM components for this operation haven't been physically issued.
        if wo.operation_id:
            required_moves = wo.production_id.move_raw_ids.filtered(
                lambda m: m.operation_id == wo.operation_id and m.state not in ('done', 'cancel')
            )
            unissued = [
                move.product_id.display_name
                for move in required_moves
                if not wo.production_id.issuance_ids.filtered(
                    lambda i: i.raw_move_id == move
                    and i.state in ('partial', 'fully_issued', 'over_issued')
                )
            ]
            if unissued:
                raise UserError(
                    'Cannot log this work order — the following materials have not been issued to this hall:\n'
                    + '\n'.join(f'• {n}' for n in unissued)
                )
        # Contractor is required for ANY quantity logged at a contractor hall —
        # not just the good-qty branch below, since contractor-hall scrap
        # (e.g. Printing) needs contractor_id too, to know who it's chargeable
        # against at billing time.
        if self.workforce_type != 'employee' and not self.contractor_id:
            raise UserError('Please select a contractor before saving.')

        entry = self.env['reema.wo.batch.entry']
        if self.qty > 0:
            vals = {
                'workorder_id': wo.id,
                'qty': self.qty,
                'notes': self.notes,
            }
            if self.workforce_type != 'employee':
                vals['contractor_id'] = self.contractor_id.id
                vals['piece_rate_id'] = wo.operation_id.piece_rate_id.id or False
            if wo.workcenter_id.is_ilo:
                # ILO Issuance quantity is provisional — the real payable amount is
                # only known once balls are logged back in at the ILO receiving step.
                vals['payment_excluded'] = True
                vals['exclusion_reason'] = 'ILO — real payment recorded at Stitching Center Receive'
            entry = self.env['reema.wo.batch.entry'].create(vals)
            if wo.workcenter_id.is_ilo and self.contractor_id:
                self.env['reema.ilo.dispatch'].create({
                    'mo_id': wo.production_id.id,
                    'contractor_id': self.contractor_id.id,
                    'ball_size': wo.production_id.ball_size,
                    'construction_type': wo.production_id.construction_type,
                    'qty_balls': int(round(entry.qty_balls)),
                    'rate': self.piece_rate_value,
                    'dispatched_by': self.env.user.id,
                    'batch_entry_id': entry.id,
                })
        if self.qty_scrap > 0:
            scrap_vals = {
                'workorder_id': wo.id,
                'batch_entry_id': entry.id,
                'qty': self.qty_scrap,
                'reason_id': self.scrap_reason_id.id,
                'notes': self.notes,
            }
            if self.workforce_type != 'employee':
                scrap_vals['contractor_id'] = self.contractor_id.id
            self.env['reema.production.scrap'].create(scrap_vals)


class ReemaIloReceiveWizard(models.TransientModel):
    _name = 'reema.ilo.receive.wizard'
    _description = 'Log ILO Balls Received'

    workorder_id = fields.Many2one('mrp.workorder', string='Work Order',
                                   required=True, readonly=True)
    workorder_name = fields.Char(related='workorder_id.name', string='Work Order', readonly=True)
    mo_id = fields.Many2one(related='workorder_id.production_id', string='Manufacturing Order', readonly=True)
    workcenter_name = fields.Char(related='workorder_id.workcenter_id.name', string='Hall', readonly=True)
    available_contractor_ids = fields.Many2many(
        'res.partner', compute='_compute_available_contractor_ids',
        string='ILO Contractors',
        help='Contractors who have dispatches for this MO — Ball Receive is an '
             'employee task, contractor identity always traces back to who was '
             'dispatched to at Stitching Center Issuance.',
    )
    contractor_id = fields.Many2one('res.partner', string='Contractor', required=True,
                                    domain="[('id', 'in', available_contractor_ids)]")
    stitching_balance_display = fields.Float(string='Stitching Balance Outstanding', compute='_compute_balances')
    repair_balance_display = fields.Float(string='Repair Balance Outstanding', compute='_compute_balances')
    qty = fields.Integer(string='Quantity Received')
    notes = fields.Char(string='Notes')
    stitching_open = fields.Boolean(compute='_compute_flow_flags')
    repair_open = fields.Boolean(compute='_compute_flow_flags')
    receipt_purpose = fields.Selection(
        [('stitching', 'Own Stitching Return'), ('repair', 'Repair Return')],
        string='Receipt Purpose',
        help='Only needs to be picked when this contractor has both an open stitching '
             'dispatch and an open repair dispatch on this MO at the same time.',
    )
    original_contractor_id = fields.Many2one(
        'res.partner', string='Original Contractor',
        domain="[('id', 'in', available_original_contractor_ids)]",
        help='Whose production these balls credit. Auto-filled to the contractor '
             'themselves for a stitching return; for a repair return, auto-filled '
             'from the repair dispatch unless more than one original contractor is '
             'mixed into this contractor\'s open repair work on this MO.',
    )
    available_original_contractor_ids = fields.Many2many(
        'res.partner', compute='_compute_available_original_contractor_ids',
        string='Available Original Contractors',
        help='Contractors whose balls were dispatched to this contractor for repair '
             'on this MO — restricts Original Contractor to only real repair links '
             'instead of every partner.',
    )

    @api.depends('workorder_id')
    def _compute_available_contractor_ids(self):
        for wiz in self:
            wiz.available_contractor_ids = self.env['reema.ilo.dispatch']._ilo_contractors_for_mo(
                wiz.workorder_id.production_id.id
            )

    @api.depends('contractor_id', 'workorder_id')
    def _compute_available_original_contractor_ids(self):
        Dispatch = self.env['reema.ilo.dispatch']
        for wiz in self:
            if wiz.contractor_id and wiz.workorder_id.production_id:
                mo_id = wiz.workorder_id.production_id.id
                candidates = Dispatch.search([
                    ('mo_id', '=', mo_id),
                    ('contractor_id', '=', wiz.contractor_id.id),
                    ('dispatch_type', '=', 'repair'),
                ]).mapped('original_contractor_id')
                # Only offer pairings still actually outstanding — a repair
                # contractor's past, already-settled job for one original
                # contractor must not remain selectable once it's reconciled,
                # or a new receipt can get misattributed to it.
                wiz.available_original_contractor_ids = candidates.filtered(
                    lambda c: Dispatch._ilo_repair_balance_by_original(
                        mo_id, wiz.contractor_id.id, c.id
                    ) > 0
                )
            else:
                wiz.available_original_contractor_ids = False

    @api.depends('contractor_id', 'workorder_id')
    def _compute_balances(self):
        Dispatch = self.env['reema.ilo.dispatch']
        for wiz in self:
            if wiz.contractor_id and wiz.workorder_id.production_id:
                mo_id = wiz.workorder_id.production_id.id
                wiz.stitching_balance_display = Dispatch._ilo_ledger_balance_by_type(
                    mo_id, wiz.contractor_id.id, 'stitching'
                )
                wiz.repair_balance_display = Dispatch._ilo_ledger_balance_by_type(
                    mo_id, wiz.contractor_id.id, 'repair'
                )
            else:
                wiz.stitching_balance_display = 0.0
                wiz.repair_balance_display = 0.0

    @api.depends('contractor_id', 'workorder_id')
    def _compute_flow_flags(self):
        for wiz in self:
            dispatches = self.env['reema.ilo.dispatch']
            if wiz.contractor_id and wiz.workorder_id.production_id:
                dispatches = self.env['reema.ilo.dispatch'].search([
                    ('mo_id', '=', wiz.workorder_id.production_id.id),
                    ('contractor_id', '=', wiz.contractor_id.id),
                ])
            wiz.stitching_open = bool(dispatches.filtered(lambda d: d.dispatch_type == 'stitching'))
            wiz.repair_open = bool(dispatches.filtered(lambda d: d.dispatch_type == 'repair'))

    @api.onchange('contractor_id')
    def _onchange_contractor_default_purpose(self):
        if self.stitching_open and not self.repair_open:
            self.receipt_purpose = 'stitching'
        elif self.repair_open and not self.stitching_open:
            self.receipt_purpose = 'repair'
        else:
            self.receipt_purpose = False

    @api.onchange('receipt_purpose', 'contractor_id')
    def _onchange_purpose_default_original(self):
        if not self.contractor_id:
            self.original_contractor_id = False
        elif self.receipt_purpose == 'stitching':
            self.original_contractor_id = self.contractor_id
        elif self.receipt_purpose == 'repair':
            candidates = self.available_original_contractor_ids
            self.original_contractor_id = candidates[0] if len(candidates) == 1 else False
        else:
            self.original_contractor_id = False

    def action_confirm(self):
        self.ensure_one()
        if not self.contractor_id:
            raise UserError('Please select a contractor.')
        if self.qty <= 0:
            raise UserError('Enter a quantity received before confirming.')
        if not self.receipt_purpose:
            raise UserError(
                f'{self.contractor_id.name} has both stitching and repair dispatches '
                f'open on this MO — select whether this receipt is their own stitching '
                f'return or a repair return.'
            )
        balance = self.env['reema.ilo.dispatch']._ilo_ledger_balance_by_type(
            self.workorder_id.production_id.id, self.contractor_id.id, self.receipt_purpose
        )
        if self.qty > balance:
            purpose_label = 'stitching' if self.receipt_purpose == 'stitching' else 'repair'
            raise UserError(
                f'Only {balance:.0f} {purpose_label} balls are currently outstanding for '
                f'{self.contractor_id.name} on this MO — cannot receive {self.qty}.'
            )
        if not self.original_contractor_id:
            raise UserError('Select the original contractor these balls belong to.')
        if self.receipt_purpose == 'repair':
            pair_balance = self.env['reema.ilo.dispatch']._ilo_repair_balance_by_original(
                self.workorder_id.production_id.id, self.contractor_id.id, self.original_contractor_id.id
            )
            if self.qty > pair_balance:
                raise UserError(
                    f'Only {pair_balance:.0f} repair balls are currently outstanding for '
                    f'{self.contractor_id.name} repairing {self.original_contractor_id.name}\'s balls '
                    f'on this MO — cannot receive {self.qty}.'
                )
        wo = self.workorder_id
        mo = wo.production_id
        notes = f'ILO Receive: {self.qty} balls received'
        if self.notes:
            notes += f' — {self.notes}'
        vals = {
            'workorder_id': wo.id,
            'contractor_id': self.contractor_id.id,
            'qty': self.qty,
            'notes': notes,
            'original_contractor_id': self.original_contractor_id.id,
            'ilo_dispatch_type': self.receipt_purpose,
        }
        if self.receipt_purpose == 'repair':
            # Same "ILO Center / Repair" piece rate Final QC's own repair-receive
            # flow pays from (see ReemaFinalQcReceiveWizard.action_confirm) — repair
            # work is billable to whoever performed it as soon as it's physically
            # back, and the original contractor whose defect caused it gets charged
            # via a matching deduction, same as that flow.
            repair_rate = self.env['reema.piece.rate'].search([
                ('workcenter_id.is_ilo', '=', True), ('work_type', '=ilike', 'Repair'),
            ], limit=1)
            if not repair_rate:
                raise UserError(
                    'No "Repair" piece rate is configured on the ILO Center work center. '
                    'Create one under Manufacturing → Configuration → Piece Rates before confirming.'
                )
            vals['piece_rate_id'] = repair_rate.id
            entry = self.env['reema.wo.batch.entry'].create(vals)
            self.env['reema.ilo.contractor.deduction'].create({
                'original_contractor_id': self.original_contractor_id.id,
                'deduction_type': 'repair',
                'mo_id': mo.id,
                'qty': self.qty,
                'construction_type': mo.construction_type,
                'rate': repair_rate.rate,
                'amount': self.qty * repair_rate.rate,
                'repair_batch_entry_id': entry.id,
            })
        else:
            # Stitching returns stay provisional — the real payable amount for the
            # original contractor's own production is settled at Initial QC Pass,
            # not here.
            vals['payment_excluded'] = True
            vals['exclusion_reason'] = 'ILO — real payment recorded at Initial QC Pass'
            self.env['reema.wo.batch.entry'].create(vals)


class ReemaIloQcWizard(models.TransientModel):
    _name = 'reema.ilo.qc.wizard'
    _description = 'Initial QC — Pass / Repair / Scrap'

    workorder_id = fields.Many2one('mrp.workorder', string='Work Order',
                                   required=True, readonly=True)
    workorder_name = fields.Char(related='workorder_id.name', string='Work Order', readonly=True)
    mo_id = fields.Many2one(related='workorder_id.production_id', string='Manufacturing Order', readonly=True)
    workcenter_name = fields.Char(related='workorder_id.workcenter_id.name', string='Hall', readonly=True)
    construction_type = fields.Selection(related='mo_id.construction_type', readonly=True)
    available_contractor_ids = fields.Many2many(
        'res.partner', compute='_compute_available_contractor_ids',
        string='Original Contractors',
    )
    contractor_id = fields.Many2one('res.partner', string='Original Contractor', required=True,
                                    domain="[('id', 'in', available_contractor_ids)]")
    pending_qty = fields.Integer(string='Pending Inspection', compute='_compute_pending_qty')
    qty_pass = fields.Integer(string='Pass Qty')
    qty_fail = fields.Integer(string='Fail Qty (Repair)')
    qty_scrap = fields.Integer(string='Scrap / Write-off Qty')
    repair_defect_type = fields.Selection(
        [('bad_stitching', 'Bad Stitching'), ('missing_panel', 'Missing Panel'),
         ('missing_bladder', 'Missing Bladder'), ('other', 'Other')],
        string='Repair Defect Type',
        help='Why the Fail quantity needs repair — recorded on the repair dispatch.',
    )
    scrap_defect_type = fields.Selection(
        [('bad_stitching', 'Bad Stitching'), ('missing_panel', 'Missing Panel'),
         ('missing_bladder', 'Missing Bladder'), ('other', 'Other')],
        string='Scrap / Write-off Reason',
        help='Why the Scrap quantity is being written off — recorded on the scrap record.',
    )
    repair_contractor_id = fields.Many2one(
        'res.partner', string='Repair Contractor',
        domain="[('is_contractor', '=', True)]",
    )
    notes = fields.Char(string='Notes')

    @api.depends('workorder_id')
    def _compute_available_contractor_ids(self):
        for wiz in self:
            wiz.available_contractor_ids = self.env['reema.ilo.dispatch']._ilo_original_contractors_for_mo(
                wiz.workorder_id.production_id.id
            )

    @api.depends('contractor_id', 'workorder_id')
    def _compute_pending_qty(self):
        for wiz in self:
            if wiz.contractor_id and wiz.workorder_id.production_id:
                wiz.pending_qty = self.env['reema.ilo.dispatch']._ilo_qc_pending_balance(
                    wiz.workorder_id.production_id.id, wiz.contractor_id.id
                )
            else:
                wiz.pending_qty = 0

    def action_confirm(self):
        self.ensure_one()
        if not self.contractor_id:
            raise UserError('Please select the original contractor.')
        if self.qty_pass < 0 or self.qty_fail < 0 or self.qty_scrap < 0:
            raise UserError('Quantities cannot be negative.')
        total = self.qty_pass + self.qty_fail + self.qty_scrap
        if total <= 0:
            raise UserError('Enter at least one quantity before confirming.')
        pending = self.env['reema.ilo.dispatch']._ilo_qc_pending_balance(
            self.workorder_id.production_id.id, self.contractor_id.id
        )
        if total > pending:
            raise UserError(
                f'Only {pending} balls are currently pending inspection for '
                f'{self.contractor_id.name} on this MO — cannot process {total}.'
            )
        repair_rate = None
        if self.qty_fail > 0:
            if self.construction_type != 'hs':
                raise UserError(
                    'The ILO repair-dispatch mechanism only applies to HS (hand-stitched) '
                    'construction. Balls on this MO cannot be sent to repair from here.'
                )
            if not self.repair_contractor_id:
                raise UserError('Select a repair contractor before logging a Fail quantity.')
            if not self.repair_defect_type:
                raise UserError('Select a repair defect type before logging a Fail quantity.')
            repair_rate = self.env['reema.piece.rate'].search([
                ('workcenter_id.is_ilo', '=', True), ('work_type', '=ilike', 'Repair'),
            ], limit=1)
            if not repair_rate:
                raise UserError(
                    'No "Repair" piece rate is configured on the ILO Center work center. '
                    'Create one under Manufacturing → Configuration → Piece Rates before '
                    'logging a Fail quantity.'
                )
        if self.qty_scrap > 0 and not self.scrap_defect_type:
            raise UserError('Select a scrap/write-off reason before logging a Scrap quantity.')

        wo = self.workorder_id
        mo = wo.production_id

        # Always log one batch entry for this decision — even a 0-pass decision
        # (all repair/scrap) needs a clickable record for this contractor+MO, since
        # the QC summary (received/passed/repair/scrap) shown on it is computed
        # live from the dispatch/scrap/receive tables, not snapshotted here. Payable
        # rate comes from the original Stitching Center Issuance line — Initial QC
        # is where ILO production is actually billed, but the rate was fixed when
        # the balls were dispatched to the contractor.
        stitch_dispatch = self.env['reema.ilo.dispatch'].search([
            ('mo_id', '=', mo.id),
            ('dispatch_type', '=', 'stitching'),
            ('contractor_id', '=', self.contractor_id.id),
        ], limit=1)
        entry_vals = {
            'workorder_id': wo.id,
            'contractor_id': self.contractor_id.id,
            'qty': self.qty_pass,
            'piece_rate_id': stitch_dispatch.batch_entry_id.piece_rate_id.id,
            'notes': self.notes,
        }
        if not self.qty_pass:
            entry_vals['payment_excluded'] = True
            entry_vals['exclusion_reason'] = 'No balls passed at this Initial QC decision — nothing payable'
        entry = self.env['reema.wo.batch.entry'].create(entry_vals)

        if self.qty_fail > 0:
            self.env['reema.ilo.dispatch'].create({
                'mo_id': mo.id,
                'contractor_id': self.repair_contractor_id.id,
                'dispatch_type': 'repair',
                'repair_source': 'initial_qc',
                'original_contractor_id': self.contractor_id.id,
                'qty_balls': self.qty_fail,
                'rate': repair_rate.rate,
                'ball_size': mo.ball_size,
                'construction_type': mo.construction_type,
                'dispatched_by': self.env.user.id,
                'defect_type': self.repair_defect_type,
                'notes': self.notes,
                'batch_entry_id': entry.id,
            })

        if self.qty_scrap > 0:
            self.env['reema.ilo.qc.scrap'].create({
                'mo_id': mo.id,
                'workorder_id': wo.id,
                'contractor_id': self.contractor_id.id,
                'qty': self.qty_scrap,
                'defect_type': self.scrap_defect_type,
                'recorded_by': self.env.user.id,
                'notes': self.notes,
                'batch_entry_id': entry.id,
            })

        mo._message_log(
            body=f'Initial QC — {self.contractor_id.name}: {self.qty_pass} passed, '
                 f'{self.qty_fail} sent to repair'
                 + (f' ({self.repair_contractor_id.name})' if self.qty_fail else '')
                 + f', {self.qty_scrap} scrapped.'
        )


class ReemaFinalQcWizard(models.TransientModel):
    """Final QC — self-contained repair loop, distinct from Initial QC's. A
    failed ball here is dispatched straight to a repair contractor and
    received back at Final QC directly (see ReemaFinalQcReceiveWizard) —
    never routed back to Initial QC. HS/ILO only, same as Initial QC's own
    repair mechanism."""
    _name = 'reema.final.qc.wizard'
    _description = 'Final QC — Pass / Repair / Scrap'

    workorder_id = fields.Many2one('mrp.workorder', string='Work Order',
                                   required=True, readonly=True)
    workorder_name = fields.Char(related='workorder_id.name', string='Work Order', readonly=True)
    mo_id = fields.Many2one(related='workorder_id.production_id', string='Manufacturing Order', readonly=True)
    workcenter_name = fields.Char(related='workorder_id.workcenter_id.name', string='Hall', readonly=True)
    construction_type = fields.Selection(related='mo_id.construction_type', readonly=True)
    available_contractor_ids = fields.Many2many(
        'res.partner', compute='_compute_available_contractor_ids',
        string='Stitching Contractors',
        help='Contractors who received a Stitching Center Issuance dispatch on this MO.',
    )
    contractor_id = fields.Many2one(
        'res.partner', string='Original Contractor',
        domain="[('id', 'in', available_contractor_ids)]",
        help='Only needed when logging a Fail (repair) or Scrap quantity — most '
             'batches at Final QC pass clean and need no contractor at all. '
             'Restricted to contractors who actually stitched on this MO; exactly '
             'which one a given fault traces back to is identified manually — Final '
             'QC has no automatic lineage through the halls in between, staff trace '
             'it from the Initial QC record/paperwork.',
    )
    pending_repair_return_qty = fields.Integer(
        string='Pending Re-Inspection (Repair Returns)', compute='_compute_pending_repair_return_qty',
        help='Balls returned from a Final QC repair job for this contractor, not yet '
             're-decided. Does NOT include first-time balls reaching Final QC for the '
             'first time — those are not tracked per original contractor before they '
             'get here, so there is no automatic cap for them here.',
    )
    qty_pass = fields.Integer(string='Pass Qty')
    qty_fail = fields.Integer(string='Fail Qty (Repair)')
    qty_scrap = fields.Integer(string='Scrap / Write-off Qty')
    repair_defect_type = fields.Selection(
        [('bad_stitching', 'Bad Stitching'), ('missing_panel', 'Missing Panel'),
         ('missing_bladder', 'Missing Bladder'), ('other', 'Other')],
        string='Repair Defect Type',
        help='Why the Fail quantity needs repair — recorded on the repair dispatch.',
    )
    scrap_defect_type = fields.Selection(
        [('bad_stitching', 'Bad Stitching'), ('missing_panel', 'Missing Panel'),
         ('missing_bladder', 'Missing Bladder'), ('other', 'Other')],
        string='Scrap / Write-off Reason',
        help='Why the Scrap quantity is being written off — recorded on the scrap record.',
    )
    repair_contractor_id = fields.Many2one(
        'res.partner', string='Repair Contractor',
        domain="[('is_contractor', '=', True)]",
    )
    notes = fields.Char(string='Notes')

    @api.depends('workorder_id')
    def _compute_available_contractor_ids(self):
        for wiz in self:
            wiz.available_contractor_ids = self.env['reema.ilo.dispatch']._ilo_original_contractors_for_mo(
                wiz.workorder_id.production_id.id
            )

    @api.depends('contractor_id', 'workorder_id')
    def _compute_pending_repair_return_qty(self):
        for wiz in self:
            if wiz.contractor_id and wiz.workorder_id.production_id:
                wiz.pending_repair_return_qty = self.env['reema.ilo.dispatch']._final_qc_repair_pending_balance(
                    wiz.workorder_id.production_id.id, wiz.contractor_id.id
                )
            else:
                wiz.pending_repair_return_qty = 0

    def action_confirm(self):
        self.ensure_one()
        if self.qty_pass < 0 or self.qty_fail < 0 or self.qty_scrap < 0:
            raise UserError('Quantities cannot be negative.')
        total = self.qty_pass + self.qty_fail + self.qty_scrap
        if total <= 0:
            raise UserError('Enter at least one quantity before confirming.')
        if (self.qty_fail > 0 or self.qty_scrap > 0) and not self.contractor_id:
            raise UserError(
                'Select the original contractor before logging a repair or scrap quantity — '
                'balls that just pass clean don\'t need one.'
            )
        repair_rate = None
        if self.qty_fail > 0:
            if self.construction_type != 'hs':
                raise UserError(
                    'The Final QC repair mechanism only applies to HS (hand-stitched) '
                    'construction. Balls on this MO cannot be sent to repair from here.'
                )
            if not self.repair_contractor_id:
                raise UserError('Select a repair contractor before logging a Fail quantity.')
            if not self.repair_defect_type:
                raise UserError('Select a repair defect type before logging a Fail quantity.')
            repair_rate = self.env['reema.piece.rate'].search([
                ('workcenter_id.is_ilo', '=', True), ('work_type', '=ilike', 'Repair'),
            ], limit=1)
            if not repair_rate:
                raise UserError(
                    'No "Repair" piece rate is configured on the ILO Center work center. '
                    'Create one under Manufacturing → Configuration → Piece Rates before '
                    'logging a Fail quantity.'
                )
        if self.qty_scrap > 0 and not self.scrap_defect_type:
            raise UserError('Select a scrap/write-off reason before logging a Scrap quantity.')

        wo = self.workorder_id
        mo = wo.production_id

        # Cap: Pass + Fail + Scrap here can't exceed what the previous hall (e.g.
        # Cleaning) actually produced. Repair-returns received back at Final QC
        # (ReemaFinalQcReceiveWizard, ilo_dispatch_type='repair') are the same
        # physical balls cycling back, not new arrivals, so they're excluded from
        # both sides of the comparison — same reasoning as qty_batch_completed's
        # own exclusion at the Ball Receive Point.
        predecessors = wo.blocked_by_workorder_ids.filtered(lambda p: p.state not in ('done', 'cancel'))
        if predecessors:
            predecessor_output = sum(predecessors.mapped('qty_balls_completed'))
            already_consumed = sum(
                wo.batch_entry_ids.filtered(lambda e: e.ilo_dispatch_type != 'repair').mapped('qty_balls')
            )
            already_consumed += sum(self.env['reema.ilo.dispatch'].search([
                ('mo_id', '=', mo.id), ('dispatch_type', '=', 'repair'),
                ('repair_source', '=', 'final_qc'),
            ]).mapped('qty_balls'))
            already_consumed += sum(self.env['reema.ilo.qc.scrap'].search([
                ('mo_id', '=', mo.id), ('workorder_id', '=', wo.id),
            ]).mapped('qty'))
            available_balls = predecessor_output - already_consumed
            if wo._units_to_balls(total) > available_balls + 0.001:
                raise UserError(
                    f'Cannot log {total} balls at Final QC.\n\n'
                    f'{", ".join(predecessors.mapped("workcenter_id.name"))} has produced '
                    f'{predecessor_output:.0f} balls.\n\n'
                    f'{already_consumed:.0f} already passed/repaired/scrapped here.\n\n'
                    f'Maximum you can log now: {available_balls:.0f}.'
                )

        if self.qty_pass > 0:
            # Payment for the underlying stitching work was already settled earlier
            # in the line (billed off the Initial QC pass entry) — Final QC's own
            # pass entry is progress tracking only, not a new payable event.
            self.env['reema.wo.batch.entry'].create({
                'workorder_id': wo.id,
                'contractor_id': self.contractor_id.id,
                'qty': self.qty_pass,
                'notes': self.notes,
                'payment_excluded': True,
                'exclusion_reason': 'Final QC pass — stitching payment already settled earlier in the line',
            })

        if self.qty_fail > 0:
            self.env['reema.ilo.dispatch'].create({
                'mo_id': mo.id,
                'contractor_id': self.repair_contractor_id.id,
                'dispatch_type': 'repair',
                'repair_source': 'final_qc',
                'original_contractor_id': self.contractor_id.id,
                'qty_balls': self.qty_fail,
                'rate': repair_rate.rate,
                'ball_size': mo.ball_size,
                'construction_type': mo.construction_type,
                'dispatched_by': self.env.user.id,
                'defect_type': self.repair_defect_type,
                'notes': self.notes,
            })

        if self.qty_scrap > 0:
            scrap = self.env['reema.ilo.qc.scrap'].create({
                'mo_id': mo.id,
                'workorder_id': wo.id,
                'contractor_id': self.contractor_id.id,
                'qty': self.qty_scrap,
                'defect_type': self.scrap_defect_type,
                'recorded_by': self.env.user.id,
                'notes': self.notes,
            })
            self.env['reema.ilo.contractor.deduction'].create({
                'original_contractor_id': self.contractor_id.id,
                'deduction_type': 'scrap',
                'mo_id': mo.id,
                'qty': self.qty_scrap,
                'construction_type': mo.construction_type,
                'scrap_id': scrap.id,
                'notes': 'Material cost — enter amount when preparing the contractor bill.',
            })

        contractor_part = f' (original contractor: {self.contractor_id.name})' if self.contractor_id else ''
        mo._message_log(
            body=f'Final QC — {self.qty_pass} passed'
                 + (f', {self.qty_fail} sent to repair ({self.repair_contractor_id.name})' if self.qty_fail else '')
                 + (f', {self.qty_scrap} scrapped' if self.qty_scrap else '')
                 + f'{contractor_part}.'
        )


class ReemaFinalQcReceiveWizard(models.TransientModel):
    """Receive a repaired ball back directly at Final QC — the repair loop
    Final QC runs itself, never touching Initial QC. Confirming this creates
    ONE batch entry that serves two purposes at once: it's the repair
    contractor's own payable record (billable through the normal Batch Logs
    flow, tracked via its own is_billed), and — tagged ilo_dispatch_type=
    'repair' — the marker that these balls are back and awaiting a fresh
    Pass/Fail/Scrap decision at Final QC. It also creates the pending
    deduction against the original contractor for the repair charge."""
    _name = 'reema.final.qc.receive.wizard'
    _description = 'Receive Repaired Ball (Final QC)'

    workorder_id = fields.Many2one('mrp.workorder', string='Work Order',
                                   required=True, readonly=True)
    workorder_name = fields.Char(related='workorder_id.name', string='Work Order', readonly=True)
    mo_id = fields.Many2one(related='workorder_id.production_id', string='Manufacturing Order', readonly=True)
    workcenter_name = fields.Char(related='workorder_id.workcenter_id.name', string='Hall', readonly=True)
    available_contractor_ids = fields.Many2many(
        'res.partner', compute='_compute_available_contractor_ids',
        string='Repair Contractors',
        help='Contractors with an outstanding Final QC repair dispatch on this MO.',
    )
    contractor_id = fields.Many2one('res.partner', string='Repair Contractor', required=True,
                                    domain="[('id', 'in', available_contractor_ids)]")
    available_original_contractor_ids = fields.Many2many(
        'res.partner', compute='_compute_available_original_contractor_ids',
        string='Available Original Contractors',
        help='Contractors whose balls were sent to this repair contractor from Final '
             'QC on this MO — restricts Original Contractor to only real repair links '
             'instead of every partner.',
    )
    original_contractor_id = fields.Many2one(
        'res.partner', string='Original Contractor', required=True,
        domain="[('id', 'in', available_original_contractor_ids)]",
        options={'no_create': True, 'no_edit': True},
        help='Whose stitching this repair charge is against — auto-filled from the '
             'dispatch unless this repair contractor has jobs for more than one '
             'original contractor open on this MO at once.',
    )
    balance_display = fields.Integer(string='Outstanding', compute='_compute_balance_display')
    qty = fields.Integer(string='Quantity Received')
    qty_warning = fields.Char(string='Quantity Warning', compute='_compute_qty_warning')
    notes = fields.Char(string='Notes')

    @api.depends('workorder_id')
    def _compute_available_contractor_ids(self):
        for wiz in self:
            wiz.available_contractor_ids = self.env['reema.ilo.dispatch'].search([
                ('mo_id', '=', wiz.workorder_id.production_id.id),
                ('dispatch_type', '=', 'repair'),
                ('repair_source', '=', 'final_qc'),
            ]).mapped('contractor_id')

    @api.depends('contractor_id', 'workorder_id')
    def _compute_available_original_contractor_ids(self):
        for wiz in self:
            if wiz.contractor_id and wiz.workorder_id.production_id:
                wiz.available_original_contractor_ids = self.env['reema.ilo.dispatch'].search([
                    ('mo_id', '=', wiz.workorder_id.production_id.id),
                    ('dispatch_type', '=', 'repair'),
                    ('repair_source', '=', 'final_qc'),
                    ('contractor_id', '=', wiz.contractor_id.id),
                ]).mapped('original_contractor_id')
            else:
                wiz.available_original_contractor_ids = False

    @api.onchange('contractor_id')
    def _onchange_contractor_default_original(self):
        if self.contractor_id and self.workorder_id.production_id:
            candidates = self.env['reema.ilo.dispatch'].search([
                ('mo_id', '=', self.workorder_id.production_id.id),
                ('dispatch_type', '=', 'repair'),
                ('repair_source', '=', 'final_qc'),
                ('contractor_id', '=', self.contractor_id.id),
            ]).mapped('original_contractor_id')
            self.original_contractor_id = candidates[0] if len(candidates) == 1 else False
        else:
            self.original_contractor_id = False

    @api.depends('contractor_id', 'original_contractor_id', 'workorder_id')
    def _compute_balance_display(self):
        for wiz in self:
            if wiz.contractor_id and wiz.original_contractor_id and wiz.workorder_id.production_id:
                wiz.balance_display = self.env['reema.ilo.dispatch']._final_qc_repair_outstanding(
                    wiz.workorder_id.production_id.id, wiz.contractor_id.id, wiz.original_contractor_id.id
                )
            else:
                wiz.balance_display = 0

    @api.depends('qty', 'balance_display')
    def _compute_qty_warning(self):
        for wiz in self:
            if wiz.qty > 0 and wiz.qty > wiz.balance_display:
                wiz.qty_warning = (
                    f'Only {wiz.balance_display} balls are currently outstanding — '
                    f'this will be rejected on Save.'
                )
            else:
                wiz.qty_warning = False

    def action_confirm(self):
        self.ensure_one()
        if not self.contractor_id:
            raise UserError('Please select the repair contractor.')
        if not self.original_contractor_id:
            raise UserError('Select the original contractor these balls belong to.')
        if self.qty <= 0:
            raise UserError('Enter a quantity received before confirming.')
        outstanding = self.env['reema.ilo.dispatch']._final_qc_repair_outstanding(
            self.workorder_id.production_id.id, self.contractor_id.id, self.original_contractor_id.id
        )
        if self.qty > outstanding:
            raise UserError(
                f'Only {outstanding} balls are currently outstanding for '
                f'{self.contractor_id.name} on this MO — cannot receive {self.qty}.'
            )
        repair_rate = self.env['reema.piece.rate'].search([
            ('workcenter_id.is_ilo', '=', True), ('work_type', '=ilike', 'Repair'),
        ], limit=1)
        if not repair_rate:
            raise UserError(
                'No "Repair" piece rate is configured on the ILO Center work center. '
                'Create one under Manufacturing → Configuration → Piece Rates before confirming.'
            )
        wo = self.workorder_id
        mo = wo.production_id
        notes = f'Final QC repair receive: {self.qty} balls received'
        if self.notes:
            notes += f' — {self.notes}'
        entry = self.env['reema.wo.batch.entry'].create({
            'workorder_id': wo.id,
            'contractor_id': self.contractor_id.id,
            'original_contractor_id': self.original_contractor_id.id,
            'ilo_dispatch_type': 'repair',
            'qty': self.qty,
            'piece_rate_id': repair_rate.id,
            'notes': notes,
        })
        self.env['reema.ilo.contractor.deduction'].create({
            'original_contractor_id': self.original_contractor_id.id,
            'deduction_type': 'repair',
            'mo_id': mo.id,
            'qty': self.qty,
            'construction_type': mo.construction_type,
            'rate': repair_rate.rate,
            'amount': self.qty * repair_rate.rate,
            'repair_batch_entry_id': entry.id,
        })
        mo._message_log(
            body=f'Final QC repair receive — {self.contractor_id.name} returned {self.qty} '
                 f'balls (original contractor: {self.original_contractor_id.name}).'
        )


class AccountMoveLineExt(models.Model):
    _inherit = 'account.move.line'

    reema_batch_entry_id = fields.Many2one(
        'reema.wo.batch.entry', string='Batch Entry', readonly=True, copy=False,
    )
    reema_mo_id = fields.Many2one(
        related='reema_batch_entry_id.mo_id', string='MO', store=True, readonly=True,
    )
    reema_po_id = fields.Many2one(
        related='reema_batch_entry_id.reema_po_id', string='PO', store=True, readonly=True,
    )
    reema_product_id = fields.Many2one(
        related='reema_batch_entry_id.mo_id.product_id', string='Product', store=True, readonly=True,
    )
    reema_balls_qty = fields.Float(string='Ball Qty', digits=(16, 2), readonly=True, copy=False)
    reema_impressions_per_ball = fields.Float(string='Imp/Ball', digits=(16, 4), readonly=True, copy=False)



class AccountMoveExt(models.Model):
    _inherit = 'account.move'

    def write(self, vals):
        # Identify which batch entries are linked to lines being deleted.
        # Must be done BEFORE super() so that a rollback cannot undo the release.
        deleted_line_ids = {
            cmd[1]
            for cmd in (vals.get('invoice_line_ids') or [])
            if isinstance(cmd, (list, tuple)) and len(cmd) >= 2 and cmd[0] == 2
        }
        entries_to_release = self.env['reema.wo.batch.entry']
        if deleted_line_ids:
            lines = self.env['account.move.line'].browse(deleted_line_ids)
            entries_to_release = lines.mapped('reema_batch_entry_id').filtered('id')

        res = super().write(vals)

        # Block saving a contractor bill that has been left with no lines.
        # UserError triggers a full rollback — no empty bill reaches the DB,
        # and entries remain billed until the user uses Delete Bill instead.
        if deleted_line_ids and entries_to_release:
            for move in self:
                if move.state == 'draft' and not move.invoice_line_ids:
                    raise UserError(
                        'Cannot save: this bill has no remaining lines.\n\n'
                        'Use the "Delete Bill" button to delete this bill — '
                        'all batch entries will be released back to unbilled automatically.'
                    )

        if entries_to_release:
            entries_to_release.write({'is_billed': False, 'bill_id': False})

        return res

    def action_delete_contractor_bill(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError('Only draft bills can be deleted this way.')
        self.invoice_line_ids.mapped('reema_batch_entry_id').filtered('id').write({
            'is_billed': False, 'bill_id': False,
        })
        self.unlink()
        return self.env.ref('reema_accounting.action_contractor_bills').read()[0]

    batch_entry_ids = fields.One2many(
        'reema.wo.batch.entry', 'bill_id', string='Batch Entries', readonly=True
    )
    is_printing_bill = fields.Boolean(
        string='Printing Bill',
        compute='_compute_is_printing_bill',
        store=True,
    )

    @api.depends('batch_entry_ids.workorder_id.workcenter_id.is_printing')
    def _compute_is_printing_bill(self):
        for move in self:
            move.is_printing_bill = any(
                e.workorder_id.workcenter_id.is_printing
                for e in move.batch_entry_ids
            )
    reema_bill_state = fields.Selection([
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
    ], string='Approval',
       compute='_compute_reema_bill_state',
       inverse='_set_reema_bill_state')

    @api.depends('checked')
    def _compute_reema_bill_state(self):
        for move in self:
            move.reema_bill_state = 'confirmed' if move.checked else 'pending'

    def _set_reema_bill_state(self):
        for move in self:
            move.checked = (move.reema_bill_state == 'confirmed')

    def action_reema_confirm(self):
        for move in self:
            if move.state != 'draft':
                raise UserError('Only draft bills can be confirmed.')
        self.write({'checked': True})

    def action_reema_reset_to_pending(self):
        for move in self:
            if move.state != 'draft':
                raise UserError('Cannot reset a posted bill.')
        self.write({'checked': False})

    def _get_move_display_name(self, show_ref=False):
        # Contractor bills: show just the bill number — no "Draft Bill" prefix
        if self.batch_entry_ids:
            name = self.name if self.name and self.name != '/' else '/'
            if show_ref and self.ref:
                name += f' ({self.ref})'
            return name
        return super()._get_move_display_name(show_ref=show_ref)
