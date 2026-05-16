from odoo import models, fields


class ResPartner(models.Model):
    _inherit = 'res.partner'

    batch_entry_count = fields.Integer(
        string='Batch Logs', compute='_compute_batch_entry_count'
    )

    def _compute_batch_entry_count(self):
        for partner in self:
            partner.batch_entry_count = self.env['reema.wo.batch.entry'].search_count([
                ('logged_by.partner_id', '=', partner.id)
            ])

    def action_view_batch_entries(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Batch Logs — {self.name}',
            'res_model': 'reema.wo.batch.entry',
            'view_mode': 'list,form',
            'domain': [('logged_by.partner_id', '=', self.id)],
        }
