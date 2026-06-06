from odoo import models, fields, api


class ReemaMaterialRequirement(models.Model):
    _name = 'reema.material.requirement'
    _description = 'Material Requirement Line'
    _order = 'product_id'

    order_id = fields.Many2one(
        'reema.production.order', string='Production Order',
        required=True, ondelete='cascade', index=True,
    )
    product_id = fields.Many2one('product.product', string='Material', readonly=True)
    uom_id = fields.Many2one('uom.uom', string='UOM', readonly=True)

    # Editable — PM picks supplier after verbal calls and types in agreed price
    supplier_id = fields.Many2one(
        'res.partner', string='Supplier',
        domain="[('supplier_rank', '>', 0)]",
        options="{'no_create': True, 'no_edit': True}",
    )
    last_price = fields.Float(
        string='Agreed Price (PKR)',
        digits='Product Price',
        help='Auto-filled from supplier pricelist. Override with verbally agreed price.',
    )

    # Computed quantities — set by _populate_requirements(), readonly
    qty_needed = fields.Float(string='Needed', digits='Product Unit of Measure', readonly=True)
    qty_on_hand = fields.Float(string='On Hand', digits='Product Unit of Measure', readonly=True)
    qty_on_order = fields.Float(string='On Order (PO)', digits='Product Unit of Measure', readonly=True)
    qty_to_procure = fields.Float(string='To Procure', digits='Product Unit of Measure', readonly=True)

    @api.onchange('supplier_id')
    def _onchange_supplier_id(self):
        if not self.supplier_id or not self.product_id:
            return
        # Look up this supplier's price in product.supplierinfo
        seller = self.env['product.supplierinfo'].search([
            ('partner_id', '=', self.supplier_id.id),
            ('product_tmpl_id', '=', self.product_id.product_tmpl_id.id),
        ], order='price asc', limit=1)
        self.last_price = seller.price if seller else 0.0
