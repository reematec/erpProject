from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

WEEKDAY_INDEX = {
    'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
    'friday': 4, 'saturday': 5, 'sunday': 6,
}


class ReemaHrAttendanceGenerateWizard(models.TransientModel):
    _name = 'reema.hr.attendance.generate.wizard'
    _description = 'Bulk-Generate Attendance'

    date_from = fields.Date(string='From', required=True, default=fields.Date.context_today)
    date_to = fields.Date(string='To', required=True, default=fields.Date.context_today)

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_from > rec.date_to:
                raise UserError(_('"From" date must be before or equal to "To" date.'))

    def action_generate(self):
        self.ensure_one()
        company = self.env.company
        weekly_off_index = WEEKDAY_INDEX.get(company.reema_hr_weekly_off_day, 6)
        overrides = {
            row.date: row.status
            for row in self.env['reema.hr.public.holiday'].search([
                ('date', '>=', self.date_from), ('date', '<=', self.date_to),
            ])
        }

        employees = self.env['hr.employee']._get_active_for_period(self.date_from, self.date_to)
        if not employees:
            raise UserError(_('No active employees found for this period.'))

        Attendance = self.env['reema.hr.attendance']
        existing = Attendance.search([
            ('employee_id', 'in', employees.ids),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
        ])
        existing_keys = {(rec.employee_id.id, rec.date) for rec in existing}
        default_check_in = company.reema_hr_shift_start

        to_create = []
        current = self.date_from
        while current <= self.date_to:
            override = overrides.get(current)
            is_holiday = (override == 'holiday') or (
                override is None and current.weekday() == weekly_off_index
            )
            for employee in employees:
                if employee.reema_join_date and employee.reema_join_date > current:
                    continue
                if employee.departure_date and employee.departure_date < current:
                    continue
                if (employee.id, current) in existing_keys:
                    continue
                vals = {'employee_id': employee.id, 'date': current}
                if is_holiday:
                    vals['state'] = 'holiday'
                else:
                    vals['state'] = 'present'
                    vals['check_in'] = default_check_in
                to_create.append(vals)
            current += timedelta(days=1)

        if to_create:
            Attendance.create(to_create)

        # Return the normal Attendance list rather than a one-off view hard-scoped
        # to just this batch's date range: that domain isn't shown as a removable
        # search chip, so it silently hides every other date and looks like older
        # attendance was wiped when it's only ever been filtered out of view.
        return self.env['ir.actions.actions']._for_xml_id('reema_hr.action_reema_hr_attendance')
