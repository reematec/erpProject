import math

from odoo import models, fields, api
from odoo.exceptions import UserError


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
        domain=[('supplier_rank', '>', 0)],
    )
    # Batch progress tracking
    batch_entry_ids = fields.One2many('reema.wo.batch.entry', 'workorder_id', string='Batch Entries')
    qty_batch_completed = fields.Float(string='Completed So Far', compute='_compute_qty_batch_completed', store=True)
    batch_released = fields.Boolean(string='Released to Next Hall', default=False)
    hall_qty = fields.Float(string='Target', compute='_compute_hall_qty', store=True)
    qty_balls_completed = fields.Float(string='Balls Done', compute='_compute_qty_balls_completed', store=True)

    @api.depends('batch_entry_ids.qty')
    def _compute_qty_batch_completed(self):
        for wo in self:
            wo.qty_batch_completed = sum(wo.batch_entry_ids.mapped('qty'))

    @api.depends('qty_production', 'operation_id.balls_per_unit')
    def _compute_hall_qty(self):
        for wo in self:
            bpu = wo.operation_id.balls_per_unit or 1.0
            wo.hall_qty = wo.qty_production / bpu

    @api.depends('batch_entry_ids.qty_balls')
    def _compute_qty_balls_completed(self):
        for wo in self:
            wo.qty_balls_completed = sum(wo.batch_entry_ids.mapped('qty_balls'))

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
        res = super().button_finish()
        for wo in self:
            wc = wo.workcenter_id
            if not wc.sfg_product_id or not wc.location_id:
                continue
            # Batch entries already created SFG moves per log entry — skip double-creation
            if wo.batch_entry_ids:
                continue
            qty = wo.qty_produced
            if not qty:
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
