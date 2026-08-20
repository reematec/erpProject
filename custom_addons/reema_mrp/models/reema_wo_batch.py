from markupsafe import Markup
from odoo import models, fields, api, tools, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_round, float_is_zero
from .reema_repair import DEFECT_TYPE_SELECTION, EDGE_CASE_DEFECT_TYPES


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
    repair_job_id = fields.Many2one(
        'reema.repair.job', string='Repair Job', readonly=True,
        help='Hybrid/machine-stitched QC only: set on the Fail-quantity entry logged '
             'at Initial/Final QC when the ball is sent to Shell Closing for repair — '
             'nets this quantity out of Balls Done until the repair job is received, '
             'same live-balance approach as the ILO repair loop.',
    )
    repair_count = fields.Integer(
        string='Number of Repairs', default=0,
        help='Repair-purpose Initial QC Pass entries only: total repair count carried '
             'over from the originating dispatch(es) — this, not qty_balls, is what '
             '_calc_amount pays the repair contractor for, since a ball can need more '
             'than one repair.',
    )
    is_initial_qc_entry = fields.Boolean(compute='_compute_qc_summary')
    is_final_qc_entry = fields.Boolean(related='workorder_id.workcenter_id.is_final_qc', readonly=True)
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
        string='Fail Balls', compute='_compute_qc_summary',
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
    # Initial or Final QC wizard submission as this entry. Matched live at read
    # time by create_date (records created in the same action_confirm() call
    # share the same transaction timestamp down to the microsecond) plus
    # contractor, OR by the explicit batch_entry_id link the wizards set going
    # forward — no backfill/migration needed, this works for entries logged
    # before that link existed too since it's a plain search, not a stored value.
    entry_repair_qty = fields.Integer(string='Repair Qty (this entry)', compute='_compute_entry_qc_outcome')
    entry_repair_defect_types = fields.Char(string='Repair Reason (this entry)', compute='_compute_entry_qc_outcome')
    entry_scrap_qty = fields.Integer(string='Scrap Qty (this entry)', compute='_compute_entry_qc_outcome')
    entry_scrap_defect_types = fields.Char(string='Scrap Reason (this entry)', compute='_compute_entry_qc_outcome')

    def _compute_entry_qc_outcome(self):
        Dispatch = self.env['reema.ilo.dispatch']
        Scrap = self.env['reema.ilo.qc.scrap']
        defect_labels = dict(Dispatch._fields['defect_type'].selection)
        for entry in self:
            wc = entry.workorder_id.workcenter_id
            repair_source = 'initial_qc' if wc.is_initial_qc else 'final_qc' if wc.is_final_qc else False
            if not repair_source or not entry.contractor_id:
                entry.entry_repair_qty = 0
                entry.entry_repair_defect_types = False
                entry.entry_scrap_qty = 0
                entry.entry_scrap_defect_types = False
                continue
            repairs = Dispatch.search([
                ('dispatch_type', '=', 'repair'), ('repair_source', '=', repair_source),
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
            # original_contractor_id, not contractor_id — for a repair-purpose
            # entry, contractor_id is who got PAID (the repair contractor),
            # but this summary is about the original contractor's production.
            # Falls back to contractor_id for legacy rows predating that field.
            contractor_id = entry.original_contractor_id.id or entry.contractor_id.id
            entry.qc_received_qty = sum(BatchEntry.search([
                ('workorder_id.production_id', '=', mo_id),
                ('workorder_id.workcenter_id.is_ball_receive_point', '=', True),
                ('original_contractor_id', '=', contractor_id),
            ]).mapped('qty'))
            # original_contractor_id (with a legacy-row fallback to contractor_id,
            # since old rows predate the field) — NOT contractor_id alone, or a
            # repair-purpose pass entry (contractor_id = repair contractor) would
            # be invisible here.
            entry.qc_pass_qty = sum(BatchEntry.search([
                ('workorder_id.production_id', '=', mo_id),
                ('workorder_id.workcenter_id.is_initial_qc', '=', True),
                '|',
                    ('original_contractor_id', '=', contractor_id),
                    '&', ('original_contractor_id', '=', False), ('contractor_id', '=', contractor_id),
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

    def _printing_total_balls(self, mo_ids):
        """Sum of Printing-hall balls completed across the given MOs."""
        total = 0.0
        for mo in mo_ids:
            printing_wo = mo.workorder_ids.filtered(lambda w: w.workcenter_id.is_printing)
            total += sum(printing_wo.mapped('qty_balls_completed'))
        return total

    def _printing_low_qty_active(self, grouped=False):
        """True when this printing-hall entry's order (or, if grouped=True, its
        order plus every order linked via "Printed Together With") totals at or
        below the hall's configurable threshold.

        grouped=False is used for the live in-progress preview (amount_earned) —
        deliberately ignores any grouping, since that can be set up right before
        billing and shouldn't make the running total flicker mid-production.
        grouped=True is the authoritative check, used only at the moment a
        contractor bill is generated (see action_create_contractor_bill)."""
        wo = self.workorder_id
        wc = wo.workcenter_id
        if not wc.is_printing:
            return False
        threshold = wc.printing_low_qty_threshold or 0.0
        mo = wo.production_id
        mo_ids = (mo | mo.reema_printing_group_ids) if grouped else mo
        return self._printing_total_balls(mo_ids) <= threshold

    def _reema_expense_account(self):
        """The WIP Labor Account to bill this entry against — the work
        center's own wip_labor_account_id. Initial QC and Final QC are
        configured the same way as every other hall, even though they're
        employee-staffed: a repair contractor's pass/fail/scrap decision is
        logged against that QC hall's own work order (that's where the
        inspection happens), so the hall still needs a real account set to
        bill the contractor for it.

        Deliberately NOT expense_account_id — that one is reserved for scrap
        deductions only (see account_move_ext.py), which must stay an
        immediate P&L hit since scrapped work never reaches Finished Goods.
        A normal bill line here is order-traceable work in progress, so it's
        deferred instead: this method name/call sites are unchanged, only the
        account it resolves to.
        """
        self.ensure_one()
        return self.workorder_id.workcenter_id.wip_labor_account_id

    def _pay_rate_and_qty(self, grouped=False):
        """(rate, quantity) this entry is paid on — single source of truth shared
        by amount_earned and contractor bill line generation.

        grouped=False (the default, used for the live preview) checks this
        entry's own order only. grouped=True (used only at bill-generation time)
        also folds in every order it's linked to via "Printed Together With" —
        see _printing_low_qty_active for why the two are kept separate."""
        self.ensure_one()
        # Repair-purpose Pass entries: a ball can need more than one repair, so pay
        # is repair-count based, not ball-count based. repair_count is carried over
        # from the originating dispatch(es) at confirm time (see ReemaIloQcWizard).
        # Falls through to the normal ball-based calc for legacy rows with no
        # repair_count recorded (pre-dating this field).
        if self.ilo_dispatch_type == 'repair' and self.repair_count:
            return self.piece_rate_id.rate or 0.0, self.repair_count
        wc = self.workorder_id.workcenter_id
        if self._printing_low_qty_active(grouped=grouped):
            rate = wc.printing_low_qty_rate_id.rate or 0.0
            return rate, self.qty_balls
        rate = self.piece_rate_id.rate or 0.0
        if (wc.pay_basis or 'ball') == 'ball':
            return rate, self.qty_balls
        ipu = self._impressions_per_ball()
        if ipu:
            return rate, self.qty_balls * ipu
        return rate, self.qty

    def _calc_amount(self):
        if self.payment_excluded:
            return 0.0
        rate, qty = self._pay_rate_and_qty(grouped=False)
        return rate * qty

    @api.depends(
        'piece_rate_id.rate', 'qty', 'qty_balls', 'payment_excluded', 'repair_count',
        'ilo_dispatch_type', 'workorder_id.workcenter_id.pay_basis',
        'workorder_id.workcenter_id.is_printing',
        'workorder_id.workcenter_id.printing_low_qty_threshold',
        'workorder_id.workcenter_id.printing_low_qty_rate_id.rate',
        'workorder_id.qty_balls_completed',
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
        Dispatch = self.env['reema.ilo.dispatch']
        Deduction = self.env['reema.ilo.contractor.deduction']
        QcScrap = self.env['reema.ilo.qc.scrap']
        ProdScrap = self.env['reema.production.scrap']
        for entry in self:
            if entry.is_billed:
                raise UserError(
                    f'Cannot delete "{entry.name}" — it has already been billed. '
                    'Remove it from the bill first.'
                )

            # Everything below is ILO/scrap side-effect cleanup — records this
            # entry's own action_confirm() created alongside it, which plain
            # stock reversal never touched (see reema_ilo.py's ON DELETE SET
            # NULL foreign keys — deleting the entry used to silently orphan
            # these instead of erroring or reversing them).
            own_lost_deductions = Deduction.search([
                ('batch_entry_id', '=', entry.id), ('deduction_type', '=', 'lost'),
            ])
            if own_lost_deductions:
                raise UserError(
                    f'Cannot delete "{entry.name}" — it includes a lost-ball report '
                    f'({own_lost_deductions[0].name}, charged to '
                    f'{own_lost_deductions[0].billed_to_id.name}). The Balls Lost '
                    'adjustment this made on the related dispatch record cannot be '
                    'automatically reversed — an administrator must correct that '
                    'dispatch and the deduction manually before this entry can be deleted.'
                )

            own_dispatches = Dispatch.search([('batch_entry_id', '=', entry.id)])
            for d in own_dispatches:
                if d.repair_count_consumed:
                    raise UserError(
                        f'Cannot delete "{entry.name}" — the repair job it dispatched to '
                        f'{d.contractor_id.name} has already been paid out at Initial/'
                        'Final QC. Delete that payable batch entry first, then this one.'
                    )
                if d.dispatch_type == 'stitching':
                    outstanding = Dispatch._ilo_ledger_balance_by_type(
                        entry.mo_id.id, d.contractor_id.id, 'stitching')
                elif d.repair_source == 'final_qc':
                    outstanding = Dispatch._final_qc_repair_outstanding(
                        entry.mo_id.id, d.contractor_id.id, d.original_contractor_id.id)
                else:
                    outstanding = Dispatch._ilo_repair_balance_by_original(
                        entry.mo_id.id, d.contractor_id.id, d.original_contractor_id.id)
                if outstanding - (d.qty_balls - d.qty_lost) < -0.001:
                    raise UserError(
                        f'Cannot delete "{entry.name}" — balls from its dispatch to '
                        f'{d.contractor_id.name} have already been received or processed '
                        'downstream. Reverse those entries first, then this one.'
                    )

            own_repair_deductions = Deduction.search([('repair_dispatch_id', 'in', own_dispatches.ids)])
            own_qc_scraps = QcScrap.search([('batch_entry_id', '=', entry.id)])
            own_scrap_deductions = Deduction.search([('scrap_id', 'in', own_qc_scraps.ids)])
            own_prod_scraps = ProdScrap.search([('batch_entry_id', '=', entry.id)])
            applied = (own_repair_deductions | own_scrap_deductions).filtered(lambda d: d.state == 'applied')
            if applied:
                raise UserError(
                    f'Cannot delete "{entry.name}" — {applied[0].name} has already been '
                    'applied to a contractor bill. Remove it from the bill first.'
                )
            if own_prod_scraps.filtered('is_billed'):
                raise UserError(
                    f'Cannot delete "{entry.name}" — its scrap record has already been billed.'
                )

            # This entry may itself have been the repair contractor's payable
            # Pass decision — free up whatever earlier dispatches it consumed
            # so their repair_count becomes claimable again if the decision is
            # redone (mirrors action_confirm's own repair_count_consumed flow).
            consumed_dispatches = Deduction.search(
                [('repair_batch_entry_id', '=', entry.id)]
            ).mapped('repair_dispatch_id')

            entry._reverse_stock_moves()
            own_repair_deductions.unlink()
            own_scrap_deductions.unlink()
            own_dispatches.unlink()
            own_qc_scraps.unlink()
            own_prod_scraps.unlink()
            if consumed_dispatches:
                consumed_dispatches.write({'repair_count_consumed': False})

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

        missing_low_qty_rate = self.filtered(
            lambda e: e._printing_low_qty_active(grouped=True)
            and not e.workorder_id.workcenter_id.printing_low_qty_rate_id
        )
        if missing_low_qty_rate:
            raise UserError(
                'The following printing entries qualify for the low-quantity flat '
                'rate (combined order total is at or below the threshold) but no '
                'Low-Qty Per-Ball Rate is set on the Printing work center:\n'
                + '\n'.join(missing_low_qty_rate.mapped('name'))
                + '\n\nGo to Manufacturing → Configuration → Work Centers and set the '
                'Low-Qty Per-Ball Rate on the Printing work center before billing.'
            )

        missing_account = self.filtered(lambda e: not e._reema_expense_account())
        if missing_account:
            wc_names = ', '.join(missing_account.mapped('workorder_id.workcenter_id.name'))
            raise UserError(
                f'The following work centers have no Labor Expense Account configured: {wc_names}\n'
                'Go to Manufacturing → Configuration → Work Centers and set the account.'
            )

        contractor = contractors
        if not contractor.is_contractor:
            contractor.is_contractor = True

        lines = []
        for entry in self.sorted('name'):
            wc = entry.workorder_id.workcenter_id
            rate, bill_qty = entry._pay_rate_and_qty(grouped=True)
            low_qty_active = wc.is_printing and entry._printing_low_qty_active(grouped=True)
            uom = entry.piece_rate_id.uom_id
            if low_qty_active and wc.printing_low_qty_rate_id.uom_id:
                uom = wc.printing_low_qty_rate_id.uom_id
            line_vals = {
                'name': entry.name,
                'quantity': bill_qty,
                'price_unit': rate,
                'account_id': entry._reema_expense_account().id,
                'reema_batch_entry_id': entry.id,
                'reema_uom_id': uom.id,
            }
            if wc.is_printing:
                line_vals['reema_balls_qty'] = entry.qty_balls
                line_vals['reema_impressions_per_ball'] = (
                    0.0 if low_qty_active else entry._impressions_per_ball()
                )
            lines.append((0, 0, line_vals))

        # Deductions against this contractor (ILO repair/lost charges + Final QC
        # scrap material cost, plus shop-floor production scrap e.g. Printing) —
        # linked to the bill via their own "Production Deductions" tab
        # (reema_ilo_deduction_ids / reema_scrap_deduction_ids on account.move),
        # NOT as invoice_line_ids rows — keeps them visually and functionally
        # separate from the actual production quantities being paid for.
        # Repair charges are fully computed already (qty x rate); scrap/lost
        # charges carry the qty/type but the amount is left for the preparer to
        # enter directly on that tab — there's no stored cost figure yet.
        pending_deductions = self.env['reema.ilo.contractor.deduction'].search([
            ('billed_to_id', '=', contractor.id),
            ('state', '=', 'pending'),
        ])

        # Contractor-hall production scrap (e.g. Printing) — same "enter cost
        # manually" pattern as the ILO scrap deduction above, sourced from
        # reema.production.scrap instead of the ILO-specific deduction model.
        # Employee-hall scrap (Shaping) never has contractor_id set, so it
        # never surfaces here — it isn't charged to anyone.
        pending_scrap = self.env['reema.production.scrap'].search([
            ('contractor_id', '=', contractor.id),
            ('is_billed', '=', False),
        ])

        # Hybrid/machine-stitched repair penalties — same "enter cost manually"
        # pattern for edge-case defect types; normal defect types already carry
        # a computed amount (qty x flat Repair rate). See reema_repair.py.
        pending_penalties = self.env['reema.repair.penalty'].search([
            ('fault_contractor_id', '=', contractor.id),
            ('is_billed', '=', False),
        ])

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
            # No _set_next_sequence() here: the bill stays "Draft" (no number
            # consumed) until posted. Odoo assigns the real BILL/26/#### number
            # automatically in _compute_name once state != 'draft'. This is what
            # lets Delete Bill work on any draft — a never-numbered bill leaves
            # no gap in the sequence when removed, unlike a numbered one (Odoo
            # blocks deleting any non-last numbered entry to protect the chain).
            move = self.env['account.move'].create({
                'move_type': 'in_invoice',
                'partner_id': contractor.id,
                'journal_id': journal.id,
                'invoice_date': fields.Date.today(),
                'invoice_line_ids': lines,
            })

        self.write({'is_billed': True, 'bill_id': move.id})
        pending_deductions.write({
            'state': 'applied', 'bill_id': move.id,
            'account_id': self[:1]._reema_expense_account().id,
        })
        pending_scrap.write({'is_billed': True, 'bill_id': move.id})
        pending_penalties.write({
            'is_billed': True, 'bill_id': move.id,
            'account_id': self[:1]._reema_expense_account().id,
        })

        # Opens as a new browser tab rather than navigating in-place, so the
        # Batch Logs list the user was working from stays open. An act_window
        # action dict can't do that (Odoo's action service only opens act_url
        # as a new tab), so this addresses the stored Contractor Bills action
        # by its real numeric id via the /odoo/action-<id>/<res_id> URL form.
        try:
            action_id = self.env.ref('reema_accounting.action_contractor_bills').id
        except Exception:
            action_id = False

        if action_id:
            return {
                'type': 'ir.actions.act_url',
                'url': f'/odoo/action-{action_id}/{move.id}',
                'target': 'new',
            }

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
    reema_product_id = fields.Many2one('product.product', related='mo_id.product_id',
                                       string='Product', store=True)
    reema_po_id = fields.Many2one('reema.production.order', related='mo_id.reema_po_id',
                                  string='PO', store=True)
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
    repair_job_id = fields.Many2one(
        'reema.repair.job', string='Repair Job', ondelete='set null',
        help='Set when this scrap entry came from a Repair Job partially '
             'resolved as unrepairable, instead of a normal QC/floor scrap.',
    )
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

    def action_return_to_pending(self):
        for scrap in self:
            if scrap.bill_id and (scrap.bill_id.state != 'draft' or scrap.bill_id.reema_bill_state != 'pending'):
                raise UserError(
                    f'Cannot remove {scrap.name} from its bill: the bill is '
                    'no longer in the drafting stage.'
                )
            scrap.bill_id.sudo().message_post(body=_(
                'Scrap deduction removed: %(name)s — PKR %(amount).2f'
            ) % {'name': scrap.name, 'amount': scrap.amount})
        self.write({'is_billed': False, 'bill_id': False})

    def action_apply_selected_to_bill(self):
        bill = self.env['account.move'].browse(self.env.context.get('reema_pick_bill_id', []))
        if not bill:
            raise UserError('No bill to add these deductions to.')
        if not self:
            raise UserError('Select at least one scrap entry to add.')
        if bill.state != 'draft' or bill.reema_bill_state != 'pending':
            raise UserError('This bill is no longer in the drafting stage.')
        self.write({'is_billed': True, 'bill_id': bill.id})
        bill.sudo().message_post(body=_(
            'Scrap deduction(s) added: %(lines)s'
        ) % {'lines': ', '.join(f'{s.name} — PKR {s.amount:.2f}' for s in self)})
        return {'type': 'ir.actions.act_window_close'}


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

    name = fields.Char(
        string='Reference', readonly=True,
        help='The underlying scrap record\'s own reference — blank for ILO QC '
             'scrap, which has no reference field of its own.',
    )
    date = fields.Datetime(string='Date', readonly=True)
    mo_id = fields.Many2one('mrp.production', string='Manufacturing Order', readonly=True)
    workorder_id = fields.Many2one('mrp.workorder', string='Work Order', readonly=True)
    workcenter_id = fields.Many2one('mrp.workcenter', string='Hall', readonly=True)
    source = fields.Selection(
        [('initial_qc', 'ILO Initial QC'), ('final_qc', 'ILO Final QC'),
         ('production', 'Production Floor')],
        string='Source', readonly=True,
    )
    contractor_id = fields.Many2one(
        'res.partner', string='Charged To', readonly=True,
        help='Contractor this scrap is chargeable against, if any — blank for '
             'employee-hall scrap (e.g. Shaping), which is never charged to anyone.',
    )
    hall_unit = fields.Selection(
        related='workcenter_id.hall_unit', string='UOM', readonly=True,
        help='qty is logged in whatever unit this hall uses (ball/panel/sheet) — '
             'shown alongside it so the same number isn\'t misread across halls '
             'with different logging units.',
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
                       combined.name,
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
                        NULL::varchar           AS name,
                        s.date::timestamp      AS date,
                        s.mo_id                AS mo_id,
                        s.workorder_id         AS workorder_id,
                        wo.workcenter_id       AS workcenter_id,
                        CASE WHEN wc.is_final_qc THEN 'final_qc' ELSE 'initial_qc' END
                                                AS source,
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
                    JOIN mrp_workcenter wc ON wc.id = wo.workcenter_id

                    UNION ALL

                    SELECT
                        p.name                   AS name,
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
    qty_balance = fields.Float(string='Balance', compute='_compute_qty_balance', readonly=True)
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

    qty_predecessor_balance = fields.Float(
        string='Available from Previous Hall', compute='_compute_qty_predecessor_balance', readonly=True,
        help='What the previous hall has produced so far minus what\'s already '
             'been processed here (good + scrap) — the real cap enforced below. '
             'Blank/0 for halls with no predecessor (first hall in the routing).',
    )

    @api.depends('workorder_id.qty_batch_completed', 'workorder_id.hall_qty')
    def _compute_qty_balance(self):
        for wiz in self:
            wiz.qty_balance = wiz.workorder_id.hall_qty - wiz.workorder_id.qty_batch_completed

    @api.depends('workorder_id.qty_balls_completed', 'workorder_id.qty_scrap_balls',
                 'workorder_id.blocked_by_workorder_ids.qty_balls_completed')
    def _compute_qty_predecessor_balance(self):
        # Separate from qty_balance (this hall's own remaining target) — this is
        # the OTHER cap: what the previous hall has actually delivered so far,
        # minus what's already been processed here. Same formula enforced as a
        # hard error in action_confirm below, shown here so a user isn't
        # surprised by that error — Balance alone (target-based) gave no hint
        # that almost nothing may actually be available yet.
        for wiz in self:
            wo = wiz.workorder_id
            predecessors = wo.blocked_by_workorder_ids.filtered(lambda p: p.state not in ('done', 'cancel'))
            if not predecessors:
                wiz.qty_predecessor_balance = 0.0
                continue
            predecessor_output = sum(predecessors.mapped('qty_balls_completed'))
            already_processed = wo.qty_balls_completed + wo.qty_scrap_balls
            wiz.qty_predecessor_balance = max(0.0, wo._balls_to_units(predecessor_output - already_processed))

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
    qty_lost = fields.Integer(
        string='Balls Reported Lost',
        help='Balls the contractor has reported as lost — never coming back. '
             'Independent of Quantity Received: either can be 0 as long as the '
             'other is not (a pure loss report with nothing physically arriving '
             'that day is valid). Charged to whoever lost it — the repair '
             'contractor for a repair return, the contractor themselves for their '
             'own stitching — not the original contractor whose batch it was '
             '(unless they are the same person).',
    )
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

    def _apply_lost_to_dispatches(self, dispatch_type, original_contractor_id=None):
        """Greedily attribute self.qty_lost across this contractor's open dispatches
        of the given type, oldest first. The exact per-dispatch split has no effect
        on any balance calculation (those only ever use the aggregate sum of
        qty_lost) — this is purely so a specific dispatch record shows where a loss
        happened, for traceability."""
        domain = [
            ('mo_id', '=', self.workorder_id.production_id.id),
            ('contractor_id', '=', self.contractor_id.id),
            ('dispatch_type', '=', dispatch_type),
        ]
        if original_contractor_id:
            domain.append(('original_contractor_id', '=', original_contractor_id))
        remaining = self.qty_lost
        for d in self.env['reema.ilo.dispatch'].search(domain, order='date, id'):
            if remaining <= 0:
                break
            capacity = d.qty_balls - d.qty_lost
            if capacity <= 0:
                continue
            take = min(capacity, remaining)
            d.qty_lost += take
            remaining -= take

    def action_confirm(self):
        self.ensure_one()
        if not self.contractor_id:
            raise UserError('Please select a contractor.')
        if self.qty < 0 or self.qty_lost < 0:
            raise UserError('Quantities cannot be negative.')
        if self.qty <= 0 and self.qty_lost <= 0:
            raise UserError('Enter a quantity received or a quantity lost before confirming.')
        if not self.receipt_purpose:
            raise UserError(
                f'{self.contractor_id.name} has both stitching and repair dispatches '
                f'open on this MO — select whether this receipt is their own stitching '
                f'return or a repair return.'
            )
        total = self.qty + self.qty_lost
        balance = self.env['reema.ilo.dispatch']._ilo_ledger_balance_by_type(
            self.workorder_id.production_id.id, self.contractor_id.id, self.receipt_purpose
        )
        if total > balance:
            purpose_label = 'stitching' if self.receipt_purpose == 'stitching' else 'repair'
            raise UserError(
                f'Only {balance:.0f} {purpose_label} balls are currently outstanding for '
                f'{self.contractor_id.name} on this MO — cannot account for {total} '
                f'(received {self.qty} + lost {self.qty_lost}).'
            )
        if not self.original_contractor_id:
            raise UserError('Select the original contractor these balls belong to.')
        if self.receipt_purpose == 'repair':
            pair_balance = self.env['reema.ilo.dispatch']._ilo_repair_balance_by_original(
                self.workorder_id.production_id.id, self.contractor_id.id, self.original_contractor_id.id
            )
            if total > pair_balance:
                raise UserError(
                    f'Only {pair_balance:.0f} repair balls are currently outstanding for '
                    f'{self.contractor_id.name} repairing {self.original_contractor_id.name}\'s balls '
                    f'on this MO — cannot account for {total} (received {self.qty} + lost {self.qty_lost}).'
                )
        wo = self.workorder_id
        mo = wo.production_id

        # Batch entry (if any physical qty arrived) is created FIRST so the
        # lost-ball deduction below can link back to it via batch_entry_id —
        # that link is what lets deleting this entry later detect and block on
        # an unreversible lost-ball charge instead of silently orphaning it.
        entry = self.env['reema.wo.batch.entry']
        if self.qty > 0:
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
                # Receive is just a holding stage — physical arrival only, no
                # judgment. Whether the repair contractor actually gets paid is
                # decided at Initial QC, not here (mirrors the stitching branch
                # below). The original contractor's deduction is NOT created here
                # any more — it's charged immediately when Initial QC issues the
                # repair (see ReemaIloQcWizard.action_confirm), on repair_count
                # rather than ball count, unambiguously tied to that one dispatch.
                # Receive deliberately stays partial-friendly (no "must return all"
                # block) — a repair contractor's returns only become visible/
                # payable to QC once the full dispatched amount for this pair is
                # back (see _ilo_qc_pending_balance_repair).
                repair_rate = self.env['reema.piece.rate'].search([
                    ('workcenter_id.is_ilo', '=', True), ('work_type', '=ilike', 'Repair'),
                ], limit=1)
                if not repair_rate:
                    raise UserError(
                        'No "Repair" piece rate is configured on the ILO Center work center. '
                        'Create one under Manufacturing → Configuration → Piece Rates before confirming.'
                    )
                vals['piece_rate_id'] = repair_rate.id
                vals['payment_excluded'] = True
                vals['exclusion_reason'] = 'ILO Repair — real payment recorded at Initial QC Pass'
            else:
                # Stitching returns stay provisional — the real payable amount for the
                # original contractor's own production is settled at Initial QC Pass,
                # not here.
                vals['payment_excluded'] = True
                vals['exclusion_reason'] = 'ILO — real payment recorded at Initial QC Pass'
            entry = self.env['reema.wo.batch.entry'].create(vals)

        if self.qty_lost > 0:
            # Repair: the repair contractor lost someone else's ball — they pay,
            # not the original contractor whose batch it was. Stitching: the
            # contractor lost their own ball — same person either way, no
            # charged_contractor_id override needed (billed_to_id falls back to
            # original_contractor_id, which already equals contractor_id here).
            original_scope = self.original_contractor_id.id if self.receipt_purpose == 'repair' else None
            self._apply_lost_to_dispatches(self.receipt_purpose, original_scope)
            self.env['reema.ilo.contractor.deduction'].create({
                'original_contractor_id': self.original_contractor_id.id,
                'charged_contractor_id': self.contractor_id.id if self.receipt_purpose == 'repair' else False,
                'deduction_type': 'lost',
                'mo_id': mo.id,
                'qty': self.qty_lost,
                'construction_type': mo.construction_type,
                'notes': f'Reported lost by {self.contractor_id.name}' + (f' — {self.notes}' if self.notes else ''),
                'batch_entry_id': entry.id if entry else False,
            })
            mo._message_log(
                body=f'ILO Receive — {self.contractor_id.name}: {self.qty_lost} ball(s) reported lost '
                     f'({self.receipt_purpose}, original contractor: {self.original_contractor_id.name}).'
            )
        return True


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
    available_returning_repair_contractor_ids = fields.Many2many(
        'res.partner', compute='_compute_available_returning_repair_contractor_ids',
        string='Available Repair Contractors',
        help='Contractors whose repaired balls (for this original contractor) are '
             'physically back at Ball Receive and still awaiting an Initial QC '
             'decision on this MO.',
    )
    returning_repair_contractor_id = fields.Many2one(
        'res.partner', string='Repair Contractor (Returned Work)',
        domain="[('id', 'in', available_returning_repair_contractor_ids)]",
        help='Whose repair work is being inspected this session — only asked when '
             'this original contractor has both a first-time batch and a repair '
             'return simultaneously pending inspection. Determines who is paid '
             'the repair fee if these balls pass.',
    )
    qc_stitching_open = fields.Boolean(compute='_compute_qc_flow_flags')
    qc_repair_open = fields.Boolean(compute='_compute_qc_flow_flags')
    inspection_purpose = fields.Selection(
        [('stitching', 'First-Time Stitching'), ('repair', 'Repair Return')],
        string='Inspection Purpose',
        help='Only needs to be picked when this original contractor has both a '
             'first-time batch and a repair return simultaneously pending '
             'inspection on this MO.',
    )
    pending_qty = fields.Integer(string='Pending Inspection (Total)', compute='_compute_pending_qty')
    pending_qty_stitching = fields.Integer(string='Pending — First-Time', compute='_compute_pending_qty')
    pending_qty_repair = fields.Integer(string='Pending — Repair Return', compute='_compute_pending_qty')
    qty_pass = fields.Integer(string='Pass Qty')
    qty_fail = fields.Integer(string='Fail Balls')
    repair_count = fields.Integer(
        string='Number of Repairs',
        help='Total individual repair marks across the Fail Qty balls — a single ball '
             'can need more than one repair. Must be at least Fail Qty. Drives the '
             'original contractor\'s deduction (charged now) and the repair '
             'contractor\'s eventual pay (repairs × rate, not balls × rate).',
    )
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
    def _compute_available_returning_repair_contractor_ids(self):
        # Use ._origin.id, not .id, on every relational id used inside a search()
        # domain here. On a live/unsaved form (.new()-context, which is how this
        # wizard actually runs in the browser before Save), any value derived
        # through a compute/onchange chain gets wrapped in a virtual NewId — .id
        # on that returns a NewId object, not a plain int, which silently matches
        # nothing in a search() domain (no error, just wrong/empty results).
        # ._origin always resolves to the real underlying record's id.
        Dispatch = self.env['reema.ilo.dispatch']
        for wiz in self:
            if wiz.contractor_id and wiz.workorder_id.production_id:
                mo_id = wiz.workorder_id.production_id.id
                contractor_id = wiz.contractor_id._origin.id
                candidates = self.env['reema.wo.batch.entry'].search([
                    ('workorder_id.production_id', '=', mo_id),
                    ('workorder_id.workcenter_id.is_ball_receive_point', '=', True),
                    ('original_contractor_id', '=', contractor_id),
                    ('ilo_dispatch_type', '=', 'repair'),
                ]).mapped('contractor_id')
                wiz.available_returning_repair_contractor_ids = candidates.filtered(
                    lambda c: Dispatch._ilo_qc_pending_balance_repair(
                        mo_id, contractor_id, c._origin.id
                    ) > 0
                )
            else:
                wiz.available_returning_repair_contractor_ids = False

    @api.depends('contractor_id', 'workorder_id', 'available_returning_repair_contractor_ids')
    def _compute_qc_flow_flags(self):
        Dispatch = self.env['reema.ilo.dispatch']
        for wiz in self:
            stitching_pending = repair_pending = 0
            if wiz.contractor_id and wiz.workorder_id.production_id:
                mo_id = wiz.workorder_id.production_id.id
                contractor_id = wiz.contractor_id._origin.id
                stitching_pending = Dispatch._ilo_qc_pending_balance_stitching(mo_id, contractor_id)
                repair_pending = sum(
                    Dispatch._ilo_qc_pending_balance_repair(mo_id, contractor_id, rc._origin.id)
                    for rc in wiz.available_returning_repair_contractor_ids
                )
            wiz.qc_stitching_open = stitching_pending > 0
            wiz.qc_repair_open = repair_pending > 0

    @api.depends('contractor_id', 'workorder_id', 'returning_repair_contractor_id',
                 'available_returning_repair_contractor_ids')
    def _compute_pending_qty(self):
        # pending_qty (Total) is deliberately the SUM of the two correctly-gated
        # buckets below, not the old ungated _ilo_qc_pending_balance — that method
        # counts every received-but-undecided repair ball regardless of whether its
        # repair contractor has fully returned everything dispatched to them, which
        # disagreed with pending_qty_repair (e.g. showed 9 when only 6 were actually
        # eligible, because 3 of a different repair contractor's 4-ball job hadn't
        # fully come back yet).
        Dispatch = self.env['reema.ilo.dispatch']
        for wiz in self:
            if wiz.contractor_id and wiz.workorder_id.production_id:
                mo_id = wiz.workorder_id.production_id.id
                contractor_id = wiz.contractor_id._origin.id
                wiz.pending_qty_stitching = Dispatch._ilo_qc_pending_balance_stitching(mo_id, contractor_id)
                repair_total = sum(
                    Dispatch._ilo_qc_pending_balance_repair(mo_id, contractor_id, rc._origin.id)
                    for rc in wiz.available_returning_repair_contractor_ids
                )
                wiz.pending_qty = wiz.pending_qty_stitching + repair_total
                wiz.pending_qty_repair = (
                    Dispatch._ilo_qc_pending_balance_repair(
                        mo_id, contractor_id, wiz.returning_repair_contractor_id._origin.id
                    ) if wiz.returning_repair_contractor_id else 0
                )
            else:
                wiz.pending_qty = wiz.pending_qty_stitching = wiz.pending_qty_repair = 0

    @api.onchange('contractor_id')
    def _onchange_contractor_default_inspection_purpose(self):
        if self.qc_stitching_open and not self.qc_repair_open:
            self.inspection_purpose = 'stitching'
        elif self.qc_repair_open and not self.qc_stitching_open:
            self.inspection_purpose = 'repair'
        else:
            self.inspection_purpose = False

    @api.onchange('inspection_purpose', 'contractor_id')
    def _onchange_purpose_default_returning_repair_contractor(self):
        if self.inspection_purpose == 'repair':
            candidates = self.available_returning_repair_contractor_ids
            self.returning_repair_contractor_id = candidates[0] if len(candidates) == 1 else False
        else:
            self.returning_repair_contractor_id = False

    def action_confirm(self):
        self.ensure_one()
        if not self.contractor_id:
            raise UserError('Please select the original contractor.')
        if self.qty_pass < 0 or self.qty_fail < 0 or self.qty_scrap < 0:
            raise UserError('Quantities cannot be negative.')
        total = self.qty_pass + self.qty_fail + self.qty_scrap
        if total <= 0:
            raise UserError('Enter at least one quantity before confirming.')
        Dispatch = self.env['reema.ilo.dispatch']
        mo_id = self.workorder_id.production_id.id
        if not self.inspection_purpose:
            if self.qc_stitching_open and self.qc_repair_open:
                raise UserError(
                    f'{self.contractor_id.name} has both a first-time stitching batch and '
                    f'a repair return simultaneously pending inspection on this MO — select '
                    f'which one this decision is for.'
                )
            self.inspection_purpose = 'repair' if self.qc_repair_open else 'stitching'
        if self.inspection_purpose == 'repair':
            if not self.returning_repair_contractor_id:
                raise UserError('Select which repair contractor performed the returned work being inspected.')
            pending = Dispatch._ilo_qc_pending_balance_repair(
                mo_id, self.contractor_id.id, self.returning_repair_contractor_id.id
            )
            purpose_label = 'repair return'
        else:
            pending = Dispatch._ilo_qc_pending_balance_stitching(mo_id, self.contractor_id.id)
            purpose_label = 'first-time'
        if total > pending:
            raise UserError(
                f'Only {pending} {purpose_label} balls are currently pending inspection for '
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
            if self.repair_count <= 0:
                raise UserError('Enter the number of repairs before logging a Fail quantity.')
            if self.repair_count < self.qty_fail:
                raise UserError(
                    'Number of Repairs cannot be less than Fail Qty — each failed ball '
                    'needs at least one repair.'
                )
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
        # live from the dispatch/scrap/receive tables, not snapshotted here.
        entry_vals = {
            'workorder_id': wo.id,
            'qty': self.qty_pass,
            'notes': self.notes,
        }
        if self.inspection_purpose == 'repair':
            # This is what actually pays the repair contractor — gated on QC
            # confirming the returned work is good, not on mere receipt.
            pass_rate = self.env['reema.piece.rate'].search([
                ('workcenter_id.is_ilo', '=', True), ('work_type', '=ilike', 'Repair'),
            ], limit=1)
            if not pass_rate:
                raise UserError(
                    'No "Repair" piece rate is configured on the ILO Center work center. '
                    'Create one under Manufacturing → Configuration → Piece Rates before confirming.'
                )
            entry_vals.update({
                'contractor_id': self.returning_repair_contractor_id.id,
                'original_contractor_id': self.contractor_id.id,
                'ilo_dispatch_type': 'repair',
                'piece_rate_id': pass_rate.id,
            })
        else:
            # Payable rate comes from the original Stitching Center Issuance
            # line — the rate was fixed when the balls were dispatched.
            stitch_dispatch = self.env['reema.ilo.dispatch'].search([
                ('mo_id', '=', mo.id),
                ('dispatch_type', '=', 'stitching'),
                ('contractor_id', '=', self.contractor_id.id),
            ], limit=1)
            entry_vals.update({
                'contractor_id': self.contractor_id.id,
                'original_contractor_id': self.contractor_id.id,
                'ilo_dispatch_type': 'stitching',
                'piece_rate_id': stitch_dispatch.batch_entry_id.piece_rate_id.id,
            })
        if not self.qty_pass:
            entry_vals['payment_excluded'] = True
            entry_vals['exclusion_reason'] = 'No balls passed at this Initial QC decision — nothing payable'
        entry = self.env['reema.wo.batch.entry'].create(entry_vals)

        if self.inspection_purpose == 'repair':
            # This pair only ever becomes visible to QC once fully received (see
            # _ilo_qc_pending_balance_repair), so whatever total this decision is
            # processing is, by construction, the whole currently-outstanding pool
            # for this (original, repair) contractor pair — pull every
            # not-yet-consumed dispatch's repair_count into this one payable entry
            # and close them out, regardless of how the Pass/Fail/Scrap split falls.
            pending_dispatches = self.env['reema.ilo.dispatch'].search([
                ('mo_id', '=', mo.id), ('dispatch_type', '=', 'repair'),
                ('original_contractor_id', '=', self.contractor_id.id),
                ('contractor_id', '=', self.returning_repair_contractor_id.id),
                ('repair_count_consumed', '=', False),
            ])
            total_repairs = sum(pending_dispatches.mapped('repair_count'))
            if total_repairs:
                entry.repair_count = total_repairs
                pending_dispatches.write({'repair_count_consumed': True})
                # Cross-reference only — the deduction was already charged to the
                # original contractor back when the repair was issued; this just
                # links it to the repair contractor's resulting payable entry.
                self.env['reema.ilo.contractor.deduction'].search([
                    ('repair_dispatch_id', 'in', pending_dispatches.ids),
                ]).write({'repair_batch_entry_id': entry.id})

        if self.qty_fail > 0:
            dispatch = self.env['reema.ilo.dispatch'].create({
                'mo_id': mo.id,
                'contractor_id': self.repair_contractor_id.id,
                'dispatch_type': 'repair',
                'repair_source': 'initial_qc',
                'original_contractor_id': self.contractor_id.id,
                'qty_balls': self.qty_fail,
                'repair_count': self.repair_count,
                'rate': repair_rate.rate,
                'ball_size': mo.ball_size,
                'construction_type': mo.construction_type,
                'dispatched_by': self.env.user.id,
                'defect_type': self.repair_defect_type,
                'notes': self.notes,
                'batch_entry_id': entry.id,
            })
            # Original contractor is charged for the repair labor cost right now,
            # at the moment the repair is issued — not deferred to receive or QC
            # Pass. This is unambiguous (1:1 with the dispatch just created) and
            # unconditional on eventual outcome, same rationale as before: they
            # caused the repair to be needed. Charged on repair_count (marks), not
            # ball count, since a ball can carry more than one repair.
            self.env['reema.ilo.contractor.deduction'].create({
                'original_contractor_id': self.contractor_id.id,
                'deduction_type': 'repair',
                'mo_id': mo.id,
                'qty': self.repair_count,
                'construction_type': mo.construction_type,
                'rate': repair_rate.rate,
                'amount': self.repair_count * repair_rate.rate,
                'repair_dispatch_id': dispatch.id,
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

        purpose_note = (
            f' — repair return ({self.returning_repair_contractor_id.name})'
            if self.inspection_purpose == 'repair' else ''
        )
        mo._message_log(
            body=f'Initial QC{purpose_note} — {self.contractor_id.name}: {self.qty_pass} passed, '
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
    qty_pass = fields.Integer(string='Pass Qty')
    qty_fail = fields.Integer(string='Fail Balls')
    repair_count = fields.Integer(
        string='Number of Repairs',
        help='Total individual repair marks across the Fail Qty balls — a single ball '
             'can need more than one repair. Must be at least Fail Qty. Drives the '
             'original contractor\'s deduction (charged now) and the repair '
             'contractor\'s eventual pay (repairs × rate, not balls × rate).',
    )
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
            if self.repair_count <= 0:
                raise UserError('Enter the number of repairs before logging a Fail quantity.')
            if self.repair_count < self.qty_fail:
                raise UserError(
                    'Number of Repairs cannot be less than Fail Qty — each failed ball '
                    'needs at least one repair.'
                )
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

        # Always log one batch entry for this decision — even a 0-pass decision
        # (all repair/scrap) needs a clickable record for this contractor+MO, and
        # somewhere for the Fail/Scrap outcome below to attach to via
        # batch_entry_id so the Balls Done click-through can show them alongside
        # the pass qty (mirrors Initial QC's ReemaIloQcWizard.action_confirm).
        entry = self.env['reema.wo.batch.entry'].create({
            'workorder_id': wo.id,
            'contractor_id': self.contractor_id.id,
            'qty': self.qty_pass,
            'notes': self.notes,
            'payment_excluded': True,
            'exclusion_reason': 'Final QC pass — stitching payment already settled earlier in the line',
        })

        if self.qty_fail > 0:
            dispatch = self.env['reema.ilo.dispatch'].create({
                'mo_id': mo.id,
                'contractor_id': self.repair_contractor_id.id,
                'dispatch_type': 'repair',
                'repair_source': 'final_qc',
                'original_contractor_id': self.contractor_id.id,
                'qty_balls': self.qty_fail,
                'repair_count': self.repair_count,
                'rate': repair_rate.rate,
                'ball_size': mo.ball_size,
                'construction_type': mo.construction_type,
                'dispatched_by': self.env.user.id,
                'defect_type': self.repair_defect_type,
                'notes': self.notes,
                'batch_entry_id': entry.id,
            })
            # Original contractor is charged for the repair labor cost right now, at
            # the moment the repair is issued — not deferred to receive. Charged on
            # repair_count (marks), not ball count, since a ball can carry more than
            # one repair. Mirrors Initial QC's ReemaIloQcWizard.action_confirm.
            self.env['reema.ilo.contractor.deduction'].create({
                'original_contractor_id': self.contractor_id.id,
                'deduction_type': 'repair',
                'mo_id': mo.id,
                'qty': self.repair_count,
                'construction_type': mo.construction_type,
                'rate': repair_rate.rate,
                'amount': self.repair_count * repair_rate.rate,
                'repair_dispatch_id': dispatch.id,
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
                'batch_entry_id': entry.id,
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
    Final QC runs itself, never touching Initial QC. Receive AND the fresh
    good/bad decision happen in this one action (unlike Initial QC's repair
    loop, which is a separate receive-then-decide-later two-step): when the
    repair contractor hands balls back, staff sort them right here into Pass
    (good, ready for packing — the repair contractor's payable qty), Still
    Defective (not accepted — handed straight back to the same contractor to
    keep working, no ledger effect, stays outstanding), or Scrap (unrepairable,
    written off, charged to the ORIGINAL contractor same as any other QC
    scrap — the repair contractor tried, it just isn't fixable). Balls Reported
    Lost (never coming back at all) stays separate, same as ILO's own receive
    wizard. Whichever combination of Pass/Scrap/Lost fully accounts for this
    (original, repair) pair's whole dispatched amount is what triggers the
    repair contractor's actual payment — partial receipts stay unbilled."""
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
    qty = fields.Integer(
        string='Qty Pass (Ready for Packing)',
        help='Balls inspected right now and confirmed good — this is what the repair '
             'contractor gets paid for and what moves forward to packing.',
    )
    qty_reject = fields.Integer(
        string='Qty Still Defective (Returned to Contractor)',
        help='Balls the repair contractor brought back that are still not fixed — not '
             'accepted, handed straight back to them to keep working. Has no effect on '
             'any balance: these balls stay outstanding on the same dispatch exactly as '
             'if this visit never happened, so nothing extra needs to be logged for them '
             'later — just bring them back again next time.',
    )
    qty_scrap = fields.Integer(
        string='Qty Scrap (Unrepairable)',
        help='Balls the repair contractor brought back that turned out unrepairable — '
             'written off. Charged to the ORIGINAL contractor, same as any other Final '
             'QC scrap (the defect traces back to their stitching, not the repair '
             'attempt) — the repair contractor still is not paid for these.',
    )
    scrap_defect_type = fields.Selection(
        [('bad_stitching', 'Bad Stitching'), ('missing_panel', 'Missing Panel'),
         ('missing_bladder', 'Missing Bladder'), ('other', 'Other')],
        string='Scrap / Write-off Reason',
    )
    qty_lost = fields.Integer(
        string='Balls Reported Lost',
        help='Balls the repair contractor has reported as lost — never coming back. '
             'Independent of the other quantities: any of them can be 0 as long as at '
             'least one is not (a pure loss report with nothing physically arriving '
             'that day is valid). Always charged to the repair contractor — a ball lost '
             'while out for repair is their responsibility, not the original '
             'contractor\'s.',
    )
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

    @api.depends('qty', 'qty_reject', 'qty_scrap', 'qty_lost', 'balance_display')
    def _compute_qty_warning(self):
        for wiz in self:
            total = wiz.qty + wiz.qty_reject + wiz.qty_scrap + wiz.qty_lost
            if total > 0 and total > wiz.balance_display:
                wiz.qty_warning = (
                    f'Only {wiz.balance_display} balls are currently outstanding — '
                    f'this will be rejected on Save.'
                )
            else:
                wiz.qty_warning = False

    def _apply_to_dispatches(self, qty, field_name):
        """Greedily attribute `qty` across this (repair contractor, original
        contractor) pair's open Final-QC-sourced dispatches, oldest first,
        incrementing `field_name` (qty_lost or qty_scrap) on each. The exact
        per-dispatch split has no effect on any balance calculation (those
        only ever use the aggregate sum) — this is purely so a specific
        dispatch record shows where a loss/scrap happened, for traceability.
        Capacity accounts for BOTH fields together since either can eat into
        the same dispatch's qty_balls. Mirrors
        ReemaIloReceiveWizard._apply_lost_to_dispatches."""
        remaining = qty
        dispatches = self.env['reema.ilo.dispatch'].search([
            ('mo_id', '=', self.workorder_id.production_id.id),
            ('dispatch_type', '=', 'repair'),
            ('repair_source', '=', 'final_qc'),
            ('contractor_id', '=', self.contractor_id.id),
            ('original_contractor_id', '=', self.original_contractor_id.id),
        ], order='date, id')
        for d in dispatches:
            if remaining <= 0:
                break
            capacity = d.qty_balls - d.qty_lost - d.qty_scrap
            if capacity <= 0:
                continue
            take = min(capacity, remaining)
            d[field_name] += take
            remaining -= take

    def action_confirm(self):
        self.ensure_one()
        if not self.contractor_id:
            raise UserError('Please select the repair contractor.')
        if not self.original_contractor_id:
            raise UserError('Select the original contractor these balls belong to.')
        if self.qty < 0 or self.qty_reject < 0 or self.qty_scrap < 0 or self.qty_lost < 0:
            raise UserError('Quantities cannot be negative.')
        if self.qty <= 0 and self.qty_reject <= 0 and self.qty_scrap <= 0 and self.qty_lost <= 0:
            raise UserError('Enter at least one quantity before confirming.')
        if self.qty_scrap > 0 and not self.scrap_defect_type:
            raise UserError('Select a scrap/write-off reason before logging a Scrap quantity.')

        outstanding = self.env['reema.ilo.dispatch']._final_qc_repair_outstanding(
            self.workorder_id.production_id.id, self.contractor_id.id, self.original_contractor_id.id
        )
        # "Still Defective" balls are handed straight back to the repair
        # contractor — they never leave the outstanding pool — but they're
        # still physically in front of you right now alongside whatever else
        # you're deciding, so the overall sanity check includes them: you
        # can't be handling more balls this visit than are actually outstanding.
        accounted = self.qty + self.qty_scrap + self.qty_lost
        handled_today = accounted + self.qty_reject
        if handled_today > outstanding:
            raise UserError(
                f'Only {outstanding} balls are currently outstanding for '
                f'{self.contractor_id.name} on this MO — cannot account for {handled_today} '
                f'(pass {self.qty} + scrap {self.qty_scrap} + lost {self.qty_lost} '
                f'+ still defective {self.qty_reject}).'
            )
        wo = self.workorder_id
        mo = wo.production_id

        if accounted <= 0:
            # Nothing accounted for this visit — purely balls handed back to
            # the contractor still defective, nothing to log as a batch entry
            # (the outstanding balance already reflects them as still owed).
            mo._message_log(
                body=f'Final QC repair receive — {self.contractor_id.name}: {self.qty_reject} ball(s) '
                     f'still defective, returned to them (original contractor: '
                     f'{self.original_contractor_id.name}).'
            )
            return True

        repair_rate = self.env['reema.piece.rate'].search([
            ('workcenter_id.is_ilo', '=', True), ('work_type', '=ilike', 'Repair'),
        ], limit=1)
        if not repair_rate:
            raise UserError(
                'No "Repair" piece rate is configured on the ILO Center work center. '
                'Create one under Manufacturing → Configuration → Piece Rates before confirming.'
            )
        notes = f'Final QC repair receive: {self.qty} passed'
        if self.qty_scrap:
            notes += f', {self.qty_scrap} scrapped'
        if self.qty_reject:
            notes += f', {self.qty_reject} still defective (returned to contractor)'
        if self.qty_lost:
            notes += f', {self.qty_lost} reported lost'
        if self.notes:
            notes += f' — {self.notes}'

        # Physical arrival AND the good/bad decision happen together here — see
        # the class docstring for why Final QC's repair loop doesn't need a
        # separate re-inspection step the way Initial QC's does. The original
        # contractor's repair-labor deduction was already charged (on
        # repair_count, not ball count) when Final QC issued the repair — see
        # ReemaFinalQcWizard.action_confirm. Whether the repair contractor
        # actually gets PAID is still gated on the WHOLE amount dispatched for
        # this (original, repair) pair being fully accounted for (pass + scrap
        # + lost) — partial visits stay excluded so a job trickling back in
        # pieces doesn't get billed at ball-count instead of repair-count.
        # Created BEFORE the lost/scrap side records below so those can link
        # back to it via batch_entry_id — that link is what lets deleting this
        # entry later detect and block on an unreversible lost-ball charge,
        # and lets a deleted scrap charge be cleaned up automatically.
        entry = self.env['reema.wo.batch.entry'].create({
            'workorder_id': wo.id,
            'contractor_id': self.contractor_id.id,
            'original_contractor_id': self.original_contractor_id.id,
            'ilo_dispatch_type': 'repair',
            'qty': self.qty,
            'piece_rate_id': repair_rate.id,
            'notes': notes,
            'payment_excluded': True,
            'exclusion_reason': 'Final QC Repair — real payment recorded once the full repair job is back',
        })

        if self.qty_lost > 0:
            # A ball lost while out for a Final QC repair is the repair
            # contractor's own responsibility, not the original contractor's —
            # same reasoning as ILO's repair-purpose lost ball.
            self._apply_to_dispatches(self.qty_lost, 'qty_lost')
            self.env['reema.ilo.contractor.deduction'].create({
                'original_contractor_id': self.original_contractor_id.id,
                'charged_contractor_id': self.contractor_id.id,
                'deduction_type': 'lost',
                'mo_id': mo.id,
                'qty': self.qty_lost,
                'construction_type': mo.construction_type,
                'notes': f'Reported lost by {self.contractor_id.name}' + (f' — {self.notes}' if self.notes else ''),
                'batch_entry_id': entry.id,
            })

        if self.qty_scrap > 0:
            # Unrepairable — the repair contractor gave it their best shot, but
            # the underlying defect traces back to the original stitching, so
            # the ORIGINAL contractor is charged, same as any other Final QC
            # scrap. The repair contractor is not paid for this quantity.
            self._apply_to_dispatches(self.qty_scrap, 'qty_scrap')
            scrap = self.env['reema.ilo.qc.scrap'].create({
                'mo_id': mo.id,
                'workorder_id': wo.id,
                'contractor_id': self.original_contractor_id.id,
                'qty': self.qty_scrap,
                'defect_type': self.scrap_defect_type,
                'recorded_by': self.env.user.id,
                'notes': f'Unrepairable after Final QC repair by {self.contractor_id.name}'
                         + (f' — {self.notes}' if self.notes else ''),
                'batch_entry_id': entry.id,
            })
            self.env['reema.ilo.contractor.deduction'].create({
                'original_contractor_id': self.original_contractor_id.id,
                'deduction_type': 'scrap',
                'mo_id': mo.id,
                'qty': self.qty_scrap,
                'construction_type': mo.construction_type,
                'scrap_id': scrap.id,
                'notes': 'Material cost — enter amount when preparing the contractor bill.',
            })

        fully_closed = (outstanding - accounted) <= 0
        if fully_closed:
            pending_dispatches = self.env['reema.ilo.dispatch'].search([
                ('mo_id', '=', mo.id), ('dispatch_type', '=', 'repair'),
                ('repair_source', '=', 'final_qc'),
                ('original_contractor_id', '=', self.original_contractor_id.id),
                ('contractor_id', '=', self.contractor_id.id),
                ('repair_count_consumed', '=', False),
            ])
            total_repairs = sum(pending_dispatches.mapped('repair_count'))
            if total_repairs:
                entry.write({
                    'repair_count': total_repairs,
                    'payment_excluded': False,
                    'exclusion_reason': False,
                })
                pending_dispatches.write({'repair_count_consumed': True})
                # Cross-reference only — the deduction was already charged to the
                # original contractor back when the repair was issued; this just
                # links it to the repair contractor's resulting payable entry.
                self.env['reema.ilo.contractor.deduction'].search([
                    ('repair_dispatch_id', 'in', pending_dispatches.ids),
                ]).write({'repair_batch_entry_id': entry.id})

        mo._message_log(
            body=f'Final QC repair receive — {self.contractor_id.name}: {self.qty} passed'
                 + (f', {self.qty_scrap} scrapped' if self.qty_scrap else '')
                 + (f', {self.qty_reject} still defective (returned to them)' if self.qty_reject else '')
                 + (f', {self.qty_lost} reported lost' if self.qty_lost else '')
                 + f' (original contractor: {self.original_contractor_id.name})'
                 + (', repair job fully closed out' if fully_closed else '') + '.'
        )


class ReemaRepairQcWizard(models.TransientModel):
    """Initial QC / Final QC decision screen for hybrid / machine-stitched
    construction — the equivalent of ReemaIloQcWizard/ReemaFinalQcWizard, but
    for balls made entirely in-house. A Fail here creates a reema.repair.job
    (sent to Shell Closing for rework) instead of an ILO dispatch. A Scrap
    here uses the plain, existing reema.production.scrap flow — real scrap is
    unrelated to fault attribution."""
    _name = 'reema.repair.qc.wizard'
    _description = 'Quality Check — Pass / Repair / Scrap (Hybrid / Machine-Stitched)'

    workorder_id = fields.Many2one('mrp.workorder', string='Work Order',
                                   required=True, readonly=True)
    workorder_name = fields.Char(related='workorder_id.name', string='Work Order', readonly=True)
    mo_id = fields.Many2one(related='workorder_id.production_id', string='Manufacturing Order', readonly=True)
    workcenter_name = fields.Char(related='workorder_id.workcenter_id.name', string='Hall', readonly=True)
    workcenter_id = fields.Many2one(related='workorder_id.workcenter_id', readonly=True)
    construction_type = fields.Selection(related='mo_id.construction_type', readonly=True)
    qty_pass = fields.Integer(string='Pass Qty')
    qty_fail = fields.Integer(string='Fail Qty (Balls)')
    available_fault_workcenter_ids = fields.Many2many(
        'mrp.workcenter', compute='_compute_available_fault_workcenter_ids',
        string='Halls on this MO',
    )
    available_fault_contractor_ids = fields.Many2many(
        'res.partner', compute='_compute_available_fault_contractor_ids',
        string='Contractors at this Hall',
    )
    fault_workcenter_id = fields.Many2one(
        'mrp.workcenter', string='Fault Hall',
        domain="[('id', 'in', available_fault_workcenter_ids)]",
        help='Which hall\'s work is at fault — restricted to halls that '
             'actually have a work order on this MO.',
    )
    fault_contractor_id = fields.Many2one(
        'res.partner', string='Fault Contractor',
        domain="[('id', 'in', available_fault_contractor_ids)]",
        help='The contractor charged for this fault.',
    )
    defect_type = fields.Selection(DEFECT_TYPE_SELECTION, string='Defect Type')
    repair_count = fields.Integer(
        string='Number of Repairs',
        help='Total individual faulty panels/repairs across the Fail Qty balls — '
             'a ball can need more than one repair. Must be at least Fail Qty.',
    )
    available_repair_contractor_ids = fields.Many2many(
        'res.partner', compute='_compute_available_repair_contractor_ids',
        string='Shell Closing Contractors',
    )
    repair_contractor_id = fields.Many2one(
        'res.partner', string='Repair Contractor (Shell Closing)',
        domain="[('id', 'in', available_repair_contractor_ids)]",
    )
    qty_scrap = fields.Integer(string='Scrap / Write-off Qty')
    scrap_enabled = fields.Boolean(default=True)
    scrap_reason_id = fields.Many2one(
        'reema.scrap.reason', string='Scrap Reason',
        domain="['|', ('workcenter_ids', '=', False), ('workcenter_ids', 'in', [workcenter_id])]",
    )
    notes = fields.Char(string='Notes')

    @api.depends('mo_id')
    def _compute_available_fault_workcenter_ids(self):
        for wiz in self:
            wiz.available_fault_workcenter_ids = wiz.mo_id.workorder_ids.mapped('workcenter_id') if wiz.mo_id else self.env['mrp.workcenter']

    @api.depends('mo_id', 'fault_workcenter_id')
    def _compute_available_fault_contractor_ids(self):
        # Scoped to the SELECTED fault hall's own work order on this MO, not
        # just "any contractor who logged anything on this MO" — otherwise a
        # contractor who never touched the blamed hall could still be charged
        # for its fault.
        for wiz in self:
            if not wiz.mo_id or not wiz.fault_workcenter_id:
                wiz.available_fault_contractor_ids = self.env['res.partner']
                continue
            wiz.available_fault_contractor_ids = self.env['reema.wo.batch.entry'].search([
                ('mo_id', '=', wiz.mo_id.id),
                ('workorder_id.workcenter_id', '=', wiz.fault_workcenter_id.id),
            ]).mapped('contractor_id')

    @api.onchange('fault_workcenter_id')
    def _onchange_fault_workcenter_id(self):
        # A contractor valid for the previous fault hall may not be valid for
        # a newly picked one — clear rather than leave a stale selection.
        self.fault_contractor_id = False

    @api.depends('mo_id')
    def _compute_available_repair_contractor_ids(self):
        for wiz in self:
            shell_wo = self.env['mrp.workorder'].search([
                ('production_id', '=', wiz.mo_id.id),
                ('workcenter_id.is_shell_closing', '=', True),
            ], limit=1) if wiz.mo_id else self.env['mrp.workorder']
            wiz.available_repair_contractor_ids = shell_wo.contractor_ids

    def action_confirm(self):
        self.ensure_one()
        if self.qty_pass < 0 or self.qty_fail < 0 or self.qty_scrap < 0:
            raise UserError('Quantities cannot be negative.')
        total = self.qty_pass + self.qty_fail + self.qty_scrap
        if total <= 0:
            raise UserError('Enter at least one quantity before confirming.')

        # Fault attribution is required for BOTH a Fail (repair) and a direct
        # Scrap — a ball scrapped straight at QC still came from some hall's
        # work, and leaving it unattributed meant nobody was ever accountable
        # for it (unlike a Fail, which always charges the fault contractor).
        if self.qty_fail > 0 or self.qty_scrap > 0:
            if not self.fault_workcenter_id:
                raise UserError('Select the fault hall before logging a Fail or Scrap quantity.')
            fault_wo = self.env['mrp.workorder'].search([
                ('production_id', '=', self.mo_id.id),
                ('workcenter_id', '=', self.fault_workcenter_id.id),
            ], limit=1)
            if not fault_wo:
                raise UserError(
                    f'{self.fault_workcenter_id.name} has no work order on this MO — '
                    'it cannot be the fault hall.'
                )
            if not self.fault_contractor_id:
                raise UserError('Select the fault contractor before logging a Fail or Scrap quantity.')
            if not self.env['reema.wo.batch.entry'].search_count([
                ('workorder_id', '=', fault_wo.id),
                ('contractor_id', '=', self.fault_contractor_id.id),
            ]):
                raise UserError(
                    f'{self.fault_contractor_id.name} has no logged work at '
                    f'{self.fault_workcenter_id.name} on this MO — cannot charge them for this fault.'
                )

        is_thb = self.construction_type == 'thb'
        if self.qty_fail > 0:
            if not self.defect_type:
                raise UserError('Select a defect type before logging a Fail quantity.')
            if self.repair_count <= 0:
                raise UserError('Enter the number of repairs before logging a Fail quantity.')
            if self.repair_count < self.qty_fail:
                raise UserError(
                    'Number of Repairs cannot be less than Fail Qty — each failed ball '
                    'needs at least one repair.'
                )
            if not is_thb:
                if not self.repair_contractor_id:
                    raise UserError('Select the Shell Closing repair contractor before logging a Fail quantity.')
                is_edge_case = self.defect_type in EDGE_CASE_DEFECT_TYPES
                rate = self.env['reema.repair.job']._repair_rate()
                if not is_edge_case and not rate:
                    raise UserError(
                        'No "Repair" piece rate is configured on the Shell Closing work center. '
                        'Create one under Manufacturing → Configuration → Piece Rates before '
                        'logging a Fail quantity.'
                    )
        if self.qty_scrap > 0 and not self.scrap_reason_id:
            raise UserError('Select a reason for the scrapped quantity.')

        wo = self.workorder_id
        # Cap: cannot log more than what has physically arrived from the
        # previous hall — same guard every other hall's batch-log wizard uses.
        total_logged = self.qty_pass + self.qty_fail + self.qty_scrap
        self_balls = wo._units_to_balls(total_logged)
        already_processed = wo.qty_balls_completed + wo.qty_scrap_balls
        for pred in wo.blocked_by_workorder_ids:
            if pred.state in ('done', 'cancel'):
                continue
            available_balls = pred.qty_balls_completed - already_processed
            if self_balls > available_balls + 0.001:
                raise UserError(
                    f'Cannot log {total_logged} balls.\n\n'
                    f'{pred.workcenter_id.name} has completed '
                    f'{pred.qty_balls_completed:.1f} balls equivalent.\n\n'
                    f'{already_processed:.1f} balls equivalent already processed here.\n\n'
                    f'Maximum you can log now: {wo._balls_to_units(available_balls):.1f}.'
                )
        mo = wo.production_id

        self.env['reema.wo.batch.entry'].create({
            'workorder_id': wo.id,
            'qty': self.qty_pass,
            'notes': self.notes,
            'payment_excluded': True,
            'exclusion_reason': 'QC pass — no piece-rate payment at this hall',
        })

        if self.qty_fail > 0:
            job_vals = {
                'mo_id': mo.id,
                'workorder_id': wo.id,
                'fault_workcenter_id': self.fault_workcenter_id.id,
                'fault_contractor_id': self.fault_contractor_id.id,
                'qty_balls': self.qty_fail,
                'repair_count': self.repair_count,
                'defect_type': self.defect_type,
                'notes': self.notes,
            }
            if is_thb:
                # THB Binding always does the rework itself — no separate
                # repair contractor to record.
                rework_note = 'Sent back to THB Binding for rework — pending return'
            else:
                job_vals['repair_contractor_id'] = self.repair_contractor_id.id
                rework_note = 'Sent to Shell Closing for repair — pending return'
            job = self.env['reema.repair.job'].create(job_vals)

            if is_thb:
                # Fault is THB Binding's own mistake: they redo it, unpaid,
                # since producing a flawless ball was their job — no penalty.
                # Fault traced to a different hall: penalty logged now but
                # priced manually at bill time, same as an MS/HYB edge case —
                # there's no THB-wide flat rate to auto-calculate from.
                if not self.fault_workcenter_id.is_thb_binding:
                    self.env['reema.repair.penalty'].create({
                        'repair_job_id': job.id,
                        'qty': self.repair_count,
                        'rate': 0.0,
                        'amount': 0.0,
                        'notes': 'Priced manually at billing time (THB).',
                    })
            else:
                is_edge_case = self.defect_type in EDGE_CASE_DEFECT_TYPES
                rate = self.env['reema.repair.job']._repair_rate()
                self.env['reema.repair.penalty'].create({
                    'repair_job_id': job.id,
                    'qty': self.repair_count,
                    'rate': 0.0 if is_edge_case else rate.rate,
                    'amount': 0.0 if is_edge_case else self.repair_count * rate.rate,
                    'notes': 'Priced manually at billing time.' if is_edge_case else False,
                })
            # Records the Fail quantity as consumed from this hall's predecessor
            # right away (so it can't be silently re-drawn/double-logged later),
            # while repair_job_id lets _compute_qty_balls_completed net it back out
            # of Balls Done until the repair job is received — otherwise these
            # balls would never get a batch entry at all here and could never
            # flow to the next hall, even once the repair comes back.
            self.env['reema.wo.batch.entry'].create({
                'workorder_id': wo.id,
                'qty': self.qty_fail,
                'notes': self.notes,
                'payment_excluded': True,
                'exclusion_reason': rework_note,
                'repair_job_id': job.id,
            })

        if self.qty_scrap > 0:
            self.env['reema.production.scrap'].create({
                'workorder_id': wo.id,
                'contractor_id': self.fault_contractor_id.id,
                'qty': self.qty_scrap,
                'reason_id': self.scrap_reason_id.id,
                'notes': self.notes,
            })

        mo._message_log(
            body=f'{wo.workcenter_id.name} — {self.qty_pass} passed'
                 + (f', {self.qty_fail} sent to repair ({self.fault_contractor_id.name} at fault)' if self.qty_fail else '')
                 + (f', {self.qty_scrap} scrapped ({self.fault_contractor_id.name} at fault)' if self.qty_scrap else '')
                 + '.'
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
    reema_workcenter_id = fields.Many2one(
        'mrp.workcenter', related='reema_batch_entry_id.workorder_id.workcenter_id',
        string='Process', store=True, readonly=True,
        help='Which hall this labor line was billed for — same traceability pattern '
             'as reema_mo_id/reema_po_id, needed to split WIP Labor back out by '
             'process when it converts to COGS at Hall 17.',
    )
    reema_product_id = fields.Many2one(
        related='reema_batch_entry_id.mo_id.product_id', string='Product', store=True, readonly=True,
    )
    reema_uom_id = fields.Many2one(
        'uom.uom', string='UOM', readonly=True, copy=False,
        help='The unit this line was actually paid on (Ball, Sheet, Panel, Impression, ...). '
             'Set at bill-generation time — normally the batch entry\'s piece rate UOM, but '
             'the Low-Qty Per-Ball Rate\'s UOM when the printing low-quantity flat rate applied.',
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

        if entries_to_release:
            entries_to_release.write({'is_billed': False, 'bill_id': False})

            # Deleting the last line of a contractor bill leaves nothing for
            # the bill to hold — auto-delete it so "delete last line, Save"
            # IS "delete the bill", in one step, instead of needing a separate
            # "Delete Bill" click on an now-empty draft. Scoped to moves that
            # actually released a batch entry just now (real contractor
            # bills), so an accountant clearing lines on an ordinary vendor
            # bill elsewhere is never affected.
            emptied = self.filtered(lambda m: m.state == 'draft' and not m.invoice_line_ids)
            if emptied:
                emptied.unlink()

        return res

    def _get_starting_sequence(self):
        # Vendor bills: short "BILL/26/0001" format (2-digit year, no month)
        # instead of the default "BILL/2026/07/0001".
        if self.journal_id.type == 'purchase' and self.move_type == 'in_invoice':
            self.ensure_one()
            move_date = self.date or self.invoice_date or fields.Date.context_today(self)
            return f"{self.journal_id.code}/{move_date.strftime('%y')}/0001"
        return super()._get_starting_sequence()

    def action_delete_contractor_bill(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError('Only draft bills can be deleted this way.')
        if self.reema_bill_state != 'pending':
            raise UserError(
                'Submitted bills cannot be deleted — use Void to send this '
                'bill back to the supervisor for correction first.'
            )
        self.invoice_line_ids.mapped('reema_batch_entry_id').filtered('id').write({
            'is_billed': False, 'bill_id': False,
        })
        # Also release ILO/scrap deductions pulled in alongside the batch entries —
        # otherwise they're left orphaned (bill_id pointing at a record that's about
        # to be deleted, state stuck at 'applied'/is_billed=True) instead of back in
        # the pending pool, and never show up again on any future bill.
        self.reema_ilo_deduction_ids.write({'state': 'pending', 'bill_id': False})
        self.reema_scrap_deduction_ids.write({'is_billed': False, 'bill_id': False})
        self.unlink()
        # ir.actions.act_window is only readable by Settings/Administration;
        # _for_xml_id() reads it via sudo() internally, which plain .read()
        # does not, so non-admin users (e.g. production staff) would otherwise
        # get an AccessError here.
        return self.env['ir.actions.act_window']._for_xml_id('reema_accounting.action_contractor_bills')

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

    # Split per type (not just one combined flag) so, e.g., a Cutting/Sorting
    # contractor who can never have an ILO charge doesn't get an "Add Pending
    # ILO Deduction" button that's always a dead end — each group's
    # visibility only promises what it can actually deliver.
    reema_has_pending_ilo_deductions = fields.Boolean(
        compute='_compute_reema_has_pending_deductions',
    )
    reema_has_pending_scrap_deductions = fields.Boolean(
        compute='_compute_reema_has_pending_deductions',
    )
    reema_has_pending_repair_penalties = fields.Boolean(
        compute='_compute_reema_has_pending_deductions',
    )

    def _compute_reema_has_pending_deductions(self):
        for move in self:
            if not move.partner_id:
                move.reema_has_pending_ilo_deductions = False
                move.reema_has_pending_scrap_deductions = False
                move.reema_has_pending_repair_penalties = False
                continue
            move.reema_has_pending_ilo_deductions = bool(
                self.env['reema.ilo.contractor.deduction'].search_count([
                    ('billed_to_id', '=', move.partner_id.id), ('state', '=', 'pending'),
                ], limit=1)
            )
            move.reema_has_pending_scrap_deductions = bool(
                self.env['reema.production.scrap'].search_count([
                    ('contractor_id', '=', move.partner_id.id), ('is_billed', '=', False),
                ], limit=1)
            )
            move.reema_has_pending_repair_penalties = bool(
                self.env['reema.repair.penalty'].search_count([
                    ('fault_contractor_id', '=', move.partner_id.id), ('is_billed', '=', False),
                ], limit=1)
            )

    def action_add_pending_ilo_deductions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Add Pending ILO Deductions',
            'res_model': 'reema.ilo.contractor.deduction',
            'view_mode': 'list',
            'views': [(self.env.ref('reema_mrp.view_reema_ilo_contractor_deduction_list').id, 'list')],
            'search_view_id': self.env.ref('reema_mrp.view_reema_ilo_contractor_deduction_search').id,
            'target': 'new',
            'domain': [('billed_to_id', '=', self.partner_id.id), ('state', '=', 'pending')],
            'context': {'reema_pick_bill_id': self.id},
        }

    def action_add_pending_scrap_deductions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Add Pending Scrap Deductions',
            'res_model': 'reema.production.scrap',
            'view_mode': 'list',
            'views': [(self.env.ref('reema_mrp.view_reema_production_scrap_list').id, 'list')],
            'search_view_id': self.env.ref('reema_mrp.view_reema_production_scrap_search').id,
            'target': 'new',
            'domain': [('contractor_id', '=', self.partner_id.id), ('is_billed', '=', False)],
            'context': {'reema_pick_bill_id': self.id},
        }

    def action_add_pending_repair_penalties(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Add Pending Repair Penalties',
            'res_model': 'reema.repair.penalty',
            'view_mode': 'list',
            'views': [(self.env.ref('reema_mrp.view_reema_repair_penalty_list').id, 'list')],
            'search_view_id': self.env.ref('reema_mrp.view_reema_repair_penalty_search').id,
            'target': 'new',
            'domain': [('fault_contractor_id', '=', self.partner_id.id), ('is_billed', '=', False)],
            'context': {'reema_pick_bill_id': self.id},
        }
    # pending (supervisor drafting, unnumbered, freely editable/deletable)
    #   -> submitted (supervisor locked it in, numbered; awaiting manager)
    #   -> confirmed (production manager approved authenticity; accounting-ready)
    # Void sends confirmed/submitted back to pending for the supervisor to fix
    # and resubmit — the bill keeps its number, it is never renumbered.
    reema_bill_state = fields.Selection([
        ('pending', 'Pending'),
        ('submitted', 'Submitted'),
        ('confirmed', 'Confirmed'),
    ], string='Approval', default='pending', copy=False, tracking=True)

    def action_reema_submit(self):
        for move in self:
            if move.state != 'draft':
                raise UserError('Only draft bills can be submitted.')
            if move.reema_bill_state != 'pending':
                raise UserError('This bill has already been submitted.')
            if not move.invoice_line_ids:
                raise UserError('Cannot submit an empty bill.')
            if not move.name or move.name == '/':
                move._set_next_sequence()
        self.write({'reema_bill_state': 'submitted'})

    def action_reema_confirm(self):
        for move in self:
            if move.state != 'draft':
                raise UserError('Only draft bills can be confirmed.')
            if move.reema_bill_state != 'submitted':
                raise UserError('Only submitted bills can be approved.')
        self.write({'reema_bill_state': 'confirmed'})

    def action_reema_reset_to_pending(self):
        for move in self:
            if move.state != 'draft':
                raise UserError('Cannot void a posted bill.')
        self.write({'reema_bill_state': 'pending'})

    def _get_move_display_name(self, show_ref=False):
        # Contractor bills: show just the bill number — no "Draft Bill" prefix
        if self.batch_entry_ids:
            name = self.name if self.name and self.name != '/' else '/'
            if show_ref and self.ref:
                name += f' ({self.ref})'
            return name
        return super()._get_move_display_name(show_ref=show_ref)
