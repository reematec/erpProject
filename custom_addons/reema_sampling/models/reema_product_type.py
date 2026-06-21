from odoo import fields, models


class ReemaProductType(models.Model):
    _name = 'reema.product.type'
    _description = 'Product Type'
    _order = 'name'

    name = fields.Char(string='Type', required=True)
    sales_account_id = fields.Many2one(
        'account.account', string='Export Sales Account', required=True,
        domain=[('account_type', 'in', ('income', 'income_other'))],
    )
