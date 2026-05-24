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
        required=True,
        index=True,
        help='Classifies the product for filtering and access control across modules.',
    )

    _PRODUCT_GROUP_NOTE = (
        'Used for filtering products in BOMs, work orders, and work center rules. '
        'Required — cannot save without it.'
    )
    _CATEG_NOTE = (
        'Controls journal accounts for stock moves (COGS, income, inventory valuation) '
        'and costing method (AVCO / FIFO / Standard).'
    )

    product_group_note = fields.Char(
        compute='_compute_field_notes',
        default=lambda self: self._PRODUCT_GROUP_NOTE,
        string=' ',
    )
    categ_note = fields.Char(
        compute='_compute_field_notes',
        default=lambda self: self._CATEG_NOTE,
        string=' ',
    )

    def _compute_field_notes(self):
        for rec in self:
            rec.product_group_note = self._PRODUCT_GROUP_NOTE
            rec.categ_note = self._CATEG_NOTE

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env['ir.sequence']
        for vals in vals_list:
            if not vals.get('product_group'):
                raise UserError(
                    'Product Group is required.\n\n'
                    'Select Raw Material, Packaging, Semi-Finished Good, '
                    'or Finished Good before saving.'
                )
            if not vals.get('default_code'):
                vals['default_code'] = seq.next_by_code('reema.product') or '/'
        return super().create(vals_list)

    @api.depends('name')
    def _compute_display_name(self):
        """Return plain product name — suppress Odoo's default [reference] prefix."""
        for template in self:
            template.display_name = template.name or False

    @api.model
    def _assign_missing_product_references(self):
        """Backfill sequence-based references for products created before this feature."""
        seq = self.env['ir.sequence']
        products = self.search([('default_code', '=', False)])
        for product in products:
            product.default_code = seq.next_by_code('reema.product')


class ProductProductReema(models.Model):
    _inherit = 'product.product'

    @api.depends('name', 'product_tmpl_id')
    def _compute_display_name(self):
        """Return plain product name — suppress Odoo's default [reference] prefix."""
        for product in self:
            product.display_name = product.name or False
