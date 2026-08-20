from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

# Product category name -> the inventory/asset account that category's stock
# sits in (see custom_addons COA). Used to route a per-product price
# correction to the material's own account instead of a generic bucket, so
# the corrected cost actually blends into that material's average cost and
# flows into COGS naturally when it's consumed — not just tracked separately.
REEMA_CATEG_ASSET_CODE = {
    'Raw Materials': '1-1-7-01',
    'Semi-Finished Goods': '1-1-7-02',
    'Work In Progress': '1-1-7-03',
    'Finished Goods': '1-1-7-04',
    'Consumables': '1-1-7-05',
    'Packing Materials': '1-1-7-06',
}


class AccountMoveVendorBillMatching(models.Model):
    """Vendor Bill <-> GRN matching, built into the Bill's own posting flow.

    A Bill linked to a Purchase Order that has GRNs recorded against it can
    only be posted once the match is approved — there is no separate record
    or separate journal entry for this. Posting the Bill itself is the one
    and only accounting event; matching just gates whether that's allowed.

    Bills with no Purchase Order (or a PO with no GRNs — services, direct
    purchases, anything outside the GRN/IGP path) are entirely unaffected
    and post exactly like a normal Odoo vendor bill.
    """
    _inherit = 'account.move'

    reema_po_id = fields.Many2one(
        'reema.purchase.order', string='Purchase Order',
        domain=[('state', 'in', ('confirmed', 'approved'))],
        tracking=True,
    )
    reema_grn_ids = fields.Many2many(
        'reema.grn', 'account_move_reema_grn_rel', 'move_id', 'grn_id',
        string='Goods Receipt Notes',
        domain="[('po_id', '=', reema_po_id), ('state', '=', 'verified')]",
        tracking=True,
    )
    reema_gate_pass_ids = fields.Many2many(
        'reema.gate.pass', 'account_move_reema_gate_pass_rel', 'move_id', 'gate_pass_id',
        string='Inward Gate Passes', compute='_compute_reema_gate_pass_ids', store=True,
    )
    reema_requires_match = fields.Boolean(
        string='Requires GRN Match', compute='_compute_reema_requires_match', store=True,
    )
    reema_match_state = fields.Selection([
        ('na',        'Not Required'),
        ('pending',   'Pending Match'),
        ('submitted', 'Waiting Approval'),
        ('matched',   'Matched'),
    ], string='Match Status', default='na', required=True, copy=False, tracking=True)
    reema_grn_amount = fields.Monetary(
        string='GRN Accepted Value', compute='_compute_reema_grn_amount', store=True,
    )
    reema_match_difference = fields.Monetary(
        string='Price Variance (Negotiated − GRN)', compute='_compute_reema_match_difference',
    )
    reema_match_submitted_by = fields.Many2one('res.users', string='Submitted By', readonly=True, copy=False, tracking=True)
    reema_match_approved_by = fields.Many2one('res.users', string='Approved By', readonly=True, copy=False, tracking=True)
    reema_partner_missing_gl = fields.Boolean(
        string='Vendor Missing GL Account', compute='_compute_reema_partner_missing_gl',
    )

    # ── Compute ──────────────────────────────────────────────────────────

    @api.depends('reema_grn_ids.gate_pass_id')
    def _compute_reema_gate_pass_ids(self):
        for move in self:
            move.reema_gate_pass_ids = move.reema_grn_ids.mapped('gate_pass_id')

    @api.depends('reema_po_id', 'reema_po_id.grn_count')
    def _compute_reema_requires_match(self):
        for move in self:
            move.reema_requires_match = bool(move.reema_po_id and move.reema_po_id.grn_count)

    @api.depends('reema_grn_ids.line_ids.accepted_qty', 'reema_grn_ids.line_ids.price_unit')
    def _compute_reema_grn_amount(self):
        for move in self:
            move.reema_grn_amount = sum(
                line.accepted_qty * line.price_unit
                for grn in move.reema_grn_ids
                for line in grn.line_ids
            )

    @api.depends('invoice_line_ids.reema_negotiated_price', 'invoice_line_ids.price_unit',
                 'invoice_line_ids.quantity', 'invoice_line_ids.reema_is_variance_line')
    def _compute_reema_match_difference(self):
        for move in self:
            if not move.reema_requires_match:
                move.reema_match_difference = 0.0
                continue
            move.reema_match_difference = sum(
                (l.reema_negotiated_price - l.price_unit) * l.quantity
                for l in move.invoice_line_ids
                if l.product_id and not l.reema_is_variance_line
            )

    @api.depends('partner_id', 'partner_id.property_account_payable_id', 'partner_id.property_account_receivable_id')
    def _compute_reema_partner_missing_gl(self):
        for move in self:
            move.reema_partner_missing_gl = bool(
                move.move_type in ('in_invoice', 'in_refund')
                and move.partner_id
                and not move.partner_id.property_account_payable_id
                and not move.partner_id.property_account_receivable_id
            )

    # ── Onchange ─────────────────────────────────────────────────────────

    @api.onchange('reema_po_id')
    def _onchange_reema_po_id(self):
        if self.reema_po_id and not self.partner_id:
            self.partner_id = self.reema_po_id.partner_id
        self._reema_sync_match_state()

    @api.onchange('reema_grn_ids')
    def _onchange_reema_grn_ids(self):
        # Rebuilds the interim-clearing lines from scratch — appropriate here
        # since changing which GRNs are linked means different materials
        # entirely, so any price corrections typed in for the old selection
        # no longer apply anyway.
        if not self.reema_grn_ids:
            return
        grni_account = self.env['account.account'].search([('code', '=', '2-1-5-01')], limit=1)
        lines = []
        for grn in self.reema_grn_ids:
            for line in grn.line_ids:
                if not line.product_id or line.accepted_qty <= 0:
                    continue
                lines.append((0, 0, {
                    'product_id': line.product_id.id,
                    'name': line.display_product,
                    'quantity': line.accepted_qty,
                    'price_unit': line.price_unit,
                    'account_id': grni_account.id if grni_account else False,
                    # Defaults to the GRN rate (no variance) until the
                    # accountant corrects it to the vendor's real price.
                    'reema_negotiated_price': line.price_unit,
                }))
        if lines:
            self.invoice_line_ids = [(5, 0, 0)] + lines

    @api.onchange('invoice_line_ids.reema_negotiated_price')
    def _onchange_reema_negotiated_price(self):
        self._reema_apply_price_variance()

    def _reema_apply_price_variance(self):
        # Turns each product line's (Negotiated Price - GRN Rate) into its
        # own correction line, on that specific product's own inventory
        # account — never touches the GRNI-clearing lines themselves (those
        # stay locked at the GRN rate so the interim account still clears
        # exactly). Only the auto-generated correction lines are replaced
        # each time; the accountant's typed-in prices on the real product
        # lines are never touched by this rebuild.
        if not self.reema_requires_match:
            return
        keep_lines = self.invoice_line_ids.filtered(lambda l: not l.reema_is_variance_line)
        old_variance_lines = self.invoice_line_ids - keep_lines
        fallback_account = self.env['account.account'].search([('code', '=', '5-9-1-01')], limit=1)
        new_variance_commands = []
        for line in keep_lines:
            if not line.product_id:
                continue
            diff = (line.reema_negotiated_price or line.price_unit) - line.price_unit
            if not diff:
                continue
            code = REEMA_CATEG_ASSET_CODE.get(line.product_id.categ_id.name)
            account = (code and self.env['account.account'].search([('code', '=', code)], limit=1)) \
                or fallback_account
            if not account:
                continue
            new_variance_commands.append((0, 0, {
                'name': _('Price Correction — %(product)s (GRN %(grn).2f → Negotiated %(neg).2f)') % {
                    'product': line.product_id.display_name,
                    'grn': line.price_unit,
                    'neg': line.reema_negotiated_price,
                },
                'quantity': line.quantity,
                'price_unit': diff,
                'account_id': account.id,
                'reema_is_variance_line': True,
            }))
        self.invoice_line_ids = [(2, l.id) for l in old_variance_lines] + new_variance_commands

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        # EXTENDS account (account_move.py). Core's version raises a blocking
        # RedirectWarning ("Cannot find a chart of accounts for this
        # company") the moment a partner with no Payable AND no Receivable
        # account is picked. Two problems with that: the wording sends the
        # accountant hunting through Accounting Configuration for a
        # company-wide problem that doesn't exist, and its button always
        # navigates the CURRENT tab away to fix it — discarding whatever
        # else was already typed on this bill. Skip core's check entirely
        # for this case (accepting the trade-off that its other onchange
        # logic, e.g. invoice_warn, is skipped too in this edge case) and
        # instead surface a plain on-page banner (see reema_partner_missing_gl
        # + view) with a button that opens the vendor's record in a new tab.
        if self.move_type in ('in_invoice', 'in_refund') and self.partner_id \
                and not self.partner_id.property_account_payable_id \
                and not self.partner_id.property_account_receivable_id:
            return
        return super()._onchange_partner_id()

    # ── Constraints ──────────────────────────────────────────────────────

    @api.constrains('reema_po_id', 'partner_id')
    def _check_reema_po_partner(self):
        for move in self:
            if move.reema_po_id and move.partner_id and move.reema_po_id.partner_id != move.partner_id:
                raise ValidationError(_(
                    'Purchase Order %(po)s belongs to %(po_partner)s, not %(partner)s.'
                ) % {
                    'po': move.reema_po_id.name,
                    'po_partner': move.reema_po_id.partner_id.name,
                    'partner': move.partner_id.name,
                })

    @api.constrains('invoice_date', 'move_type', 'batch_entry_ids')
    def _check_reema_bill_date_required(self):
        # Scoped to Vendor Bills only (in_invoice/in_refund with no
        # batch_entry_ids — that field marks a Contractor Bill instead, see
        # reema_accounting/models/reema_contractor_bill_approval.py). Core
        # Odoo only enforces this at Post time, defaulting to today's date
        # if left blank; here it's required even to save as a draft.
        for move in self:
            if move.move_type in ('in_invoice', 'in_refund') \
                    and not move.batch_entry_ids and not move.invoice_date:
                raise ValidationError(_('Bill Date is required — enter it before saving.'))

    # ── CRUD ─────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        moves.filtered(lambda m: m.move_type == 'in_invoice')._reema_sync_match_state()
        return moves

    def write(self, vals):
        res = super().write(vals)
        if 'reema_po_id' in vals:
            self.filtered(lambda m: m.move_type == 'in_invoice')._reema_sync_match_state()
        return res

    def _reema_sync_match_state(self):
        for move in self:
            requires = bool(move.reema_po_id and move.reema_po_id.grn_count)
            if requires and move.reema_match_state == 'na':
                move.reema_match_state = 'pending'
            elif not requires and move.reema_match_state == 'pending':
                move.reema_match_state = 'na'

    # ── Actions ──────────────────────────────────────────────────────────

    def action_reema_submit_match(self):
        for move in self:
            if move.reema_match_state != 'pending':
                raise UserError(_('Only a bill Pending Match can be submitted.'))
            if not move.invoice_date:
                raise UserError(_('Bill Date is required before submitting for match approval.'))
            if not move.reema_grn_ids:
                raise UserError(_('Link at least one Goods Receipt Note before submitting.'))
            zero_priced = move.invoice_line_ids.filtered(
                lambda l: l.product_id and not l.reema_is_variance_line and l.price_unit == 0
            )
            if zero_priced:
                raise UserError(_(
                    'These materials are priced at zero on the linked GRN — no real material '
                    'should be free. Fix the rate on the Purchase Order/GRN before submitting:\n%s'
                ) % '\n'.join('• %s' % l.product_id.display_name for l in zero_priced))
            if move.reema_match_difference and not move.invoice_line_ids.filtered('reema_is_variance_line'):
                raise UserError(_(
                    'This bill has a price variance of %.2f vs the GRN-booked amount, '
                    'but no correction account could be found for it — ask an admin to '
                    'check the chart of accounts.'
                ) % move.reema_match_difference)
            move.write({
                'reema_match_state': 'submitted',
                'reema_match_submitted_by': self.env.uid,
            })
            price_lines = move.invoice_line_ids.filtered(
                lambda l: l.product_id and not l.reema_is_variance_line
                and l.reema_negotiated_price != l.price_unit
            )
            price_detail = ''.join(
                _('<li>%(product)s: GRN %(grn).2f → Negotiated %(neg).2f</li>') % {
                    'product': l.product_id.display_name,
                    'grn': l.price_unit,
                    'neg': l.reema_negotiated_price,
                } for l in price_lines
            )
            move._message_log(body=_(
                'Submitted for match approval by %(user)s — GRN booked %(grn).2f, '
                'price variance %(variance).2f.%(detail)s'
            ) % {
                'user': self.env.user.name,
                'grn': move.reema_grn_amount,
                'variance': move.reema_match_difference,
                'detail': ('<ul>%s</ul>' % price_detail) if price_detail else '',
            })
            owners = self.env.ref('reema_purchase.group_reema_owner').users
            for user in owners:
                move.with_context(mail_activity_quick_update=True).activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_('Approve Vendor Bill Match'),
                    note=_('Vendor Bill <b>%(bill)s</b> submitted by <b>%(user)s</b> is '
                           'waiting for your match approval — price variance %(variance).2f.') % {
                        'bill': move.name or move.ref or _('New'),
                        'user': self.env.user.name,
                        'variance': move.reema_match_difference,
                    },
                    user_id=user.id,
                )

    def action_reema_approve_match(self):
        for move in self:
            if move.reema_match_state != 'submitted':
                raise UserError(_('Only a bill Waiting Approval can be approved.'))
            move.sudo().activity_ids.unlink()
            move.write({
                'reema_match_state': 'matched',
                'reema_match_approved_by': self.env.uid,
            })
            move._message_log(body=_(
                'Match approved by %s — bill can now be posted.'
            ) % self.env.user.name)

    def action_reema_reject_match(self):
        for move in self:
            if move.reema_match_state != 'submitted':
                raise UserError(_('Only a bill Waiting Approval can be sent back.'))
            move.sudo().activity_ids.unlink()
            move.write({'reema_match_state': 'pending'})
            move._message_log(body=_('Match returned to Pending by %s.') % self.env.user.name)

    def action_reema_print_vendor_bill(self):
        # Open the Vendor Bill HTML preview in a new browser tab, same as
        # PO/GRN in this module. type="object" forces a save first (core
        # Odoo behaviour) — printing a still-unsaved bill needs a real
        # record/number the same way core's own Print does.
        if not self:
            return False
        return {
            'type': 'ir.actions.act_url',
            'url': '/report/html/reema_purchase.report_vendor_bill_template/%s'
                   % ','.join(str(i) for i in self.ids),
            'target': 'new',
        }

    def action_post(self):
        missing_date = self.filtered(
            lambda m: m.move_type in ('in_invoice', 'in_refund')
            and not m.batch_entry_ids and not m.invoice_date
        )
        if missing_date:
            raise UserError(_(
                'These bills have no Bill Date set:\n%s'
            ) % '\n'.join('• %s' % (m.name or m.ref or _('New')) for m in missing_date))
        blocked = self.filtered(lambda m: m.reema_match_state in ('pending', 'submitted'))
        if blocked:
            raise UserError(_(
                'These bills are linked to a Purchase Order with Goods Receipt Notes and must '
                'be matched and approved before posting:\n%s'
            ) % '\n'.join('• %s' % (m.name or m.ref or _('New')) for m in blocked))
        missing_gl = self.filtered('reema_partner_missing_gl')
        if missing_gl:
            raise UserError(_(
                'These vendors have no Payable account set up yet — use the "Open Vendor '
                'Record" button on the bill to fix it, then try posting again:\n%s'
            ) % '\n'.join('• %s' % m.partner_id.name for m in missing_gl))
        return super().action_post()


class AccountMoveLineVendorBillMatching(models.Model):
    _inherit = 'account.move.line'

    reema_negotiated_price = fields.Monetary(
        string='Negotiated Price',
        help='The accountant\'s corrected price per unit, taken from the '
             'vendor\'s real invoice — defaults to the GRN-booked rate. Any '
             'difference is posted as a separate price-correction line '
             'against the material\'s own inventory account, not this line.',
    )
    reema_is_variance_line = fields.Boolean(
        string='Auto Price-Correction Line', default=False, copy=False,
    )
