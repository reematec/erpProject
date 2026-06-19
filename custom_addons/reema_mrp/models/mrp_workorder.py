import math

from markupsafe import Markup
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_round, float_is_zero


class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    workforce_type = fields.Selection(
        related='workcenter_id.workforce_type', store=True, readonly=True
    )
    contractor_ids = fields.Many2many(
        'res.partner',
        'mrp_workorder_contractor_rel',
        'workorder_id', 'partner_id',
        string='Contractors',
        domain="[('supplier_rank', '>', 0), ('is_contractor', '=', True)]",
    )
    # Batch progress tracking
    batch_entry_ids = fields.One2many('reema.wo.batch.entry', 'workorder_id', string='Batch Entries')
    qty_batch_completed = fields.Float(string='Completed So Far', compute='_compute_qty_batch_completed', store=True)
    batch_released = fields.Boolean(string='Released to Next Hall', default=False)
    hall_qty = fields.Float(string='Target', compute='_compute_hall_qty', store=True)
    qty_balls_completed = fields.Float(string='Balls Done', compute='_compute_qty_balls_completed', store=True)
    wip_labor_cost = fields.Float(string='Labor Cost (PKR)', compute='_compute_wip_labor_cost', store=True, digits=(16, 2))
    hall_uom_name = fields.Char(related='operation_id.piece_rate_id.uom_id.name', string='UOM', readonly=True)
    hall_unit_label = fields.Selection(related='workcenter_id.hall_unit', string='Logging Unit', readonly=True)
    state = fields.Selection(selection=[
        ('pending', 'WO Waiting'),
        ('waiting', 'No Stock'),
        ('ready', 'Ready'),
        ('progress', 'In Progress'),
        ('done', 'Done'),
        ('cancel', 'Cancelled'),
    ])

    @api.depends('batch_entry_ids.qty')
    def _compute_qty_batch_completed(self):
        for wo in self:
            wo.qty_batch_completed = sum(wo.batch_entry_ids.mapped('qty'))

    @api.depends('qty_production', 'operation_id.balls_per_unit',
                 'workcenter_id.hall_unit')
    def _compute_hall_qty(self):
        for wo in self:
            wo.hall_qty = wo._balls_to_units(wo.qty_production)

    def _get_total_panels(self):
        """Panels per ball for this work order's product, read from the
        sampling blueprint (constant per ball design). 0 if not resolvable."""
        self.ensure_one()
        mo = self.production_id
        if not mo:
            return 0
        po_line = self.env['reema.production.order.line'].search(
            [('mo_id', '=', mo.id)], limit=1
        )
        if po_line and po_line.sample_id:
            return po_line.sample_id.total_panels
        return 0

    def _units_to_balls(self, qty_units):
        """Convert a quantity logged in this hall's unit into balls."""
        self.ensure_one()
        unit = self.workcenter_id.hall_unit or 'ball'
        if unit == 'panel':
            panels = self._get_total_panels()
            return qty_units / panels if panels else 0.0
        if unit == 'sheet':
            return qty_units * (self.operation_id.balls_per_unit or 1.0)
        return qty_units

    def _balls_to_units(self, qty_balls):
        """Convert a ball quantity back into this hall's logging unit."""
        self.ensure_one()
        unit = self.workcenter_id.hall_unit or 'ball'
        if unit == 'panel':
            panels = self._get_total_panels()
            return qty_balls * panels
        if unit == 'sheet':
            bpu = self.operation_id.balls_per_unit or 1.0
            return qty_balls / bpu if bpu else qty_balls
        return qty_balls

    @api.depends('batch_entry_ids.qty_balls')
    def _compute_qty_balls_completed(self):
        for wo in self:
            wo.qty_balls_completed = sum(wo.batch_entry_ids.mapped('qty_balls'))

    @api.depends('batch_entry_ids.amount_earned')
    def _compute_wip_labor_cost(self):
        for wo in self:
            wo.wip_labor_cost = sum(wo.batch_entry_ids.mapped('amount_earned'))

    # Extend state computation: a work order blocked by a predecessor is also unblocked
    # when the predecessor sets batch_released=True (partial completion released to next hall).
    @api.depends('blocked_by_workorder_ids.batch_released')
    def _compute_state(self):
        super()._compute_state()
        for wo in self:
            if self._context.get('no_recursion'):
                continue
            if wo.state != 'pending':
                continue
            predecessors = wo.blocked_by_workorder_ids.with_context(no_recursion=True)
            if not predecessors:
                continue
            all_released = all(
                p.state in ('done', 'cancel') or p.batch_released
                for p in predecessors
            )
            if all_released:
                wo.state = 'ready' if wo.production_availability == 'assigned' else 'waiting'

    def _set_qty_producing(self):
        # Odoo's default inverse propagates wo.qty_producing back to production_id.qty_producing.
        # We suppress that here: the MO's qty_producing is driven exclusively by packing
        # batch entries via reema_wo_batch._sync_mo_qty_producing.
        pass

    @api.constrains('contractor_ids')
    def _check_contractor_batch_entries(self):
        for wo in self:
            assigned = wo.contractor_ids
            for entry in wo.batch_entry_ids:
                if entry.contractor_id and entry.contractor_id not in assigned:
                    raise ValidationError(
                        "Cannot remove contractor '%s' — batch logs have already been "
                        "recorded under them on this work order." % entry.contractor_id.name
                    )

    def write(self, vals):
        if 'contractor_ids' in vals:
            old_contractors = {wo: set(wo.contractor_ids.mapped('name')) for wo in self}
        res = super().write(vals)
        if 'contractor_ids' in vals:
            for wo in self:
                new_names = set(wo.contractor_ids.mapped('name'))
                old_names = old_contractors[wo]
                added = new_names - old_names
                removed = old_names - new_names
                if added or removed:
                    parts = []
                    if added:
                        parts.append(f"Added: {', '.join(sorted(added))}")
                    if removed:
                        parts.append(f"Removed: {', '.join(sorted(removed))}")
                    wo.production_id._message_log(
                        body=Markup(f'Contractors updated on <b>{wo.name}</b> ({wo.workcenter_id.name}): {" | ".join(parts)}.'),
                    )
        return res

    def button_start(self, raise_on_invalid_state=False):
        res = super().button_start(raise_on_invalid_state=raise_on_invalid_state)
        for wo in self.filtered(lambda w: w.state == 'progress'):
            wo.production_id._message_log(
                body=Markup(f'▶ Work order <b>{wo.name}</b> ({wo.workcenter_id.name}) started by {self.env.user.name}.'),
            )
        return res

    def action_open_parent_mo(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.production',
            'res_id': self.production_id.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }

    def action_log_batch(self):
        self.ensure_one()
        if self.state != 'progress':
            raise UserError(
                'The work order must be started before logging batch progress.\n\n'
                'Click the Start button on this work order first. '
                'Starting requires: material issued by the store, '
                'and output received from the previous hall (if applicable).'
            )
        return {
            'type': 'ir.actions.act_window',
            'name': 'Log Batch Progress',
            'res_model': 'reema.batch.entry.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_workorder_id': self.id},
        }

    def button_pending(self):
        for wo in self:
            if wo.state in ('done', 'cancel'):
                raise UserError(f'Work order "{wo.name}" is already {wo.state} and cannot be paused.')
        return super().button_pending()

    def button_finish(self):
        for wo in self:
            if wo.state in ('done', 'cancel'):
                continue
            if wo.state != 'progress':
                raise UserError(
                    f'Work order "{wo.name}" must be started before it can be marked done.\n\n'
                    'Click the Start button first. Starting requires a contractor assigned, '
                    'material issued by the store, and output received from the previous hall (if applicable).'
                )
            # ILO work centers: block completion until all dispatched balls have been received
            if wo.workcenter_id.is_ilo:
                dispatches = self.env['reema.ilo.dispatch'].search([
                    ('mo_id', '=', wo.production_id.id),
                    ('state', '=', 'dispatched'),
                    ('qty_pending', '>', 0),
                ])
                if dispatches:
                    pending_total = sum(dispatches.mapped('qty_pending'))
                    raise UserError(
                        f'Work order "{wo.name}" cannot be completed yet.\n\n'
                        f'{pending_total} balls are still pending at ILO centers. '
                        f'Record receipts for all dispatches before finishing this step.'
                    )
            if not wo.batch_entry_ids:
                raise UserError(
                    f'Work order "{wo.name}": log at least one batch before marking it as done.'
                )
            min_required = math.floor(wo.hall_qty)
            if min_required > 0 and wo.qty_batch_completed < min_required:
                raise UserError(
                    f'Work order "{wo.name}": not enough quantity logged.\n\n'
                    f'Target: {wo.hall_qty:.2f} — minimum required: {min_required} — '
                    f'logged so far: {wo.qty_batch_completed:.2f}.'
                )
        wos_finishing = self.filtered(lambda w: w.state == 'progress')
        res = super().button_finish()
        for wo in wos_finishing:
            wo.production_id._message_log(
                body=Markup(f'✓ Work order <b>{wo.name}</b> ({wo.workcenter_id.name}) marked done by {self.env.user.name}.'),
            )
        for wo in self:
            wc = wo.workcenter_id
            if not wc.sfg_product_id or not wc.location_id:
                continue
            # Batch entries already created SFG moves per log entry — skip double-creation
            if wo.batch_entry_ids:
                continue
            rounding = wc.sfg_product_id.uom_id.rounding
            qty = float_round(wo.qty_produced, precision_rounding=rounding)
            if float_is_zero(qty, precision_rounding=rounding):
                continue
            # Move SFG product from virtual production location into this hall's stock location.
            production_loc = self.env['stock.location'].search([('usage', '=', 'production')], limit=1)
            if not production_loc:
                continue
            move = self.env['stock.move'].create({
                'name': f'SFG: {wc.sfg_product_id.name}',
                'product_id': wc.sfg_product_id.id,
                'product_uom': wc.sfg_product_id.uom_id.id,
                'product_uom_qty': qty,
                'location_id': production_loc.id,
                'location_dest_id': wc.location_id.id,
                'origin': wo.production_id.name,
                'company_id': wo.company_id.id,
            })
            move._action_confirm()
            move.quantity = qty
            move._action_done()
        return res
