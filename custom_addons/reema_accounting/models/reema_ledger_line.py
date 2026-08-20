from odoo import fields, models, tools


class ReemaLedgerLine(models.Model):
    """Read-only running-balance ledger for Customers / Vendors / Contractors /
    Payroll — a SQL view over account.move.line, scoped to exactly the
    accounts each of those sections owns individually (or, for the shared
    Contractors Payable account, split per contractor via the line's own
    partner_id). One shared model backs all four menu entries; only the
    domain differs per action (see reema_ledger_views.xml / reema_hr's
    Payroll ledger menu).

    Which accounts qualify (verified against live data, not just code
    convention — account.account.code is company-dependent jsonb in 18.0,
    not a plain column, so filtering is done structurally instead):
      - Customer:   account_type='asset_receivable', account has its own partner_id
      - Vendor:     account_type='liability_payable', account has its own partner_id
      - Contractor: account_type='asset_current' + own partner_id (their advance
                    account), OR the one shared liability_payable account with
                    no partner_id of its own (Contractors Payable — every line
                    against it carries the contractor on aml.partner_id instead)
      - Employee:   account.reema_hr_employee_id is set (their own account,
                    never carries partner_id — employees aren't res.partner)
    """
    _name = 'reema.ledger.line'
    _description = 'Ledger Line (Customers / Vendors / Contractors / Payroll)'
    _auto = False
    _order = 'date, id'

    move_id = fields.Many2one('account.move', string='Journal Entry', readonly=True)
    date = fields.Date(readonly=True)
    name = fields.Char(string='Label', readonly=True)
    ref = fields.Char(string='Reference', readonly=True)
    journal_id = fields.Many2one('account.journal', readonly=True)
    account_id = fields.Many2one('account.account', readonly=True)
    # Derived, not the raw aml.partner_id — for individually-owned accounts
    # (customer/vendor/contractor-advance) this is the account's own
    # partner_id (aml.partner_id is often blank even on those lines); for the
    # one shared Contractors Payable account it falls back to aml.partner_id,
    # which IS reliably set there since it's the only way to tell contractors
    # apart on that account. Blank for Payroll (employees aren't partners).
    partner_id = fields.Many2one('res.partner', string='Partner', readonly=True)
    debit = fields.Monetary(readonly=True)
    credit = fields.Monetary(readonly=True)
    balance = fields.Monetary(readonly=True)
    running_balance = fields.Monetary(
        string='Balance', readonly=True,
        help='Cumulative balance within this account (and, for the shared '
             'Contractors Payable account, within this contractor), ordered by date.',
    )
    # Company currency (PKR), not the line's own transaction currency —
    # debit/credit/balance/running_balance are always stored in company
    # currency regardless of what the source document (e.g. a USD invoice)
    # was raised in, so the monetary widget must key off this, not
    # aml.currency_id (that would show "$" on a PKR amount for any foreign-
    # currency invoice line).
    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW reema_ledger_line AS (
                SELECT
                    aml.id AS id,
                    aml.move_id AS move_id,
                    aml.date AS date,
                    aml.name AS name,
                    am.ref AS ref,
                    aml.journal_id AS journal_id,
                    aml.account_id AS account_id,
                    COALESCE(acc.partner_id, aml.partner_id) AS partner_id,
                    aml.debit AS debit,
                    aml.credit AS credit,
                    aml.balance AS balance,
                    rc.currency_id AS currency_id,
                    aml.company_id AS company_id,
                    SUM(aml.balance) OVER (
                        PARTITION BY aml.account_id, COALESCE(acc.partner_id, aml.partner_id)
                        ORDER BY aml.date, aml.move_id, aml.id
                    ) AS running_balance
                FROM account_move_line aml
                JOIN account_move am ON am.id = aml.move_id
                JOIN account_account acc ON acc.id = aml.account_id
                JOIN res_company rc ON rc.id = aml.company_id
                WHERE am.state = 'posted'
                  AND (
                      (acc.partner_id IS NOT NULL AND acc.account_type IN
                          ('asset_receivable', 'liability_payable', 'asset_current'))
                      OR (acc.partner_id IS NULL AND acc.account_type = 'liability_payable')
                      OR acc.reema_hr_employee_id IS NOT NULL
                  )
            )
        """)
