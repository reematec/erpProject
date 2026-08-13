import calendar

from odoo import _, api, fields, models
from odoo.exceptions import UserError


def _default_date_from(self):
    today = fields.Date.context_today(self)
    return today.replace(day=1)


def _default_date_to(self):
    today = fields.Date.context_today(self)
    last_day = calendar.monthrange(today.year, today.month)[1]
    return today.replace(day=last_day)


class ReemaHrPayslipGenerateWizard(models.TransientModel):
    _name = 'reema.hr.payslip.generate.wizard'
    _description = 'Bulk-Generate Payslips'

    date_from = fields.Date(string='From', required=True, default=_default_date_from)
    date_to = fields.Date(string='To', required=True, default=_default_date_to)
    employee_ids = fields.Many2many('hr.employee', string='Employees')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'employee_ids' in fields_list:
            date_from = res.get('date_from') or _default_date_from(self)
            date_to = res.get('date_to') or _default_date_to(self)
            res['employee_ids'] = [(6, 0, self.env['hr.employee']._get_active_for_period(date_from, date_to).ids)]
        return res

    @api.onchange('date_from', 'date_to')
    def _onchange_dates(self):
        for rec in self:
            if rec.date_from and rec.date_to:
                rec.employee_ids = self.env['hr.employee']._get_active_for_period(rec.date_from, rec.date_to)

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_from > rec.date_to:
                raise UserError(_('"From" date must be before or equal to "To" date.'))

    def action_generate(self):
        self.ensure_one()
        # Many2many fields silently drop archived (active=False) target records
        # on read unless the reading recordset's own context disables that
        # filter — matters here since a mid-month departure is exactly the
        # case this wizard needs to include.
        employees = self.with_context(active_test=False).employee_ids
        if not employees:
            raise UserError(_('Select at least one employee.'))

        Payslip = self.env['reema.hr.payslip']
        existing_employee_ids = set(Payslip.search([
            ('employee_id', 'in', employees.ids),
            ('date_from', '=', self.date_from),
            ('date_to', '=', self.date_to),
        ]).mapped('employee_id.id'))

        to_create = [
            {'employee_id': employee.id, 'date_from': self.date_from, 'date_to': self.date_to}
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
