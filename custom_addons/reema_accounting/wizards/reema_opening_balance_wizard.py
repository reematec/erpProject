from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ReemaOpeningBalanceWizard(models.TransientModel):
    """One-entry-at-a-time front end for account.account's own opening_debit/
    opening_credit fields. Core's own editable Chart of Accounts list
    (account.init_accounts_tree) shows every account with Type/Reconcile/
    Tax/Tags columns and jumps into the full Account form on row click —
    built for setting up a chart of accounts from scratch, not for quickly
    keying in a handful of opening balances against accounts that already
    exist. This picks one account, one Debit or Credit amount, and an
    optional note, and writes straight through company._update_opening_move
    (the same call account.account's inverse eventually makes), which keeps
    the opening move balanced against the unaffected-earnings account
    automatically.
    """
    _name = 'reema.opening.balance.wizard'
    _description = 'Opening Balance Entry'

    account_id = fields.Many2one(
        'account.account', string='Account', required=True,
        domain=[('account_type', '!=', 'equity_unaffected')],
    )
    currency_id = fields.Many2one(related='account_id.company_currency_id', string='Currency')
    debit = fields.Monetary(string='Debit')
    credit = fields.Monetary(string='Credit')
    note = fields.Char(string='Description', help='Optional label for this opening balance line.')

    @api.constrains('debit', 'credit')
    def _check_debit_credit(self):
        for wizard in self:
            if wizard.debit and wizard.credit:
                raise UserError(_('Enter either a Debit or a Credit amount, not both.'))

    def _apply(self):
        self.ensure_one()
        if not self.debit and not self.credit:
            raise UserError(_('Enter a Debit or Credit amount.'))
        company = self.env.company
        company._update_opening_move({self.account_id: (self.debit or None, self.credit or None)})
        if self.note:
            move = company.account_opening_move_id
            line = move.line_ids.filtered(
                lambda l: l.account_id == self.account_id
                and ((self.debit and l.balance > 0) or (self.credit and l.balance < 0))
            )[:1]
            if line:
                line.name = self.note

    def action_save_and_new(self):
        self._apply()
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Opening Balance'),
            'res_model': 'reema.opening.balance.wizard',
            'view_mode': 'form',
            'target': 'new',
        }

    def action_save_and_close(self):
        self._apply()
        return {'type': 'ir.actions.act_window_close'}
