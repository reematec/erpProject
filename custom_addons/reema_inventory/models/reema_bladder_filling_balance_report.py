from odoo import api, models


class ReportBladderFillingBalance(models.AbstractModel):
    _name = 'report.reema_inventory.report_bladder_filling_balance'
    _description = 'Bladder Filling Balance Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['reema.bladder.filling.balance'].browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': 'reema.bladder.filling.balance',
            'docs': docs,
            'total_issued': sum(docs.mapped('qty_issued')),
            'total_filled': sum(docs.mapped('qty_filled')),
            'total_damaged': sum(docs.mapped('qty_damaged')),
            'total_lost': sum(docs.mapped('qty_lost')),
            'total_outstanding': sum(docs.mapped('qty_outstanding')),
            'company': self.env.company,
        }
