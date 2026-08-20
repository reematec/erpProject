from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

REEMA_CHEQUE_TYPE_SELECTION = [('open', 'Open'), ('cross', 'Cross')]


class AccountPaymentRegisterExt(models.TransientModel):
    _inherit = 'account.payment.register'

    # Mirrors reema.contractor.advance.journal_type — lets the contractor
    # payment wizard view (account_menu_views.xml) show Paid From Bank /
    # Cheque No. only when journal_id is actually a bank journal, same as
    # the Contractor Advance voucher.
    reema_journal_type = fields.Selection(related='journal_id.type', string='Journal Type')
    reema_bank_id = fields.Many2one(
        'reema.bank.account', string='Paid From Bank',
        help='Company bank account this payment is being paid from.',
    )
    reema_cheque_no = fields.Char(string='Cheque / Transaction No.')
    reema_cheque_type = fields.Selection(
        REEMA_CHEQUE_TYPE_SELECTION, string='Cheque Type', default='open',
    )
    reema_post_dated = fields.Boolean(string='Post-dated')
    reema_post_dated_date = fields.Date(string='Post-dated To')
    reema_description = fields.Char(string='Description')

    def _create_payment_vals_from_wizard(self, batch_result):
        payment_vals = super()._create_payment_vals_from_wizard(batch_result)
        payment_vals.update(self._reema_extra_payment_vals())
        return payment_vals

    def _create_payment_vals_from_batch(self, batch_result):
        payment_vals = super()._create_payment_vals_from_batch(batch_result)
        payment_vals.update(self._reema_extra_payment_vals())
        return payment_vals

    def _reema_extra_payment_vals(self):
        return {
            'reema_bank_id': self.reema_bank_id.id,
            'reema_cheque_no': self.reema_cheque_no,
            'reema_cheque_type': self.reema_cheque_type,
            'reema_post_dated': self.reema_post_dated,
            'reema_post_dated_date': self.reema_post_dated_date,
            'reema_description': self.reema_description,
        }


class AccountPaymentExt(models.Model):
    _inherit = 'account.payment'

    # Lets the Vendor Payments form (account_menu_views.xml) show Paid From
    # Bank / Cheque No. / Cheque Type / Post-dated only when journal_id is
    # actually a bank journal — same convention as the register wizard above.
    reema_journal_type = fields.Selection(related='journal_id.type', string='Journal Type')
    reema_bank_id = fields.Many2one(
        'reema.bank.account', string='Paid From Bank',
    )
    reema_cheque_no = fields.Char(string='Cheque / Transaction No.')
    reema_cheque_type = fields.Selection(
        REEMA_CHEQUE_TYPE_SELECTION, string='Cheque Type', default='open',
    )
    reema_post_dated = fields.Boolean(string='Post-dated')
    reema_post_dated_date = fields.Date(string='Post-dated To')
    reema_description = fields.Char(string='Description')

    @api.constrains('reema_post_dated', 'reema_post_dated_date')
    def _check_reema_post_dated_date(self):
        for rec in self:
            if rec.reema_post_dated and not rec.reema_post_dated_date:
                raise ValidationError(_('Please enter the Post-dated To date for a post-dated cheque.'))

    def _get_aml_default_display_name_list(self):
        # Core's default is "{Payment Method}: {memo}" — for a contractor
        # bill payment memo is the bill number (see the register wizard's
        # readonly "communication" field), so it renders as e.g. "Manual
        # Payment: BILL/26/0001". On the General Ledger that repeats the
        # bill number the Entry column already shows, without saying who
        # got paid. Scoped to contractors only (is_contractor) — regular
        # Vendor Payments keep the core label untouched.
        self.ensure_one()
        if self.partner_id.is_contractor:
            return [('label', '%s — Payment' % self.partner_id.name)]
        return super()._get_aml_default_display_name_list()

    def action_print_payment_voucher(self):
        if not self:
            return False
        return {
            'type': 'ir.actions.act_url',
            'url': '/report/html/reema_accounting.report_payment_voucher/%s' % ','.join(str(i) for i in self.ids),
            'target': 'new',
        }
