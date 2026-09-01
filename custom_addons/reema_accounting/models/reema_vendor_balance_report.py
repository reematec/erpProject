from odoo import api, models


class ReportVendorBalance(models.AbstractModel):
    _name = 'report.reema_accounting.report_vendor_balance'
    _description = 'Vendor Balance Summary Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['reema.vendor.balance'].browse(docids).sorted('account_code')
        return {
            'doc_ids': docids,
            'doc_model': 'reema.vendor.balance',
            'docs': docs,
            'total_debit': sum(docs.mapped('debit')),
            'total_credit': sum(docs.mapped('credit')),
            'company': self.env.company,
        }
