from odoo import api, fields, models
from odoo.exceptions import UserError

VENDOR_PREFIX = '2-1-1'
CONTRACTOR_PAYABLE_CODE = '2-1-2-01'
CONTRACTOR_ADVANCE_PREFIX = '1-1-3'
EMPLOYEE_ADVANCE_PREFIX = '1-1-4'
CUSTOMER_PREFIX = '1-1-2'


class ResPartnerExt(models.Model):
    _inherit = 'res.partner'

    reema_advance_account_id = fields.Many2one(
        'account.account',
        string='Advance Account',
        help='Individual current-asset account (1-1-3-xx) tracking advances given to this contractor.',
    )

    def _get_contractor_payable_account(self):
        """Return the shared Contractors Payable account (2-1-2-01) or False if not found."""
        return self.env['account.account'].search(
            [('code', '=', CONTRACTOR_PAYABLE_CODE)], limit=1
        )

    def _assign_contractor_payable(self):
        """Link any contractor without a payable account to the shared 2-1-2-01 account.

        Silent no-op when the account doesn't exist yet — never blocks partner save.
        """
        candidates = self.filtered(
            lambda p: p.is_contractor and not p.property_account_payable_id
        )
        if not candidates:
            return
        shared_payable = self._get_contractor_payable_account()
        if not shared_payable:
            return
        candidates.property_account_payable_id = shared_payable

    def _assign_customer_receivable(self):
        """Auto-create individual receivable account (1-1-2-xx) for customers that don't have one yet."""
        candidates = self.filtered(
            lambda p: p.customer_rank > 0
            and not (
                p.property_account_receivable_id
                and p.property_account_receivable_id.code.startswith(CUSTOMER_PREFIX + '-')
            )
        )
        for partner in candidates:
            code = partner._next_account_code(CUSTOMER_PREFIX)
            account = partner.env['account.account'].sudo().create({
                'name': partner.name + ' — Receivable',
                'code': code,
                'account_type': 'asset_receivable',
                'reconcile': True,
                'partner_id': partner.id,
            })
            partner.property_account_receivable_id = account

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        partners._assign_contractor_payable()
        partners._assign_customer_receivable()
        return partners

    def write(self, vals):
        result = super().write(vals)
        if vals.get('is_contractor'):
            self._assign_contractor_payable()
        if vals.get('customer_rank'):
            self._assign_customer_receivable()
        return result

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
        Contractors: assign to shared Contractors Payable account only.
        Advance account is created separately when a contractor actually needs one.
        """
        shared_payable = self._get_contractor_payable_account()
        if not shared_payable:
            raise UserError(
                f'Shared payable account {CONTRACTOR_PAYABLE_CODE} not found in the Chart of Accounts. '
                f'Please create it first.'
            )
        if self.property_account_payable_id == shared_payable:
            raise UserError(
                f'This contractor is already assigned to {shared_payable.code} · {shared_payable.name}.'
            )
        self.property_account_payable_id = shared_payable

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Contractor Payable Account Assigned',
                'message': f'Payable: {shared_payable.code} · {shared_payable.name}',
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
