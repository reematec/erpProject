from odoo import fields, models


class ReemaHrPublicHoliday(models.Model):
    _name = 'reema.hr.public.holiday'
    _description = 'Attendance Calendar Override'
    _order = 'date'

    date = fields.Date(string='Date', required=True)
    status = fields.Selection([
        ('holiday', 'Public Holiday'),
        ('working', 'Working Day'),
    ], string='Status', required=True, default='holiday',
        help='Public Holiday: everyone gets Holiday attendance on this date, regardless of weekday. '
             'Working Day: forces a normally weekly-off date (e.g. Sunday) to be generated as a working day instead — '
             'use this for day swaps, e.g. working Sunday in exchange for a Saturday off.')
    name = fields.Char(
        string='Description', required=True,
        help='E.g. "Independence Day", or "Worked instead of Sat 15 — see swap".',
    )
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)

    _sql_constraints = [
        ('date_uniq', 'unique(date, company_id)', 'A calendar override for this date is already defined.'),
    ]
