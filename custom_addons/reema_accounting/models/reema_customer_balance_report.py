from odoo import api, models


class ReportCustomerBalance(models.AbstractModel):
    _name = 'report.reema_accounting.report_customer_balance'
    _description = 'Customer Balance Summary Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['reema.customer.balance'].browse(docids).sorted('account_code')
        return {
            'doc_ids': docids,
            'doc_model': 'reema.customer.balance',
            'docs': docs,
            'total_balance': sum(docs.mapped('balance')),
            'company': self.env.company,
        }
