from odoo import models, fields, api


class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    contractor_id = fields.Many2one('res.partner', string='Contractor', domain=[('supplier_rank', '>', 0)])
    piece_rate_id = fields.Many2one('reema.piece.rate', string='Applied Piece Rate', compute='_compute_piece_rate', store=True)
    labor_cost = fields.Float(string='Labor Cost', compute='_compute_labor_cost', store=True)

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

    @api.depends('qty_produced', 'piece_rate_id')
    def _compute_labor_cost(self):
        for wo in self:
            wo.labor_cost = wo.qty_produced * (wo.piece_rate_id.rate if wo.piece_rate_id else 0.0)

    def button_finish(self):
        res = super().button_finish()
        for wo in self:
            wc = wo.workcenter_id
            # Skip halls with no SFG product or no location configured
            if not wc.sfg_product_id or not wc.location_id:
                continue
            qty = wo.qty_produced
            if not qty:
                continue
            # Move SFG product from virtual production location into this hall's stock location.
            # Source is the virtual production location (consumed materials "become" the SFG here).
            # Destination is the hall's own location — stays there until physically picked up.
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
