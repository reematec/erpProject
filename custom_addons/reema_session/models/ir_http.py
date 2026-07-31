"""Expose the bottom-chatter model list to the web client.

Which models always show the chatter below the form (instead of aside on
wide screens) is picked from Settings > Technical > Database Structure >
Chatter Layout — a checkbox list of chatter-enabled models
(``ir.model.reema_bottom_chatter``). Takes effect on next page load, no
module upgrade needed.
"""
from odoo import models


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    def session_info(self):
        info = super().session_info()
        models_ = self.env['ir.model'].sudo().search([
            ('reema_bottom_chatter', '=', True),
        ])
        info['bottom_chatter_models'] = models_.mapped('model')
        return info
