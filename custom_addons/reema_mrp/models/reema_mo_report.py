from odoo import api, models


class ReportManufacturingOrder(models.AbstractModel):
    # HTML preview report for one or more Manufacturing Orders. Mirrors the piece
    # rate / BOM reports: report_type qweb-html, opened in a new tab via an
    # act_url, with an in-page screen-only Print/Close toolbar.
    _name = 'report.reema_mrp.report_mo'
    _description = 'Manufacturing Order Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['mrp.production'].browse(docids)
        # Build consumed qty per (mo, product) from backflush moves.
        # Backflush creates independent stock.move records (not updating move_raw_ids)
        # linked only via origin = '{mo.name} / {wo.name} / {batch.name}'.
        consumed_map = {}
        for mo in docs:
            # Use only moves from EXISTING batch entries — orphan moves
            # (from batches that were later deleted) are excluded.
            batches = self.env['reema.wo.batch.entry'].search([
                ('workorder_id.production_id', '=', mo.id)
            ])
            valid_origins = [
                f'{mo.name} / {b.workorder_id.name} / {b.name}'
                for b in batches
            ]
            by_product = {}
            if valid_origins:
                moves = self.env['stock.move'].search([
                    ('origin', 'in', valid_origins),
                    ('state', 'not in', ['draft', 'cancel']),
                ])
                for m in moves:
                    by_product[m.product_id.id] = (
                        by_product.get(m.product_id.id, 0.0) + m.quantity
                    )
            consumed_map[mo.id] = by_product
        return {
            'doc_ids': docids,
            'doc_model': 'mrp.production',
            'docs': docs,
            'company': self.env.company,
            'consumed_map': consumed_map,
        }
