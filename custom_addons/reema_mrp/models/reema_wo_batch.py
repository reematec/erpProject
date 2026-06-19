from markupsafe import Markup
from odoo import models, fields, api
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

    def _calc_amount(self):
        rate = self.piece_rate_id.rate or 0.0
        op = self.workorder_id.operation_id
        if (op.pay_basis or 'hall') == 'ball':
            return rate * self.qty_balls
        ipu = op.impressions_per_ball or 0.0
        if ipu:
            return rate * self.qty_balls * ipu
        return rate * self.qty

    @api.depends(
        'piece_rate_id.rate', 'qty', 'qty_balls',
        'workorder_id.operation_id.pay_basis',
        'workorder_id.operation_id.impressions_per_ball',
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
            op = entry.workorder_id.operation_id
            wc = entry.workorder_id.workcenter_id
            pay_basis = op.pay_basis or 'hall'
            ipu = op.impressions_per_ball or 0.0
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


class ReemaBatchEntryWizard(models.TransientModel):
    _name = 'reema.batch.entry.wizard'
    _description = 'Log Batch Progress'

    workorder_id = fields.Many2one('mrp.workorder', string='Work Order',
                                   required=True, readonly=True)
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
    notes = fields.Char(string='Notes')
    qty_warning = fields.Char(string='Quantity Warning', compute='_compute_qty_warning')

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

    def action_confirm(self):
        self.ensure_one()
        wo = self.workorder_id
        if self.qty <= 0:
            raise UserError('Quantity must be greater than zero.')
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
        for pred in wo.blocked_by_workorder_ids:
            if pred.state in ('done', 'cancel'):
                continue
            self_balls = wo._units_to_balls(self.qty)
            available_balls = pred.qty_balls_completed - wo.qty_balls_completed
            available_units = wo._balls_to_units(available_balls)
            if self_balls > available_balls + 0.001:
                uom_label = 'units'
                raise UserError(
                    f'Cannot log {self.qty:.1f} {uom_label}.\n\n'
                    f'{pred.workcenter_id.name} has completed '
                    f'{pred.qty_balls_completed:.1f} balls equivalent.\n\n'
                    f'{wo.qty_balls_completed:.1f} balls equivalent already processed here.\n\n'
                    f'Maximum you can log now: {available_units:.1f} {uom_label}.'
                )
        vals = {
            'workorder_id': wo.id,
            'qty': self.qty,
            'notes': self.notes,
        }
        if self.workforce_type != 'employee':
            if not self.contractor_id:
                raise UserError('Please select a contractor before saving.')
            vals['contractor_id'] = self.contractor_id.id
            vals['piece_rate_id'] = wo.operation_id.piece_rate_id.id or False
        self.env['reema.wo.batch.entry'].create(vals)


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
