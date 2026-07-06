from odoo import models, fields, api


class ReemaIloDispatchExt(models.Model):
    _inherit = 'reema.ilo.dispatch'

    outward_pass_line_ids = fields.One2many(
        'reema.ilo.outward.pass.line', 'dispatch_id', string='Outward Pass Lines',
    )
    is_outward_passed = fields.Boolean(
        string='Outward Pass Attached', compute='_compute_is_outward_passed', store=True,
    )

    @api.depends('outward_pass_line_ids')
    def _compute_is_outward_passed(self):
        for rec in self:
            rec.is_outward_passed = bool(rec.outward_pass_line_ids)
