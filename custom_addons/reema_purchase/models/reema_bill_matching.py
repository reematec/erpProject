from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ReemaBillMatching(models.Model):
    _name = 'reema.bill.matching'
    _description = 'Purchase Bill Matching (3-Way Match)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name desc'

    name = fields.Char(
        string='Reference', readonly=True, copy=False,
        default=lambda self: _('New'), tracking=True,
    )
    date = fields.Date(
        string='Date', default=fields.Date.context_today, required=True,
    )
    po_id = fields.Many2one(
        'reema.purchase.order', string='Purchase Order', required=True,
        tracking=True,
    )
    partner_id = fields.Many2one(
        'res.partner', related='po_id.partner_id', string='Supplier', store=True,
    )
    gate_pass_ids = fields.Many2many(
        'reema.gate.pass', string='Inward Gate Passes',
        domain="[('po_id', '=', po_id)]",
    )
    grn_ids = fields.Many2many(
        'reema.grn', string='Goods Receipt Notes',
        domain="[('po_id', '=', po_id), ('state', 'in', ('approved', 'accounted'))]",
    )
    invoice_id = fields.Many2one(
        'account.move', string='Supplier Bill',
        domain=[('move_type', '=', 'in_invoice')],
        tracking=True,
    )

    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id,
    )

    # ── Comparison amounts ────────────────────────────────────────────────
    po_amount = fields.Monetary(
        string='PO Total', related='po_id.amount_total',
        currency_field='currency_id', store=True,
    )
    grn_amount = fields.Monetary(
        string='GRN Total', compute='_compute_grn_amount',
        currency_field='currency_id', store=True,
    )
    invoice_amount = fields.Monetary(
        string='Bill Total', related='invoice_id.amount_total',
        currency_field='currency_id', store=True,
    )
    difference = fields.Monetary(
        string='Difference (GRN − Bill)',
        compute='_compute_difference',
        currency_field='currency_id',
    )

    notes = fields.Text(string='Remarks / Discrepancy Notes')
    state = fields.Selection([
        ('draft',     'Draft'),
        ('submitted', 'Waiting Owner Approval'),
        ('approved',  'Owner Approved'),
        ('posted',    'Posted'),
    ], default='draft', required=True, tracking=True, copy=False)

    move_id = fields.Many2one(
        'account.move', string='Payable Journal Entry', readonly=True,
    )
    submitted_by = fields.Many2one('res.users', string='Submitted By', readonly=True)
    approved_by = fields.Many2one('res.users', string='Approved By', readonly=True)

    # ── Compute ──────────────────────────────────────────────────────────

    @api.depends('grn_ids.line_ids.accepted_qty', 'grn_ids.line_ids.price_unit')
    def _compute_grn_amount(self):
        for rec in self:
            rec.grn_amount = sum(
                line.accepted_qty * line.price_unit
                for grn in rec.grn_ids
                for line in grn.line_ids
            )

    @api.depends('grn_amount', 'invoice_amount')
    def _compute_difference(self):
        for rec in self:
            rec.difference = rec.grn_amount - rec.invoice_amount

    # ── CRUD ─────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('reema.bill.matching') or _('New')
        return super().create(vals_list)

    # ── Actions ──────────────────────────────────────────────────────────

    def action_submit_for_approval(self):
        for rec in self:
            if not rec.grn_ids:
                raise UserError(_('Please link at least one approved GRN before submitting.'))
            if not rec.invoice_id:
                raise UserError(_('Please link the Supplier Bill before submitting.'))
            rec.write({'state': 'submitted', 'submitted_by': self.env.uid})
            rec.message_post(
                body=_('Submitted for Owner approval by %s. '
                        'PO: %s | GRN: %s | Bill: %s') % (
                    self.env.user.name,
                    rec.po_amount,
                    rec.grn_amount,
                    rec.invoice_amount,
                )
            )

    def action_approve(self):
        for rec in self:
            if rec.state != 'submitted':
                raise UserError(_('Only submitted matchings can be approved.'))
            move = rec._post_payable_entry()
            rec.grn_ids.write({'state': 'accounted'})
            rec.write({
                'state': 'posted',
                'approved_by': self.env.uid,
                'move_id': move.id,
            })
            rec.message_post(
                body=_('Approved and posted by %s. Payable entry: %s') % (
                    self.env.user.name, move.name
                )
            )

    def action_reject(self):
        for rec in self:
            rec.write({'state': 'draft'})
            rec.message_post(body=_('Rejected and returned to draft by %s.') % self.env.user.name)

    # ── Accounting ────────────────────────────────────────────────────────

    def _post_payable_entry(self):
        self.ensure_one()
        journal = self.env['account.journal'].search(
            [('type', '=', 'purchase'), ('company_id', '=', self.env.company.id)], limit=1
        )
        if not journal:
            raise UserError(_('No purchase journal found. Please configure one.'))

        grni_account = self.env.ref('reema_purchase.account_grni_clearing', raise_if_not_found=False)
        if not grni_account:
            raise UserError(_('GRNI Clearing account not found.'))

        payable_account = self.partner_id.property_account_payable_id
        if not payable_account:
            raise UserError(
                _('No payable account configured for supplier "%s".') % self.partner_id.name
            )

        grn_amount = self.grn_amount
        bill_amount = self.invoice_amount

        move_lines = [
            # Dr: GRNI Clearing (clear the interim)
            (0, 0, {
                'account_id': grni_account.id,
                'debit': grn_amount,
                'credit': 0.0,
                'name': _('GRNI Clearing — %s') % self.name,
                'partner_id': self.partner_id.id,
            }),
            # Cr: Accounts Payable (supplier)
            (0, 0, {
                'account_id': payable_account.id,
                'debit': 0.0,
                'credit': bill_amount,
                'name': _('Payable — %s — %s') % (self.partner_id.name, self.po_id.name),
                'partner_id': self.partner_id.id,
            }),
        ]

        # If GRN and Bill amounts differ, post variance
        variance = grn_amount - bill_amount
        if abs(variance) > 0.01:
            variance_account = self.env['account.account'].search(
                [('code', 'like', '6%'), ('account_type', '=', 'expense')], limit=1
            )
            if variance_account:
                if variance > 0:
                    move_lines.append((0, 0, {
                        'account_id': variance_account.id,
                        'debit': 0.0,
                        'credit': variance,
                        'name': _('Purchase Price Variance — %s') % self.name,
                    }))
                else:
                    move_lines.append((0, 0, {
                        'account_id': variance_account.id,
                        'debit': abs(variance),
                        'credit': 0.0,
                        'name': _('Purchase Price Variance — %s') % self.name,
                    }))

        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': self.date,
            'ref': self.name,
            'journal_id': journal.id,
            'line_ids': move_lines,
        })
        move.action_post()
        return move
