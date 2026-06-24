from datetime import datetime
from odoo import models, fields, api, _


class ReemaStockLedger(models.AbstractModel):
    _name = 'reema.stock.ledger'
    _description = 'Reema Stock Ledger'

    # States that represent open (not yet executed) forecast movements.
    _OPEN_STATES = ('assigned', 'partially_available', 'confirmed', 'waiting')

    @api.model
    def get_ledger_lines(self, product_id, is_template, warehouse_id,
                         opening_date=None):
        Warehouse = self.env['stock.warehouse']
        Location = self.env['stock.location']
        Move = self.env['stock.move']

        warehouse = Warehouse.browse(warehouse_id)
        stock_locs = Location.search([('id', 'child_of', warehouse.lot_stock_id.id)])
        loc_ids = set(stock_locs.ids)

        if is_template:
            template = self.env['product.template'].browse(product_id)
            products = template.product_variant_ids
            product_name = template.display_name
            uom_name = template.uom_id.name
        else:
            products = self.env['product.product'].browse(product_id)
            product_name = products.display_name
            uom_name = products.uom_id.name

        # Current physical stock — the anchor the whole ledger reconciles to.
        qty_on_hand = sum(
            p.with_context(warehouse=warehouse.id).qty_available for p in products
        )

        mf = Move._fields
        has_raw = 'raw_material_production_id' in mf
        has_prod = 'production_id' in mf
        has_purchase = 'purchase_line_id' in mf
        has_sale = 'sale_line_id' in mf

        # 1) DONE moves = actual history. Each is one row; together they net to
        #    qty_on_hand. We list them individually and rewind the opening
        #    balance with them, so "opening as of date D" = real stock at D.
        done_moves = Move.search([
            ('product_id', 'in', products.ids),
            ('state', '=', 'done'),
            '|',
            ('location_id', 'in', list(loc_ids)),
            ('location_dest_id', 'in', list(loc_ids)),
        ], order='date asc')

        entries = []
        for move in done_moves:
            in_src = move.location_id.id in loc_ids
            in_dst = move.location_dest_id.id in loc_ids
            if in_src == in_dst:
                continue
            qty = move.quantity
            if not qty:
                continue
            entries.append({
                'sort_date': move.date,
                'date': move.date.strftime('%d/%m/%Y') if move.date else '—',
                'description': self._describe_actual(
                    move, in_dst, has_raw, has_prod, has_purchase, has_sale),
                'is_incoming': in_dst,
                'qty': qty,
                'ledger_state': 'done',
                'is_done': True,
            })

        # 2) OPEN moves = forecast. Grouped by source document so one MO/PO/SO is
        #    a single line, de-duplicated against the fulfilment plumbing moves
        #    (issuance / in-production consumption) it spawns.
        open_moves = Move.search([
            ('product_id', 'in', products.ids),
            ('state', 'in', self._OPEN_STATES),
            '|',
            ('location_id', 'in', list(loc_ids)),
            ('location_dest_id', 'in', list(loc_ids)),
        ], order='date asc')

        groups = {}
        for move in open_moves:
            in_src = move.location_id.id in loc_ids
            in_dst = move.location_dest_id.id in loc_ids
            if in_src == in_dst:
                continue
            is_incoming = in_dst

            key, desc_main = self._classify_move(
                move, is_incoming, has_raw, has_prod, has_purchase, has_sale
            )
            if key is None:
                continue

            g = groups.get(key)
            if not g:
                g = {
                    'qty': 0.0,
                    'dates': [],
                    'states': set(),
                    'is_incoming': is_incoming,
                    'desc_main': desc_main,
                }
                groups[key] = g
            g['qty'] += move.product_uom_qty
            if move.date:
                g['dates'].append(move.date)
            g['states'].add(move.state)

        for g in groups.values():
            if not g['qty']:
                continue
            state_label, ledger_state = self._aggregate_state(g['states'])
            sort_date = min(g['dates']) if g['dates'] else None
            entries.append({
                'sort_date': sort_date,
                'date': sort_date.strftime('%d/%m/%Y') if sort_date else '—',
                'description': f"{g['desc_main']} [{state_label}]",
                'is_incoming': g['is_incoming'],
                'qty': g['qty'],
                'ledger_state': ledger_state,
                'is_done': False,
            })

        # Effective opening date: default to the earliest movement so the whole
        # card is shown.
        opening_dt = fields.Datetime.to_datetime(opening_date) if opening_date else None
        all_dates = [e['sort_date'] for e in entries if e['sort_date']]
        if opening_dt is None:
            opening_dt = min(all_dates) if all_dates else fields.Datetime.now()

        # Opening balance: start from current on-hand, then for every entry dated
        # ON/AFTER the opening date REWIND its effect (done rows already baked
        # into on-hand; open rows are future). Entries dated BEFORE the opening
        # date stay folded into the opening position and are not listed. This
        # reconciles exactly: opening + listed deltas == on_hand + forecast.
        opening_balance = qty_on_hand
        in_window = []
        for e in entries:
            if e['sort_date'] and e['sort_date'] < opening_dt:
                if e['is_done']:
                    # Before the window: leave its effect inside the opening.
                    continue
                # Backlog forecast before the window folds into opening.
                opening_balance += e['qty'] if e['is_incoming'] else -e['qty']
            else:
                if e['is_done']:
                    # Rewind this actual out of on-hand to recover the opening,
                    # then show it as a row.
                    opening_balance += -e['qty'] if e['is_incoming'] else e['qty']
                in_window.append(e)

        in_window.sort(key=lambda e: (e['sort_date'] or datetime.max,
                                      0 if e['is_done'] else 1,
                                      e['description']))

        lines = []
        balance = opening_balance
        for e in in_window:
            if e['is_incoming']:
                balance += e['qty']
                qty_in, qty_out = e['qty'], None
            else:
                balance -= e['qty']
                qty_in, qty_out = None, e['qty']
            lines.append({
                'date': e['date'],
                'description': e['description'],
                'qty_in': qty_in,
                'qty_out': qty_out,
                'balance': balance,
                'ledger_state': e['ledger_state'],
            })

        return {
            'product_name': product_name,
            'uom_name': uom_name,
            'on_hand': qty_on_hand,
            'opening_balance': opening_balance,
            'opening_date': opening_dt.strftime('%Y-%m-%d'),
            'closing_balance': balance,
            'lines': lines,
        }

    def _describe_actual(self, move, is_incoming,
                         has_raw, has_prod, has_purchase, has_sale):
        """Human-readable description for a completed (done) move."""
        if has_purchase and move.purchase_line_id:
            po = move.purchase_line_id.order_id
            desc = f"Receipt {po.name}"
            if po.partner_id:
                desc += f" from {po.partner_id.display_name}"
        elif has_prod and move.production_id:
            desc = f"Produced by {move.production_id.name}"
        elif has_raw and move.raw_material_production_id:
            desc = f"Consumed by {move.raw_material_production_id.name}"
        elif has_sale and move.sale_line_id:
            so = move.sale_line_id.order_id
            desc = f"Delivered {so.name}"
            if so.partner_id:
                desc += f" to {so.partner_id.display_name}"
        elif move.picking_id:
            desc = move.picking_id.name
            if move.picking_id.picking_type_id:
                desc += f" — {move.picking_id.picking_type_id.name}"
        else:
            verb = "Received" if is_incoming else "Issued"
            desc = f"{verb} {move.origin}" if move.origin else (
                "Stock Receipt" if is_incoming else "Stock Issue")
        return f"{desc} [Done]"

    def _classify_move(self, move, is_incoming,
                       has_raw, has_prod, has_purchase, has_sale):
        """Return (group_key, base_description) for a forecast-relevant move,
        or (None, None) for a fulfilment/plumbing move that must be ignored."""
        if is_incoming:
            if has_purchase and move.purchase_line_id:
                po = move.purchase_line_id.order_id
                desc = f"Purchase {po.name}"
                if po.partner_id:
                    desc += f" from {po.partner_id.display_name}"
                return ('po', po.id), desc
            if has_prod and move.production_id:
                mo = move.production_id
                return ('mo_in', mo.id), f"Produced by {mo.name}"
            return None, None

        # Outgoing
        if has_raw and move.raw_material_production_id:
            mo = move.raw_material_production_id
            desc = f"Required by {mo.name}"
            if mo.product_id:
                desc += f" — {mo.product_id.display_name}"
            return ('mo_out', mo.id), desc
        if has_sale and move.sale_line_id:
            so = move.sale_line_id.order_id
            desc = f"Delivery {so.name}"
            if so.partner_id:
                desc += f" to {so.partner_id.display_name}"
            return ('so', so.id), desc
        return None, None

    def _aggregate_state(self, states):
        """Collapse the states of a document's moves into one label."""
        if states <= {'assigned'}:
            return 'Reserved', 'reserved'
        if 'assigned' in states or 'partially_available' in states:
            return 'Partly Reserved', 'partial'
        return 'Demand', 'demand'


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def action_product_tmpl_forecast_report(self):
        return {
            'type': 'ir.actions.client',
            'tag': 'reema_stock_ledger',
            'name': _('Stock Ledger'),
            'context': {
                'active_id': self.id,
                'active_model': 'product.template',
            },
        }


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def action_product_forecast_report(self):
        return {
            'type': 'ir.actions.client',
            'tag': 'reema_stock_ledger',
            'name': _('Stock Ledger'),
            'context': {
                'active_id': self.id,
                'active_model': 'product.product',
            },
        }
