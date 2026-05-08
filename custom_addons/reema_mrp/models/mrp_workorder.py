from odoo import models, fields, api
from odoo.exceptions import UserError


class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    contractor_ids = fields.Many2many(
        'res.partner',
        'mrp_workorder_contractor_rel',
        'workorder_id', 'partner_id',
        string='Contractors',
        domain=[('supplier_rank', '>', 0)],
    )
    piece_rate_id = fields.Many2one('reema.piece.rate', string='Applied Piece Rate', compute='_compute_piece_rate', store=True)
    labor_cost = fields.Float(string='Labor Cost', compute='_compute_labor_cost', store=True)

    # Batch progress tracking
    batch_entry_ids = fields.One2many('reema.wo.batch.entry', 'workorder_id', string='Batch Entries')
    qty_batch_completed = fields.Float(string='Completed So Far', compute='_compute_qty_batch_completed', store=True)
    batch_released = fields.Boolean(string='Released to Next Hall', default=False)
    hall_qty = fields.Float(string='Target', compute='_compute_hall_qty', store=True)
    qty_balls_completed = fields.Float(string='Balls Done', compute='_compute_qty_balls_completed', store=True)

    @api.depends('production_id.construction_type', 'production_id.ball_size', 'workcenter_id', 'production_id.complexity_level')
    def _compute_piece_rate(self):
        for wo in self:
            rate = self.env['reema.piece.rate'].search([
                ('hall_id', '=', wo.workcenter_id.id),
                ('construction_type', '=', wo.production_id.construction_type),
                ('ball_size', '=', wo.production_id.ball_size),
                ('complexity_level', '=', wo.production_id.complexity_level),
                ('active', '=', True)
            ], limit=1)
            wo.piece_rate_id = rate.id if rate else False

    @api.depends('batch_entry_ids.labor_cost', 'qty_produced', 'piece_rate_id')
    def _compute_labor_cost(self):
        for wo in self:
            if wo.batch_entry_ids:
                # Batch flow: labor cost summed from each contractor's entries
                wo.labor_cost = sum(wo.batch_entry_ids.mapped('labor_cost'))
            else:
                # Standard single-finish flow: qty_produced × hall rate
                wo.labor_cost = wo.qty_produced * (wo.piece_rate_id.rate if wo.piece_rate_id else 0.0)

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
        if self.state in ('done', 'cancel'):
            raise UserError('Cannot log progress on a finished or cancelled work order.')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Log Batch Progress',
            'res_model': 'reema.batch.entry.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_workorder_id': self.id},
        }

    def button_finish(self):
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
            production_loc = self.env.ref('stock.location_production')
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
