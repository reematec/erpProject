from odoo import models, fields, api

class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    construction_type = fields.Selection([
        ('hs', 'Hand Stitched (HS)'),
        ('ms', 'Machine Stitched (MS)'),
        ('hyb', 'Hybrid (HYB)'),
        ('thb', 'Thermo Bonded (THB)')
    ], string='Construction Type', required=True, default='hyb')
    
    ball_size = fields.Selection([
        ('5', 'Size 5'),
        ('4', 'Size 4'),
        ('3', 'Size 3'),
        ('mini', 'Mini/Skills')
    ], string='Ball Size', default='5', required=True)

    complexity_level = fields.Selection([
        ('standard', 'Standard'),
        ('high', 'High Complexity'),
        ('premium', 'Premium/Pro')
    ], string='Complexity', default='standard')
