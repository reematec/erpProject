from odoo import _, fields, models, tools
from odoo.exceptions import UserError


class ReemaCustomerBalance(models.Model):
    """Read-only summary of every individual customer receivable account
    (1-1-2-xx, one per customer — see res_partner_ext.py's
    _assign_customer_receivable), with its current posted balance. Mirrors
    reema.vendor.balance exactly; the only structural difference is
    account_type='asset_receivable' instead of 'liability_payable'.
    """
    _name = 'reema.customer.balance'
    _description = 'Customer Balance Summary'
    _auto = False
    _order = 'account_code'

    partner_id = fields.Many2one('res.partner', string='Customer', readonly=True)
    account_id = fields.Many2one('account.account', string='Account', readonly=True)
    account_code = fields.Char(string='Account Code', readonly=True)
    balance = fields.Monetary(string='Balance', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW reema_customer_balance AS (
                SELECT
                    acc.id AS id,
                    acc.partner_id AS partner_id,
                    acc.id AS account_id,
                    acc.code_store ->> aar.res_company_id::text AS account_code,
                    COALESCE(SUM(aml.balance) FILTER (WHERE am.state = 'posted'), 0) AS balance,
                    rc.currency_id AS currency_id,
                    aar.res_company_id AS company_id
                FROM account_account acc
                JOIN account_account_res_company_rel aar ON aar.account_account_id = acc.id
                JOIN res_company rc ON rc.id = aar.res_company_id
                LEFT JOIN account_move_line aml ON aml.account_id = acc.id
                LEFT JOIN account_move am ON am.id = aml.move_id
                WHERE acc.account_type = 'asset_receivable'
                  AND acc.partner_id IS NOT NULL
                GROUP BY acc.id, acc.partner_id, acc.code_store, rc.currency_id, aar.res_company_id
            )
        """)

    def action_print_customer_balance(self):
        # See reema.vendor.balance.action_print_vendor_balance for why the
        # "skip zero" choice has to be an explicit button, not a filter.
        records = self if self else self.search([])
        if self.env.context.get('reema_hide_zero_balance'):
            records = records.filtered(lambda r: r.balance)
        if not records:
            raise UserError(_('There are no customer balances to print.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/report/html/reema_accounting.report_customer_balance/%s' % ','.join(str(i) for i in records.ids),
            'target': 'new',
        }
