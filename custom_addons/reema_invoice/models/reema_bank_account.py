from odoo import models, fields


class ReemaBankAccount(models.Model):
    _name = 'reema.bank.account'
    _description = 'Predefined Bank Account'
    _order = 'name'

    # Bank name is the display name shown in the dropdown on the invoice.
    name = fields.Char(string='Bank Name', required=True)
    account_title = fields.Char(string='Account Title')
    address = fields.Text(string='Bank Address')
    account_number = fields.Char(string='Account Number')
    iban = fields.Char(string='IBAN')
    swift = fields.Char(string='SWIFT / BIC')
    # archive instead of delete so old invoices keep their bank label readable
    active = fields.Boolean(default=True)
