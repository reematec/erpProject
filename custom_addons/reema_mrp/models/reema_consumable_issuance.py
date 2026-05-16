from markupsafe import Markup
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ReemaConsumableTransaction(models.Model):
    _name = 'reema.consumable.transaction'
    _description = 'Consumable Store Transaction'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(string='Reference', readonly=True, copy=False, tracking=True)
    transaction_type = fields.Selection([
        ('issuance', 'Issuance (Store → Hall)'),
        ('return', 'Return (Hall → Store)'),
    ], string='Type', required=True, default='issuance', tracking=True)
    date = fields.Datetime(string='Processed On', readonly=True)
    product_id = fields.Many2one('product.product', string='Product', tracking=True)
    product_uom_id = fields.Many2one('uom.uom', related='product_id.uom_id',
                                     string='UOM', readonly=True)
    qty = fields.Float(string='Quantity')
    location_id = fields.Many2one(
        'stock.location', string='Hall',
        domain="[('usage', '=', 'internal')]"
    )
    contractor_id = fields.Many2one('res.partner', string='Issued To')
    carried_by = fields.Char(string='Carried By')
    reason = fields.Char(string='Reason')
    notes = fields.Char(string='Notes')
    move_id = fields.Many2one('stock.move', string='Stock Move', readonly=True)
    processed_by = fields.Many2one('res.users', string='Processed By', readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Done'),
        ('voided', 'Voided'),
    ], default='draft', string='Status', required=True, tracking=True)

    def get_formview_id(self, access_uid=None):
        if self.transaction_type == 'return':
            return self.env.ref('reema_mrp.reema_consumable_return_view_form').id
        return self.env.ref('reema_mrp.reema_consumable_issuance_view_form').id

    def action_new_issuance(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'New Consumable Issuance',
            'res_model': 'reema.consumable.transaction',
            'view_mode': 'form',
            'view_id': self.env.ref('reema_mrp.reema_consumable_issuance_view_form').id,
            'context': {'default_transaction_type': 'issuance'},
            'target': 'current',
        }

    def action_new_return(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'New Consumable Return',
            'res_model': 'reema.consumable.transaction',
            'view_mode': 'form',
            'view_id': self.env.ref('reema_mrp.reema_consumable_return_view_form').id,
            'context': {'default_transaction_type': 'return'},
            'target': 'current',
        }

    @api.onchange('contractor_id')
    def _onchange_contractor_id(self):
        if self.contractor_id:
            self.carried_by = self.contractor_id.name

    def action_process(self):
        self.ensure_one()
        if not self.product_id:
            raise UserError('Please select a product.')
        if self.qty <= 0:
            raise UserError('Quantity must be greater than zero.')
        if not self.location_id:
            raise UserError('Please select the hall location.')
        if self.transaction_type == 'issuance' and not self.contractor_id:
            raise UserError('Please select who the consumable is issued to.')
        if self.transaction_type == 'return' and not self.reason:
            raise UserError('Please enter a reason for the return.')

        warehouse_stock = self.env['stock.warehouse'].search([], limit=1).lot_stock_id
        if not warehouse_stock:
            raise UserError('Could not determine the warehouse stock location.')

        uom_name = self.product_uom_id.name or ''

        if self.transaction_type == 'issuance':
            src = warehouse_stock
            dst = self.location_id
            move_name = f'CDI: {self.product_id.name}'
            seq_code = 'reema.consumable.issuance'
        else:
            src = self.location_id
            dst = warehouse_stock
            move_name = f'CDR: {self.product_id.name}'
            seq_code = 'reema.consumable.return'

        if self.transaction_type == 'issuance':
            quants = self.env['stock.quant'].search([
                ('product_id', '=', self.product_id.id),
                ('location_id', 'child_of', src.id),
            ])
            available_qty = sum(q.quantity - q.reserved_quantity for q in quants)
            if self.qty > available_qty + 0.001:
                raise UserError(
                    f'Insufficient stock for {self.product_id.name}.\n\n'
                    f'Available at {src.complete_name}: '
                    f'{max(available_qty, 0):.3f} {uom_name}\n'
                    f'Requested: {self.qty:.3f} {uom_name}'
                )

        move = self.env['stock.move'].create({
            'name': move_name,
            'product_id': self.product_id.id,
            'product_uom': self.product_uom_id.id,
            'product_uom_qty': self.qty,
            'location_id': src.id,
            'location_dest_id': dst.id,
            'company_id': self.env.company.id,
        })
        move._action_confirm()
        move.quantity = self.qty
        move._action_done()

        seq = self.env['ir.sequence'].next_by_code(seq_code) or _('New')
        self.write({
            'name': seq,
            'state': 'done',
            'move_id': move.id,
            'processed_by': self.env.uid,
            'date': fields.Datetime.now(),
        })

        if self.transaction_type == 'issuance':
            self.message_post(body=Markup(
                f'<b>Consumable issued</b><br/>'
                f'Product: <b>{self.product_id.name}</b><br/>'
                f'Qty: <b>{self.qty:.3f} {uom_name}</b><br/>'
                f'To Hall: {self.location_id.name}<br/>'
                f'Issued to: {self.contractor_id.name}<br/>'
                f'<b>Processed by: {self.env.user.name}</b>'
            ))
        else:
            self.message_post(body=Markup(
                f'<b>Consumable returned to store</b><br/>'
                f'Product: <b>{self.product_id.name}</b><br/>'
                f'Qty: <b>{self.qty:.3f} {uom_name}</b><br/>'
                f'From Hall: {self.location_id.name}<br/>'
                f'Reason: {self.reason}<br/>'
                f'<b>Processed by: {self.env.user.name}</b>'
            ))

    def action_void(self):
        self.ensure_one()
        if self.state == 'voided':
            raise UserError('This record has already been voided.')
        if self.transaction_type != 'issuance':
            raise UserError('Only issuances can be voided.')

        if self.location_id and self.move_id and self.move_id.state == 'done':
            warehouse_stock = self.env['stock.warehouse'].search([], limit=1).lot_stock_id
            move = self.env['stock.move'].create({
                'name': f'CDI Void: {self.product_id.name}',
                'product_id': self.product_id.id,
                'product_uom': self.product_uom_id.id,
                'product_uom_qty': self.qty,
                'location_id': self.location_id.id,
                'location_dest_id': warehouse_stock.id,
                'origin': f'Void: {self.name}',
                'company_id': self.env.company.id,
            })
            move._action_confirm()
            move.quantity = self.qty
            move._action_done()

        self.state = 'voided'
        self.message_post(body=Markup(
            f'<b>Issuance voided</b><br/>'
            f'Qty reversed: <b>{self.qty:.3f} {self.product_uom_id.name}</b><br/>'
            f'<b>Voided by: {self.env.user.name}</b>'
        ))
