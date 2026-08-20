from odoo import _, fields, models, tools
from odoo.exceptions import UserError


class ReemaContractorBalance(models.Model):
    """Read-only summary of every contractor's individual advance account
    (1-1-3-xx, account_type='asset_current' with its own partner_id) — see
    res_partner_ext.py's _get_or_create_advance_account. Mirrors
    reema.vendor.balance exactly; the only structural difference is
    account_type='asset_current' + res.partner.is_contractor instead of
    'liability_payable'.

    Deliberately does NOT touch the shared Contractors Payable account
    (2-1-2-01): what's owed to each contractor is read off their unpaid
    bills (reema.contractor.bill.approval), not a balance split off that
    shared account.
    """
    _name = 'reema.contractor.balance'
    _description = 'Contractor Balance Summary'
    _auto = False
    _order = 'account_code'

    partner_id = fields.Many2one('res.partner', string='Contractor', readonly=True)
    account_code = fields.Char(
        string='Account', readonly=True,
        help='This contractor\'s advance account (1-1-3-xx) — blank if none has been created yet.',
    )
    balance = fields.Monetary(string='Balance', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW reema_contractor_balance AS (
                SELECT
                    p.id AS id,
                    p.id AS partner_id,
                    acc.code_store ->> aar.res_company_id::text AS account_code,
                    COALESCE(SUM(aml.balance) FILTER (WHERE am.state = 'posted'), 0) AS balance,
                    (SELECT currency_id FROM res_company ORDER BY id LIMIT 1) AS currency_id,
                    (SELECT id FROM res_company ORDER BY id LIMIT 1) AS company_id
                FROM res_partner p
                LEFT JOIN account_account acc
                    ON acc.partner_id = p.id AND acc.account_type = 'asset_current'
                LEFT JOIN account_account_res_company_rel aar ON aar.account_account_id = acc.id
                LEFT JOIN account_move_line aml ON aml.account_id = acc.id
                LEFT JOIN account_move am ON am.id = aml.move_id
                WHERE p.is_contractor = true
                GROUP BY p.id, acc.code_store, aar.res_company_id
            )
        """)

    def action_print_contractor_balance(self):
        # See reema.vendor.balance.action_print_vendor_balance for why the
        # "skip zero" choice has to be an explicit button, not a filter.
        records = self if self else self.search([])
        if self.env.context.get('reema_hide_zero_balance'):
            records = records.filtered(lambda r: r.balance)
        if not records:
            raise UserError(_('There are no contractor balances to print.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/report/html/reema_accounting.report_contractor_balance/%s' % ','.join(str(i) for i in records.ids),
            'target': 'new',
        }
