from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class ReemaHrAttendance(models.Model):
    _name = 'reema.hr.attendance'
    _description = 'Daily Attendance'
    _order = 'date desc, employee_id'

    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, ondelete='cascade', index=True,
    )
    date = fields.Date(string='Date', required=True, default=fields.Date.context_today)
    state = fields.Selection([
        ('present', 'Present'),
        ('absent', 'Absent'),
        ('leave', 'Leave'),
        ('half_day', 'Half Day'),
        ('holiday', 'Holiday'),
    ], string='Status', default='present', required=True,
        help='Holiday: weekly off (Sunday) or a public holiday. Excluded from present/absent/late '
             'tallies on the payslip — the standard working-days divisor already prices these in. '
             'Half Day is also set automatically when Check Out is at/before Half Time End.')
    check_in = fields.Float(string='Check In', help='Time of arrival, e.g. 9.50 = 9:30 AM.')
    half_time_out = fields.Float(string='Half Time Out', help='Time left for the lunch break.')
    half_time_in = fields.Float(string='Half Time In', help='Time returned from the lunch break.')
    check_out = fields.Float(
        string='Check Out',
        help='Time of departure. If at/before the company\'s Half Time End, the day is '
             'auto-classified as Half Day. If before Shift End otherwise, an early-leave '
             'deduction is applied.',
    )
    late_minutes = fields.Integer(
        string='Late (minutes)', compute='_compute_deductions', store=True,
    )
    early_minutes = fields.Integer(
        string='Early Leave (minutes)', compute='_compute_deductions', store=True,
    )
    currency_id = fields.Many2one(related='employee_id.currency_id', string='Currency')
    late_deduction = fields.Monetary(
        string='Late Deduction', currency_field='currency_id',
        compute='_compute_deductions', store=True,
    )
    early_deduction = fields.Monetary(
        string='Early Leave Deduction', currency_field='currency_id',
        compute='_compute_deductions', store=True,
    )
    deduction_waived = fields.Boolean(
        string='Waive Deduction (Full Day)', default=False,
        help='Management override: skips the late-arrival and early-leave deductions for this '
             'day and counts it as a full day on the payslip, even if the status is Half Day.',
    )
    company_id = fields.Many2one(related='employee_id.company_id', string='Company', store=True)
    payroll_locked = fields.Boolean(
        string='Payroll Locked', compute='_compute_payroll_locked',
        help='A confirmed or paid payslip already covers this date for this employee — '
             'attendance can no longer be edited. Cancel that payslip first if a correction '
             'is genuinely needed.',
    )

    _sql_constraints = [
        ('employee_date_uniq', 'unique(employee_id, date)',
         'Attendance for this employee on this date already exists.'),
    ]

    @api.constrains('check_in', 'check_out', 'half_time_out', 'half_time_in')
    def _check_times(self):
        for rec in self:
            for label, value in (
                (_('Check-in'), rec.check_in), (_('Check-out'), rec.check_out),
                (_('Half Time Out'), rec.half_time_out), (_('Half Time In'), rec.half_time_in),
            ):
                if value and not (0 <= value < 24):
                    raise ValidationError(_('%s time must be between 00:00 and 24:00.') % label)
            if rec.check_in and rec.check_out and rec.check_out <= rec.check_in:
                raise ValidationError(_('Check-out time must be after check-in time.'))
            if rec.half_time_out and rec.half_time_in and rec.half_time_in <= rec.half_time_out:
                raise ValidationError(_('Half Time In must be after Half Time Out.'))
            if rec.check_in and rec.half_time_out and rec.half_time_out <= rec.check_in:
                raise ValidationError(_('Half Time Out must be after Check-in.'))
            if rec.half_time_in and rec.check_out and rec.check_out <= rec.half_time_in:
                raise ValidationError(_('Check-out must be after Half Time In.'))

    @api.depends('check_in', 'check_out', 'state', 'date', 'deduction_waived',
                 'employee_id.monthly_salary',
                 'employee_id.company_id.reema_hr_shift_start',
                 'employee_id.company_id.reema_hr_shift_end',
                 'employee_id.company_id.reema_hr_half_time_end',
                 'employee_id.company_id.reema_hr_grace_minutes',
                 'employee_id.company_id.reema_hr_hours_per_day',
                 'employee_id.company_id.reema_hr_weekly_off_day')
    def _compute_deductions(self):
        for rec in self:
            company = rec.employee_id.company_id
            if rec.state not in ('present', 'half_day') or not company or not rec.date:
                rec.late_minutes = 0
                rec.late_deduction = 0.0
                rec.early_minutes = 0
                rec.early_deduction = 0.0
                continue

            # Daily rate ÷ hours per day ÷ 60 = per-minute rate. Daily rate
            # itself is Monthly Salary ÷ working days in this attendance's
            # month (calendar days minus weekly-offs and public holidays,
            # not raw calendar days — a Sunday-heavy month shouldn't
            # understate the rate).
            working_days = company._get_working_days_in_month(rec.date.year, rec.date.month)
            hours_per_day = company.reema_hr_hours_per_day
            daily_rate = (rec.employee_id.monthly_salary / working_days) if working_days else 0.0
            hourly_rate = (daily_rate / hours_per_day) if hours_per_day else 0.0
            minute_rate = hourly_rate / 60.0

            # Grace period is a threshold, not a per-minute discount: arrive
            # within grace and there's no deduction at all; arrive even one
            # minute past grace and the FULL late duration is deducted,
            # counted from shift start — the grace minutes themselves are
            # not excluded once they're exceeded.
            late_minutes = 0
            if rec.check_in:
                grace_cutoff = company.reema_hr_shift_start + (company.reema_hr_grace_minutes / 60.0)
                if rec.check_in > grace_cutoff:
                    late_minutes = max(0, round((rec.check_in - company.reema_hr_shift_start) * 60))
            rec.late_minutes = late_minutes
            rec.late_deduction = 0.0 if rec.deduction_waived else minute_rate * late_minutes

            # Half Day already prices in half a day's pay, so an early-leave
            # deduction on top of that would double-penalize the same absence.
            early_minutes = 0
            if rec.check_out and rec.state == 'present' and rec.check_out < company.reema_hr_shift_end:
                early_minutes = max(0, round((company.reema_hr_shift_end - rec.check_out) * 60))
            rec.early_minutes = early_minutes
            rec.early_deduction = 0.0 if rec.deduction_waived else minute_rate * early_minutes

    def _auto_classify_half_day(self):
        for rec in self:
            company = rec.employee_id.company_id
            if rec.state not in ('present', 'half_day') or not company:
                continue
            if rec.check_out:
                new_state = 'half_day' if rec.check_out <= company.reema_hr_half_time_end else 'present'
            elif rec.half_time_out and not rec.half_time_in:
                # Left for the lunch break and never logged a return or a
                # check-out at all — treat as having only worked the morning.
                new_state = 'half_day'
            else:
                continue
            if rec.state != new_state:
                rec.state = new_state

    _AUTO_CLASSIFY_TRIGGER_FIELDS = ('check_out', 'half_time_out', 'half_time_in')

    def _find_locking_payslip(self):
        self.ensure_one()
        if not self.employee_id or not self.date:
            return self.env['reema.hr.payslip']
        return self.env['reema.hr.payslip'].search([
            ('employee_id', '=', self.employee_id.id),
            ('state', 'in', ('confirmed', 'paid')),
            ('date_from', '<=', self.date),
            ('date_to', '>=', self.date),
        ], limit=1)

    @api.depends('employee_id', 'date')
    def _compute_payroll_locked(self):
        for rec in self:
            rec.payroll_locked = bool(rec._find_locking_payslip())

    def _check_payroll_lock(self):
        for rec in self:
            locked_payslip = rec._find_locking_payslip()
            if locked_payslip:
                raise UserError(_(
                    'Attendance for %(employee)s on %(date)s is locked — payslip %(payslip)s for '
                    'this period is already confirmed. Cancel that payslip first if a correction '
                    'is genuinely needed.'
                ) % {
                    'employee': rec.employee_id.name,
                    'date': rec.date,
                    'payslip': locked_payslip.name,
                })

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._check_payroll_lock()
        for rec, vals in zip(records, vals_list):
            if any(f in vals for f in rec._AUTO_CLASSIFY_TRIGGER_FIELDS) and 'state' not in vals:
                rec._auto_classify_half_day()
        return records

    def write(self, vals):
        self._check_payroll_lock()
        res = super().write(vals)
        if any(f in vals for f in self._AUTO_CLASSIFY_TRIGGER_FIELDS) and 'state' not in vals:
            self._auto_classify_half_day()
        return res

    def unlink(self):
        self._check_payroll_lock()
        return super().unlink()

    def action_mark_holiday(self):
        if not self:
            raise UserError(_('Select the attendance rows to mark as a holiday first.'))
        self.write({'state': 'holiday'})

    def action_mark_present(self):
        if not self:
            raise UserError(_('Select the attendance rows to mark as present first.'))
        self.write({'state': 'present'})
