from odoo import fields, models


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
            'reema_description': self.reema_description,
        }


class AccountPaymentExt(models.Model):
    _inherit = 'account.payment'

    reema_bank_id = fields.Many2one(
        'reema.bank.account', string='Paid From Bank',
    )
    reema_cheque_no = fields.Char(string='Cheque / Transaction No.')
    reema_description = fields.Char(string='Description')
