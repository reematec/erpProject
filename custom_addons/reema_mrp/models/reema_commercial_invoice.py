from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare

from .reema_box_packing_list import _reema_qty_str, _reema_compress_box_ranges


class AccountMoveCommercialInvoiceExt(models.Model):
    _inherit = 'account.move'

    # Marks the Dr Receivable / Cr Sales entry created when a Commercial
    # Invoice is confirmed — same identification purpose as
    # is_packing_list_cogs/is_fg_conversion elsewhere in this module.
    is_commercial_invoice_revenue = fields.Boolean(default=False, copy=False)


class ReemaPackingListCommercialInvoiceExt(models.Model):
    _inherit = 'reema.packing.list'

    # Legacy — the (old) Packing List is being retired; new Commercial
    # Invoices link to reema.box.packing.list instead (see
    # ReemaBoxPackingListCommercialInvoiceExt below). Kept only so
    # already-confirmed Commercial Invoices from before the switch still
    # resolve their historical link and cancel correctly.
    auto_created_ci_id = fields.Many2one(
        'reema.commercial.invoice', string='Auto-created by Commercial Invoice',
        readonly=True, copy=False,
    )


class ReemaBoxPackingListCommercialInvoiceExt(models.Model):
    _inherit = 'reema.box.packing.list'

    # Set only on a Box Packing List that a Commercial Invoice created for
    # itself (the "no Box Packing List exists yet" path) — lets that
    # Commercial Invoice's own Cancel button know it's safe (and expected)
    # to cancel this Box Packing List too. A Box Packing List the user
    # built independently, then merely attached to a Commercial Invoice, is
    # never touched here.
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
    # Either attach one existing, already-confirmed Box Packing List — its
    # lines populate automatically the moment it's picked (locked, since
    # that shipment already happened; clearing it clears the lines again) —
    # or leave this empty and enter Order/Article/Qty directly, in which
    # case confirming this invoice quietly creates a real Box Packing List
    # behind the scenes from what was typed here (one placeholder box run
    # holding everything), reusing all of its existing allocation/
    # shortfall/COGS logic rather than reimplementing any of it.
    box_packing_id = fields.Many2one(
        'reema.box.packing.list', string='Box Packing List',
        domain="[('partner_id', '=', partner_id), ('state', '=', 'confirmed')]",
        help='Leave empty to enter Order/Article/Qty directly on this '
             'invoice instead — a Box Packing List will be created '
             'automatically when this invoice is confirmed.',
    )
    # Legacy — the old Packing List is retired; no longer offered for new
    # invoices (see box_packing_id above), kept only so already-confirmed
    # Commercial Invoices from before the switch still show their
    # historical link correctly.
    packing_list_id = fields.Many2one(
        'reema.packing.list', string='Packing List (legacy)',
        readonly=True, copy=False,
        help='From before the switch to Box Packing List — no longer used '
             'for new invoices.',
    )
    line_ids = fields.One2many('reema.commercial.invoice.line', 'ci_id', string='Lines')
    box_entry_ids = fields.One2many(
        'reema.commercial.invoice.box', 'ci_id', string='Boxes',
        help='Only used in standalone mode (no Box Packing List picked above) — '
             'enter real box runs here (same as the Box Packing List\'s own Boxes '
             'tab) if you need a real, printable carton breakdown from this '
             'invoice. Leave empty for a quick invoice with no real breakdown — '
             'one placeholder box gets created instead.',
    )

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

    @api.depends('box_packing_id.total_boxes', 'packing_list_id.total_cartons')
    def _compute_total_cartons(self):
        for rec in self:
            rec.total_cartons = rec.box_packing_id.total_boxes or rec.packing_list_id.total_cartons

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

    @api.onchange('box_packing_id')
    def _onchange_box_packing_id(self):
        # Clear and, if a Box Packing List is now selected, immediately
        # repopulate the lines from it (locked qty — that shipment already
        # happened). Clearing the Box Packing List clears the lines back out.
        self.line_ids = [(5, 0, 0)]
        if self.box_packing_id:
            if not self.partner_id:
                self.partner_id = self.box_packing_id.partner_id
            self.line_ids = [(0, 0, {
                'box_article_id': article.id,
                'invoice_id': article.invoice_id.id,
                'pi_line_id': article.pi_line_id.id,
                'qty': article.qty,
                'price_unit': article.pi_line_id.price_unit,
            }) for article in self.box_packing_id.article_ids]
            if not self.container_no:
                self.container_no = self.box_packing_id.container_no

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

    @api.constrains('box_packing_id', 'partner_id')
    def _check_box_pl_partner_match(self):
        for rec in self:
            if rec.box_packing_id and rec.box_packing_id.partner_id != rec.partner_id:
                raise UserError(_(
                    'Box Packing List "%s" belongs to a different client than this invoice.'
                ) % rec.box_packing_id.name)

    @api.constrains('box_packing_id')
    def _check_box_pl_not_double_invoiced(self):
        for rec in self:
            if not rec.box_packing_id:
                continue
            other = self.search([
                ('box_packing_id', '=', rec.box_packing_id.id),
                ('state', '!=', 'cancelled'),
                ('id', '!=', rec.id),
            ], limit=1)
            if other:
                raise UserError(_(
                    'Box Packing List "%(pl)s" is already attached to Commercial Invoice "%(ci)s".'
                ) % {'pl': rec.box_packing_id.name, 'ci': other.name})

    @api.constrains('box_packing_id', 'line_ids')
    def _check_line_mode(self):
        for rec in self:
            if rec.box_packing_id and rec.line_ids.filtered(lambda l: not l.box_article_id):
                raise UserError(_(
                    'Lines on this invoice don\'t match its Box Packing List — reselect '
                    'it to refresh them.'
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

        standalone_lines = self.line_ids.filtered(lambda l: not l.box_article_id)
        if standalone_lines:
            box_entries = self.box_entry_ids
            if box_entries:
                empty_boxes = box_entries.filtered(lambda b: not b.line_ids)
                if empty_boxes:
                    raise UserError(_(
                        'Carton run(s) %s have no contents — remove them or add articles to them.'
                    ) % ', '.join(b.carton_range or _('(new)') for b in empty_boxes))
                mismatches = []
                for line in standalone_lines:
                    if float_compare(line.packed_qty, line.qty, precision_digits=2) != 0:
                        mismatches.append(_(
                            '%(article)s: invoiced %(qty).2f, packed %(packed).2f'
                        ) % {
                            'article': line.description or line.pi_line_id.display_name,
                            'qty': line.qty, 'packed': line.packed_qty,
                        })
                if mismatches:
                    raise UserError(_(
                        'Packed quantity on the Boxes tab does not match invoiced quantity for:\n%s'
                    ) % '\n'.join(mismatches))

            pl = self.env['reema.box.packing.list'].sudo().create({
                'partner_id': self.partner_id.id,
                'date': self.date,
                'client_address': self.ship_to_address,
                'container_no': self.container_no,
                'auto_created_ci_id': self.id,
            })
            articles = self.env['reema.box.packing.list.article']
            line_to_article = {}
            for line in standalone_lines:
                article = self.env['reema.box.packing.list.article'].sudo().create({
                    'box_packing_id': pl.id,
                    'invoice_id': line.invoice_id.id,
                    'pi_line_id': line.pi_line_id.id,
                    'qty': line.qty,
                })
                line.box_article_id = article.id
                line_to_article[line.id] = article
                articles |= article

            if box_entries:
                # Real box breakdown was entered on the Boxes tab — replicate
                # it exactly under the new Box Packing List.
                for run in box_entries.sorted(lambda r: (r.sequence, r.id)):
                    self.env['reema.box.packing.list.box'].sudo().create({
                        'box_packing_id': pl.id,
                        'sequence': run.sequence,
                        'carton_size': run.carton_size,
                        'carton_weight': run.carton_weight,
                        'carton_qty': run.carton_qty,
                        'line_ids': [
                            (0, 0, {'article_id': line_to_article[bl.article_id.id].id, 'qty': bl.qty})
                            for bl in run.line_ids
                        ],
                    })
            else:
                # No box breakdown was entered — one placeholder box run
                # holding everything, just to satisfy the Box Packing
                # List's own packed-qty-must-match-ordered-qty guard.
                self.env['reema.box.packing.list.box'].sudo().create({
                    'box_packing_id': pl.id,
                    'carton_qty': 1,
                    'line_ids': [(0, 0, {'article_id': a.id, 'qty': a.qty}) for a in articles],
                })
            pl.message_post(body=_(
                'Auto-created by Commercial Invoice %s — no Box Packing List existed '
                'yet for this shipment.'
            ) % self.name)
            pl.action_confirm()
            self.box_packing_id = pl.id

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

        if self.box_packing_id and self.box_packing_id.auto_created_ci_id == self \
                and self.box_packing_id.state == 'confirmed':
            self.box_packing_id.action_cancel()
        # Legacy — an old Commercial Invoice confirmed before the switch to
        # Box Packing List may still hold this link.
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

    def _compute_display_name(self):
        # This model has no 'name' field, so without this override the
        # Boxes tab's Article dropdown (box_line_ids.article_id, in the new
        # models below) would fall back to Odoo's raw "model,id" default.
        for line in self:
            label = line.description or (line.pi_line_id.display_name if line.pi_line_id else False) or _('Line')
            line.display_name = f'{label} ({line.invoice_id.name})' if line.invoice_id else label

    # Set only when this line was pulled in from an existing, already-shipped
    # Box Packing List — the invoice as a whole is locked in that case (see
    # the "Lines" page's readonly condition), not this field individually:
    # marking it (or invoice_id/pi_line_id/qty below) readonly here would
    # make the web client drop their onchange-set value entirely when
    # saving a brand-new row, since readonly fields aren't sent back to
    # create() — confirmed by reproducing the resulting NOT NULL violation
    # on invoice_id via a Form()-based save test.
    box_article_id = fields.Many2one(
        'reema.box.packing.list.article', string='Box Packing Article', ondelete='restrict',
    )
    # Legacy — from before the switch to Box Packing List; no longer set on
    # new lines, kept only so already-confirmed invoices still resolve it.
    packing_list_line_id = fields.Many2one(
        'reema.packing.list.line', string='Packing List Line (legacy)',
        readonly=True, ondelete='restrict',
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

    # Box breakdown — only meaningful in standalone mode (see
    # ReemaCommercialInvoice.box_entry_ids); left at zero/empty when this
    # invoice is instead pulling lines from an existing Box Packing List.
    box_line_ids = fields.One2many(
        'reema.commercial.invoice.box.line', 'article_id', string='Box Placements',
        help='Every box row this article has actually been placed into, on '
             'this invoice\'s own Boxes tab.',
    )
    packed_qty = fields.Float(
        string='Packed', compute='_compute_box_stats', store=True,
        help='Sum of this article\'s quantity across every box on the Boxes '
             'tab — must match Qty before this invoice can be confirmed, if '
             'the Boxes tab is used at all.',
    )
    box_count = fields.Integer(string='Cartons', compute='_compute_box_stats', store=True)
    box_numbers = fields.Char(string='Carton Nos.', compute='_compute_box_stats', store=True)

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

    @api.depends('box_line_ids.qty', 'box_line_ids.box_id.carton_qty',
                 'box_line_ids.box_id.box_no_start', 'box_line_ids.box_id.box_no_end',
                 'ci_id.box_entry_ids.carton_qty')
    def _compute_box_stats(self):
        # Same run-based math as reema.box.packing.list.article — see that
        # model's _compute_box_stats for the full rationale.
        for line in self:
            packed = 0.0
            box_nos = set()
            for bl in line.box_line_ids:
                run = bl.box_id
                packed += (run.carton_qty or 0) * bl.qty
                if run.carton_qty:
                    box_nos.update(range(run.box_no_start, run.box_no_end + 1))
            line.packed_qty = packed
            sorted_nos = sorted(box_nos)
            line.box_count = len(sorted_nos)
            total_boxes = sum(line.ci_id.box_entry_ids.mapped('carton_qty')) or len(sorted_nos)
            pad = max(2, len(str(total_boxes))) if total_boxes else 2
            line.box_numbers = _reema_compress_box_ranges(sorted_nos, pad)

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

    @api.depends('pi_line_id', 'box_article_id', 'box_article_id.qty',
                 'packing_list_line_id', 'packing_list_line_id.qty')
    def _compute_available_qty(self):
        for line in self:
            if line.box_article_id or line.packing_list_line_id:
                # Pulled from a Box Packing List (or, legacy, the old
                # Packing List) — that shipment already happened, so show
                # what it actually shipped rather than 0 (which would read
                # as "nothing available", misleading for a line that isn't
                # claiming anything new).
                line.available_qty = line.box_article_id.qty or line.packing_list_line_id.qty
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

    @api.constrains('box_article_id', 'invoice_id', 'pi_line_id', 'qty')
    def _check_pulled_line_not_altered(self):
        # Lines pulled from a Box Packing List are locked server-side, not
        # via UI readonly — a readonly= on these fields tied to
        # box_packing_id (set by the same onchange that populates them)
        # makes the web client drop their onchange-set values from the
        # save entirely.
        for line in self:
            article = line.box_article_id
            if not article:
                continue
            if (line.invoice_id != article.invoice_id or line.pi_line_id != article.pi_line_id
                    or float_compare(line.qty, article.qty, precision_digits=2) != 0):
                raise UserError(_(
                    'This line was pulled from Box Packing List "%s" and can\'t be '
                    'hand-edited — clear and reselect it instead.'
                ) % article.box_packing_id.name)


class ReemaCommercialInvoiceBox(models.Model):
    # A row here is a RUN of identical physical boxes, same concept as
    # reema.box.packing.list.box — see that model's own class docstring for
    # the full rationale. Only used in standalone mode (see
    # ReemaCommercialInvoice.box_entry_ids): at Confirm, these get
    # transferred into real reema.box.packing.list.box/.box.line records
    # under the Box Packing List this invoice creates for itself.
    _name = 'reema.commercial.invoice.box'
    _description = 'Commercial Invoice — Carton Run'
    _order = 'sequence, id'

    ci_id = fields.Many2one('reema.commercial.invoice', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    carton_size = fields.Char(string='Box Size', help='e.g. "40x30x30 cm"')
    carton_weight = fields.Float(string='Box Weight (kg)', digits=(10, 2), help='Empty-box weight, each.')
    carton_qty = fields.Integer(
        string='No. of Boxes', default=1, required=True,
        help='How many identical physical boxes this run covers. Contents '
             'below is PER BOX, not the run total.',
    )
    box_no_start = fields.Integer(string='From', compute='_compute_box_no_range', store=True)
    box_no_end = fields.Integer(string='To', compute='_compute_box_no_range', store=True)
    carton_range = fields.Char(
        string='Carton No.', compute='_compute_carton_range', store=True,
        help='This run\'s box numbers within the whole shipment, e.g. "01-04".',
    )
    line_ids = fields.One2many(
        'reema.commercial.invoice.box.line', 'box_id', string='Contents',
        help='What goes in EACH box of this run — one row per article for a '
             'mixed box, or just one row for a single-article run.',
    )
    total_qty = fields.Float(
        string='Total Qty', compute='_compute_total_qty', store=True,
        help='No. of Boxes × the sum of Contents qty — the total across this whole run.',
    )
    contents_summary = fields.Char(
        string='Contents (per box)', compute='_compute_contents_summary', store=True,
    )
    is_mixed = fields.Boolean(string='Mixed', compute='_compute_contents_summary', store=True)

    @api.depends('carton_qty', 'sequence', 'ci_id.box_entry_ids.carton_qty',
                 'ci_id.box_entry_ids.sequence')
    def _compute_box_no_range(self):
        for ci in self.mapped('ci_id'):
            runs_in_self = self.filtered(lambda r: r.ci_id == ci)
            all_runs = ci.box_entry_ids.sorted(lambda r: r.sequence)
            start = 1
            for run in all_runs:
                if run in runs_in_self:
                    run.box_no_start = start
                    run.box_no_end = start + (run.carton_qty or 0) - 1
                start += (run.carton_qty or 0)
        for run in self.filtered(lambda r: not r.ci_id):
            run.box_no_start = 1
            run.box_no_end = run.carton_qty or 1

    @api.depends('box_no_start', 'box_no_end', 'carton_qty', 'ci_id.box_entry_ids.carton_qty')
    def _compute_carton_range(self):
        for run in self:
            if not run.carton_qty:
                run.carton_range = False
                continue
            total = sum(run.ci_id.box_entry_ids.mapped('carton_qty')) or run.box_no_end or 0
            pad = max(2, len(str(total)))
            if run.carton_qty == 1:
                run.carton_range = str(run.box_no_start).zfill(pad)
            else:
                run.carton_range = '%s-%s' % (str(run.box_no_start).zfill(pad), str(run.box_no_end).zfill(pad))

    @api.depends('line_ids.qty', 'carton_qty')
    def _compute_total_qty(self):
        for box in self:
            box.total_qty = (box.carton_qty or 0) * sum(box.line_ids.mapped('qty'))

    @api.depends('line_ids.qty', 'line_ids.article_id')
    def _compute_contents_summary(self):
        for box in self:
            if not box.line_ids:
                box.contents_summary = _('empty')
                box.is_mixed = False
                continue
            parts = sorted(
                ((line.article_id.display_name or '', line.qty) for line in box.line_ids),
                key=lambda t: t[0]
            )
            box.is_mixed = len(parts) > 1
            contents = ', '.join('%s x%s' % (name, _reema_qty_str(qty)) for name, qty in parts)
            box.contents_summary = (_('Mixed — %s') % contents) if box.is_mixed else contents

    def _reema_check_not_overpacked(self):
        for article in self.mapped('line_ids.article_id'):
            if float_compare(article.packed_qty, article.qty, precision_digits=2) > 0:
                raise UserError(_(
                    'Too much "%(article)s" packed into boxes: %(packed).2f packed vs. '
                    '%(qty).2f on this invoice (%(over).2f over). Reduce a run\'s '
                    'No. of Boxes or Contents qty.'
                ) % {
                    'article': article.description or article.pi_line_id.display_name,
                    'packed': article.packed_qty, 'qty': article.qty,
                    'over': article.packed_qty - article.qty,
                })

    @api.constrains('carton_qty')
    def _check_carton_qty_not_overpacked(self):
        self._reema_check_not_overpacked()

    def action_delete_box(self):
        self.ensure_one()
        self.unlink()
        return {'type': 'ir.actions.act_window_close'}


class ReemaCommercialInvoiceBoxLine(models.Model):
    _name = 'reema.commercial.invoice.box.line'
    _description = 'Commercial Invoice — Box Contents'
    _order = 'box_id, id'

    box_id = fields.Many2one('reema.commercial.invoice.box', required=True, ondelete='cascade')
    article_id = fields.Many2one(
        'reema.commercial.invoice.line', string='Article', required=True,
        options="{'no_open': True, 'no_create': True, 'no_edit': True}",
        help='Which line from this invoice is in this box, and how many.',
    )
    description = fields.Char(related='article_id.description', string='Description', readonly=True)
    client_sku = fields.Char(related='article_id.client_sku', string='SKU', readonly=True)
    sample_color = fields.Char(related='article_id.sample_color', string='Color', readonly=True)
    size = fields.Char(related='article_id.size', string='Size', readonly=True)
    qty = fields.Float(string='Qty', required=True, help='How many of this article go in EACH box of this run.')

    @api.constrains('qty')
    def _check_qty_positive(self):
        for line in self:
            if float_compare(line.qty, 0.0, precision_digits=2) <= 0:
                raise UserError(_('Quantity must be greater than zero.'))

    @api.constrains('qty', 'article_id')
    def _check_not_overpacked(self):
        self.mapped('box_id')._reema_check_not_overpacked()

    @api.constrains('article_id', 'box_id')
    def _check_article_same_ci(self):
        for line in self:
            if line.article_id.ci_id != line.box_id.ci_id:
                raise UserError(_(
                    'Article "%(article)s" belongs to a different invoice than run %(box)s.'
                ) % {'article': line.article_id.display_name, 'box': line.box_id.carton_range or _('(new)')})
