from odoo import fields, models
from odoo.exceptions import UserError

VENDOR_PREFIX = '2-1-1'
CONTRACTOR_PAYABLE_CODE = '2-1-2-01'
CONTRACTOR_ADVANCE_PREFIX = '1-1-3'
EMPLOYEE_ADVANCE_PREFIX = '1-1-4'
CUSTOMER_PREFIX = '1-1-2'


class ResPartnerExt(models.Model):
    _inherit = 'res.partner'

    is_contractor = fields.Boolean(
        string='Is Contractor',
        default=False,
        help="Check if this partner is a labor contractor. "
             "Contractors share a single Payable account (2-1-2-01) and each get "
             "their own Advance account (1-1-3-xx) for advance tracking.",
    )

    reema_advance_account_id = fields.Many2one(
        'account.account',
        string='Advance Account',
        help='Individual current-asset account (1-1-3-xx) tracking advances given to this contractor.',
    )

    def _next_account_code(self, prefix):
        existing = self.env['account.account'].search(
            [('code', '=like', prefix + '-%')],
            order='code desc',
            limit=1,
        )
        if not existing:
            return f'{prefix}-01'
        seq = int(existing.code.rsplit('-', 1)[1])
        return f'{prefix}-{seq + 1:02d}'

    def _account_is_individual_vendor(self, account):
        return account and account.code.startswith(VENDOR_PREFIX + '-')

    def action_create_supplier_gl_account(self):
        self.ensure_one()

        if self.is_contractor:
            return self._setup_contractor_gl()
        else:
            return self._setup_vendor_gl()

    def _setup_contractor_gl(self):
        """
        Contractors: assign to shared 2121 Contractors Payable + create individual advance account.
        """
        if self.reema_advance_account_id:
            raise UserError(
                f'This contractor is already configured:\n'
                f'  Payable: {self.property_account_payable_id.code} · {self.property_account_payable_id.name}\n'
                f'  Advance: {self.reema_advance_account_id.code} · {self.reema_advance_account_id.name}'
            )

        shared_payable = self.env['account.account'].search(
            [('code', '=', CONTRACTOR_PAYABLE_CODE)], limit=1
        )
        if not shared_payable:
            raise UserError(
                f'Shared payable account {CONTRACTOR_PAYABLE_CODE} not found in the Chart of Accounts. '
                f'Please create it first.'
            )
        self.property_account_payable_id = shared_payable

        advance_code = self._next_account_code(CONTRACTOR_ADVANCE_PREFIX)
        advance_account = self.env['account.account'].create({
            'name': self.name + ' — Advance',
            'code': advance_code,
            'account_type': 'asset_current',
            'partner_id': self.id,
        })
        self.reema_advance_account_id = advance_account

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Contractor GL Accounts Configured',
                'message': (
                    f'Payable: {shared_payable.code} · {shared_payable.name}  |  '
                    f'Advance: {advance_code} · {self.name} — Advance'
                ),
                'sticky': False,
                'type': 'success',
            },
        }

    def _setup_vendor_gl(self):
        """
        Vendors: individual liability_payable account under 211x (unchanged behaviour).
        """
        existing = self.property_account_payable_id
        if self._account_is_individual_vendor(existing):
            raise UserError(
                f'GL account is already correctly assigned: '
                f'{existing.code} · {existing.name}'
            )

        code = self._next_account_code(VENDOR_PREFIX)
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
            if account.code.startswith(CUSTOMER_PREFIX + '-'):
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
