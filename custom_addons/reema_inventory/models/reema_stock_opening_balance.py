from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class ReemaStockOpeningBalance(models.Model):
    """One-time stock initiation, separate from Inventory Adjustments (which is
    for correcting an existing on-hand count, not for seeding a product's very
    first quantity). Posts a single stock move from the product's own
    Inventory Adjustment virtual location — the same source Odoo's own
    Inventory Adjustments screen uses — into the chosen location, so the
    on-hand result and audit trail are identical to core, just entered
    through a purpose-built one-row-per-product form."""
    _name = 'reema.stock.opening.balance'
    _description = 'Stock Opening Balance'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, name desc'

    name = fields.Char(
        string='Reference', readonly=True, copy=False,
        default=lambda self: _('New'), tracking=True,
    )
    date = fields.Date(string='Date', required=True, default=fields.Date.today, tracking=True)
    product_id = fields.Many2one(
        'product.product', string='Product', required=True,
        domain=[('is_storable', '=', True)],
        tracking=True,
    )
    uom_id = fields.Many2one(related='product_id.uom_id', string='UoM', readonly=True)
    location_id = fields.Many2one(
        'stock.location', string='Location', required=True,
        domain=[('usage', '=', 'internal')],
        default=lambda self: self.env['stock.warehouse'].search(
            [('company_id', '=', self.env.company.id)], limit=1).lot_stock_id,
        tracking=True,
    )
    quantity = fields.Float(
        string='Opening Quantity', required=True, digits='Product Unit of Measure', tracking=True,
    )
    notes = fields.Char(string='Notes')
    entered_by = fields.Many2one('res.users', string='Entered By', default=lambda self: self.env.user)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, default=lambda self: self.env.company,
    )
    state = fields.Selection(
        [('draft', 'Draft'), ('posted', 'Posted')],
        string='Status', default='draft', required=True, tracking=True, copy=False,
    )
    move_id = fields.Many2one(
        'stock.move', string='Stock Move', readonly=True, copy=False,
        help='The move that brought this opening quantity into stock, sourced '
             'from the product\'s Inventory Adjustment virtual location.',
    )

    @api.constrains('quantity')
    def _check_quantity(self):
        for rec in self:
            if rec.quantity <= 0:
                raise ValidationError(_('Opening Quantity must be greater than 0.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('reema.stock.opening.balance') or _('New')
        return super().create(vals_list)

    def unlink(self):
        if any(rec.state == 'posted' for rec in self):
            raise UserError(_('A Posted opening balance cannot be deleted. Reset it to Draft first if this was an error.'))
        return super().unlink()

    def action_post(self):
        for rec in self:
            if rec.state == 'posted':
                raise UserError(_('This opening balance has already been posted.'))
            existing_qty = sum(self.env['stock.quant'].search([
                ('product_id', '=', rec.product_id.id),
                ('location_id', '=', rec.location_id.id),
            ]).mapped('quantity'))
            if existing_qty:
                raise UserError(_(
                    '%(product)s already has %(qty)s on hand at %(location)s. Opening balances are '
                    'for first-time stock initiation only — use Inventory Adjustments for corrections '
                    'to stock that already exists.'
                ) % {
                    'product': rec.product_id.display_name,
                    'qty': existing_qty,
                    'location': rec.location_id.complete_name,
                })
            source_loc = rec.product_id.with_company(rec.company_id).property_stock_inventory
            if not source_loc:
                raise UserError(_('No Inventory Adjustment location configured for %s.') % rec.product_id.display_name)
            move = self.env['stock.move'].create({
                'name': f'Opening Balance: {rec.product_id.display_name}',
                'product_id': rec.product_id.id,
                'product_uom': rec.product_id.uom_id.id,
                'product_uom_qty': rec.quantity,
                'location_id': source_loc.id,
                'location_dest_id': rec.location_id.id,
                'origin': rec.name,
                'company_id': rec.company_id.id,
            })
            move._action_confirm()
            move.quantity = rec.quantity
            move.picked = True
            move._action_done()
            rec.move_id = move.id
            rec.state = 'posted'
            rec._message_log(body=_(
                'Posted: opening quantity %(qty)s x %(product)s at %(location)s.'
            ) % {
                'qty': rec.quantity,
                'product': rec.product_id.display_name,
                'location': rec.location_id.complete_name,
            })

    def action_reset_to_draft(self):
        for rec in self:
            if rec.move_id:
                raise UserError(_(
                    'This opening balance already moved stock — it cannot be reset to Draft. '
                    'Correct the stock impact manually via Inventory if this was an error.'
                ))
            rec.state = 'draft'
