from odoo import api, models


class ReportPackingList(models.AbstractModel):
    # HTML preview report, same pattern as MO/Piece Rate: report_type
    # qweb-html, opened in a new tab via action_print_packing_list(), no
    # in-page toolbar (user prints with Ctrl+P).
    _name = 'report.reema_mrp.report_packing_list'
    _description = 'Packing List Report'

    def _reema_qty_str(self, value):
        # Packed quantities are always whole units (balls aren't split) —
        # trimmed the same way REPORTS.md's float convention does, so a
        # genuine fraction would still render sanely if it ever occurred.
        return ('%.6f' % (value or 0.0)).rstrip('0').rstrip('.')

    def _reema_print_rows(self, line):
        """One line's cartons, split into a full-cartons row and a partial-
        last-carton row when it doesn't divide evenly — matches the real
        document, which never blends a partial carton into the full count.
        Carton numbering restarts at 01 for every article (never a running
        count across the whole Packing List). The full-cartons row is
        always shown as a "01-NN" range — even a single full carton — so it
        reads as distinct from the partial row's own single carton number."""
        n = line.carton_qty or 0
        per = line.qty_per_carton or 0
        common = {
            'client_sku': line.client_sku, 'description': line.description,
            'sample_color': line.sample_color, 'size': line.size,
        }
        if n <= 0:
            return [dict(common, carton_range='', qty_per_carton=self._reema_qty_str(per),
                         qty=self._reema_qty_str(line.qty), no_border=False)]
        last = line.carton_last_qty
        is_partial = per > 0 and 0 < last < per
        full_count = (n - 1) if is_partial else n
        rows = []
        if full_count > 0:
            if is_partial:
                carton_range = '01-%02d' % full_count
            else:
                carton_range = '01' if full_count == 1 else '01-%02d' % full_count
            # no_border=True here (not on the partial row below) — Bootstrap
            # draws the line between two rows as the upper row's own
            # bottom border, not the lower row's top border.
            rows.append(dict(common,
                carton_range=carton_range, qty_per_carton=self._reema_qty_str(per),
                qty=self._reema_qty_str(full_count * per), no_border=is_partial,
            ))
        if is_partial:
            # The same article's trailing partial carton, not a new item.
            rows.append(dict(common,
                carton_range='%02d' % n, qty_per_carton=self._reema_qty_str(last),
                qty=self._reema_qty_str(last), no_border=False,
            ))
        return rows

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['reema.packing.list'].browse(docids)
        # Group each Packing List's lines by order, preserving the order
        # they first appear in, and split each line's cartons into print
        # rows — mirrors the real document's layout exactly.
        grouped_map = {}
        for pl in docs:
            groups = []
            index_by_invoice = {}
            for line in pl.line_ids:
                inv = line.invoice_id
                if inv.id not in index_by_invoice:
                    index_by_invoice[inv.id] = len(groups)
                    groups.append({'invoice': inv, 'rows': []})
                groups[index_by_invoice[inv.id]]['rows'].extend(self._reema_print_rows(line))
            grouped_map[pl.id] = groups
        return {
            'doc_ids': docids,
            'doc_model': 'reema.packing.list',
            'docs': docs,
            'grouped_map': grouped_map,
        }
