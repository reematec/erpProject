from odoo import fields, models


class AccountAccountExt(models.Model):
    _inherit = 'account.account'

    reema_hr_employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        ondelete='set null',
        help='The employee this individual advances/loans GL account belongs to.',
    )
