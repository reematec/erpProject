from odoo import models, fields, api
from odoo.exceptions import UserError


PRODUCT_GROUP_SELECTION = [
    ('raw_material', 'Raw Material'),
    ('packaging',    'Packaging'),
    ('sfg',          'Semi-Finished Good'),
    ('finished_good','Finished Good'),
]


class ProductTemplateReema(models.Model):
    _inherit = 'product.template'

    product_group = fields.Selection(
        PRODUCT_GROUP_SELECTION,
        string='Product Group',
        index=True,
        help='Classifies the product for filtering and access control across modules.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('product_group'):
                raise UserError(
                    'Product Group is required.\n\n'
                    'Select Raw Material, Packaging, Semi-Finished Good, '
                    'or Finished Good before saving.'
                )
        return super().create(vals_list)
