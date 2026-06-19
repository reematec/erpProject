from odoo import models, fields


class MrpWorkcenter(models.Model):
    _inherit = 'mrp.workcenter'

    is_qc_point = fields.Boolean(string='Is QC Point', default=False)
    is_packing = fields.Boolean(string='Is Packing Station', default=False)
    is_ilo = fields.Boolean(string='ILO Work Center', default=False,
                            help='If enabled, work order completion is gated on confirmed ILO receipt.')
    is_printing = fields.Boolean(
        string='Printing Work Center',
        default=False,
        help='Enable for screen-printing work centers. When checked, contractor bills '
             'for this hall will show Ball Qty, Impressions/Ball, and Total Impressions '
             'columns so the payable amount can be verified against actual impression counts.',
    )
    hall_unit = fields.Selection([
        ('sheet', 'Sheet'),
        ('panel', 'Panel'),
        ('ball', 'Ball'),
    ], string='Logging Unit', default='ball', required=True,
        help='Physical unit batches are logged in at this hall, used to convert to balls:\n'
             '• Sheet (e.g. Lamination): balls = qty × Balls per Unit (set on the BOM operation).\n'
             '• Panel (e.g. Cutting, Printing, Sorting): balls = qty ÷ panels per ball '
             '(read from the product\'s sampling blueprint).\n'
             '• Ball (e.g. Stitching, Shaping, QC): logged directly in balls (1:1).')
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
        domain=[('code', '=like', '5-2-1%')],
        help='Account debited when a contractor bill is posted for this work center.',
    )
