from odoo import api, models


class ReportPayrollBalance(models.AbstractModel):
    _name = 'report.reema_hr.report_payroll_balance'
    _description = 'Payroll Balance Summary Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['reema.payroll.balance'].browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': 'reema.payroll.balance',
            'docs': docs,
            'total_balance': sum(docs.mapped('balance')),
            'company': self.env.company,
        }
