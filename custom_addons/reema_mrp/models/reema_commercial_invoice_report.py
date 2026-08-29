from odoo import api, models


class ReportCommercialInvoice(models.AbstractModel):
    # HTML preview report, same pattern as the Packing List report: report_type
    # qweb-html, opened in a new tab via action_print_commercial_invoice(), no
    # in-page toolbar (user prints with Ctrl+P).
    _name = 'report.reema_mrp.report_commercial_invoice'
    _description = 'Commercial Invoice Report'

    # Printed label per Sampling Blueprint ball_type — matches the real
    # document's footer breakdown ("13050 PCS FOOTBALLS", "330 PCS
    # DODGEBALLS"). Falls back to the line's own description for any type
    # not in this map, or that isn't set at all.
    _BALL_TYPE_LABELS = {
        'football': 'FOOTBALLS',
        'futsal': 'FUTSAL BALLS',
        'handball': 'HANDBALLS',
        'volleyball': 'VOLLEYBALLS',
        'freestyle': 'FREESTYLE BALLS',
        'training': 'TRAINING BALLS',
        'dodgeball': 'DODGEBALLS',
    }

    def _reema_qty_str(self, value):
        return ('%.6f' % (value or 0.0)).rstrip('0').rstrip('.')

    def _reema_commodity_breakdown(self, ci):
        """(list of {'label', 'qty'} in first-seen order, list of distinct
        HS codes present) — the real document groups shipped quantity by
        commodity type, and lists whichever HS code(s) apply separately,
        not necessarily one per commodity (a minor commodity can go without
        one, same as the real document does for dodgeballs)."""
        groups = []
        index_by_type = {}
        hs_codes = []
        for line in ci.line_ids:
            ball_type = line.sample_id.ball_type
            label = self._BALL_TYPE_LABELS.get(ball_type)
            if not label:
                first_word = (line.description or 'ITEMS').split()[0]
                label = f'{first_word.upper()}S'
            if ball_type not in index_by_type:
                index_by_type[ball_type] = len(groups)
                groups.append({'label': label, 'qty': 0.0})
            groups[index_by_type[ball_type]]['qty'] += line.qty
            hs = line.sample_id.hs_code
            if hs and hs not in hs_codes:
                hs_codes.append(hs)
        for grp in groups:
            grp['qty'] = self._reema_qty_str(grp['qty'])
        return groups, hs_codes

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['reema.commercial.invoice'].browse(docids)
        grouped_map = {}
        breakdown_map = {}
        for ci in docs:
            groups = []
            index_by_invoice = {}
            for line in ci.line_ids:
                inv = line.invoice_id
                if inv.id not in index_by_invoice:
                    index_by_invoice[inv.id] = len(groups)
                    groups.append({'invoice': inv, 'lines': []})
                groups[index_by_invoice[inv.id]]['lines'].append({
                    'client_sku': line.client_sku or line.sample_code,
                    'description': line.description,
                    'sample_color': line.sample_color,
                    'size': line.size,
                    'qty': self._reema_qty_str(line.qty),
                    'price_unit': f'{line.price_unit:,.2f}',
                    'amount': f'{line.amount:,.2f}',
                })
            grouped_map[ci.id] = groups
            commodity_groups, hs_codes = self._reema_commodity_breakdown(ci)
            breakdown_map[ci.id] = {'groups': commodity_groups, 'hs_codes': hs_codes}
        return {
            'doc_ids': docids,
            'doc_model': 'reema.commercial.invoice',
            'docs': docs,
            'grouped_map': grouped_map,
            'breakdown_map': breakdown_map,
        }
