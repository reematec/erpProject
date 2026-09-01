from odoo import _, fields, models, tools
from odoo.exceptions import UserError


class ReemaVendorBalance(models.Model):
    """Read-only summary of every individual vendor payable account
    (2-1-1-xx, one per vendor — see res_partner_ext.py's _setup_vendor_gl),
    with its current posted balance. One row per vendor account, unlike
    reema.ledger.line which is one row per transaction for a single vendor.
    """
    _name = 'reema.vendor.balance'
    _description = 'Vendor Balance Summary'
    _auto = False
    _order = 'account_code'

    partner_id = fields.Many2one('res.partner', string='Vendor', readonly=True)
    account_id = fields.Many2one('account.account', string='Account', readonly=True)
    account_code = fields.Char(string='Account Code', readonly=True)
    debit = fields.Monetary(string='Debit', readonly=True)
    credit = fields.Monetary(string='Credit', readonly=True)
    balance = fields.Monetary(string='Balance', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        # account_account.code is company-dependent jsonb in 18.0 (code_store),
        # not a plain column — filtering is done structurally instead, same
        # approach as reema_ledger_line.py: an individual vendor payable
        # account is exactly "liability_payable with its own partner_id"
        # (the one shared Contractors Payable account has no partner_id of
        # its own), which is precisely the 2-1-1-xx set by construction —
        # see res_partner_ext.py's _setup_vendor_gl.
        # account.account has no company_id column in 18.0 (it's the m2m
        # account_account_res_company_rel) — join through that, same as
        # code_store's per-company jsonb key, to get one row per account.
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW reema_vendor_balance AS (
                SELECT
                    acc.id AS id,
                    acc.partner_id AS partner_id,
                    acc.id AS account_id,
                    acc.code_store ->> aar.res_company_id::text AS account_code,
                    COALESCE(SUM(aml.debit) FILTER (WHERE am.state = 'posted'), 0) AS debit,
                    COALESCE(SUM(aml.credit) FILTER (WHERE am.state = 'posted'), 0) AS credit,
                    COALESCE(SUM(aml.balance) FILTER (WHERE am.state = 'posted'), 0) AS balance,
                    rc.currency_id AS currency_id,
                    aar.res_company_id AS company_id
                FROM account_account acc
                JOIN account_account_res_company_rel aar ON aar.account_account_id = acc.id
                JOIN res_company rc ON rc.id = aar.res_company_id
                LEFT JOIN account_move_line aml ON aml.account_id = acc.id
                LEFT JOIN account_move am ON am.id = aml.move_id
                WHERE acc.account_type = 'liability_payable'
                  AND acc.partner_id IS NOT NULL
                GROUP BY acc.id, acc.partner_id, acc.code_store, rc.currency_id, aar.res_company_id
            )
        """)

    def action_print_vendor_balance(self):
        # Bound to two list view header buttons sharing this method: "Print"
        # (all rows — selected rows if any are ticked, else everything) and
        # "Print (Skip Zero)", which passes reema_hide_zero_balance=True in
        # its button context to drop zero-balance rows from whichever set
        # (selected or full) would otherwise be printed. A screen-side
        # search filter alone isn't enough here — a header button only ever
        # receives the ticked row ids, never the list's active search
        # domain, so with no rows selected the "skip zero" choice has to be
        # made explicit on the button itself, not implied by the filter.
        records = self if self else self.search([])
        if self.env.context.get('reema_hide_zero_balance'):
            records = records.filtered(lambda r: r.balance)
        if not records:
            raise UserError(_('There are no vendor balances to print.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/report/html/reema_accounting.report_vendor_balance/%s' % ','.join(str(i) for i in records.ids),
            'target': 'new',
        }
