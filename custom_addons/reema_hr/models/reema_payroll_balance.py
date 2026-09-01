from odoo import _, fields, models, tools
from odoo.exceptions import UserError


class ReemaPayrollBalance(models.Model):
    """Read-only summary of every active employee's individual Advances &
    Loans account (1-1-4-xx, account_type='asset_current', keyed by
    reema_hr_employee_id instead of partner_id since employees aren't
    res.partner — see hr_employee.py's _get_or_create_advance_loan_account),
    with its current posted balance. One row per active employee, including
    employees with no advances/loans yet. Lives in reema_hr (not
    reema_accounting) because reema_hr_employee_id is defined here.
    """
    _name = 'reema.payroll.balance'
    _description = 'Payroll Balance Summary'
    _auto = False
    _order = 'employee_id'

    employee_id = fields.Many2one('hr.employee', string='Employee', readonly=True)
    account_code = fields.Char(
        string='Account', readonly=True,
        help='This employee\'s Advances & Loans account (1-1-4-xx) — blank if none has been created yet.',
    )
    debit = fields.Monetary(string='Debit', readonly=True)
    credit = fields.Monetary(string='Credit', readonly=True)
    balance = fields.Monetary(string='Balance', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW reema_payroll_balance AS (
                SELECT
                    e.id AS id,
                    e.id AS employee_id,
                    acc.code_store ->> aar.res_company_id::text AS account_code,
                    COALESCE(SUM(aml.debit) FILTER (WHERE am.state = 'posted'), 0) AS debit,
                    COALESCE(SUM(aml.credit) FILTER (WHERE am.state = 'posted'), 0) AS credit,
                    COALESCE(SUM(aml.balance) FILTER (WHERE am.state = 'posted'), 0) AS balance,
                    (SELECT currency_id FROM res_company ORDER BY id LIMIT 1) AS currency_id,
                    (SELECT id FROM res_company ORDER BY id LIMIT 1) AS company_id
                FROM hr_employee e
                LEFT JOIN account_account acc
                    ON acc.reema_hr_employee_id = e.id AND acc.account_type = 'asset_current'
                LEFT JOIN account_account_res_company_rel aar ON aar.account_account_id = acc.id
                LEFT JOIN account_move_line aml ON aml.account_id = acc.id
                LEFT JOIN account_move am ON am.id = aml.move_id
                WHERE e.active = true
                GROUP BY e.id, acc.code_store, aar.res_company_id
            )
        """)

    def action_print_payroll_balance(self):
        # See reema_accounting's reema.vendor.balance.action_print_vendor_balance
        # for why the "skip zero" choice has to be an explicit button, not a filter.
        records = self if self else self.search([])
        if self.env.context.get('reema_hide_zero_balance'):
            records = records.filtered(lambda r: r.balance)
        if not records:
            raise UserError(_('There are no payroll balances to print.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/report/html/reema_hr.report_payroll_balance/%s' % ','.join(str(i) for i in records.ids),
            'target': 'new',
        }
