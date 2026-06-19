from odoo import models, fields


class ReemaProductSpec(models.Model):
    _name = 'reema.product.spec'
    _description = 'Product Specification'
    _order = 'sequence, id'

    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Product',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Attribute', required=True)
    value = fields.Char(string='Value', required=True)
