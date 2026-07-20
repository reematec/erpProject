from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class ReemaContractorAdvance(models.Model):
    _name = 'reema.contractor.advance'
    _description = 'Contractor Advance Voucher'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Voucher No.', readonly=True, copy=False,
        default=lambda self: _('New'), tracking=True,
    )
    partner_id = fields.Many2one(
        'res.partner', string='Contractor', required=True, tracking=True,
        domain=[('is_contractor', '=', True)],
    )
    date = fields.Date(
        string='Date', required=True, default=fields.Date.context_today,
    )
    journal_id = fields.Many2one(
        'account.journal', string='Payment Method', required=True,
        domain=[('type', 'in', ('cash', 'bank'))],
    )
    amount = fields.Float(
        string='Amount (PKR)', digits=(12, 2), required=True,
    )
    purpose = fields.Char(
        string='Description', required=True,
        help='Reason for the advance — printed on the voucher and used as the journal entry label.',
    )
    journal_type = fields.Selection(related='journal_id.type', string='Journal Type')
    bank_id = fields.Many2one(
        'reema.bank.account', string='Paid From Bank',
        help='Company bank account this advance is being paid from.',
    )
    cheque_no = fields.Char(string='Cheque / Transaction No.')
    advance_type = fields.Selection(
        [('against_bill', 'Against Bill'), ('long_term', 'Long Term Advance')],
        string='Advance Type', default='against_bill', required=True, tracking=True,
        help='Against Bill: expected to be recovered in one go on the next Contractor Bill.\n'
             'Long Term Advance: recovered gradually over several bills at a fixed amount per bill.',
    )
    deduction_per_bill = fields.Float(
        string='Deduction per Bill (PKR)', digits=(12, 2),
        help='Suggested recovery amount per Contractor Bill for this Long Term Advance. '
             'Shown as a hint on future bills for this contractor — not applied automatically.',
    )
    state = fields.Selection(
        [('draft', 'Draft'), ('posted', 'Posted'), ('cancelled', 'Cancelled')],
        default='draft', required=True, copy=False, tracking=True,
    )
    move_id = fields.Many2one(
        'account.move', string='Journal Entry', readonly=True, copy=False,
    )
    reversal_move_id = fields.Many2one(
        'account.move', string='Reversal Entry', readonly=True, copy=False,
    )
    advance_account_id = fields.Many2one(
        'account.account', string='Advance Account',
        compute='_compute_advance_account_id',
    )
    outstanding_advance = fields.Float(
        string='Outstanding Advance (PKR)', digits=(12, 2),
        compute='_compute_outstanding_advance',
        help='Contractor\'s current unrecovered advance balance, before this voucher.',
    )
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company, required=True,
    )

    @api.depends('partner_id')
    def _compute_advance_account_id(self):
        for rec in self:
            rec.advance_account_id = rec.partner_id.reema_advance_account_id

    @api.depends('partner_id')
    def _compute_outstanding_advance(self):
        for rec in self:
            rec.outstanding_advance = rec.partner_id._get_outstanding_advance() if rec.partner_id else 0.0

    @api.constrains('advance_type', 'deduction_per_bill')
    def _check_deduction_per_bill(self):
        for rec in self:
            if rec.advance_type == 'long_term' and rec.deduction_per_bill <= 0:
                raise ValidationError(_('Please enter a Deduction per Bill amount for a Long Term Advance.'))

    def unlink(self):
        if any(rec.state == 'posted' for rec in self):
            raise UserError(_('A posted advance voucher cannot be deleted — reverse it instead.'))
        return super().unlink()

    def action_confirm(self):
        for rec in self:
            if rec.amount <= 0:
                raise UserError(_('Amount must be greater than zero.'))
            # Numbered here, not in create() — the web client autosaves a
            # dirty-but-valid new record when the user navigates away
            # in-app (e.g. an "update available, refresh" prompt), with no
            # confirmation and without action_confirm ever running. If the
            # sequence were consumed at create(), that accidental draft would
            # permanently burn a real voucher number. Deferring it to the
            # actual "Give Advance" click means a stray autosaved draft just
            # sits there as an easily-deleted "New" row, never numbered.
            if rec.name == _('New'):
                rec.name = self.env['ir.sequence'].next_by_code('reema.contractor.advance') or _('New')
            advance_account = rec.partner_id._get_or_create_advance_account()
            liquidity_account = rec.journal_id.default_account_id
            if not liquidity_account:
                raise UserError(_('Selected payment method has no default account configured.'))
            move = self.env['account.move'].create({
                'move_type': 'entry',
                'journal_id': rec.journal_id.id,
                'date': rec.date,
                'ref': f'{rec.name} — {rec.purpose}',
                'line_ids': [
                    (0, 0, {
                        'account_id': advance_account.id,
                        'partner_id': rec.partner_id.id,
                        'name': rec.purpose,
                        'debit': rec.amount,
                        'credit': 0.0,
                    }),
                    (0, 0, {
                        'account_id': liquidity_account.id,
                        'partner_id': rec.partner_id.id,
                        'name': rec.purpose,
                        'debit': 0.0,
                        'credit': rec.amount,
                    }),
                ],
            })
            move.action_post()
            rec.write({'move_id': move.id, 'state': 'posted'})
            rec.message_post(
                body=_('Advance of %s posted to %s via %s.') % (rec.amount, advance_account.display_name, rec.journal_id.name),
                subtype_xmlid='mail.mt_note',
            )

    def action_void(self):
        for rec in self:
            if rec.state == 'posted':
                raise UserError(_('A posted advance voucher cannot be voided directly — reverse it instead.'))
            rec.write({'state': 'cancelled'})

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state == 'posted':
                raise UserError(_('A posted advance voucher cannot be reset to draft — reverse it instead.'))
            rec.write({'state': 'draft'})

    def action_reverse(self):
        for rec in self:
            if rec.state != 'posted':
                raise UserError(_('Only a posted advance voucher can be reversed.'))
            reversal = rec.move_id._reverse_moves(default_values_list=[{
                'ref': _('Reversal of %s') % rec.name,
                'date': fields.Date.context_today(rec),
            }])
            reversal.action_post()
            rec.write({'reversal_move_id': reversal.id, 'state': 'cancelled'})
            rec.message_post(
                body=_('Advance voucher reversed by %s.') % self.env.user.name,
                subtype_xmlid='mail.mt_note',
            )

    def action_print_advance_voucher(self):
        if not self:
            return False
        return {
            'type': 'ir.actions.act_url',
            'url': '/report/html/reema_accounting.report_contractor_advance/%s' % ','.join(str(i) for i in self.ids),
            'target': 'new',
        }
