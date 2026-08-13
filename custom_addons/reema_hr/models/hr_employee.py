from odoo import api, fields, models

ADVANCE_LOAN_PREFIX = '1-1-4'


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    currency_id = fields.Many2one(
        related='company_id.currency_id', string='Currency', readonly=True,
    )
    reema_join_date = fields.Date(
        string='Joining Date', groups='hr.group_hr_user', tracking=True,
        help='Attendance is only generated for this employee from this date onward. '
             'Leave blank if unknown. Quit date is the core HR "Departure Date", set '
             'when the employee is archived.',
    )
    monthly_salary = fields.Monetary(
        string='Monthly Salary', currency_field='currency_id', groups='hr.group_hr_user',
        help='Basic monthly salary. Payslips prorate this by attendance.',
    )
    daily_rate = fields.Monetary(
        string='Daily Rate', currency_field='currency_id', groups='hr.group_hr_user',
        compute='_compute_daily_rate', store=True,
        help='Monthly Salary ÷ Standard Working Days per Month (company setting).',
    )
    has_eobi = fields.Boolean(string='Has EOBI', groups='hr.group_hr_user')
    eobi_amount = fields.Monetary(
        string='EOBI Deduction', currency_field='currency_id', groups='hr.group_hr_user',
        help='Fixed monthly EOBI amount deducted on each payslip.',
    )
    has_pessi = fields.Boolean(string='Has PESSI', groups='hr.group_hr_user')
    pessi_amount = fields.Monetary(
        string='PESSI Deduction', currency_field='currency_id', groups='hr.group_hr_user',
        help='Fixed monthly PESSI amount deducted on each payslip.',
    )
    reema_advance_loan_account_id = fields.Many2one(
        'account.account', string='Advances & Loans Account', readonly=True, copy=False,
        groups='hr.group_hr_user',
        help='Individual current-asset account (1-1-4-xx) tracking this employee\'s outstanding advances and loans.',
    )
    reema_advance_loan_balance = fields.Monetary(
        string='Advances & Loans Balance', currency_field='currency_id',
        compute='_compute_advance_loan_balance', groups='hr.group_hr_user',
    )
    reema_advance_ids = fields.One2many(
        'reema.hr.employee.advance', 'employee_id', string='Advances/Loans', groups='hr.group_hr_user',
    )
    reema_attendance_ids = fields.One2many(
        'reema.hr.attendance', 'employee_id', string='Attendance', groups='hr.group_hr_user',
    )
    reema_payslip_ids = fields.One2many(
        'reema.hr.payslip', 'employee_id', string='Payslips', groups='hr.group_hr_user',
    )
    reema_advance_count = fields.Integer(compute='_compute_reema_hr_counts', groups='hr.group_hr_user')
    reema_payslip_count = fields.Integer(compute='_compute_reema_hr_counts', groups='hr.group_hr_user')

    def _compute_reema_hr_counts(self):
        for employee in self:
            employee.reema_advance_count = len(employee.reema_advance_ids)
            employee.reema_payslip_count = len(employee.reema_payslip_ids)

    def action_view_reema_advances(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Advances/Loans',
            'res_model': 'reema.hr.employee.advance',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id},
        }

    def action_view_reema_payslips(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Payslips',
            'res_model': 'reema.hr.payslip',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id},
        }

    @api.depends('monthly_salary', 'company_id.reema_hr_standard_days_per_month')
    def _compute_daily_rate(self):
        for employee in self:
            days = employee.company_id.reema_hr_standard_days_per_month
            employee.daily_rate = (employee.monthly_salary / days) if days else 0.0

    def _compute_advance_loan_balance(self):
        for employee in self:
            employee.reema_advance_loan_balance = employee._get_outstanding_advance_loan()

    def _get_outstanding_advance_loan(self):
        """Sum of posted journal-line balances on this employee's advances/loans
        account — what they still owe back to the company."""
        self.ensure_one()
        account = self.reema_advance_loan_account_id
        if not account:
            return 0.0
        lines = self.env['account.move.line'].search([
            ('account_id', '=', account.id),
            ('move_id.state', '=', 'posted'),
        ])
        return sum(lines.mapped('balance'))

    def _get_or_create_advance_loan_account(self):
        """Return this employee's individual advances/loans account (1-1-4-xx),
        auto-creating it on first use — mirrors res.partner's contractor advance
        account. Called when an advance or loan is first posted, not on
        employee create, since most employees never need one."""
        self.ensure_one()
        if self.reema_advance_loan_account_id:
            return self.reema_advance_loan_account_id
        code = self._next_account_code(ADVANCE_LOAN_PREFIX)
        account = self.env['account.account'].sudo().create({
            'name': self.name + ' — Advances & Loans',
            'code': code,
            'account_type': 'asset_current',
            'reconcile': True,
            'reema_hr_employee_id': self.id,
        })
        self.sudo().reema_advance_loan_account_id = account
        return account

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

    @api.model
    def _get_active_for_period(self, date_from, date_to):
        """Employees whose employment period overlaps [date_from, date_to] —
        i.e. joined on or before date_to, and (if departed) didn't leave
        before date_from. Includes archived employees who left partway
        through the range, since they still need attendance for the days
        they worked. A blank joining/departure date means no bound on that
        side."""
        domain = [
            '|', ('reema_join_date', '=', False), ('reema_join_date', '<=', date_to),
            '|', ('departure_date', '=', False), ('departure_date', '>=', date_from),
        ]
        return self.with_context(active_test=False).search(domain)

    def _get_next_due_advance_lines(self):
        """Next due installment line for each of this employee's posted
        advances/loans, oldest voucher first. A plain Advance has a single
        line for its full amount; a Loan yields its next due installment."""
        self.ensure_one()
        lines = self.env['reema.hr.employee.advance.line']
        vouchers = self.env['reema.hr.employee.advance'].search([
            ('employee_id', '=', self.id),
            ('state', '=', 'posted'),
        ], order='date asc, id asc')
        for voucher in vouchers:
            due = voucher.line_ids.filtered(lambda l: l.state == 'due')[:1]
            lines |= due
        return lines
