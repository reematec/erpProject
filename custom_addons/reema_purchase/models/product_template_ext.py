from odoo import models, fields, api


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        if 'is_storable' in fields_list:
            defaults.setdefault('is_storable', True)
        return defaults

    reema_spec_ids = fields.One2many(
        'reema.product.spec', 'product_tmpl_id',
        string='Specifications',
    )
    reema_inspection_check_ids = fields.One2many(
        'reema.product.inspection.check', 'product_tmpl_id',
        string='Inspection Checklist',
    )

    purchase_approval_required = fields.Boolean(
        string='Owner Approval Required for Purchase',
        default=True,
        help='When enabled, any Purchase Order containing this product requires Owner/Admin final approval. '
             'Disable only for low-risk consumables or general items. Configurable by Owner/Admin only.',
    )

    stock_move_count = fields.Integer(compute='_compute_stock_move_count', string='Stock Moves')

    def _compute_stock_move_count(self):
        for tmpl in self:
            tmpl.stock_move_count = self.env['stock.move'].sudo().search_count([
                ('product_id.product_tmpl_id', '=', tmpl.id),
                ('state', '=', 'done'),
            ])

    def action_view_stock_moves(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Stock Moves — %s' % self.name,
            'res_model': 'stock.move',
            'view_mode': 'list,form',
            'domain': [
                ('product_id.product_tmpl_id', '=', self.id),
                ('state', '=', 'done'),
            ],
        }
