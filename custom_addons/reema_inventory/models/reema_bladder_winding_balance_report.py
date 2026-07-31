from odoo import api, models


class ReportBladderWindingBalance(models.AbstractModel):
    _name = 'report.reema_inventory.report_bladder_winding_balance'
    _description = 'Bladder Winding Balance Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['reema.bladder.winding.balance'].browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': 'reema.bladder.winding.balance',
            'docs': docs,
            'total_issued': sum(docs.mapped('qty_issued')),
            'total_wound': sum(docs.mapped('qty_wound')),
            'total_damaged': sum(docs.mapped('qty_damaged')),
            'total_lost': sum(docs.mapped('qty_lost')),
            'total_outstanding': sum(docs.mapped('qty_outstanding')),
            'company': self.env.company,
        }
