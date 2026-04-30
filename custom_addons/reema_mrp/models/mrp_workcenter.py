from odoo import models, fields

class MrpWorkcenter(models.Model):
    _inherit = 'mrp.workcenter'

    is_qc_point = fields.Boolean(string='Is QC Point', default=False)
    sfg_product_id = fields.Many2one('product.product', string='SFG Product Output')
