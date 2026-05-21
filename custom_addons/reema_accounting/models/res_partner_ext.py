from odoo import fields, models
from odoo.exceptions import UserError

VENDOR_PREFIX = '211'
CONTRACTOR_PREFIX = '212'
CUSTOMER_PREFIX = '112'


class ResPartnerExt(models.Model):
    _inherit = 'res.partner'

    is_contractor = fields.Boolean(
        string='Is Contractor',
        default=False,
        help="Check if this partner is a labor contractor (account goes under 212). "
             "Leave unchecked for material vendors (account goes under 211).",
    )

    def _next_account_code(self, prefix):
        existing = self.env['account.account'].search(
            [('code', '=like', prefix + '%')],
            order='code desc',
            limit=1,
        )
        return str(int(existing.code) + 1) if existing else prefix + '1'

    def _supplier_prefix(self):
        return CONTRACTOR_PREFIX if self.is_contractor else VENDOR_PREFIX

    def _account_is_individual(self, account):
        return account and (
            account.code.startswith(VENDOR_PREFIX) or
            account.code.startswith(CONTRACTOR_PREFIX)
        )

    def action_create_supplier_gl_account(self):
        self.ensure_one()
        correct_prefix = self._supplier_prefix()
        existing = self.property_account_payable_id

        if self._account_is_individual(existing):
            if existing.code.startswith(correct_prefix):
                raise UserError(
                    f'GL account is already correctly assigned: '
                    f'{existing.code} · {existing.name}'
                )
            # Wrong prefix — try to fix it
            wrong_prefix = CONTRACTOR_PREFIX if correct_prefix == VENDOR_PREFIX else VENDOR_PREFIX
            has_entries = bool(self.env['account.move.line'].search(
                [('account_id', '=', existing.id)], limit=1
            ))
            if has_entries:
                raise UserError(
                    f'Cannot reassign: account {existing.code} already has posted journal entries. '
                    f'Please contact your accountant to manually reclass the entries to a {correct_prefix}x account.'
                )
            self.property_account_payable_id = False
            existing.unlink()

        code = self._next_account_code(correct_prefix)
        account = self.env['account.account'].create({
            'name': self.name + ' — Payable',
            'code': code,
            'account_type': 'liability_payable',
            'reconcile': True,
            'partner_id': self.id,
        })
        self.property_account_payable_id = account
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'GL Account Created',
                'message': f'{code} · {self.name} — Payable created and assigned.',
                'sticky': False,
                'type': 'success',
            },
        }

    def action_create_customer_gl_account(self):
        self.ensure_one()
        if self.property_account_receivable_id:
            account = self.property_account_receivable_id
            if account.code.startswith(CUSTOMER_PREFIX):
                raise UserError(
                    f'This partner already has an individual GL account assigned: '
                    f'{account.code} · {account.name}'
                )
        code = self._next_account_code(CUSTOMER_PREFIX)
        account = self.env['account.account'].create({
            'name': self.name + ' — Receivable',
            'code': code,
            'account_type': 'asset_receivable',
            'reconcile': True,
            'partner_id': self.id,
        })
        self.property_account_receivable_id = account
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'GL Account Created',
                'message': f'{code} · {self.name} — Receivable created and assigned.',
                'sticky': False,
                'type': 'success',
            },
        }
