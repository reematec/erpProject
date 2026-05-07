from odoo import models, fields


class MrpWorkcenter(models.Model):
    _inherit = 'mrp.workcenter'

    is_qc_point = fields.Boolean(string='Is QC Point', default=False)
    sfg_product_id = fields.Many2one('product.product', string='SFG Product Output',
                                     domain=[('product_group', '=', 'sfg')])
    location_id = fields.Many2one('stock.location', string='Hall Location',
                                  domain=[('usage', '=', 'internal')],
                                  help='Stock location for this hall. SFG products are moved here when a work order completes.')
