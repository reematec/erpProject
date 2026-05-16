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
        readonly=True, default=lambda self: _('New'),
    )
    date = fields.Date(
        string='PI Date', default=fields.Date.context_today,
        required=True, tracking=True,
    )
    state = fields.Selection([
        ('pending',  'Pending'),
        ('sent',     'Sent'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
        ('closed',   'Shipped'),
    ], string='Status', default='pending', required=True, tracking=True)

    # ── Customer Details ──────────────────────────────────────────────────────
    # no_create / no_edit: client must already exist — export staff cannot add partners.
    partner_id = fields.Many2one(
        'res.partner', string='Client', required=True, tracking=True,
    )
    # Auto-filled when a client is selected via _onchange_partner_id below.
    client_address = fields.Text(string='Client Address')

    # Client's purchase order reference
    client_order_number = fields.Char(string='Client Order Number', tracking=True)
    client_order_date   = fields.Date(string='Client Order Date')
    payment_terms_id    = fields.Many2one('account.payment.term', string='Payment Terms')

    # ── Shipping & Terms ──────────────────────────────────────────────────────
    # Auto-filled from the current company — no manual entry needed.
    our_address = fields.Text(
        string='Our Address', compute='_compute_our_address', store=False,
    )
    country_of_origin = fields.Char(string='Country of Origin', default='Pakistan')

    transport_method = fields.Selection([
        ('sea',     'Sea Freight'),
        ('air',     'Air Freight'),
        ('road',    'Road Transport'),
        ('courier', 'Courier'),
    ], string='Shipping Method', tracking=True)

    shipping_date      = fields.Date(string='Shipping Date', tracking=True)
    # account.incoterms comes from the 'account' module (e.g. FOB, CIF, EXW).
    incoterm_id        = fields.Many2one('account.incoterms', string='Incoterms')
    incoterm_location  = fields.Char(string='Incoterm Location', default='Sialkot, Pakistan')
    destination        = fields.Char(string='Destination')

    # ── Carton & Weight ───────────────────────────────────────────────────────
    # These fields feed the packing details section of the PI PDF.
    carton_qty   = fields.Integer(string='Number of Cartons')
    carton_size  = fields.Char(string='Carton Size (L×W×H cm)')
    total_cbm    = fields.Float(string='Total CBM', digits=(10, 3))
    gross_weight = fields.Float(string='Gross Weight (kg)', digits=(10, 2))
    net_weight   = fields.Float(string='Net Weight (kg)', digits=(10, 2))

    # Inline shipping documents — each row has a custom label + one file.
    # Using a child model lets users upload multiple files with meaningful names
    # (e.g. "Sticker", "Hologram Layout", "Carton Marking") instead of unnamed attachments.
    document_ids = fields.One2many(
        'reema.invoice.document', 'invoice_id', string='Shipping Documents',
    )

    # ── Bank Details ──────────────────────────────────────────────────────────
    # Selecting a bank fills all the detail fields automatically (onchange below).
    # The detail fields remain editable so one-off overrides are possible per invoice.
    bank_id      = fields.Many2one('reema.bank.account', string='Select Bank')
    bank_name    = fields.Char(string='Bank Name')
    bank_title   = fields.Char(string='Account Title')
    bank_address = fields.Text(string='Bank Address')
    account_num  = fields.Char(string='Account Number')
    iban         = fields.Char(string='IBAN')
    swift        = fields.Char(string='SWIFT / BIC')

    # ── Lines & Totals ────────────────────────────────────────────────────────
    line_ids = fields.One2many('reema.invoice.line', 'invoice_id', string='Invoice Lines')

    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    total_qty = fields.Float(
        string='Total Qty', compute='_compute_totals', store=True,
    )
    total_amount = fields.Monetary(
        string='Total Amount', compute='_compute_totals', store=True,
        currency_field='currency_id',
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
        currency_field='currency_id',
    )
    net_total_payable = fields.Monetary(
        string='Net Total Payable', compute='_compute_totals', store=True,
        currency_field='currency_id',
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
                if rec.state != 'pending':
                    raise UserError(
                        f"Pro Forma Invoice {rec.name} is locked.\n\n"
                        f"Only invoices in Pending status can be edited. "
                        f"Use 'Reset to Pending' if a correction is needed."
                    )
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('reema.invoice') or _('New')
        return super().create(vals_list)

    # ── Status workflow buttons ───────────────────────────────────────────────

    def action_sent(self):
        self.write({'state': 'sent'})

    def action_accept(self):
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
        self.write({'state': 'pending'})

    def action_print_invoice(self):
        return self.env.ref('reema_invoice.action_report_reema_invoice').report_action(self)


class ReemaInvoiceLine(models.Model):
    _name = 'reema.invoice.line'
    _description = 'Reema Pro Forma Invoice Line'

    invoice_id = fields.Many2one('reema.invoice', string='Invoice', ondelete='cascade')

    # Linking to the Sampling Blueprint gives us the product DNA automatically.
    # string='Sample' here — the view labels it "Name" in the column header.
    sample_id = fields.Many2one(
        'reema.sampling.blueprint', string='Sample', required=True,
    )

    # sample_name auto-fills from the sample's product name but stays editable.
    # In Odoo a non-related Char field is always editable; we populate it in onchange.
    sample_name  = fields.Char(string='Name')
    # sample_code stores the reference (e.g. RG/2026-0001) — auto-filled when sample_id
    # is selected via onchange. Stored as Char so the code is stable on the PDF even if
    # the sample reference is later changed.
    sample_code  = fields.Char(string='Sample Code')
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

    @api.onchange('sample_id')
    def _onchange_sample_id(self):
        # Pre-fill all line fields from the selected sample.
        # Because these are now plain Char fields (not related), the user can still edit them
        # after selection — for example to override the color for a specific order.
        if self.sample_id:
            s = self.sample_id
            self.sample_name  = s.name
            self.sample_code  = s.reference
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
