from odoo import _, fields, models


class AccountMoveWipExt(models.Model):
    _inherit = 'account.move'

    # Set only on the WIP journal entries created from Material Issuance/
    # Return below — lets a later phase (WIP -> Finished Goods) find
    # everything debited to a specific batch's WIP by a real FK, instead of
    # string-matching the ref field.
    reema_production_order_id = fields.Many2one(
        'reema.production.order', string='Production Order', readonly=True,
    )


class ReemaMaterialIssuanceWipCosting(models.Model):
    _inherit = 'reema.material.issuance'

    def _reema_post_wip_entry(self, qty, direction, ref_label):
        """Dr WIP / Cr Raw Material on issue; the reverse on return.

        Valued at the material's current cost (product.standard_price) —
        Odoo already runs real-time weighted-average costing on this
        category (property_cost_method='average', property_valuation=
        'real_time', confirmed live on 'Raw Materials'/etc.), so there's no
        need to build a separate running-average tracker: standard_price
        already IS the running average this whole costing approach agreed
        on, maintained automatically by Odoo itself from every GRN receipt.

        Known gap, not fixed here: standard_price is set from the GRN/PO
        rate at goods-receipt time. A later price correction on the Bill
        (see reema_purchase/account_move_ext.py) adjusts the Raw Material
        GL balance correctly but does NOT feed back into this valuation
        layer — so standard_price can lag the vendor's real negotiated
        price until the next GRN receipt. Separate fix if it matters enough
        to chase; not blocking for WIP posting itself.
        """
        self.ensure_one()
        product = self.product_id
        categ = product.categ_id
        material_account = categ.property_stock_valuation_account_id
        wip_account = self.env['account.account'].search([('code', '=', '1-1-7-03')], limit=1)
        if not material_account or not wip_account:
            self._message_log(body=_(
                'WIP entry skipped for %(product)s — missing %(what)s account.'
            ) % {
                'product': product.display_name,
                'what': 'stock valuation' if not material_account else 'Work In Progress (1-1-7-03)',
            })
            return False
        amount = qty * product.standard_price
        if not amount:
            return False
        journal = self.env['account.journal'].sudo().search(
            [('code', '=', 'STK'), ('company_id', '=', self.env.company.id)], limit=1
        )
        if not journal:
            return False
        if direction == 'issue':
            debit_account, credit_account = wip_account, material_account
        else:
            debit_account, credit_account = material_account, wip_account
        label = '%s — %s' % (ref_label, product.display_name)
        move = self.env['account.move'].sudo().create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': fields.Date.context_today(self),
            'ref': ref_label,
            'reema_production_order_id': self.production_order_id.id if self.production_order_id else False,
            'line_ids': [
                (0, 0, {'account_id': debit_account.id, 'name': label, 'debit': amount, 'credit': 0.0}),
                (0, 0, {'account_id': credit_account.id, 'name': label, 'debit': 0.0, 'credit': amount}),
            ],
        })
        move.sudo().action_post()
        self._message_log(body=_(
            'WIP entry posted — %(label)s: %(qty).3f x %(cost).2f = PKR %(amount).2f (%(dir)s).'
        ) % {
            'label': label, 'qty': qty, 'cost': product.standard_price,
            'amount': amount, 'dir': 'to WIP' if direction == 'issue' else 'back from WIP',
        })
        return move
