from odoo import api, models


class ReportBoxPackingList(models.AbstractModel):
    # HTML preview report, same pattern as the existing Packing List/MO/
    # Piece Rate reports: report_type qweb-html, opened in a new tab via
    # action_print_box_packing_list(), no in-page toolbar (user prints with
    # Ctrl+P).
    #
    # Laid out like the existing Packing List: identical consecutive
    # cartons get merged into ONE printed row with a carton-number range
    # (e.g. "016-030"), not one block per physical box — a real container
    # shipment can run into hundreds of boxes, and most of them are
    # identical runs (same size, same contents) except for the odd mixed
    # or smaller-last box. Only where a box's contents/size actually change
    # does a new row start.
    _name = 'report.reema_mrp.report_box_packing_list'
    _description = 'Box Packing List Report'

    def _reema_qty_str(self, value):
        # Packed quantities are always whole units (balls aren't split) —
        # trimmed the same way REPORTS.md's float convention does, so a
        # genuine fraction would still render sanely if it ever occurred.
        return ('%.6f' % (value or 0.0)).rstrip('0').rstrip('.')

    def _reema_box_rows(self, box_packing_list):
        """One row per carton run — each run record already covers however
        many identical physical boxes it represents (carton_qty) and already
        carries its own box-number range (carton_range), so this just reads
        the runs in order; no cross-record grouping needed."""
        rows = []
        for box in box_packing_list.box_ids.sorted(lambda b: (b.sequence, b.id)):
            count = box.carton_qty or 0
            articles = [{
                'order': line.article_id.invoice_id.client_order_number or line.article_id.invoice_id.name,
                'client_sku': line.client_sku,
                'description': line.description,
                'sample_color': line.sample_color,
                'size': line.size,
                'qty_per_carton': self._reema_qty_str(line.qty),
                'qty_total': self._reema_qty_str(line.qty * count),
            } for line in box.line_ids]
            rows.append({
                'carton_range': box.carton_range,
                'carton_count': count,
                'carton_size': box.carton_size,
                'carton_weight': self._reema_qty_str(box.carton_weight),
                'articles': articles,
            })
        return rows

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['reema.box.packing.list'].browse(docids)
        rows_map = {pl.id: self._reema_box_rows(pl) for pl in docs}
        return {
            'doc_ids': docids,
            'doc_model': 'reema.box.packing.list',
            'docs': docs,
            'rows_map': rows_map,
        }
