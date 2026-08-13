from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ReemaHrPayslipPayWizard(models.TransientModel):
    _name = 'reema.hr.payslip.pay.wizard'
    _description = 'Pay Payslips'

    payslip_ids = fields.Many2many(
        'reema.hr.payslip', string='Payslips',
        default=lambda self: self.env.context.get('default_payslip_ids', []),
    )
    journal_id = fields.Many2one(
        'account.journal', string='Payment Method', required=True,
        domain=[('type', 'in', ('cash', 'bank'))],
    )
    total_amount = fields.Monetary(string='Total Net Pay', compute='_compute_total_amount', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)

    @api.depends('payslip_ids.net_pay')
    def _compute_total_amount(self):
        for rec in self:
            rec.total_amount = sum(rec.payslip_ids.mapped('net_pay'))

    def action_confirm(self):
        self.ensure_one()
        if not self.payslip_ids:
            raise UserError(_('No payslips selected.'))
        if any(p.state != 'confirmed' for p in self.payslip_ids):
            raise UserError(_('Only confirmed payslips can be paid. Confirm all selected payslips first.'))
        for payslip in self.payslip_ids:
            payslip.action_pay(self.journal_id.id)
        return {'type': 'ir.actions.act_window_close'}
