import calendar

from odoo import _, api, fields, models
from odoo.exceptions import UserError


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
             'tallies on the payslip — the standard working-days divisor already prices these in.')
    check_in = fields.Float(string='Check In', help='Time of arrival, e.g. 9.50 = 9:30 AM.')
    check_out = fields.Float(string='Check Out')
    late_minutes = fields.Integer(
        string='Late (minutes)', compute='_compute_late', store=True,
    )
    currency_id = fields.Many2one(related='employee_id.currency_id', string='Currency')
    late_deduction = fields.Monetary(
        string='Late Deduction', currency_field='currency_id',
        compute='_compute_late', store=True,
    )
    company_id = fields.Many2one(related='employee_id.company_id', string='Company', store=True)

    _sql_constraints = [
        ('employee_date_uniq', 'unique(employee_id, date)',
         'Attendance for this employee on this date already exists.'),
    ]

    @api.depends('check_in', 'state', 'date', 'employee_id.monthly_salary',
                 'employee_id.company_id.reema_hr_shift_start',
                 'employee_id.company_id.reema_hr_grace_minutes',
                 'employee_id.company_id.reema_hr_hours_per_day')
    def _compute_late(self):
        for rec in self:
            company = rec.employee_id.company_id
            if rec.state not in ('present', 'half_day') or not rec.check_in or not company or not rec.date:
                rec.late_minutes = 0
                rec.late_deduction = 0.0
                continue
            cutoff = company.reema_hr_shift_start + (company.reema_hr_grace_minutes / 60.0)
            late_minutes = max(0, round((rec.check_in - cutoff) * 60))
            rec.late_minutes = late_minutes
            # Hourly rate = Monthly Salary ÷ calendar days in this attendance's
            # month ÷ standard hours per day — mirrors the existing manual
            # payroll sheet's formula, but with actual days-in-month instead
            # of a hardcoded 31 so it stays correct in shorter months.
            days_in_month = calendar.monthrange(rec.date.year, rec.date.month)[1]
            hours_per_day = company.reema_hr_hours_per_day
            hourly_rate = (
                rec.employee_id.monthly_salary / days_in_month / hours_per_day
                if days_in_month and hours_per_day else 0.0
            )
            rec.late_deduction = hourly_rate * (late_minutes / 60.0)

    def action_mark_holiday(self):
        if not self:
            raise UserError(_('Select the attendance rows to mark as a holiday first.'))
        self.write({'state': 'holiday'})

    def action_mark_present(self):
        if not self:
            raise UserError(_('Select the attendance rows to mark as present first.'))
        self.write({'state': 'present'})
