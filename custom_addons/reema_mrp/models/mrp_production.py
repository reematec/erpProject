from odoo import models, fields, api
from odoo.exceptions import UserError


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

    def action_confirm(self):
        res = super().action_confirm()
        # Material is issued physically via reema.material.issuance (RMI).
        # Odoo must never lock stock via reservation — clear any auto-reservation
        # that the base confirm or scheduler may have applied to raw material moves.
        self.move_raw_ids.filtered(
            lambda m: m.state not in ('done', 'cancel')
        )._do_unreserve()
        return res
