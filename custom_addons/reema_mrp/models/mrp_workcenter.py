from odoo import models, fields


class MrpWorkcenter(models.Model):
    _inherit = 'mrp.workcenter'

    is_qc_point = fields.Boolean(string='Is QC Point', default=False)
    sfg_product_id = fields.Many2one('product.product', string='SFG Product Output',
                                     domain=[('product_group', '=', 'sfg')])
    location_id = fields.Many2one('stock.location', string='Hall Location',
                                  domain=[('usage', '=', 'internal')],
                                  help='Stock location for this hall. SFG products are moved here when a work order completes.')
    workforce_type = fields.Selection([
        ('contractor', 'Contractor'),
        ('employee', 'Employee'),
    ], string='Workforce Type', default='contractor', required=True)
    expense_account_id = fields.Many2one(
        'account.account',
        string='Labor Expense Account',
        domain=[('code', '=like', '52%')],
        help='Account debited when a contractor bill is posted for this work center.',
    )
