from odoo import models, fields, api
from odoo.exceptions import UserError
from odoo.tools import float_round


PRODUCT_GROUP_SELECTION = [
    ('raw_material', 'Raw Material'),
    ('packaging',    'Packaging'),
    ('sfg',          'Semi-Finished Good'),
    ('finished_good','Finished Good'),
]


class ProductTemplateReema(models.Model):
    _inherit = 'product.template'

    product_group = fields.Selection(
        PRODUCT_GROUP_SELECTION,
        string='Product Group',
        required=True,
        index=True,
        help='Classifies the product for filtering and access control across modules.',
    )

    _PRODUCT_GROUP_NOTE = (
        'Used for filtering products in BOMs, work orders, and work center rules. '
        'Required — cannot save without it. '
        'Values are fixed selections defined in the system (not configurable from the UI).'
    )
    _CATEG_NOTE = (
        'Controls journal accounts for stock moves (COGS, income, inventory valuation) '
        'and costing method (AVCO / FIFO / Standard). '
        'Values come from Inventory → Configuration → Product Categories.'
    )

    product_group_note = fields.Char(
        compute='_compute_field_notes',
        default=lambda self: self._PRODUCT_GROUP_NOTE,
        string=' ',
    )
    categ_note = fields.Char(
        compute='_compute_field_notes',
        default=lambda self: self._CATEG_NOTE,
        string=' ',
    )

    def _compute_field_notes(self):
        for rec in self:
            rec.product_group_note = self._PRODUCT_GROUP_NOTE
            rec.categ_note = self._CATEG_NOTE

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env['ir.sequence']
        for vals in vals_list:
            if not vals.get('product_group'):
                raise UserError(
                    'Product Group is required.\n\n'
                    'Select Raw Material, Packaging, Semi-Finished Good, '
                    'or Finished Good before saving.'
                )
            if not vals.get('default_code'):
                vals['default_code'] = seq.next_by_code('reema.product') or '/'
        return super().create(vals_list)

    @api.depends('name')
    def _compute_display_name(self):
        """Return plain product name — suppress Odoo's default [reference] prefix."""
        for template in self:
            template.display_name = template.name or False

    @api.model
    def _assign_missing_product_references(self):
        """Backfill sequence-based references for products created before this feature."""
        seq = self.env['ir.sequence']
        products = self.search([('default_code', '=', False)])
        for product in products:
            product.default_code = seq.next_by_code('reema.product')


class ProductProductReema(models.Model):
    _inherit = 'product.product'

    @api.depends('name', 'product_tmpl_id')
    def _compute_display_name(self):
        """Return plain product name — suppress Odoo's default [reference] prefix."""
        for product in self:
            product.display_name = product.name or False

    def _reema_fulfilment_move_ids(self):
        """Stock moves that merely FULFIL an MO raw-material requirement, i.e.
        the reema material-issuance and return moves. These move the same
        material that the standard MRP requirement move
        (raw_material_production_id) already represents, so counting them again
        double-counts demand in the Forecasted quantity. Returns their ids so
        they can be excluded from the forecast computation (this keeps the
        Inventory > Products 'Forecasted' column in sync with the Stock Ledger).
        """
        if not self.ids:
            return []
        IssuanceLine = self.env['reema.material.issuance.line'].sudo()
        ReturnLine = self.env['reema.material.return.line'].sudo()
        issuance_moves = IssuanceLine.search(
            [('move_id.product_id', 'in', self.ids)]).mapped('move_id')
        return_moves = ReturnLine.search(
            [('move_id.product_id', 'in', self.ids)]).mapped('move_id')
        return list(set(issuance_moves.ids) | set(return_moves.ids))

    def _compute_quantities_dict(self, lot_id, owner_id, package_id,
                                 from_date=False, to_date=False):
        res = super()._compute_quantities_dict(
            lot_id, owner_id, package_id, from_date, to_date)

        excluded_ids = self._reema_fulfilment_move_ids()
        if not excluded_ids:
            return res

        Move = self.env['stock.move'].with_context(active_test=False)
        _, domain_move_in_loc, domain_move_out_loc = self._get_domain_locations()
        todo_states = ('waiting', 'confirmed', 'assigned', 'partially_available')

        date_domain = []
        if from_date:
            date_domain.append(('date', '>=', from_date))
        if to_date:
            date_domain.append(('date', '<=', to_date))

        base = [
            ('product_id', 'in', self.ids),
            ('id', 'in', excluded_ids),
            ('state', 'in', todo_states),
        ] + date_domain
        in_adj = {
            p.id: q for p, q in Move._read_group(
                base + domain_move_in_loc, ['product_id'], ['product_qty:sum'])
        }
        out_adj = {
            p.id: q for p, q in Move._read_group(
                base + domain_move_out_loc, ['product_id'], ['product_qty:sum'])
        }

        for product in self:
            pid = product.id
            opid = product._origin.id
            if pid not in res:
                continue
            rounding = product.uom_id.rounding
            inc = res[pid]['incoming_qty'] - float_round(
                in_adj.get(opid, 0.0), precision_rounding=rounding)
            out = res[pid]['outgoing_qty'] - float_round(
                out_adj.get(opid, 0.0), precision_rounding=rounding)
            res[pid]['incoming_qty'] = inc
            res[pid]['outgoing_qty'] = out
            res[pid]['virtual_available'] = float_round(
                res[pid]['qty_available'] + inc - out, precision_rounding=rounding)
        return res
