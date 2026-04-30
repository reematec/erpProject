from odoo import models, fields, api

class ReemaPieceRate(models.Model):
    _name = 'reema.piece.rate'
    _description = 'Piece Rate Matrix'
    _order = 'hall_id, construction_type, ball_size'

    hall_id = fields.Many2one('mrp.workcenter', string='Hall/WorkCenter', required=True)
    construction_type = fields.Selection([
        ('hs', 'Hand Stitched (HS)'),
        ('ms', 'Machine Stitched (MS)'),
        ('hyb', 'Hybrid (HYB)'),
        ('thb', 'Thermo Bonded (THB)')
    ], string='Construction Type', required=True)
    
    ball_size = fields.Selection([
        ('5', 'Size 5'),
        ('4', 'Size 4'),
        ('3', 'Size 3'),
        ('mini', 'Mini/Skills')
    ], string='Ball Size', default='5')

    complexity_level = fields.Selection([
        ('standard', 'Standard'),
        ('high', 'High Complexity'),
        ('premium', 'Premium/Pro')
    ], string='Complexity', default='standard')

    lamination_type = fields.Char(string='Lamination Type', help="e.g., Latex, Adhesive, etc.")
    
    uom_id = fields.Many2one('uom.uom', string='Unit of Measure', required=True)
    rate = fields.Float(string='Rate per Unit', required=True, digits=(16, 2))
    
    active = fields.Boolean(default=True)
    date_start = fields.Date(string='Valid From', default=fields.Date.context_today)
    date_end = fields.Date(string='Valid To')

    def name_get(self):
        result = []
        for rec in self:
            name = f"[{rec.hall_id.name}] {rec.construction_type.upper()} - {rec.ball_size} - {rec.rate}/{rec.uom_id.name}"
            result.append((rec.id, name))
        return result
