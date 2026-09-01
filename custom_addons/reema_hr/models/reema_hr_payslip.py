import calendar
import datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

SALARY_EXPENSE_CODE = '6-1-1-01'
SALARY_PAYABLE_CODE = '2-1-3-01'
EOBI_PAYABLE_CODE = '2-1-3-02'
PESSI_PAYABLE_CODE = '2-1-3-04'

MONTH_SELECTION = [
    ('1', 'January'), ('2', 'February'), ('3', 'March'), ('4', 'April'),
    ('5', 'May'), ('6', 'June'), ('7', 'July'), ('8', 'August'),
    ('9', 'September'), ('10', 'October'), ('11', 'November'), ('12', 'December'),
]


class ReemaHrPayslip(models.Model):
    _name = 'reema.hr.payslip'
    _description = 'Payslip'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Payslip No.', readonly=True, copy=False,
        default=lambda self: _('New'), tracking=True,
    )
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, tracking=True)
    currency_id = fields.Many2one(related='employee_id.currency_id', string='Currency')
    period_month = fields.Selection(
        MONTH_SELECTION, string='Month', required=True, tracking=True,
        default=lambda self: str(fields.Date.context_today(self).month),
    )
    period_year = fields.Integer(
        string='Year', required=True, tracking=True,
        default=lambda self: fields.Date.context_today(self).year,
    )
    date_from = fields.Date(
        string='From', compute='_compute_period_dates', store=True,
    )
    date_to = fields.Date(
        string='To', compute='_compute_period_dates', store=True,
    )
    monthly_salary = fields.Monetary(
        string='Monthly Salary', currency_field='currency_id',
        related='employee_id.monthly_salary', readonly=True,
        help='Employee\'s full basic monthly salary, before proration.',
    )
    daily_rate = fields.Monetary(
        string='Daily Rate', currency_field='currency_id',
        compute='_compute_daily_rate', store=True,
        help='Monthly Salary ÷ working days in the month (calendar days minus weekly-offs '
             'and public holidays) — matches the same basis used for late/early-leave '
             'deductions, so a Sunday-heavy or holiday-heavy month doesn\'t understate pay.',
    )

    total_days = fields.Integer(
        string='Total Days', compute='_compute_total_days', store=True,
        help='Calendar days in this payslip\'s month.',
    )
    working_days = fields.Integer(
        string='Working Days', compute='_compute_working_days', store=True,
        help='Expected working days this month per the company\'s weekly-off day and public '
             'holiday calendar — the same basis Daily Rate uses. Independent of whether '
             'attendance has been generated yet; once it has, Present + Absent + Leave + '
             'Half should reconcile against this.',
    )
    present_days = fields.Float(string='Present Days', readonly=True)
    late_minutes = fields.Integer(
        string='Late Arrival (minutes)', readonly=True,
        help='Total late-arrival minutes across this month\'s attendance.',
    )
    late_deduction_waived = fields.Boolean(
        string='Waive Late Deduction', groups='reema_hr.group_reema_hr_manager', tracking=True,
        help='Skip the whole month\'s late-arrival deduction for this payslip, regardless of '
             'any per-day waivers already set on individual attendance records.',
    )
    early_minutes = fields.Integer(
        string='Early Leave (minutes)', readonly=True,
        help='Total early-leave minutes across this month\'s attendance.',
    )
    early_leave_deduction_waived = fields.Boolean(
        string='Waive Early Leave Deduction', groups='reema_hr.group_reema_hr_manager', tracking=True,
        help='Skip the whole month\'s early-leave deduction for this payslip, regardless of '
             'any per-day waivers already set on individual attendance records.',
    )
    half_days = fields.Float(string='Half Days', readonly=True)
    half_waived_days = fields.Float(
        string='Half Day Waived', groups='reema_hr.group_reema_hr_manager', tracking=True,
        help='Quantity of Half Days management has approved to pay in full instead of half-pay '
             '— fractional values allowed (e.g. 1.5). The remainder (Half Days minus this) stays '
             'at half-pay. Cannot exceed Half Days.',
    )
    absent_days = fields.Integer(string='Absent Days', readonly=True)
    absent_waived_days = fields.Float(
        string='Absent Waived', groups='reema_hr.group_reema_hr_manager', tracking=True,
        help='Quantity of Absent days management has approved as paid despite the absence — '
             'fractional values allowed (e.g. 1.5). The remainder (Absent Days minus this) stays '
             'unpaid/deducted. Cannot exceed Absent Days.',
    )
    leave_days = fields.Integer(string='Leave Days', readonly=True)
    holiday_days = fields.Integer(
        string='Holiday Days', compute='_compute_holiday_days', store=True,
        help='Total Days minus Working Days — weekly offs and public holidays combined, per '
             'the company calendar. Always reconciles with Working Days, independent of '
             'whether attendance has been generated for this period yet.',
    )

    absent_deduction = fields.Monetary(
        string='Absent', currency_field='currency_id', readonly=True,
        help='Daily Rate × (Absent Days − Absent Waived) — the unpaid portion of Absent Days.',
    )
    half_day_deduction = fields.Monetary(
        string='Half Day', currency_field='currency_id', readonly=True,
        help='Daily Rate × 0.5 × (Half Days − Half Day Waived) — the half-pay portion of Half Days.',
    )
    gross_pay = fields.Monetary(
        string='Gross Pay', currency_field='currency_id', readonly=True,
        help='Monthly Salary minus Absent Deduction and Half Day Deduction — full pay for '
             'every working day actually worked (or waived), before late/early-leave deductions.',
    )
    late_deduction = fields.Monetary(string='Late', currency_field='currency_id', readonly=True)
    early_leave_deduction = fields.Monetary(string='Early Leave', currency_field='currency_id', readonly=True)
    net_salary_expense = fields.Monetary(string='Net Salary Expense', currency_field='currency_id', readonly=True)
    advance_deduction = fields.Monetary(
        string='Advance', currency_field='currency_id', readonly=True, copy=False,
        help='Recovered from Advance Against Salary vouchers only, dated on or before this payslip\'s period.',
    )
    advance_deduction_waived = fields.Boolean(
        string='Waive Advance', groups='reema_hr.group_reema_hr_manager', tracking=True,
        help='Skip advance recovery for this payslip — the due amount rolls forward to the next one.',
    )
    loan_deduction = fields.Monetary(
        string='Loan', currency_field='currency_id', readonly=True, copy=False,
        help='Recovered from Loan (Installments) vouchers only, dated on or before this payslip\'s period.',
    )
    loan_deduction_waived = fields.Boolean(
        string='Waive Loan', groups='reema_hr.group_reema_hr_manager', tracking=True,
        help='Skip this loan installment for this payslip — it rolls forward to the next one.',
    )
    eobi_deduction = fields.Monetary(string='EOBI', currency_field='currency_id', readonly=True, copy=False)
    pessi_deduction = fields.Monetary(string='PESSI', currency_field='currency_id', readonly=True, copy=False)
    net_pay = fields.Monetary(
        string='Net Pay', currency_field='currency_id', compute='_compute_net_pay', store=True,
    )

    advance_loan_line_recovered_ids = fields.One2many(
        'reema.hr.employee.advance.line', 'payslip_id', string='Advance/Loan Installments Recovered',
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('paid', 'Paid'),
        ('cancelled', 'Cancelled'),
    ], default='draft', required=True, copy=False, tracking=True)
    move_id = fields.Many2one('account.move', string='Accrual Entry', readonly=True, copy=False)
    payment_move_id = fields.Many2one('account.move', string='Payment Entry', readonly=True, copy=False)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)

    _sql_constraints = [
        ('date_check', 'CHECK(date_from <= date_to)', 'From date must be before or equal to the To date.'),
        ('employee_period_uniq', 'unique(employee_id, period_month, period_year)',
         'A payslip for this employee and month already exists.'),
    ]

    @api.constrains('absent_waived_days', 'absent_days', 'half_waived_days', 'half_days')
    def _check_waived_days(self):
        for rec in self:
            if rec.absent_waived_days < 0 or rec.half_waived_days < 0:
                raise ValidationError(_('Waived days cannot be negative.'))
            if rec.absent_waived_days > rec.absent_days:
                raise ValidationError(
                    _('Absent Waived cannot exceed Absent Days (%s).') % rec.absent_days)
            if rec.half_waived_days > rec.half_days:
                raise ValidationError(
                    _('Half Day Waived cannot exceed Half Days (%s).') % rec.half_days)

    @api.depends('period_month', 'period_year')
    def _compute_period_dates(self):
        for rec in self:
            if not rec.period_month or not rec.period_year:
                rec.date_from = False
                rec.date_to = False
                continue
            month = int(rec.period_month)
            last_day = calendar.monthrange(rec.period_year, month)[1]
            rec.date_from = datetime.date(rec.period_year, month, 1)
            rec.date_to = datetime.date(rec.period_year, month, last_day)

    @api.depends('date_from', 'date_to')
    def _compute_total_days(self):
        for rec in self:
            rec.total_days = (rec.date_to - rec.date_from).days + 1 if rec.date_from and rec.date_to else 0

    @api.depends('date_from', 'company_id.reema_hr_weekly_off_day')
    def _compute_working_days(self):
        for rec in self:
            if not rec.date_from:
                rec.working_days = 0
                continue
            company = rec.company_id or rec.env.company
            rec.working_days = company._get_working_days_in_month(rec.date_from.year, rec.date_from.month)

    @api.depends('total_days', 'working_days')
    def _compute_holiday_days(self):
        for rec in self:
            rec.holiday_days = rec.total_days - rec.working_days

    @api.depends('employee_id.monthly_salary', 'working_days')
    def _compute_daily_rate(self):
        for rec in self:
            rec.daily_rate = (rec.employee_id.monthly_salary / rec.working_days) if rec.working_days else 0.0

    @api.depends('net_salary_expense', 'advance_deduction', 'loan_deduction', 'eobi_deduction', 'pessi_deduction')
    def _compute_net_pay(self):
        for rec in self:
            rec.net_pay = (
                rec.net_salary_expense - rec.advance_deduction - rec.loan_deduction
                - rec.eobi_deduction - rec.pessi_deduction
            )

    @api.onchange('employee_id', 'period_month', 'period_year', 'date_from', 'date_to',
                  'advance_deduction_waived', 'loan_deduction_waived',
                  'late_deduction_waived', 'early_leave_deduction_waived',
                  'absent_waived_days', 'half_waived_days')
    def _onchange_recompute_attendance(self):
        for rec in self:
            if rec.employee_id and rec.date_from and rec.date_to:
                rec._recompute_from_attendance()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._recompute_from_attendance()
        return records

    def action_recompute(self):
        self._check_hr_group()
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only a draft payslip can be recomputed.'))
        self._recompute_from_attendance()

    def _recompute_from_attendance(self):
        for rec in self:
            if rec.state != 'draft' or not rec.employee_id:
                continue
            attendance = self.env['reema.hr.attendance'].search([
                ('employee_id', '=', rec.employee_id.id),
                ('date', '>=', rec.date_from),
                ('date', '<=', rec.date_to),
            ])
            # A waived Half Day is paid as a full day per management's override —
            # it no longer counts toward the half-day tally.
            present = len(attendance.filtered(
                lambda a: a.state == 'present' or (a.state == 'half_day' and a.deduction_waived)))
            half = len(attendance.filtered(lambda a: a.state == 'half_day' and not a.deduction_waived))
            absent = len(attendance.filtered(lambda a: a.state == 'absent'))
            leave = len(attendance.filtered(lambda a: a.state == 'leave'))
            late_minutes = sum(attendance.mapped('late_minutes'))
            early_minutes = sum(attendance.mapped('early_minutes'))
            late_deduction = 0.0 if rec.late_deduction_waived else sum(attendance.mapped('late_deduction'))
            early_leave_deduction = 0.0 if rec.early_leave_deduction_waived else sum(attendance.mapped('early_deduction'))
            # Waived quantities can't exceed the freshly recomputed totals —
            # clamp rather than error, since this recompute can be triggered
            # implicitly (e.g. changing the employee) without the user having
            # touched the waiver fields at all.
            absent_waived = min(rec.absent_waived_days, absent)
            half_waived = min(rec.half_waived_days, half)
            # Use a fresh, UNROUNDED daily rate for this math — not rec.daily_rate,
            # which is a Monetary field rounded to currency precision (e.g.
            # 30000/27 = 1111.111... stores/reads back as 1111.11). Multiplying
            # that rounded value back out by working_days loses a few paisa
            # (1111.11 × 27 = 29999.97, not 30000.00), so a fully-present or
            # fully-waived month would silently short the employee. The
            # displayed Daily Rate field can stay rounded for readability;
            # only the money math needs full precision.
            raw_daily_rate = (rec.monthly_salary / rec.working_days) if rec.working_days else 0.0
            # Leave is paid (full daily rate); Absent is unpaid except for any
            # waived quantity (paid in full); Half is half-pay except for any
            # waived quantity (paid in full instead of half). Expressed as
            # explicit deductions off Monthly Salary (rather than an additive
            # present/leave/... formula) so the payslip can show the actual
            # rupee amount lost to absences/half-days, and so that waiving
            # every absent/half day visibly reconstitutes to exactly Monthly
            # Salary (both deductions hit zero) — present days always add up
            # to Working Days, so Monthly Salary minus these two deductions
            # is mathematically identical to the old additive formula, just
            # transparent instead of opaque.
            absent_deduction = raw_daily_rate * (absent - absent_waived)
            half_day_deduction = raw_daily_rate * 0.5 * (half - half_waived)
            gross_pay = rec.monthly_salary - absent_deduction - half_day_deduction
            net_salary_expense = gross_pay - late_deduction - early_leave_deduction
            eobi_deduction = rec.employee_id.eobi_amount if rec.employee_id.has_eobi else 0.0
            pessi_deduction = rec.employee_id.pessi_amount if rec.employee_id.has_pessi else 0.0
            remaining = net_salary_expense - eobi_deduction - pessi_deduction
            recovered_lines = rec._preview_advance_loan_recovery(remaining)
            advance_deduction = sum(recovered_lines.filtered(lambda l: l.advance_type == 'advance').mapped('amount'))
            loan_deduction = sum(recovered_lines.filtered(lambda l: l.advance_type == 'loan').mapped('amount'))
            rec.write({
                'present_days': present,
                'half_days': half,
                'half_waived_days': half_waived,
                'absent_days': absent,
                'absent_waived_days': absent_waived,
                'leave_days': leave,
                'late_minutes': late_minutes,
                'early_minutes': early_minutes,
                'absent_deduction': absent_deduction,
                'half_day_deduction': half_day_deduction,
                'gross_pay': gross_pay,
                'late_deduction': late_deduction,
                'early_leave_deduction': early_leave_deduction,
                'net_salary_expense': net_salary_expense,
                'eobi_deduction': eobi_deduction,
                'pessi_deduction': pessi_deduction,
                'advance_deduction': advance_deduction,
                'loan_deduction': loan_deduction,
            })

    def _preview_advance_loan_recovery(self, remaining):
        """Given `remaining` (net salary expense minus statutory deductions),
        returns the advance/loan installment lines that would be recovered
        this cycle — oldest due first, never pushing net pay negative, never
        including a voucher dated after this payslip's own period, and
        skipping whichever type (advance/loan) is waived on this payslip
        (skipped lines just stay due for the next payslip). Used both for
        the live draft preview and, unchanged, at actual confirm time, so
        the two always agree."""
        self.ensure_one()
        lines = self.env['reema.hr.employee.advance.line']
        if not self.employee_id:
            return lines
        for line in self.employee_id._get_next_due_advance_lines(cutoff_date=self.date_to):
            if line.advance_type == 'advance' and self.advance_deduction_waived:
                continue
            if line.advance_type == 'loan' and self.loan_deduction_waived:
                continue
            if line.amount <= remaining:
                lines |= line
                remaining -= line.amount
            else:
                break
        return lines

    def _get_salary_expense_account(self):
        account = self.env['account.account'].search([('code', '=', SALARY_EXPENSE_CODE)], limit=1)
        if not account:
            raise UserError(_('Salary Expense account %s not found in the Chart of Accounts.') % SALARY_EXPENSE_CODE)
        return account

    def _get_salary_payable_account(self):
        account = self.env['account.account'].search([('code', '=', SALARY_PAYABLE_CODE)], limit=1)
        if not account:
            raise UserError(_('Salaries Payable account %s not found in the Chart of Accounts.') % SALARY_PAYABLE_CODE)
        return account

    def _get_eobi_payable_account(self):
        account = self.env['account.account'].search([('code', '=', EOBI_PAYABLE_CODE)], limit=1)
        if not account:
            raise UserError(_('EOBI Payable account %s not found in the Chart of Accounts.') % EOBI_PAYABLE_CODE)
        return account

    def _get_pessi_payable_account(self):
        account = self.env['account.account'].search([('code', '=', PESSI_PAYABLE_CODE)], limit=1)
        if not account:
            raise UserError(_('PESSI Payable account %s not found in the Chart of Accounts.') % PESSI_PAYABLE_CODE)
        return account

    def unlink(self):
        if any(rec.state in ('confirmed', 'paid') for rec in self):
            raise UserError(_('A confirmed payslip cannot be deleted — cancel it instead.'))
        return super().unlink()

    def _check_hr_group(self):
        # Segregation of duties, other half of action_pay's own check: preparing/
        # confirming/cancelling a payslip is HR's job, not Accounts' — enforced
        # here (not just via button visibility, which only stops normal UI use)
        # so it holds regardless of which menu/view/RPC call the request came
        # from. Mirrors action_pay raising for the opposite direction.
        if not self.env.user.has_group('reema_hr.group_reema_hr_user'):
            raise UserError(_('Only HR staff can do this.'))

    def action_confirm(self):
        self._check_hr_group()
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only a draft payslip can be confirmed.'))
            rec._recompute_from_attendance()
            if rec.net_salary_expense <= 0:
                raise UserError(_('Net salary expense must be greater than zero — record attendance for this period first.'))
            if rec.name == _('New'):
                # Context key ir_sequence_date (not the sequence_date= kwarg!) so the
                # embedded year/month (PAY/26/07/00001) reflect the payslip's own
                # period, not whenever it happens to get confirmed — a July payslip
                # confirmed late in August must still read as a July payslip, not
                # silently mislabel itself August. next_by_code's own sequence_date=
                # param only affects date-range bucket selection on sequences with
                # use_date_range=True (ours doesn't) — for a plain/"standard"
                # sequence it's silently ignored and %(y)s/%(month)s always fall
                # back to today's date unless ir_sequence_date is set via context.
                rec.name = self.env['ir.sequence'].with_context(
                    ir_sequence_date=rec.date_to).next_by_code('reema.hr.payslip') or _('New')

            eobi_deduction = rec.eobi_deduction
            pessi_deduction = rec.pessi_deduction
            remaining = rec.net_salary_expense - eobi_deduction - pessi_deduction
            if remaining < 0:
                raise UserError(_('EOBI/PESSI deductions exceed this payslip\'s net salary expense — check attendance and statutory amounts.'))

            recovered_lines = rec._preview_advance_loan_recovery(remaining)
            advance_deduction = sum(recovered_lines.filtered(lambda l: l.advance_type == 'advance').mapped('amount'))
            loan_deduction = sum(recovered_lines.filtered(lambda l: l.advance_type == 'loan').mapped('amount'))
            net_pay = remaining - advance_deduction - loan_deduction

            expense_account = rec._get_salary_expense_account()
            payable_account = rec._get_salary_payable_account()
            move_lines = [(0, 0, {
                'account_id': expense_account.id,
                'name': rec.name,
                'debit': rec.net_salary_expense,
                'credit': 0.0,
            })]
            advance_account = rec.employee_id.reema_advance_loan_account_id
            if advance_deduction > 0:
                move_lines.append((0, 0, {
                    'account_id': advance_account.id,
                    'name': _('Advance recovery — %s') % rec.name,
                    'debit': 0.0,
                    'credit': advance_deduction,
                }))
            if loan_deduction > 0:
                move_lines.append((0, 0, {
                    'account_id': advance_account.id,
                    'name': _('Loan recovery — %s') % rec.name,
                    'debit': 0.0,
                    'credit': loan_deduction,
                }))
            if eobi_deduction > 0:
                move_lines.append((0, 0, {
                    'account_id': rec._get_eobi_payable_account().id,
                    'name': _('EOBI — %s') % rec.name,
                    'debit': 0.0,
                    'credit': eobi_deduction,
                }))
            if pessi_deduction > 0:
                move_lines.append((0, 0, {
                    'account_id': rec._get_pessi_payable_account().id,
                    'name': _('PESSI — %s') % rec.name,
                    'debit': 0.0,
                    'credit': pessi_deduction,
                }))
            move_lines.append((0, 0, {
                'account_id': payable_account.id,
                'name': rec.name,
                'debit': 0.0,
                'credit': net_pay,
            }))
            # .sudo(): a plain HR Manager (group_reema_hr_manager) only implies
            # account.group_account_readonly, not enough to create/post a journal
            # entry — this mirrors the same pattern already used for auto-creating
            # an employee's advance/loan GL account (hr_employee.py), a system-level
            # side effect of a permitted HR action rather than reason to broaden
            # every HR Manager's general accounting write access.
            move = self.env['account.move'].sudo().create({
                'move_type': 'entry',
                'journal_id': self.env['account.journal'].search(
                    [('code', '=', 'JV')], limit=1).id,
                'date': rec.date_to,
                'line_ids': move_lines,
            })
            move.action_post()

            recovered_lines.write({'state': 'paid', 'payslip_id': rec.id})
            for voucher in recovered_lines.mapped('advance_id'):
                if all(l.state == 'paid' for l in voucher.line_ids):
                    voucher.state = 'closed'

            rec.write({
                'advance_deduction': advance_deduction,
                'loan_deduction': loan_deduction,
                'move_id': move.id,
                'state': 'confirmed',
            })
            rec._message_log(body=_('Payslip confirmed. Net pay: %s') % net_pay)

    def action_pay(self, journal_id=None):
        # Segregation of duties: HR prepares and confirms salaries, but only
        # Accounts staff may trigger the actual bank/cash payment — enforced
        # here (not just via button visibility) so it holds regardless of
        # which menu/view the call came from.
        if not self.env.user.has_group('reema_accounting.group_reema_accountant'):
            raise UserError(_('Only Accounts staff can pay a payslip.'))
        for rec in self:
            if rec.state != 'confirmed':
                raise UserError(_('Only a confirmed payslip can be paid.'))
            journal = self.env['account.journal'].browse(journal_id) if journal_id else False
            if not journal:
                raise UserError(_('Select a payment method to pay this payslip.'))
            liquidity_account = journal.default_account_id
            if not liquidity_account:
                raise UserError(_('Selected payment method has no default account configured.'))
            payable_account = rec._get_salary_payable_account()
            move = self.env['account.move'].create({
                'move_type': 'entry',
                'journal_id': journal.id,
                'date': fields.Date.context_today(rec),
                'ref': _('Payment of %s') % rec.name,
                'line_ids': [
                    (0, 0, {
                        'account_id': payable_account.id,
                        'name': rec.name,
                        'debit': rec.net_pay,
                        'credit': 0.0,
                    }),
                    (0, 0, {
                        'account_id': liquidity_account.id,
                        'name': rec.name,
                        'debit': 0.0,
                        'credit': rec.net_pay,
                    }),
                ],
            })
            move.action_post()
            rec.write({'payment_move_id': move.id, 'state': 'paid'})
            rec._message_log(body=_('Payslip paid via %s.') % journal.name)

    def action_cancel(self):
        self._check_hr_group()
        for rec in self:
            if rec.state == 'paid':
                raise UserError(_('A paid payslip cannot be cancelled — reverse the payment entry manually first.'))
            if rec.state == 'confirmed':
                if rec.move_id:
                    reversal = rec.move_id._reverse_moves(default_values_list=[{
                        'ref': _('Reversal of %s') % rec.name,
                        'date': fields.Date.context_today(rec),
                    }])
                    reversal.action_post()
                rec.advance_loan_line_recovered_ids.write({'state': 'due', 'payslip_id': False})
                for voucher in rec.advance_loan_line_recovered_ids.mapped('advance_id'):
                    if voucher.state == 'closed':
                        voucher.state = 'posted'
            rec.write({'state': 'cancelled'})

    def action_reset_to_draft(self):
        self._check_hr_group()
        for rec in self:
            if rec.state != 'cancelled':
                raise UserError(_('Only a cancelled payslip can be reset to draft.'))
            rec.write({
                'state': 'draft',
                'advance_deduction': 0.0,
                'loan_deduction': 0.0,
                'eobi_deduction': 0.0,
                'pessi_deduction': 0.0,
            })

    def action_open_pay_wizard(self):
        if not self.env.user.has_group('reema_accounting.group_reema_accountant'):
            raise UserError(_('Only Accounts staff can pay a payslip.'))
        if not self:
            raise UserError(_('Select at least one payslip to pay.'))
        if any(rec.state != 'confirmed' for rec in self):
            raise UserError(_('Only confirmed payslips can be paid. Confirm the selected payslips first.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Pay Payslips'),
            'res_model': 'reema.hr.payslip.pay.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_payslip_ids': self.ids},
        }

    def action_print_payslip(self):
        # Open the HTML preview in a new browser tab — the user prints with
        # Ctrl+P and closes the tab. Follows the standard reema HTML-report
        # pattern (see custom_addons/REPORTS.md); no binding_model_id, so it
        # never appears in the cog Print menu.
        #
        # Called from the list header with nothing ticked: print the LIST
        # currently showing (one summary table, respecting whatever the list's
        # active search/filter is) rather than one full-page stub per payslip
        # — e.g. with July 2026 selected via the Month/Year picker, this
        # prints a single payroll-register sheet for the whole month. Odoo's
        # MultiRecordViewButton passes the list's active domain in via
        # context['active_domain'] for exactly this case (same mechanism
        # list-wide Export/etc. already rely on). With one or more rows
        # explicitly ticked (or called from the form, always exactly one
        # record), prints each of those as its own individual detailed slip.
        if not self:
            # Note: check *presence* of the key, not truthiness — an empty list
            # ([]) is a legitimate "no filter, show everything" domain (e.g. the
            # Accounting > Payroll > Payslips screen, which has no default month
            # filter), and is falsy in Python, so `if active_domain` would wrongly
            # treat it the same as "no domain sent at all" and print nothing.
            if 'active_domain' in self.env.context:
                records = self.search(self.env.context['active_domain'])
            else:
                records = self
            if not records:
                raise UserError(_('No payslips to print — select one or more, or adjust the list filter first.'))
            # print_fields: the on-screen column order at the moment Print was
            # clicked (payslip_month_filter_list.js reads it straight off the
            # rendered <th data-name> elements) — lets the summary sheet mirror
            # whichever columns are actually visible, not a fixed hardcoded set.
            print_fields = self.env.context.get('print_fields') or []
            url = '/report/html/reema_hr.report_payslip_list/%s' % ','.join(str(i) for i in records.ids)
            if print_fields:
                url += '?print_fields=%s' % ','.join(print_fields)
            return {
                'type': 'ir.actions.act_url',
                'url': url,
                'target': 'new',
            }
        return {
            'type': 'ir.actions.act_url',
            'url': '/report/html/reema_hr.report_payslip/%s' % ','.join(str(i) for i in self.ids),
            'target': 'new',
        }
