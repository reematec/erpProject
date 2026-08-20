from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ReemaInvoice(models.Model):
    _name = 'reema.invoice'
    _description = 'Reema Pro Forma Invoice'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    # PI Number is auto-generated from the sequence (e.g. RG/2026-0001).
    # readonly=True prevents manual edits; the create() method below sets it.
    name = fields.Char(
        string='PI Number', required=True, copy=False,
        readonly=True, default=lambda self: _('New'), tracking=True,
    )
    date = fields.Date(
        string='PI Date', default=fields.Date.context_today,
        required=True, tracking=True,
    )
    state = fields.Selection([
        ('draft',    'Draft'),
        ('pending',  'Pending'),
        ('sent',     'Sent'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
        ('closed',   'Shipped'),
    ], string='Status', default='draft', required=True, tracking=True)

    # ── Customer Details ──────────────────────────────────────────────────────
    # no_create / no_edit: client must already exist — export staff cannot add partners.
    partner_id = fields.Many2one(
        'res.partner', string='Client', required=True, tracking=True,
    )
    # Auto-filled when a client is selected via _onchange_partner_id below.
    client_address = fields.Text(string='Client Address', tracking=True)

    # Client's purchase order reference
    client_order_number = fields.Char(string='Client Order Number', tracking=True)
    client_order_date   = fields.Date(string='Client Order Date', tracking=True)
    payment_terms_id    = fields.Many2one('account.payment.term', string='Payment Terms', tracking=True)

    # ── Shipping & Terms ──────────────────────────────────────────────────────
    # Auto-filled from the current company — no manual entry needed.
    our_address = fields.Text(
        string='Our Address', compute='_compute_our_address', store=False,
    )
    country_of_origin = fields.Char(string='Country of Origin', default='Pakistan', tracking=True)

    transport_method = fields.Selection([
        ('sea',     'Sea Freight'),
        ('air',     'Air Freight'),
        ('road',    'Road Transport'),
        ('courier', 'Courier'),
    ], string='Shipping Method', tracking=True)

    shipping_date      = fields.Date(string='Shipping Date', tracking=True)
    # account.incoterms comes from the 'account' module (e.g. FOB, CIF, EXW).
    incoterm_id        = fields.Many2one('account.incoterms', string='Incoterms', tracking=True)
    incoterm_location  = fields.Char(string='Incoterm Location', default='Sialkot, Pakistan', tracking=True)
    destination        = fields.Char(string='Destination', tracking=True)

    # ── Carton & Weight ───────────────────────────────────────────────────────
    # These fields feed the packing details section of the PI PDF.
    carton_qty   = fields.Integer(string='Number of Cartons', tracking=True)
    carton_size  = fields.Char(string='Carton Size (L×W×H cm)', tracking=True)
    total_cbm    = fields.Float(string='Total CBM', digits=(10, 3), tracking=True)
    gross_weight = fields.Float(string='Gross Weight (kg)', digits=(10, 2), tracking=True)
    net_weight   = fields.Float(string='Net Weight (kg)', digits=(10, 2), tracking=True)

    # Inline shipping documents — each row has a custom label + one file.
    # Using a child model lets users upload multiple files with meaningful names
    # (e.g. "Sticker", "Hologram Layout", "Carton Marking") instead of unnamed attachments.
    document_ids = fields.One2many(
        'reema.invoice.document', 'invoice_id', string='Shipping Documents',
    )

    # ── Bank Details ──────────────────────────────────────────────────────────
    # Selecting a bank fills all the detail fields automatically (onchange below).
    # The detail fields remain editable so one-off overrides are possible per invoice.
    bank_id      = fields.Many2one('reema.bank.account', string='Select Bank', tracking=True)
    bank_name    = fields.Char(string='Bank Name', tracking=True)
    bank_title   = fields.Char(string='Account Title', tracking=True)
    bank_address = fields.Text(string='Bank Address', tracking=True)
    account_num  = fields.Char(string='Account Number', tracking=True)
    iban         = fields.Char(string='IBAN', tracking=True)
    swift        = fields.Char(string='SWIFT / BIC', tracking=True)

    # ── Lines & Totals ────────────────────────────────────────────────────────
    line_ids = fields.One2many('reema.invoice.line', 'invoice_id', string='Invoice Lines')

    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env['res.currency'].search([('name', '=', 'USD')], limit=1)
                              or self.env.company.currency_id,
        tracking=True,
    )
    total_qty = fields.Float(
        string='Total Qty', compute='_compute_totals', store=True, tracking=True,
    )
    total_amount = fields.Monetary(
        string='Total Amount', compute='_compute_totals', store=True,
        currency_field='currency_id', tracking=True,
    )
    # Inline additional charges — each row has a custom label and an amount.
    # This replaces the old fixed handling_charges / courier_charges fields
    # so the user can add any number of charges (Handling, Courier, Insurance, etc.)
    # or leave the list empty when none apply.
    charge_ids = fields.One2many(
        'reema.invoice.charge', 'invoice_id', string='Additional Charges',
    )
    total_charges = fields.Monetary(
        string='Total Charges', compute='_compute_totals', store=True,
        currency_field='currency_id', tracking=True,
    )
    net_total_payable = fields.Monetary(
        string='Net Total Payable', compute='_compute_totals', store=True,
        currency_field='currency_id', tracking=True,
    )

    move_id = fields.Many2one(
        'account.move', string='Journal Entry', readonly=True, copy=False, tracking=True,
    )

    # ── Computed / onchange ───────────────────────────────────────────────────

    @api.depends('line_ids.qty', 'line_ids.price_subtotal', 'charge_ids.amount')
    def _compute_totals(self):
        for rec in self:
            rec.total_qty         = sum(rec.line_ids.mapped('qty'))
            rec.total_amount      = sum(rec.line_ids.mapped('price_subtotal'))
            rec.total_charges     = sum(rec.charge_ids.mapped('amount'))
            rec.net_total_payable = rec.total_amount + rec.total_charges

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        # Pulls the partner's full formatted postal address into the text field.
        self.client_address = self.partner_id._display_address() if self.partner_id else False

    @api.onchange('bank_id')
    def _onchange_bank_id(self):
        # When a bank is selected from the predefined list, copy all its details
        # into the individual fields so they appear on the PDF.
        # The individual fields stay editable — useful for one-off changes without
        # modifying the master bank record.
        if self.bank_id:
            b = self.bank_id
            self.bank_name    = b.name
            self.bank_title   = b.account_title
            self.bank_address = b.address
            self.account_num  = b.account_number
            self.iban         = b.iban
            self.swift        = b.swift
        else:
            self.bank_name    = False
            self.bank_title   = False
            self.bank_address = False
            self.account_num  = False
            self.iban         = False
            self.swift        = False

    def _compute_our_address(self):
        for rec in self:
            rec.our_address = self.env.company.partner_id._display_address()

    # ── Create ────────────────────────────────────────────────────────────────

    _LOCKED_FIELDS = {
        'partner_id', 'client_address', 'date', 'client_order_number',
        'client_order_date', 'payment_terms_id', 'country_of_origin',
        'transport_method', 'shipping_date', 'incoterm_id', 'incoterm_location',
        'destination', 'carton_qty', 'carton_size', 'total_cbm', 'gross_weight',
        'net_weight', 'bank_id', 'bank_name', 'bank_title', 'bank_address',
        'account_num', 'iban', 'swift', 'line_ids', 'charge_ids', 'document_ids',
    }

    def write(self, vals):
        blocked = self._LOCKED_FIELDS & vals.keys()
        if blocked:
            for rec in self:
                if rec.state not in ('draft', 'pending'):
                    raise UserError(
                        f"Pro Forma Invoice {rec.name} is locked.\n\n"
                        f"Only invoices in Draft or Pending status can be edited. "
                        f"Use 'Reset to Pending' if a correction is needed."
                    )
        return super().write(vals)

    @api.model
    def _cleanup_phantom_drafts(self):
        cutoff = fields.Datetime.now() - __import__('datetime').timedelta(hours=24)
        phantoms = self.search([
            ('state', '=', 'draft'),
            ('name', '=', _('New')),
            ('create_date', '<', cutoff),
        ])
        if phantoms:
            phantoms.sudo().unlink()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('reema.invoice') or _('New')
        return super().create(vals_list)

    def action_confirm(self):
        self.write({'state': 'pending'})

    def action_discard(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError("Only draft invoices can be discarded.")
        self.unlink()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'reema.invoice',
            'view_mode': 'list',
            'target': 'current',
        }

    def unlink(self):
        if any(rec.state != 'draft' for rec in self):
            raise UserError("Only draft invoices can be deleted.")
        return super().unlink()

    # ── Status workflow buttons ───────────────────────────────────────────────

    def action_sent(self):
        self.write({'state': 'sent'})

    def action_accept(self):
        for rec in self:
            rec._create_accounting_entry()
        self.write({'state': 'accepted'})

    def action_reject(self):
        self.write({'state': 'rejected'})

    def action_close(self):
        self.write({'state': 'closed'})

    def action_undo_shipped(self):
        self.write({'state': 'accepted'})

    def action_reset_to_pending(self):
        for rec in self:
            for po in rec.production_order_ids:
                active_mos = po.line_ids.mapped('mo_id').filtered(
                    lambda mo: mo.state != 'cancel'
                )
                if active_mos:
                    mo_names = ', '.join(active_mos.mapped('name'))
                    raise UserError(
                        f"Cannot reset {rec.name} to Pending.\n\n"
                        f"Cancel the following Manufacturing Orders in {po.name} first:\n"
                        f"{mo_names}"
                    )
                if po.state != 'cancelled':
                    raise UserError(
                        f"Cannot reset {rec.name} to Pending.\n\n"
                        f"Production Order {po.name} must be cancelled first."
                    )
        for rec in self:
            if rec.move_id and rec.move_id.state == 'posted':
                rec.move_id.button_cancel()
                rec.move_id.unlink()
                rec.move_id = False
        self.write({'state': 'pending'})

    def _create_accounting_entry(self):
        self.ensure_one()
        self = self.sudo()
        company = self.env.company
        company_currency = company.currency_id
        invoice_currency = self.currency_id
        date = fields.Date.today()
        is_foreign = invoice_currency != company_currency

        if not self.line_ids:
            raise UserError('Cannot accept an invoice with no lines.')

        receivable_account = self.partner_id.property_account_receivable_id
        if not receivable_account:
            raise UserError(
                f'Customer "{self.partner_id.name}" has no receivable account set. '
                f'Create a GL account for this customer first.'
            )

        pkr_total = invoice_currency._convert(
            self.net_total_payable, company_currency, company, date
        )
        rate = pkr_total / self.net_total_payable if self.net_total_payable else 0.0
        terms = self.payment_terms_id.name or ''

        # Receivable line: PI | FC amount @ rate | Payment Terms
        if is_foreign:
            recv_desc = f"{self.name} | {invoice_currency.name} {self.net_total_payable:,.2f} @ {rate:,.4f}"
        else:
            recv_desc = f"{self.name} | {company_currency.name} {pkr_total:,.2f}"
        if terms:
            recv_desc += f" | {terms}"

        recv_line_vals = {
            'account_id': receivable_account.id,
            'name': recv_desc,
            'debit': pkr_total,
            'credit': 0.0,
        }
        if is_foreign:
            # Only stamp a foreign currency_id/amount_currency when the line
            # actually is foreign — setting currency_id (even to the company's
            # own currency) makes Odoo derive debit/credit FROM amount_currency,
            # so passing amount_currency=0.0 here would silently zero out
            # pkr_total on domestic invoices.
            recv_line_vals['currency_id'] = invoice_currency.id
            recv_line_vals['amount_currency'] = self.net_total_payable
        move_lines = [(0, 0, recv_line_vals)]

        account_totals = {}
        for line in self.line_ids:
            account = line.sample_id.product_type_id.sales_account_id
            if not account:
                raise UserError(
                    f'Sample "{line.sample_code}" has no Product Type or Sales Account configured. '
                    f'Go to Sampling > Configuration > Product Types, then set the Product Type '
                    f'on the sampling blueprint.'
                )
            pkr_line = invoice_currency._convert(
                line.price_subtotal, company_currency, company, date
            )
            type_name = line.sample_id.product_type_id.name
            if account.id not in account_totals:
                account_totals[account.id] = {'pkr': 0.0, 'fc': 0.0, 'type_name': type_name}
            account_totals[account.id]['pkr'] += pkr_line
            account_totals[account.id]['fc'] += line.price_subtotal

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

        # Narration — full summary visible on the journal entry form
        narration = [
            f"Pro Forma Invoice : {self.name}",
            f"Customer          : {self.partner_id.name}",
            f"PI Date           : {self.date}",
        ]
        if self.client_order_number:
            narration.append(f"Client Order No.  : {self.client_order_number}")
        narration.append(f"Invoice Total     : {invoice_currency.name} {self.net_total_payable:,.2f}")
        if is_foreign:
            narration += [
                f"Exchange Rate     : 1 {invoice_currency.name} = {rate:,.4f} {company_currency.name}",
                f"{company_currency.name} Equivalent  : {company_currency.name} {pkr_total:,.2f}",
            ]

        journal = self.env['account.journal'].search(
            [('type', '=', 'sale'), ('company_id', '=', company.id)], limit=1
        )
        if not journal:
            raise UserError('No Sales journal found. Please configure one in Accounting.')

        move = self.env['account.move'].sudo().create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': date,
            'ref': self.name,
            'narration': '\n'.join(narration),
            'line_ids': move_lines,
        })
        move.action_post()
        self.move_id = move

    def action_view_move(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.move_id.id,
            'target': 'current',
        }

    def action_print_invoice(self):
        return {
            'type': 'ir.actions.act_url',
            'url': '/report/html/reema_invoice.report_reema_invoice_html/%s' % ','.join(str(i) for i in self.ids),
            'target': 'new',
        }

    def action_open_accept_wizard(self):
        self.ensure_one()
        wizard = self.env['reema.invoice.accept.wizard'].create({'invoice_id': self.id})
        return {
            'type': 'ir.actions.act_window',
            'name': 'Accept Invoice',
            'res_model': 'reema.invoice.accept.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }


class ReemaInvoiceLine(models.Model):
    _name = 'reema.invoice.line'
    _description = 'Reema Pro Forma Invoice Line'

    invoice_id = fields.Many2one('reema.invoice', string='Invoice', ondelete='cascade')

    # Linking to the Sampling Blueprint gives us the product DNA automatically.
    # string='Sample' here — the view labels it "Name" in the column header.
    sample_id = fields.Many2one(
        'reema.sampling.blueprint', string='Sample', required=True,
    )

    sample_name = fields.Char(
        string='Name',
        compute='_compute_sample_fields', store=True, readonly=False,
    )
    sample_code = fields.Char(
        string='Sample Code',
        compute='_compute_sample_fields', store=True, readonly=False,
    )
    description  = fields.Char(string='Description')

    # Color, HS Code, and EAN pre-fill from the sample but can be overridden per line.
    # (Previously they were related/readonly, which prevented editing — this is the fix.)
    sample_color = fields.Char(string='Color')
    hs_code      = fields.Char(string='HS Code')
    ean          = fields.Char(string='EAN')

    client_sku   = fields.Char(string='Client SKU')

    # Free-text size — no longer locked to the sample's size dropdown.
    # The user can type any value (e.g. "Size 5", "Custom", "XL") without being restricted.
    size         = fields.Char(string='Size')

    qty           = fields.Float(string='Qty', default=1.0)
    price_unit    = fields.Monetary(string='Unit Price', currency_field='currency_id')
    price_subtotal = fields.Monetary(
        string='Amount', compute='_compute_subtotal', store=True,
        currency_field='currency_id',
    )
    currency_id = fields.Many2one('res.currency', related='invoice_id.currency_id')

    @api.depends('qty', 'price_unit')
    def _compute_subtotal(self):
        for line in self:
            line.price_subtotal = line.qty * line.price_unit

    @api.depends('sample_id', 'sample_id.product_tmpl_id.name')
    def _compute_sample_fields(self):
        for line in self:
            line.sample_name = line.sample_id.product_tmpl_id.name or False
            line.sample_code = line.sample_id.reference or False

    @api.onchange('sample_id')
    def _onchange_sample_id(self):
        if self.sample_id:
            s = self.sample_id
            self.sample_color = s.color
            self.hs_code      = s.hs_code
            self.ean          = s.barcode


class ReemaInvoiceDocument(models.Model):
    """One shipping document category per row — a label plus its attached files.

    Why ir.attachment instead of fields.Binary:
    - Binary stores the entire file as base64 in PostgreSQL, which bloats the DB
      and causes render-resets when the binary widget fires blur in editable lists.
    - ir.attachment stores files in Odoo's filestore (disk), keeping the DB lean.
    - The many2many_binary widget gives users a clear "Attach Files" button with
      in-place preview for images and download links for PDFs.
    """
    _name = 'reema.invoice.document'
    _description = 'Invoice Shipping Document'

    invoice_id = fields.Many2one('reema.invoice', ondelete='cascade')
    # Custom label — e.g. "Sticker", "Hologram Layout", "Carton Marking"
    name = fields.Char(string='Document Name')
    # Files stored as ir.attachment records (Odoo filestore / disk).
    # Multiple files per document type are supported (e.g. 3 sticker image variants).
    attachment_ids = fields.Many2many(
        'ir.attachment',
        relation='reema_inv_doc_att_rel',
        column1='doc_id',
        column2='att_id',
        string='Files',
    )
    # Computed count shown in the inline list so users can see at a glance
    # how many files each document type has without opening the popup.
    file_count = fields.Integer(
        string='File Count', compute='_compute_file_count', store=False,
    )

    @api.depends('attachment_ids')
    def _compute_file_count(self):
        for rec in self:
            rec.file_count = len(rec.attachment_ids)


class ReemaInvoiceCharge(models.Model):
    """One additional charge per row — description + amount.
    Replaces the old fixed handling_charges / courier_charges fields.
    The user can add any number of rows (Handling, Courier, Insurance, etc.)
    or leave the list empty when there are no extras.
    """
    _name = 'reema.invoice.charge'
    _description = 'Invoice Additional Charge'

    invoice_id  = fields.Many2one('reema.invoice', ondelete='cascade')
    name        = fields.Char(string='Description', required=True)
    amount      = fields.Monetary(currency_field='currency_id')
    # currency_id is pulled from the parent invoice so the monetary widget
    # displays the correct symbol without the user having to set it manually.
    currency_id = fields.Many2one('res.currency', related='invoice_id.currency_id')


class AccountIncotermsReema(models.Model):
    _inherit = 'account.incoterms'

    @api.depends('code')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.code or ''


class ReemaInvoiceAcceptWizard(models.TransientModel):
    _name = 'reema.invoice.accept.wizard'
    _description = 'Accept Invoice Confirmation'

    invoice_id = fields.Many2one('reema.invoice', required=True, ondelete='cascade')

    def action_confirm(self):
        self.invoice_id.action_accept()
        return {'type': 'ir.actions.act_window_close'}


