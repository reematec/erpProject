from markupsafe import Markup
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_round, float_is_zero


class AccountMoveLineConsumableHallExt(models.Model):
    _inherit = 'account.move.line'

    # Tags the Hall Floor (1-1-7-09) / Consumables Stock (1-1-7-05) lines
    # posted at issuance/return time below, so balances can be audited per
    # hall later — same tagging idea as reema_consumable_mo_id in
    # reema_consumable_stock_take.py, just keyed by location instead of MO.
    reema_hall_location_id = fields.Many2one(
        'stock.location', string='Hall (Consumable Move)', readonly=True, copy=False,
    )


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
    account_move_id = fields.Many2one('account.move', string='Accounting Entry', readonly=True, copy=False)
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
        move.move_line_ids.write({'picked': True})
        move._action_done()

        seq = self.env['ir.sequence'].next_by_code(seq_code) or _('New')
        self.write({
            'name': seq,
            'state': 'done',
            'move_id': move.id,
            'processed_by': self.env.uid,
            'date': fields.Datetime.now(),
        })

        acc_move = self._reema_post_hall_floor_entry()
        if acc_move:
            self.account_move_id = acc_move

        if self.transaction_type == 'issuance':
            self._message_log(body=Markup(
                f'<b>Consumable issued</b><br/>'
                f'Product: <b>{self.product_id.name}</b><br/>'
                f'Qty: <b>{self.qty:.3f} {uom_name}</b><br/>'
                f'To Hall: {self.location_id.name}<br/>'
                f'Issued to: {self.contractor_id.name}<br/>'
                f'<b>Processed by: {self.env.user.name}</b>'
            ))
        else:
            self._message_log(body=Markup(
                f'<b>Consumable returned to store</b><br/>'
                f'Product: <b>{self.product_id.name}</b><br/>'
                f'Qty: <b>{self.qty:.3f} {uom_name}</b><br/>'
                f'From Hall: {self.location_id.name}<br/>'
                f'Reason: {self.reason}<br/>'
                f'<b>Processed by: {self.env.user.name}</b>'
            ))

    def _reema_post_hall_floor_entry(self):
        """Move value in lockstep with the physical stock move above: on
        issuance, value leaves Consumables Stock (1-1-7-05) and lands in
        Consumables — Hall Floor (1-1-7-09) — a holding account for value
        that's physically at a hall but not yet attributed to any order.
        Reversed on return. The Consumable Stock Take later drains this
        account into WIP or COGS per order, once the actual per-order split
        is known."""
        self.ensure_one()
        Account = self.env['account.account'].sudo()
        consumables_stock_acc = Account.search([('code', '=', '1-1-7-05')], limit=1)
        hall_floor_acc = Account.search([('code', '=', '1-1-7-09')], limit=1)
        if not (consumables_stock_acc and hall_floor_acc):
            raise UserError(_('Missing Consumables Stock (1-1-7-05) or '
                               'Consumables — Hall Floor (1-1-7-09) account.'))

        amount = float_round(self.qty * (self.product_id.standard_price or 0.0), precision_digits=2)
        if float_is_zero(amount, precision_digits=2):
            return False

        journal = self.env['account.journal'].sudo().search(
            [('code', '=', 'STK'), ('company_id', '=', self.env.company.id)], limit=1
        )
        if not journal:
            raise UserError(_('No STK journal configured.'))

        is_issuance = self.transaction_type == 'issuance'
        debit_acc = hall_floor_acc if is_issuance else consumables_stock_acc
        credit_acc = consumables_stock_acc if is_issuance else hall_floor_acc
        label = f'{self.name} — {self.product_id.name} @ {self.location_id.name}'

        move = self.env['account.move'].sudo().create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': fields.Date.context_today(self),
            'ref': label,
            'line_ids': [
                (0, 0, {
                    'account_id': debit_acc.id, 'name': label,
                    'debit': amount, 'credit': 0.0,
                    'reema_hall_location_id': self.location_id.id,
                }),
                (0, 0, {
                    'account_id': credit_acc.id, 'name': label,
                    'debit': 0.0, 'credit': amount,
                    'reema_hall_location_id': self.location_id.id,
                }),
            ],
        })
        move.sudo().action_post()
        return move

    def _reema_reverse_hall_floor_entry(self):
        self.ensure_one()
        if not self.account_move_id or self.account_move_id.state != 'posted':
            return False
        orig = self.account_move_id
        reversal = self.env['account.move'].sudo().create({
            'move_type': 'entry',
            'journal_id': orig.journal_id.id,
            'date': fields.Date.context_today(self),
            'ref': f'Reversal: {orig.name}',
            'line_ids': [(0, 0, {
                'account_id': line.account_id.id, 'name': line.name,
                'debit': line.credit, 'credit': line.debit,
                'reema_hall_location_id': line.reema_hall_location_id.id,
            }) for line in orig.line_ids],
        })
        reversal.sudo().action_post()
        return reversal

    def action_void(self):
        self.ensure_one()
        if self.state == 'voided':
            raise UserError('This record has already been voided.')

        is_issuance = self.transaction_type == 'issuance'
        label = 'Issuance' if is_issuance else 'Return'

        if self.location_id and self.move_id and self.move_id.state == 'done':
            warehouse_stock = self.env['stock.warehouse'].search([], limit=1).lot_stock_id
            # Issuance moved Store -> Hall, so voiding it reverses Hall -> Store
            # (as before). Return moved Hall -> Store, so voiding it must
            # reverse the OTHER way, Store -> Hall.
            src = self.location_id if is_issuance else warehouse_stock
            dst = warehouse_stock if is_issuance else self.location_id
            move = self.env['stock.move'].create({
                'name': f'{"CDI" if is_issuance else "CDR"} Void: {self.product_id.name}',
                'product_id': self.product_id.id,
                'product_uom': self.product_uom_id.id,
                'product_uom_qty': self.qty,
                'location_id': src.id,
                'location_dest_id': dst.id,
                'origin': f'Void: {self.name}',
                'company_id': self.env.company.id,
            })
            move._action_confirm()
            move.quantity = self.qty
            move.move_line_ids.write({'picked': True})
            move._action_done()

        self._reema_reverse_hall_floor_entry()
        self.state = 'voided'
        self._message_log(body=Markup(
            f'<b>{label} voided</b><br/>'
            f'Qty reversed: <b>{self.qty:.3f} {self.product_uom_id.name}</b><br/>'
            f'<b>Voided by: {self.env.user.name}</b>'
        ))
