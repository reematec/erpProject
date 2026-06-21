from odoo import api, models


class ReportPieceRateList(models.AbstractModel):
    _name = 'report.reema_mrp.report_piece_rate_list'
    _description = 'Piece Rate List Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        Rate = self.env['reema.piece.rate']
        rates = Rate.search([])  # active only by default; _order = workcenter_id, work_type
        groups = {}
        for r in rates:
            groups.setdefault(r.workcenter_id, Rate.browse())
            groups[r.workcenter_id] |= r
        grouped = sorted(groups.items(), key=lambda kv: (kv[0].name or '').lower())
        return {
            'grouped': grouped,
            'company': self.env.company,
        }
