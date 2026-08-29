from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare


class AccountMoveCommercialInvoiceExt(models.Model):
    _inherit = 'account.move'

    # Marks the Dr Receivable / Cr Sales entry created when a Commercial
    # Invoice is confirmed — same identification purpose as
    # is_packing_list_cogs/is_fg_conversion elsewhere in this module.
    is_commercial_invoice_revenue = fields.Boolean(default=False, copy=False)


class ReemaPackingListCommercialInvoiceExt(models.Model):
    _inherit = 'reema.packing.list'

    # Set only on a Packing List that a Commercial Invoice created for
    # itself (the "no Packing List exists yet" path) — lets that Commercial
    # Invoice's own Cancel button know it's safe (and expected) to cancel
    # this Packing List too. A Packing List the user built independently,
    # then merely attached to a Commercial Invoice, is never touched here.
    auto_created_ci_id = fields.Many2one(
        'reema.commercial.invoice', string='Auto-created by Commercial Invoice',
        readonly=True, copy=False,
    )


class ReemaCommercialInvoice(models.Model):
    _name = 'reema.commercial.invoice'
    _description = 'Commercial Invoice'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    name = fields.Char(string='Reference', readonly=True, copy=False, default='New')
    date = fields.Date(string='Date', default=fields.Date.context_today, required=True)
    commercial_invoice_no = fields.Char(
        string='Invoice No.', tracking=True,
        help='The real, external invoice number printed on the document '
             '(e.g. "RG/6460-UK") — pushed automatically onto every Packing '
             'List and Pro Forma Invoice this Commercial Invoice covers.',
    )
    partner_id = fields.Many2one(
        'res.partner', string='Client', required=True, tracking=True,
        domain=[('customer_rank', '>', 0)],
        help='A Commercial Invoice always belongs to one client — it can '
             'bundle several of that client\'s orders, but never more than '
             'one client.',
    )

    # ── Two ways to fill in the lines below ─────────────────────────────────
    # Either attach one existing, already-confirmed Packing List — its lines
    # populate automatically the moment it's picked (locked, since that
    # shipment already happened; clearing the Packing List clears them again)
    # — or leave this empty and enter Order/Article/Qty directly, in which
    # case confirming this invoice quietly creates a real Packing List behind
    # the scenes from what was typed here, reusing all of its existing
    # allocation/shortfall/COGS logic rather than reimplementing any of it.
    packing_list_id = fields.Many2one(
        'reema.packing.list', string='Packing List',
        domain="[('partner_id', '=', partner_id), ('state', '=', 'confirmed')]",
        help='Leave empty to enter Order/Article/Qty directly on this '
             'invoice instead — a Packing List will be created automatically '
             'when this invoice is confirmed.',
    )
    line_ids = fields.One2many('reema.commercial.invoice.line', 'ci_id', string='Lines')

    # ── Ship-to / Bill-to ────────────────────────────────────────────────────
    ship_to_name = fields.Char(string='Goods Addressed To')
    ship_to_address = fields.Text(string='Shipping Address')
    bill_to_name = fields.Char(string='For A/C Of')
    bill_to_address = fields.Text(string='Billing Address')

    # ── Shipment references ─────────────────────────────────────────────────
    container_no = fields.Char(string='Container No.')
    bl_no = fields.Char(string='B/L No.')
    vessel_name = fields.Char(string='Vessel / Per')
    bl_date = fields.Date(string='B/L Date')
    incoterm_id = fields.Many2one('account.incoterms', string='Incoterms', tracking=True)
    incoterm_location = fields.Char(string='Incoterm Location', default='Karachi, Pakistan')
    payment_terms_id = fields.Many2one('account.payment.term', string='Payment Terms', tracking=True)

    # ── Bank Details — same shape as the Pro Forma Invoice's own fields ───────
    bank_id = fields.Many2one('reema.bank.account', string='Select Bank', tracking=True)
    bank_name = fields.Char(string='Bank Name', tracking=True)
    bank_title = fields.Char(string='Account Title', tracking=True)
    bank_address = fields.Text(string='Bank Address', tracking=True)
    account_num = fields.Char(string='Account Number', tracking=True)
    iban = fields.Char(string='IBAN', tracking=True)
    swift = fields.Char(string='SWIFT / BIC', tracking=True)

    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env['res.currency'].search([('name', '=', 'USD')], limit=1)
                              or self.env.company.currency_id,
        tracking=True,
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True)
    account_move_id = fields.Many2one('account.move', string='Revenue Entry', readonly=True, copy=False)

    order_no_display = fields.Char(string='Order No(s)', compute='_compute_order_no_display')
    total_qty = fields.Float(string='Total Qty', compute='_compute_totals')
    total_amount = fields.Monetary(
        string='Total', compute='_compute_totals', currency_field='currency_id',
    )
    total_cartons = fields.Integer(string='Total Cartons', compute='_compute_total_cartons')
    amount_in_words = fields.Char(string='Amount in Words', compute='_compute_amount_in_words')

    @api.depends('line_ids.invoice_id')
    def _compute_order_no_display(self):
        for rec in self:
            names = rec.line_ids.mapped('invoice_id.name')
            rec.order_no_display = ', '.join(sorted(set(names)))

    @api.depends('line_ids.qty', 'line_ids.amount')
    def _compute_totals(self):
        for rec in self:
            rec.total_qty = sum(rec.line_ids.mapped('qty'))
            rec.total_amount = sum(rec.line_ids.mapped('amount'))

    @api.depends('packing_list_id.total_cartons')
    def _compute_total_cartons(self):
        for rec in self:
            rec.total_cartons = rec.packing_list_id.total_cartons

    @api.depends('total_amount', 'currency_id')
    def _compute_amount_in_words(self):
        for rec in self:
            rec.amount_in_words = rec.currency_id.amount_to_text(rec.total_amount) if rec.currency_id else False

    @api.onchange('partner_id')
    def _onchange_partner_id_address(self):
        if self.partner_id:
            addr = self.partner_id._display_address()
            self.ship_to_name = self.partner_id.name
            self.ship_to_address = addr
            self.bill_to_name = self.partner_id.name
            self.bill_to_address = addr

    @api.onchange('packing_list_id')
    def _onchange_packing_list_id(self):
        # Clear and, if a Packing List is now selected, immediately
        # repopulate the lines from it (locked qty — that shipment already
        # happened). Clearing the Packing List clears the lines back out.
        self.line_ids = [(5, 0, 0)]
        if self.packing_list_id:
            if not self.partner_id:
                self.partner_id = self.packing_list_id.partner_id
            self.line_ids = [(0, 0, {
                'packing_list_line_id': pl_line.id,
                'invoice_id': pl_line.invoice_id.id,
                'pi_line_id': pl_line.pi_line_id.id,
                'qty': pl_line.qty,
                'price_unit': pl_line.pi_line_id.price_unit,
            }) for pl_line in self.packing_list_id.line_ids]
            if not self.container_no:
                self.container_no = self.packing_list_id.container_no

    @api.onchange('bank_id')
    def _onchange_bank_id(self):
        if self.bank_id:
            b = self.bank_id
            self.bank_name = b.name
            self.bank_title = b.account_title
            self.bank_address = b.address
            self.account_num = b.account_number
            self.iban = b.iban
            self.swift = b.swift
        else:
            self.bank_name = False
            self.bank_title = False
            self.bank_address = False
            self.account_num = False
            self.iban = False
            self.swift = False

    @api.constrains('packing_list_id', 'partner_id')
    def _check_pl_partner_match(self):
        for rec in self:
            if rec.packing_list_id and rec.packing_list_id.partner_id != rec.partner_id:
                raise UserError(_(
                    'Packing List "%s" belongs to a different client than this invoice.'
                ) % rec.packing_list_id.name)

    @api.constrains('packing_list_id')
    def _check_pl_not_double_invoiced(self):
        for rec in self:
            if not rec.packing_list_id:
                continue
            other = self.search([
                ('packing_list_id', '=', rec.packing_list_id.id),
                ('state', '!=', 'cancelled'),
                ('id', '!=', rec.id),
            ], limit=1)
            if other:
                raise UserError(_(
                    'Packing List "%(pl)s" is already attached to Commercial Invoice "%(ci)s".'
                ) % {'pl': rec.packing_list_id.name, 'ci': other.name})

    @api.constrains('packing_list_id', 'line_ids')
    def _check_line_mode(self):
        for rec in self:
            if rec.packing_list_id and rec.line_ids.filtered(lambda l: not l.packing_list_line_id):
                raise UserError(_(
                    'Lines on this invoice don\'t match its Packing List — reselect '
                    'the Packing List to refresh them.'
                ))

    def copy(self, default=None):
        # Blocked outright — same reasoning as Packing List: a duplicated
        # invoice would re-claim already-invoiced Packing List lines or
        # re-post revenue for the same shipment. Start a fresh one instead.
        raise UserError(_('Commercial Invoices can\'t be duplicated — start a new one instead.'))

    def unlink(self):
        for rec in self:
            if rec.state == 'confirmed':
                raise UserError(_('Cancel "%s" before deleting it.') % rec.name)
        return super().unlink()

    def action_confirm(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Only a draft Commercial Invoice can be confirmed.'))
        if not self.line_ids:
            raise UserError(_('Add at least one line before confirming.'))

        if self.name == 'New':
            self.name = self.env['ir.sequence'].next_by_code('reema.commercial.invoice') or 'New'

        standalone_lines = self.line_ids.filtered(lambda l: not l.packing_list_line_id)
        if standalone_lines:
            pl = self.env['reema.packing.list'].sudo().create({
                'partner_id': self.partner_id.id,
                'date': self.date,
                'client_address': self.ship_to_address,
                'container_no': self.container_no,
                'auto_created_ci_id': self.id,
            })
            for line in standalone_lines:
                pl_line = self.env['reema.packing.list.line'].sudo().create({
                    'packing_list_id': pl.id,
                    'invoice_id': line.invoice_id.id,
                    'pi_line_id': line.pi_line_id.id,
                    'qty': line.qty,
                })
                line.packing_list_line_id = pl_line.id
            pl.message_post(body=_(
                'Auto-created by Commercial Invoice %s — no Packing List existed '
                'yet for this shipment.'
            ) % self.name)
            pl.action_confirm()
            self.packing_list_id = pl.id

        move = self._create_revenue_entry()
        self.state = 'confirmed'
        self.message_post(body=_(
            'Commercial Invoice confirmed — %(currency)s %(amount)s revenue posted (entry %(move)s).'
        ) % {'currency': self.currency_id.name, 'amount': f'{self.total_amount:,.2f}', 'move': move.name})

    def action_cancel(self):
        self.ensure_one()
        if self.state != 'confirmed':
            raise UserError(_('Only a confirmed Commercial Invoice can be cancelled.'))
        if self.account_move_id and self.account_move_id.sudo().state == 'posted':
            orig = self.account_move_id.sudo()
            reversal_lines = [(0, 0, {
                'account_id': line.account_id.id, 'name': line.name,
                'debit': line.credit, 'credit': line.debit,
                'currency_id': line.currency_id.id,
                'amount_currency': -line.amount_currency,
            }) for line in orig.line_ids]
            reversal = self.env['account.move'].sudo().create({
                'move_type': 'entry',
                'journal_id': orig.journal_id.id,
                'date': fields.Date.context_today(self),
                'ref': f'Reversal: {orig.ref}',
                'is_commercial_invoice_revenue': True,
                'line_ids': reversal_lines,
            })
            reversal.sudo().action_post()

        if self.packing_list_id and self.packing_list_id.auto_created_ci_id == self \
                and self.packing_list_id.state == 'confirmed':
            self.packing_list_id.action_cancel()

        self.state = 'cancelled'
        self.message_post(body=_('Commercial Invoice cancelled — revenue entry reversed.'))

    def _create_revenue_entry(self):
        self.ensure_one()
        self = self.sudo()
        company = self.env.company
        company_currency = company.currency_id
        invoice_currency = self.currency_id
        date = self.date
        is_foreign = invoice_currency != company_currency

        receivable_account = self.partner_id.property_account_receivable_id
        if not receivable_account:
            raise UserError(_(
                'Customer "%s" has no receivable account set. Create a GL '
                'account for this customer first.'
            ) % self.partner_id.name)

        total_fc = sum(self.line_ids.mapped('amount'))
        if float_compare(total_fc, 0.0, precision_digits=2) <= 0:
            raise UserError(_('Nothing to post — total invoice value is zero.'))
        pkr_total = invoice_currency._convert(total_fc, company_currency, company, date)
        rate = pkr_total / total_fc if total_fc else 0.0
        terms = self.payment_terms_id.name or ''
        orders = self.order_no_display

        if is_foreign:
            recv_desc = f"{self.name} | {orders} | {invoice_currency.name} {total_fc:,.2f} @ {rate:,.4f}"
        else:
            recv_desc = f"{self.name} | {orders} | {company_currency.name} {pkr_total:,.2f}"
        if terms:
            recv_desc += f" | {terms}"

        recv_line_vals = {
            'account_id': receivable_account.id,
            'name': recv_desc,
            'debit': pkr_total,
            'credit': 0.0,
        }
        if is_foreign:
            recv_line_vals['currency_id'] = invoice_currency.id
            recv_line_vals['amount_currency'] = total_fc
        move_lines = [(0, 0, recv_line_vals)]

        account_totals = {}
        for line in self.line_ids:
            account = line.sample_id.product_type_id.sales_account_id
            if not account:
                raise UserError(_(
                    'Sample "%s" has no Product Type or Sales Account configured. '
                    'Go to Sampling > Configuration > Product Types, then set the '
                    'Product Type on the sampling blueprint.'
                ) % (line.sample_code or line.description or line.pi_line_id.display_name))
            pkr_line = invoice_currency._convert(line.amount, company_currency, company, date)
            type_name = line.sample_id.product_type_id.name
            if account.id not in account_totals:
                account_totals[account.id] = {'pkr': 0.0, 'fc': 0.0, 'type_name': type_name}
            account_totals[account.id]['pkr'] += pkr_line
            account_totals[account.id]['fc'] += line.amount

        for account_id, amounts in account_totals.items():
            if is_foreign:
                credit_desc = (
                    f"{self.name} | {amounts['type_name']} | "
                    f"{invoice_currency.name} {amounts['fc']:,.2f}"
                )
            else:
                credit_desc = f"{self.name} | {amounts['type_name']} | {company_currency.name} {amounts['pkr']:,.2f}"
            credit_line_vals = {
                'account_id': account_id,
                'name': credit_desc,
                'debit': 0.0,
                'credit': amounts['pkr'],
            }
            if is_foreign:
                credit_line_vals['currency_id'] = invoice_currency.id
                credit_line_vals['amount_currency'] = -amounts['fc']
            move_lines.append((0, 0, credit_line_vals))

        narration = [
            f"Commercial Invoice : {self.name}",
        ]
        if self.commercial_invoice_no:
            narration.append(f"Invoice No.        : {self.commercial_invoice_no}")
        narration += [
            f"Customer           : {self.partner_id.name}",
            f"Order No(s)        : {orders}",
            f"Invoice Total      : {invoice_currency.name} {total_fc:,.2f}",
        ]
        if is_foreign:
            narration += [
                f"Exchange Rate      : 1 {invoice_currency.name} = {rate:,.4f} {company_currency.name}",
                f"{company_currency.name} Equivalent    : {company_currency.name} {pkr_total:,.2f}",
            ]

        journal = self.env['account.journal'].search(
            [('type', '=', 'sale'), ('company_id', '=', company.id)], limit=1
        )
        if not journal:
            raise UserError(_('No Sales journal found. Please configure one in Accounting.'))

        move = self.env['account.move'].sudo().create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': date,
            'ref': self.name,
            'narration': '\n'.join(narration),
            'is_commercial_invoice_revenue': True,
            'line_ids': move_lines,
        })
        move.action_post()
        self.account_move_id = move
        return move

    def action_print_commercial_invoice(self):
        if not self:
            return False
        return {
            'type': 'ir.actions.act_url',
            'url': '/report/html/reema_mrp.report_commercial_invoice/%s' % ','.join(str(i) for i in self.ids),
            'target': 'new',
        }


class ReemaCommercialInvoiceLine(models.Model):
    _name = 'reema.commercial.invoice.line'
    _description = 'Commercial Invoice Line'
    _order = 'ci_id, sequence, id'

    ci_id = fields.Many2one('reema.commercial.invoice', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)

    # Set only when this line was pulled in from an existing, already-shipped
    # Packing List — the invoice as a whole is locked in that case (see the
    # "Lines" page's readonly condition), not this field individually:
    # marking it (or invoice_id/pi_line_id/qty below) readonly here would
    # make the web client drop their onchange-set value entirely when
    # saving a brand-new row, since readonly fields aren't sent back to
    # create() — confirmed by reproducing the resulting NOT NULL violation
    # on invoice_id via a Form()-based save test.
    packing_list_line_id = fields.Many2one(
        'reema.packing.list.line', string='Packing List Line', ondelete='restrict',
    )

    invoice_id = fields.Many2one(
        'reema.invoice', string='Order', required=True,
        domain="[('partner_id', '=', parent.partner_id)]",
        options="{'no_open': True, 'no_create': True, 'no_edit': True}",
    )
    pi_line_id = fields.Many2one(
        'reema.invoice.line', string='Article', required=True,
        help='The ordered article being invoiced.',
    )
    available_qty = fields.Float(
        string='Ready to Ship', compute='_compute_available_qty',
        help='Only meaningful for a directly-entered line (no Packing List '
             'yet) — produced and Finished-Goods-converted quantity still '
             'available for this specific article/order.',
    )
    qty = fields.Float(string='Qty')
    price_unit = fields.Float(string='Unit Price', digits=(10, 2))
    amount = fields.Float(string='Amount', compute='_compute_amount', store=True, digits=(10, 2))

    sample_id = fields.Many2one(related='pi_line_id.sample_id', string='Sample', readonly=True)
    sample_code = fields.Char(string='Sample Code', compute='_compute_pi_fields', store=True, readonly=False)
    description = fields.Char(string='Description', compute='_compute_pi_fields', store=True, readonly=False)
    sample_color = fields.Char(string='Color', compute='_compute_pi_fields', store=True, readonly=False)
    hs_code = fields.Char(string='HS Code', compute='_compute_pi_fields', store=True, readonly=False)
    client_sku = fields.Char(string='Client SKU', compute='_compute_pi_fields', store=True, readonly=False)
    size = fields.Char(string='Size', compute='_compute_pi_fields', store=True, readonly=False)

    @api.depends('qty', 'price_unit')
    def _compute_amount(self):
        for line in self:
            line.amount = line.qty * line.price_unit

    @api.depends('pi_line_id')
    def _compute_pi_fields(self):
        for line in self:
            article = line.pi_line_id
            line.sample_code = article.sample_code or False
            line.description = article.description or article.sample_name or article.sample_id.name or False
            line.sample_color = article.sample_color or False
            line.hs_code = article.hs_code or False
            line.client_sku = article.client_sku or False
            line.size = article.size or False

    @api.onchange('pi_line_id')
    def _onchange_pi_line_id_price(self):
        if self.pi_line_id:
            self.price_unit = self.pi_line_id.price_unit

    def _reema_source_po_lines(self):
        self.ensure_one()
        if not self.pi_line_id:
            return self.env['reema.production.order.line']
        return self.env['reema.production.order.line'].sudo().search([
            ('invoice_line_id', '=', self.pi_line_id.id),
        ])

    def _reema_eligible_batches(self):
        self.ensure_one()
        mo_ids = self._reema_source_po_lines().mapped('mo_id').ids
        if not mo_ids:
            return self.env['reema.wo.batch.entry']
        return self.env['reema.wo.batch.entry'].sudo().search([
            ('mo_id', 'in', mo_ids),
            ('workorder_id.workcenter_id.is_packing', '=', True),
            ('fg_account_move_id', '!=', False),
        ], order='date asc')

    @api.depends('pi_line_id', 'packing_list_line_id', 'packing_list_line_id.qty')
    def _compute_available_qty(self):
        for line in self:
            if line.packing_list_line_id:
                # Pulled from a Packing List — that shipment already
                # happened, so show what it actually shipped rather than
                # 0 (which would read as "nothing available", misleading
                # for a line that isn't claiming anything new).
                line.available_qty = line.packing_list_line_id.qty
                continue
            if not line.pi_line_id:
                line.available_qty = 0.0
                continue
            batches = line._reema_eligible_batches()
            line.available_qty = sum(batches.mapped('qty_remaining'))

    @api.constrains('pi_line_id', 'invoice_id')
    def _check_invoice_matches_article(self):
        for line in self:
            if line.pi_line_id and line.pi_line_id.invoice_id != line.invoice_id:
                raise UserError(_(
                    'Article "%(article)s" belongs to order %(real)s, not %(picked)s.'
                ) % {
                    'article': line.pi_line_id.display_name,
                    'real': line.pi_line_id.invoice_id.name,
                    'picked': line.invoice_id.name,
                })

    @api.constrains('qty')
    def _check_qty_positive(self):
        for line in self:
            if float_compare(line.qty, 0.0, precision_digits=2) <= 0:
                raise UserError(_('Quantity must be greater than zero.'))

    @api.constrains('packing_list_line_id', 'invoice_id', 'pi_line_id', 'qty')
    def _check_pulled_line_not_altered(self):
        # Lines pulled from a Packing List are locked server-side, not via
        # UI readonly — a readonly= on these fields tied to packing_list_id
        # (set by the same onchange that populates them) makes the web
        # client drop their onchange-set values from the save entirely.
        for line in self:
            pll = line.packing_list_line_id
            if not pll:
                continue
            if (line.invoice_id != pll.invoice_id or line.pi_line_id != pll.pi_line_id
                    or float_compare(line.qty, pll.qty, precision_digits=2) != 0):
                raise UserError(_(
                    'This line was pulled from Packing List "%s" and can\'t be '
                    'hand-edited — clear and reselect the Packing List instead.'
                ) % pll.packing_list_id.name)
