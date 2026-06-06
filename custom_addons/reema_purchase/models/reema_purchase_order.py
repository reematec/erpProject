from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ReemaPurchaseOrder(models.Model):
    _name = 'reema.purchase.order'
    _description = 'Purchase Order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name desc'

    name = fields.Char(
        string='PO Number', readonly=True, copy=False,
        default=lambda self: _('New'), tracking=True,
    )
    date = fields.Date(
        string='PO Date', default=fields.Date.context_today,
        required=True, tracking=True,
    )
    partner_id = fields.Many2one(
        'res.partner', string='Supplier', required=True,
        domain=[('supplier_rank', '>', 0), ('is_contractor', '=', False)],
        tracking=True,
    )
    partner_ref = fields.Char(string='RFQ Reference', tracking=True,
                               help="Supplier's quotation or reference number")
    date_expected = fields.Date(string='Expected Delivery', tracking=True)
    payment_term_id = fields.Many2one(
        'account.payment.term', string='Payment Terms', tracking=True,
    )
    buyer_id = fields.Many2one(
        'res.users', string='Prepared By',
        default=lambda self: self.env.user, tracking=True, readonly=True,
    )
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    notes = fields.Text(string='Terms & Conditions')
    state = fields.Selection([
        ('draft',     'Draft'),
        ('submitted', 'Waiting Confirmation'),
        ('confirmed', 'Confirmed'),
        ('approved',  'Approved'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True, copy=False)

    line_ids = fields.One2many('reema.purchase.order.line', 'order_id', string='Order Lines')

    amount_untaxed = fields.Monetary(
        string='Untaxed Amount', compute='_compute_amounts', store=True,
    )
    amount_tax = fields.Monetary(
        string='Tax', compute='_compute_amounts', store=True,
    )
    amount_total = fields.Monetary(
        string='Total', compute='_compute_amounts', store=True,
    )

    needs_approval = fields.Boolean(
        string='Requires Owner Approval',
        compute='_compute_needs_approval', store=True,
    )

    gate_pass_count = fields.Integer(compute='_compute_gate_pass_count')
    grn_count = fields.Integer(compute='_compute_grn_count')
    product_summary = fields.Char(
        string='Items', compute='_compute_product_summary',
    )

    # ── Compute ────────────────────────────────────────────────────────────

    @api.depends('line_ids.price_subtotal', 'line_ids.price_tax')
    def _compute_amounts(self):
        for rec in self:
            rec.amount_untaxed = sum(rec.line_ids.mapped('price_subtotal'))
            rec.amount_tax = sum(rec.line_ids.mapped('price_tax'))
            rec.amount_total = rec.amount_untaxed + rec.amount_tax

    @api.depends('line_ids.product_id.purchase_approval_required')
    def _compute_needs_approval(self):
        for rec in self:
            rec.needs_approval = any(
                line.product_id.purchase_approval_required
                for line in rec.line_ids if line.product_id
            )

    @api.depends('line_ids.product_id')
    def _compute_product_summary(self):
        for rec in self:
            names = rec.line_ids.mapped('product_id.name')
            rec.product_summary = ', '.join(names) if names else ''

    def _compute_gate_pass_count(self):
        for rec in self:
            rec.gate_pass_count = self.env['reema.gate.pass'].sudo().search_count(
                [('po_id', '=', rec.id)]
            )

    def _compute_grn_count(self):
        for rec in self:
            rec.grn_count = self.env['reema.grn'].sudo().search_count(
                [('po_id', '=', rec.id)]
            )

    # ── CRUD ────────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('reema.purchase.order') or _('New')
        return super().create(vals_list)

    # ── Actions ─────────────────────────────────────────────────────────────

    def action_submit(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError(_('Cannot submit a Purchase Order with no lines.'))
            rec.write({'state': 'submitted'})
            rec.sudo().message_post(body=_('PO submitted for Production Manager confirmation.'), subtype_xmlid='mail.mt_note', author_id=self.env.user.partner_id.id)
            managers = self.env.ref('reema_purchase.group_reema_purchase_manager').users
            for user in managers:
                rec.with_context(mail_activity_quick_update=True).activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_('Confirm Purchase Order'),
                    note=_('PO <b>%s</b> submitted by <b>%s</b> is waiting for your confirmation.') % (
                        rec.name, rec.buyer_id.name or self.env.user.name),
                    user_id=user.id,
                )

    def action_confirm(self):
        for rec in self:
            rec.sudo().activity_ids.unlink()
            rec.write({'state': 'confirmed'})
            rec.sudo().message_post(body=_('PO confirmed by %s.') % self.env.user.name, subtype_xmlid='mail.mt_note', author_id=self.env.user.partner_id.id)
            if not rec.needs_approval:
                rec.sudo().message_post(body=_('No owner approval required — PO is active.'), subtype_xmlid='mail.mt_note', author_id=self.env.user.partner_id.id)
            else:
                owners = self.env.ref('reema_purchase.group_reema_owner').users
                for user in owners:
                    rec.with_context(mail_activity_quick_update=True).activity_schedule(
                        'mail.mail_activity_data_todo',
                        summary=_('Approve Purchase Order'),
                        note=_('PO <b>%s</b> confirmed by <b>%s</b> is waiting for your final approval.') % (
                            rec.name, self.env.user.name),
                        user_id=user.id,
                    )

    def action_approve(self):
        for rec in self:
            rec.sudo().activity_ids.unlink()
            rec.write({'state': 'approved'})
            rec.sudo().message_post(body=_('PO approved by %s.') % self.env.user.name, subtype_xmlid='mail.mt_note', author_id=self.env.user.partner_id.id)

    def action_cancel(self):
        for rec in self:
            if rec.grn_count:
                raise UserError(_('Cannot cancel: GRN(s) exist for this PO.'))
            rec.sudo().activity_ids.unlink()
            rec.write({'state': 'cancelled'})
            rec.sudo().message_post(body=_('PO cancelled by %s.') % self.env.user.name, subtype_xmlid='mail.mt_note', author_id=self.env.user.partner_id.id)

    def action_reset_to_draft(self):
        for rec in self:
            rec.write({'state': 'draft'})

    def action_print_po(self):
        return self.env.ref('reema_purchase.report_purchase_order').report_action(self)

    def action_view_gate_passes(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Inward Gate Passes'),
            'res_model': 'reema.gate.pass',
            'view_mode': 'list,form',
            'domain': [('po_id', '=', self.id)],
            'context': {'default_po_id': self.id},
        }

    def action_view_grns(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('GRNs'),
            'res_model': 'reema.grn',
            'view_mode': 'list,form',
            'domain': [('po_id', '=', self.id)],
            'context': {'default_po_id': self.id},
        }


class ReemaPurchaseOrderLine(models.Model):
    _name = 'reema.purchase.order.line'
    _description = 'Purchase Order Line'
    _order = 'order_id, sequence, id'

    order_id = fields.Many2one(
        'reema.purchase.order', string='Purchase Order',
        required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one(
        'product.product', string='Product / Material', required=True,
        domain=[('product_tmpl_id.product_group', '=', 'raw_material')],
    )
    name = fields.Char(string='Description')
    product_qty = fields.Float(string='Ordered Qty', default=1.0, required=True)
    product_uom_id = fields.Many2one(
        'uom.uom', string='Unit',
        related='product_id.uom_po_id', store=True,
    )
    price_unit = fields.Float(string='Unit Price (PKR)', required=True)
    color = fields.Char(string='Color')
    thickness = fields.Char(string='Thickness / Spec')
    tax_ids = fields.Many2many('account.tax', string='Tax',
                                domain=[('type_tax_use', '=', 'purchase')])

    price_subtotal = fields.Monetary(
        string='Subtotal', compute='_compute_price', store=True,
        currency_field='currency_id',
    )
    price_tax = fields.Monetary(
        string='Tax Amount', compute='_compute_price', store=True,
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(related='order_id.currency_id', store=True)

    qty_received = fields.Float(
        string='Received Qty', compute='_compute_qty_received',
    )

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.name = self.product_id.display_name
            self.price_unit = self.product_id.standard_price

    @api.depends('product_qty', 'price_unit', 'tax_ids')
    def _compute_price(self):
        for line in self:
            taxes = line.tax_ids.compute_all(
                line.price_unit, line.currency_id, line.product_qty,
                product=line.product_id, partner=line.order_id.partner_id,
            )
            line.price_subtotal = taxes['total_excluded']
            line.price_tax = taxes['total_included'] - taxes['total_excluded']

    def _compute_qty_received(self):
        for line in self:
            grn_lines = self.env['reema.grn.line'].sudo().search([
                ('po_line_id', '=', line.id),
                ('grn_id.state', 'in', ['approved', 'accounted']),
            ])
            line.qty_received = sum(grn_lines.mapped('accepted_qty'))
