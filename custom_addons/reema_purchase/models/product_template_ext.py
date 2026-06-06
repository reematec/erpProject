from odoo import models, fields


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    purchase_approval_required = fields.Boolean(
        string='Owner Approval Required for Purchase',
        default=True,
        help='When enabled, any Purchase Order containing this product requires Owner/Admin final approval. '
             'Disable only for low-risk consumables or general items. Configurable by Owner/Admin only.',
    )
