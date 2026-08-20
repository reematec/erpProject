import calendar
import datetime

from odoo import api, fields, models

WEEKDAY_INDEX = {
    'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
    'friday': 4, 'saturday': 5, 'sunday': 6,
}


class ResCompany(models.Model):
    _inherit = 'res.company'

    reema_hr_shift_start = fields.Float(
        string='Shift Start Time', default=9.0,
        help='Expected daily start time. Check-ins after this time (plus the grace period) are marked late.',
    )
    reema_hr_shift_end = fields.Float(
        string='Shift End Time', default=18.0,
        help='Expected daily end time.',
    )
    reema_hr_half_time_start = fields.Float(
        string='Half Time Start', default=13.0,
        help='Start of the midday break.',
    )
    reema_hr_half_time_end = fields.Float(
        string='Half Time End', default=14.0,
        help='End of the midday break.',
    )
    reema_hr_grace_minutes = fields.Integer(
        string='Attendance Grace Period (minutes)', default=10,
        help='Minutes after shift start before lateness starts counting toward a deduction.',
    )
    reema_hr_hours_per_day = fields.Float(
        string='Standard Hours per Day', compute='_compute_hours_per_day', store=True,
        help='Auto-calculated as (Shift End - Shift Start) - (Half Time End - Half Time Start). '
             'Used to derive an hourly late/early-leave deduction rate: Monthly Salary ÷ calendar '
             'days in the attendance month ÷ this value.',
    )
    reema_hr_weekly_off_day = fields.Selection([
        ('monday', 'Monday'),
        ('tuesday', 'Tuesday'),
        ('wednesday', 'Wednesday'),
        ('thursday', 'Thursday'),
        ('friday', 'Friday'),
        ('saturday', 'Saturday'),
        ('sunday', 'Sunday'),
    ], string='Weekly Off Day', default='sunday',
        help='Generate Attendance automatically marks this weekday as a Holiday for everyone.')

    @api.depends('reema_hr_shift_start', 'reema_hr_shift_end',
                 'reema_hr_half_time_start', 'reema_hr_half_time_end')
    def _compute_hours_per_day(self):
        for company in self:
            shift_span = company.reema_hr_shift_end - company.reema_hr_shift_start
            break_span = company.reema_hr_half_time_end - company.reema_hr_half_time_start
            company.reema_hr_hours_per_day = max(0.0, shift_span - max(0.0, break_span))

    def _get_working_days_in_month(self, year, month):
        """Calendar days in the given month minus the weekly off day and any
        public holidays — the same rule Generate Attendance uses to decide
        which days are holidays. Used as the divisor for daily/hourly pay
        rates so a Sunday-heavy or holiday-heavy month doesn't understate an
        employee's per-day rate. Independent of whether attendance has
        actually been generated for that month yet."""
        self.ensure_one()
        last_day = calendar.monthrange(year, month)[1]
        date_from = datetime.date(year, month, 1)
        date_to = datetime.date(year, month, last_day)
        weekly_off_index = WEEKDAY_INDEX.get(self.reema_hr_weekly_off_day, 6)
        overrides = {
            row.date: row.status
            for row in self.env['reema.hr.public.holiday'].search([
                ('company_id', '=', self.id),
                ('date', '>=', date_from), ('date', '<=', date_to),
            ])
        }
        working_days = 0
        current = date_from
        while current <= date_to:
            override = overrides.get(current)
            is_holiday = (override == 'holiday') or (
                override is None and current.weekday() == weekly_off_index
            )
            if not is_holiday:
                working_days += 1
            current += datetime.timedelta(days=1)
        return working_days
