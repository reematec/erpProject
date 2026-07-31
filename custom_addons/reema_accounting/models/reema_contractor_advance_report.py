from odoo import api, models


class ReportContractorAdvanceOverview(models.AbstractModel):
    _name = 'report.reema_accounting.report_contractor_advance_overview'
    _description = 'Contractor Advances Overview Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['reema.contractor.advance'].browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': 'reema.contractor.advance',
            'docs': docs,
            'total_amount': sum(docs.mapped('amount')),
            'company': self.env.company,
        }
