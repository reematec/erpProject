import calendar
import datetime

from odoo import _, fields, models
from odoo.exceptions import UserError

from ..models.reema_hr_payslip import MONTH_SELECTION


class ReemaHrPayslipGenerateWizard(models.TransientModel):
    _name = 'reema.hr.payslip.generate.wizard'
    _description = 'Bulk-Generate Payslips'

    period_month = fields.Selection(
        MONTH_SELECTION, string='Month', required=True,
        default=lambda self: str(fields.Date.context_today(self).month),
    )
    period_year = fields.Integer(
        string='Year', required=True,
        default=lambda self: fields.Date.context_today(self).year,
    )

    def action_generate(self):
        self.ensure_one()
        month = int(self.period_month)
        last_day = calendar.monthrange(self.period_year, month)[1]
        date_from = datetime.date(self.period_year, month, 1)
        date_to = datetime.date(self.period_year, month, last_day)

        employees = self.env['hr.employee']._get_active_for_period(date_from, date_to)
        if not employees:
            raise UserError(_('No active employees found for this month.'))

        Payslip = self.env['reema.hr.payslip']
        existing_employee_ids = set(Payslip.search([
            ('employee_id', 'in', employees.ids),
            ('period_month', '=', self.period_month),
            ('period_year', '=', self.period_year),
        ]).mapped('employee_id.id'))

        to_create = [
            {'employee_id': employee.id, 'period_month': self.period_month, 'period_year': self.period_year}
            for employee in employees
            if employee.id not in existing_employee_ids
        ]
        if to_create:
            Payslip.create(to_create)

        # Return the normal Payslips list rather than a one-off view hard-scoped
        # to just this batch: that domain isn't shown as a removable search chip,
        # so it silently hides every other payslip and can look like the rest
        # went missing (see the same issue already fixed on the Attendance wizard).
        return self.env['ir.actions.actions']._for_xml_id('reema_hr.action_reema_hr_payslip')
