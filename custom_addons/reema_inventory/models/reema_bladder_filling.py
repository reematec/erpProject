from odoo import models, fields, api, tools, _
from odoo.exceptions import UserError, ValidationError


class ReemaBladderFillingIssue(models.Model):
    _name = 'reema.bladder.filling.issue'
    _description = 'Bladder Filling Issue'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, name desc'

    name = fields.Char(
        string='Reference', readonly=True, copy=False,
        default=lambda self: _('New'), tracking=True,
    )
    date = fields.Date(string='Issue Date', required=True, default=fields.Date.today, tracking=True)
    vendor_id = fields.Many2one(
        'res.partner', string='Filling Vendor', required=True,
        domain=[('supplier_rank', '>', 0), ('is_contractor', '=', False)],
        tracking=True,
    )
    mo_id = fields.Many2one(
        'mrp.production', string='Manufacturing Order', required=True,
        tracking=True,
    )
    account_id = fields.Many2one(
        'product.product', string='Bladder Account', required=True,
        help='The raw bladder product being sent for polyester fiber filling, '
             'e.g. "Futsal Bladder, 80-90g, 130mm".',
        tracking=True,
    )
    qty = fields.Integer(string='Qty Sent', required=True, tracking=True)
    filling_weight = fields.Float(
        string='Filling Weight (g)', required=True, digits=(10, 2),
        help='Target weight of polyester fiber the vendor is asked to fill '
             'into each bladder, to reduce bounce for futsal balls.',
    )
    rate = fields.Float(string='Rate per Bladder (PKR)', digits=(10, 2))
    issued_by = fields.Many2one(
        'res.users', string='Issued By', default=lambda self: self.env.user,
    )
    notes = fields.Text(string='Notes')
    state = fields.Selection(
        [('draft', 'Draft'), ('dispatched', 'Pending Return'), ('closed', 'Closed')],
        string='Status', default='draft', required=True, tracking=True, copy=False,
    )
    move_id = fields.Many2one(
        'stock.move', string='Outward Stock Move', readonly=True, copy=False,
        help='The move that took this batch of raw bladders from the MO\'s '
             'source location to the Bladder Filling (vendor) location.',
    )

    receipt_ids = fields.One2many('reema.bladder.filling.receipt', 'issue_id', string='Receipts')
    receipt_count = fields.Integer(compute='_compute_receipt_count', string='Receipt Count')

    qty_issued_vendor = fields.Integer(
        compute='_compute_vendor_ledger', string='Issued to Vendor',
        help='Total Qty Sent across every Issue with this same Vendor and Bladder '
             'Account, regardless of Manufacturing Order.',
    )
    qty_filled = fields.Integer(
        compute='_compute_vendor_ledger', string='Filled',
    )
    qty_accounted = fields.Integer(
        compute='_compute_vendor_ledger', string='Accounted',
    )
    qty_outstanding = fields.Integer(
        compute='_compute_vendor_ledger', string='Outstanding',
        help='Issued to Vendor minus Accounted, across every Issue with this same '
             'Vendor and Bladder Account — not just this one.',
    )

    @api.depends('vendor_id', 'account_id')
    def _compute_vendor_ledger(self):
        for rec in self:
            if not (rec.vendor_id and rec.account_id):
                rec.qty_issued_vendor = rec.qty_filled = rec.qty_accounted = rec.qty_outstanding = 0
                continue
            siblings = self.search([
                ('vendor_id', '=', rec.vendor_id.id),
                ('account_id', '=', rec.account_id.id),
            ])
            received = siblings.receipt_ids.filtered(lambda r: r.state == 'received')
            rec.qty_issued_vendor = sum(siblings.mapped('qty'))
            rec.qty_filled = sum(received.mapped('qty_filled'))
            rec.qty_accounted = rec.qty_filled + sum(received.mapped('qty_damaged')) + sum(received.mapped('qty_lost'))
            rec.qty_outstanding = rec.qty_issued_vendor - rec.qty_accounted

    def _compute_receipt_count(self):
        for rec in self:
            rec.receipt_count = len(rec.receipt_ids)

    @api.constrains('qty', 'filling_weight')
    def _check_positive(self):
        for rec in self:
            if rec.qty <= 0:
                raise ValidationError(_('Qty Sent must be greater than 0.'))
            if rec.filling_weight <= 0:
                raise ValidationError(_('Filling Weight must be greater than 0.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('reema.bladder.filling.issue') or _('New')
        return super().create(vals_list)

    def unlink(self):
        if any(rec.state != 'draft' for rec in self):
            raise UserError(_('Only a Draft Issue can be deleted — this one already has a stock move against it.'))
        return super().unlink()

    def action_print(self):
        return {
            'type': 'ir.actions.act_url',
            'url': '/report/html/reema_inventory.report_bladder_filling_issue_slip/%s' % ','.join(str(i) for i in self.ids),
            'target': 'new',
        }

    def action_view_receipts(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Receipts'),
            'res_model': 'reema.bladder.filling.receipt',
            'view_mode': 'list,form',
            'domain': [('issue_id', '=', self.id)],
            'context': {'default_issue_id': self.id},
        }

    def action_confirm(self):
        vendor_loc = self.env.ref('reema_inventory.stock_location_bladder_filling')
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only a Draft Issue can be confirmed.'))
            source_loc = rec.mo_id.location_src_id
            quants = self.env['stock.quant'].search([
                ('product_id', '=', rec.account_id.id),
                ('location_id', 'child_of', source_loc.id),
            ])
            available_qty = sum(quants.mapped('quantity'))
            if rec.qty > available_qty + 0.001:
                raise UserError(_(
                    'Insufficient stock for %(product)s.\n\n'
                    'Available at %(location)s: %(available).0f\n'
                    'Requested: %(requested).0f'
                ) % {
                    'product': rec.account_id.display_name,
                    'location': source_loc.complete_name,
                    'available': max(available_qty, 0),
                    'requested': rec.qty,
                })
            move = self.env['stock.move'].create({
                'name': f'Bladder Filling Issue: {rec.account_id.display_name}',
                'product_id': rec.account_id.id,
                'product_uom': rec.account_id.uom_id.id,
                'product_uom_qty': rec.qty,
                'location_id': source_loc.id,
                'location_dest_id': vendor_loc.id,
                'origin': f'{rec.name} / {rec.mo_id.name}',
                'company_id': rec.mo_id.company_id.id,
            })
            move._action_confirm()
            move.quantity = rec.qty
            move.picked = True
            move._action_done()
            rec.move_id = move.id
            rec.state = 'dispatched'
            rec._message_log(body=_(
                'Confirmed: %(qty)s x %(product)s moved to %(location)s.'
            ) % {'qty': rec.qty, 'product': rec.account_id.display_name, 'location': vendor_loc.complete_name})

    def action_reopen(self):
        for rec in self:
            rec.state = 'dispatched'
            rec.sudo().message_post(
                body=_('Reopened by %s.') % self.env.user.name,
                subtype_xmlid='mail.mt_note',
            )


class ReemaBladderFillingReceipt(models.Model):
    _name = 'reema.bladder.filling.receipt'
    _description = 'Bladder Filling Receipt'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, name desc'

    name = fields.Char(
        string='Reference', readonly=True, copy=False,
        default=lambda self: _('New'), tracking=True,
    )
    issue_id = fields.Many2one(
        'reema.bladder.filling.issue', string='Issue', required=True,
        domain=[('state', '=', 'dispatched')],
        tracking=True,
    )
    vendor_id = fields.Many2one(related='issue_id.vendor_id', string='Filling Vendor', store=True, readonly=True)
    mo_id = fields.Many2one(related='issue_id.mo_id', string='Manufacturing Order', store=True, readonly=True)
    account_id = fields.Many2one(related='issue_id.account_id', string='Bladder Account', store=True, readonly=True)
    filling_weight = fields.Float(related='issue_id.filling_weight', string='Filling Weight (g)', store=True, readonly=True)
    rate = fields.Float(related='issue_id.rate', string='Rate per Bladder (PKR)', store=True, readonly=True)

    filled_account_id = fields.Many2one(
        'product.product', string='Filled Bladder Account',
        help='The processed bladder product this batch is received into stock as, '
             'e.g. "Futsal Bladder, 80-90g, 130mm, Filling 20g".',
        tracking=True,
    )
    qty_filled = fields.Integer(string='Qty Filled (Payable)', default=0, tracking=True)
    qty_damaged = fields.Integer(string='Qty Damaged (Returned Unfilled)', default=0, tracking=True)
    qty_lost = fields.Integer(string='Qty Lost (Not Returned)', default=0, tracking=True)

    vendor_pass_number = fields.Char(
        string='Vendor Pass No.',
        help='The vendor\'s own delivery/challan reference, for audit trail.',
    )
    date = fields.Date(string='Receipt Date', required=True, default=fields.Date.today, tracking=True)
    received_by = fields.Many2one('res.users', string='Received By', default=lambda self: self.env.user)
    notes = fields.Text(string='Notes')
    amount = fields.Float(
        string='Amount (PKR)', compute='_compute_amount', store=True, digits=(10, 2),
        help='qty_filled x rate — the vendor is paid for bladders actually filled, not qty sent.',
    )
    state = fields.Selection(
        [('draft', 'Draft'), ('received', 'Received')],
        string='Status', default='draft', required=True, tracking=True, copy=False,
    )
    consume_move_id = fields.Many2one(
        'stock.move', string='Consume Move', readonly=True, copy=False,
        help='Raw bladder (qty_filled) consumed from the vendor location.',
    )
    produce_move_id = fields.Many2one(
        'stock.move', string='Produce Move', readonly=True, copy=False,
        help='Filled bladder (qty_filled) produced into the MO source location.',
    )
    scrap_move_id = fields.Many2one(
        'stock.move', string='Scrap Move', readonly=True, copy=False,
        help='Raw bladder (qty_damaged + qty_lost) written off from the vendor '
             'location to Scrap — damaged bladders returned unfilled, and '
             'bladders the vendor never returned.',
    )

    @api.depends('qty_filled', 'rate')
    def _compute_amount(self):
        for rec in self:
            rec.amount = rec.qty_filled * rec.rate

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('reema.bladder.filling.receipt') or _('New')
        return super().create(vals_list)

    def unlink(self):
        if any(rec.state == 'received' for rec in self):
            raise UserError(_('A received receipt cannot be deleted. Reset it to Draft first if this was an error.'))
        return super().unlink()

    def action_print(self):
        return {
            'type': 'ir.actions.act_url',
            'url': '/report/html/reema_inventory.report_bladder_filling_receipt_slip/%s' % ','.join(str(i) for i in self.ids),
            'target': 'new',
        }

    def action_reset_to_draft(self):
        for rec in self:
            if rec.consume_move_id or rec.produce_move_id or rec.scrap_move_id:
                raise UserError(_(
                    'This receipt already moved stock (consumed/produced/scrapped bladders) — '
                    'it cannot be reset to Draft. Correct the stock impact manually via Inventory '
                    'if this was an error.'
                ))
            if rec.issue_id.state == 'closed':
                rec.issue_id.state = 'dispatched'
            rec.with_context(mail_notrack=True).write({'state': 'draft'})
            rec.sudo().message_post(
                body=_('Receipt reversed to Draft by %s.') % self.env.user.name,
                subtype_xmlid='mail.mt_note',
            )

    def _create_move(self, product, qty, location, location_dest, label):
        move = self.env['stock.move'].create({
            'name': label,
            'product_id': product.id,
            'product_uom': product.uom_id.id,
            'product_uom_qty': qty,
            'location_id': location.id,
            'location_dest_id': location_dest.id,
            'origin': f'{self.name} / {self.issue_id.name}',
            'company_id': self.issue_id.mo_id.company_id.id,
        })
        move._action_confirm()
        move.quantity = qty
        move.picked = True
        move._action_done()
        return move

    def action_receive(self):
        vendor_loc = self.env.ref('reema_inventory.stock_location_bladder_filling')
        production_loc = self.env['stock.location'].search([('usage', '=', 'production')], limit=1)
        scrap_loc = self.env['stock.location'].search([('scrap_location', '=', True)], limit=1)
        for rec in self:
            if rec.state == 'received':
                raise UserError(_('This receipt has already been confirmed.'))
            if not rec.filled_account_id and rec.qty_filled:
                raise UserError(_('Select the Filled Bladder Account before confirming a receipt with filled quantity.'))
            total_this = rec.qty_filled + rec.qty_damaged + rec.qty_lost
            if total_this <= 0:
                raise UserError(_('Enter at least one quantity (Filled, Damaged, or Lost) before confirming.'))
            sibling_total = sum(
                (r.qty_filled + r.qty_damaged + r.qty_lost)
                for r in rec.issue_id.receipt_ids
                if r.state == 'received' and r.id != rec.id
            )
            if sibling_total + total_this > rec.issue_id.qty:
                raise UserError(_(
                    'Total accounted (%(total)s) would exceed the quantity issued (%(issued)s).'
                ) % {'total': sibling_total + total_this, 'issued': rec.issue_id.qty})

            if rec.qty_filled:
                if not production_loc:
                    raise UserError(_('No stock location with usage "Production" found. Please configure one.'))
                rec.consume_move_id = rec._create_move(
                    rec.account_id, rec.qty_filled, vendor_loc, production_loc,
                    f'Bladder Filling Receipt: consume {rec.account_id.display_name}',
                ).id
                rec.produce_move_id = rec._create_move(
                    rec.filled_account_id, rec.qty_filled, production_loc, rec.issue_id.mo_id.location_src_id,
                    f'Bladder Filling Receipt: produce {rec.filled_account_id.display_name}',
                ).id
            damaged_and_lost = rec.qty_damaged + rec.qty_lost
            if damaged_and_lost:
                if not scrap_loc:
                    raise UserError(_('No Scrap location found. Please configure one.'))
                rec.scrap_move_id = rec._create_move(
                    rec.account_id, damaged_and_lost, vendor_loc, scrap_loc,
                    f'Bladder Filling Receipt: scrap {rec.account_id.display_name}',
                ).id

            rec.state = 'received'
            if sibling_total + total_this >= rec.issue_id.qty:
                rec.issue_id.state = 'closed'
            rec._message_log(
                body=_(
                    'Received: %(filled)s filled, %(damaged)s damaged, %(lost)s lost. '
                    'Amount due: PKR %(amount)s'
                ) % {
                    'filled': rec.qty_filled, 'damaged': rec.qty_damaged, 'lost': rec.qty_lost,
                    'amount': f'{rec.amount:,.2f}',
                }
            )


class ReemaBladderFillingBalance(models.Model):
    """Issued vs. Filled/Damaged/Lost ledger, one row per (MO, Vendor) —
    recomputed on every read so 'Outstanding' always reflects reality, same
    approach as reema.bladder.winding.balance."""
    _name = 'reema.bladder.filling.balance'
    _description = 'Bladder Filling Issued vs Received Balance'
    _auto = False
    _order = 'vendor_id, mo_id'

    mo_id = fields.Many2one('mrp.production', string='Manufacturing Order', readonly=True)
    vendor_id = fields.Many2one('res.partner', string='Filling Vendor', readonly=True)
    qty_issued = fields.Integer(string='Qty Issued', readonly=True)
    qty_filled = fields.Integer(string='Qty Filled', readonly=True)
    qty_damaged = fields.Integer(string='Qty Damaged', readonly=True)
    qty_lost = fields.Integer(string='Qty Lost', readonly=True)
    qty_outstanding = fields.Integer(string='Qty Outstanding', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW reema_bladder_filling_balance AS (
                SELECT
                    row_number() OVER (ORDER BY rp.name, mp.name) AS id,
                    d.mo_id,
                    d.vendor_id,
                    d.qty_issued,
                    COALESCE(rcv.qty_filled, 0)  AS qty_filled,
                    COALESCE(rcv.qty_damaged, 0) AS qty_damaged,
                    COALESCE(rcv.qty_lost, 0)    AS qty_lost,
                    d.qty_issued
                        - COALESCE(rcv.qty_filled, 0)
                        - COALESCE(rcv.qty_damaged, 0)
                        - COALESCE(rcv.qty_lost, 0)  AS qty_outstanding
                FROM (
                    SELECT mo_id, vendor_id, SUM(qty) AS qty_issued
                    FROM reema_bladder_filling_issue
                    GROUP BY mo_id, vendor_id
                ) d
                JOIN mrp_production mp ON mp.id = d.mo_id
                JOIN res_partner    rp ON rp.id = d.vendor_id
                LEFT JOIN (
                    SELECT i.mo_id, i.vendor_id,
                           SUM(r.qty_filled)  AS qty_filled,
                           SUM(r.qty_damaged) AS qty_damaged,
                           SUM(r.qty_lost)    AS qty_lost
                    FROM reema_bladder_filling_receipt r
                    JOIN reema_bladder_filling_issue i ON i.id = r.issue_id
                    WHERE r.state = 'received'
                    GROUP BY i.mo_id, i.vendor_id
                ) rcv ON rcv.mo_id = d.mo_id AND rcv.vendor_id = d.vendor_id
            )
        """)

    def action_print(self):
        # Bound to the list view header button. With no selection (the normal
        # case — this is a read-only ledger), print every row currently
        # matching the search view's filters, not every row in the DB.
        if self:
            records = self
        else:
            records = self.search(self.env.context.get('active_domain') or [])
        if not records:
            raise UserError(_('There are no rows to print.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/report/html/reema_inventory.report_bladder_filling_balance/%s' % ','.join(str(i) for i in records.ids),
            'target': 'new',
        }
