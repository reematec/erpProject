from odoo import api, models


class ReportContractorBalance(models.AbstractModel):
    _name = 'report.reema_accounting.report_contractor_balance'
    _description = 'Contractor Balance Summary Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['reema.contractor.balance'].browse(docids).sorted('account_code')
        return {
            'doc_ids': docids,
            'doc_model': 'reema.contractor.balance',
            'docs': docs,
            'total_balance': sum(docs.mapped('balance')),
            'company': self.env.company,
        }
