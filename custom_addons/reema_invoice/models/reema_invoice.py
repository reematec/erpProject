from odoo import models, fields, api, _


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
        ('closed',   'Closed'),
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

    # ── Bank Details ──────────────────────────────────────────────────────────
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
    handling_charges = fields.Monetary(
        string='Handling Charges', currency_field='currency_id',
    )
    courier_charges = fields.Monetary(
        string='Courier Charges', currency_field='currency_id',
    )
    net_total_payable = fields.Monetary(
        string='Net Total Payable', compute='_compute_totals', store=True,
        currency_field='currency_id',
    )

    # ── Computed / onchange ───────────────────────────────────────────────────

    @api.depends('line_ids.qty', 'line_ids.price_subtotal', 'handling_charges', 'courier_charges')
    def _compute_totals(self):
        for rec in self:
            rec.total_qty         = sum(rec.line_ids.mapped('qty'))
            rec.total_amount      = sum(rec.line_ids.mapped('price_subtotal'))
            rec.net_total_payable = rec.total_amount + rec.handling_charges + rec.courier_charges

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        # Pulls the partner's full formatted postal address into the text field.
        self.client_address = self.partner_id._display_address() if self.partner_id else False

    def _compute_our_address(self):
        for rec in self:
            rec.our_address = self.env.company.partner_id._display_address()

    # ── Create ────────────────────────────────────────────────────────────────

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

    def action_reset_to_pending(self):
        self.write({'state': 'pending'})

    def action_print_invoice(self):
        return self.env.ref('reema_invoice.action_report_reema_invoice').report_action(self)


class ReemaInvoiceLine(models.Model):
    _name = 'reema.invoice.line'
    _description = 'Reema Pro Forma Invoice Line'

    invoice_id = fields.Many2one('reema.invoice', string='Invoice', ondelete='cascade')

    # Linking to the Sampling Blueprint gives us the product DNA automatically.
    sample_id = fields.Many2one(
        'reema.sampling.blueprint', string='Sample Code', required=True,
    )

    # These fields are read-only and auto-populate when sample_id is selected.
    sample_name  = fields.Char(string='Name',    related='sample_id.name',    readonly=True)
    sample_color = fields.Char(string='Color',   related='sample_id.color',   readonly=True)
    hs_code      = fields.Char(string='HS Code', related='sample_id.hs_code', readonly=True)
    ean          = fields.Char(string='EAN',     related='sample_id.barcode', readonly=True)

    client_sku = fields.Char(string='Client SKU')

    # Size is filtered to only show sizes defined on the selected sample (via onchange domain).
    size_id = fields.Many2one('reema.sampling.size.line', string='Size', required=True)

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
        # Restrict the Size dropdown to sizes that belong to the chosen sample only.
        if self.sample_id:
            return {'domain': {'size_id': [('blueprint_id', '=', self.sample_id.id)]}}
        return {'domain': {'size_id': []}}
