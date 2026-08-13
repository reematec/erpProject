from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    reema_hr_shift_start = fields.Float(
        string='Shift Start Time', default=9.0,
        help='Expected daily start time. Check-ins after this time (plus the grace period) are marked late.',
    )
    reema_hr_grace_minutes = fields.Integer(
        string='Attendance Grace Period (minutes)', default=10,
        help='Minutes after shift start before lateness starts counting toward a deduction.',
    )
    reema_hr_hours_per_day = fields.Float(
        string='Standard Hours per Day', default=8.0,
        help='Used to derive an hourly late-deduction rate: Monthly Salary ÷ calendar days in the '
             'attendance month ÷ this value.',
    )
    reema_hr_standard_days_per_month = fields.Integer(
        string='Standard Working Days per Month', default=26,
        help='Used to derive each employee\'s daily rate from their monthly salary.',
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
