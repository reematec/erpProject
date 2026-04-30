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
                ('hall_id', '=', wo.workcenter_id.id), # Assuming WorkCenter is mapped to Hall
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
        res = super(MrpWorkorder, self).button_finish()
        # Custom logic for SFG Stock Movement can be added here
        # This will move the SFG product defined in the WorkCenter
        return res
