from odoo import models, fields


class ReemaProductInspectionCheck(models.Model):
    _name = 'reema.product.inspection.check'
    _description = 'Product Inspection Check'
    _order = 'sequence, id'

    product_tmpl_id = fields.Many2one(
        'product.template', required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(default=10)
    check_name = fields.Char(string='Check', required=True)
    expected_value = fields.Char(string='Standard / Expected')
