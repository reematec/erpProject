from odoo import models, fields, api
from odoo.exceptions import UserError


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    responsible_name = fields.Char(related='user_id.name', string='Responsible', readonly=True)
    reema_po_line_ids = fields.One2many('reema.production.order.line', 'mo_id')

    construction_type = fields.Selection([
        ('hs', 'Hand Stitched (HS)'),
        ('ms', 'Machine Stitched (MS)'),
        ('hyb', 'Hybrid (HYB)'),
        ('thb', 'Thermo Bonded (THB)')
    ], string='Construction Type', required=True, default='hyb')
    
    ball_size = fields.Char(string='Ball Size')

    complexity_level = fields.Selection([
        ('standard', 'Standard'),
        ('high', 'High Complexity'),
        ('premium', 'Premium/Pro')
    ], string='Complexity', default='standard')

    # The sampling blueprint for this MO's product. Shown in the form (labelled
    # "Product") instead of the raw product_id so clicking it opens the sample
    # sheet rather than the plain product form — mirrors mrp.bom.sample_id.
    sample_id = fields.Many2one(
        'reema.sampling.blueprint', string='Sample', compute='_compute_sample_id')

    @api.depends('product_id')
    def _compute_sample_id(self):
        Blueprint = self.env['reema.sampling.blueprint']
        for mo in self:
            mo.sample_id = Blueprint.search(
                [('product_tmpl_id', '=', mo.product_id.product_tmpl_id.id)], limit=1
            ) if mo.product_id else False

    ilo_dispatch_count = fields.Integer(compute='_compute_ilo_dispatch_count', string='ILO Dispatches')
    ilo_repair_qty_balls = fields.Integer(compute='_compute_ilo_repair_scrap_qty', string='ILO Repair Balls')
    ilo_scrap_qty = fields.Integer(compute='_compute_ilo_repair_scrap_qty', string='ILO Scrapped Balls')

    has_active_issuance = fields.Boolean(compute='_compute_has_active_issuance')

    extra_material_issuance = fields.Selection([
        ('flexible', 'Allowed'),
        ('warning', 'Allowed with Warning'),
        ('strict', 'Blocked'),
    ], string='Extra Material Issuance', default='warning', required=True)

    def _compute_has_active_issuance(self):
        for rec in self:
            rec.has_active_issuance = bool(
                rec.issuance_ids.filtered(lambda i: i.state != 'cancelled')
            )

    def _compute_ilo_dispatch_count(self):
        for rec in self:
            rec.ilo_dispatch_count = self.env['reema.ilo.dispatch'].search_count([('mo_id', '=', rec.id)])

    def _compute_ilo_repair_scrap_qty(self):
        Dispatch = self.env['reema.ilo.dispatch']
        Scrap = self.env['reema.ilo.qc.scrap']
        for rec in self:
            rec.ilo_repair_qty_balls = sum(Dispatch.search([
                ('mo_id', '=', rec.id), ('dispatch_type', '=', 'repair'),
            ]).mapped('qty_balls'))
            rec.ilo_scrap_qty = sum(Scrap.search([('mo_id', '=', rec.id)]).mapped('qty'))

    def action_view_ilo_dispatches(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'ILO Dispatches',
            'res_model': 'reema.ilo.dispatch',
            'view_mode': 'list,form',
            'domain': [('mo_id', '=', self.id)],
            'context': {'default_mo_id': self.id},
        }

    def action_view_ilo_repairs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'ILO Repair Dispatches',
            'res_model': 'reema.ilo.dispatch',
            'view_mode': 'list,form',
            'domain': [('mo_id', '=', self.id), ('dispatch_type', '=', 'repair')],
        }

    def action_view_ilo_scrap(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'ILO QC Scrap',
            'res_model': 'reema.ilo.qc.scrap',
            'view_mode': 'list',
            'domain': [('mo_id', '=', self.id)],
        }

    def action_print_mo(self):
        # Open the MO HTML preview in a new browser tab (works for a single order
        # from the form, or several selected orders from the list). The user
        # prints with the in-page Print button / Ctrl+P and closes the tab.
        if not self:
            return False
        return {
            'type': 'ir.actions.act_url',
            'url': '/report/html/reema_mrp.report_mo/%s' % ','.join(str(i) for i in self.ids),
            'target': 'new',
        }

    def _check_no_active_issuances(self):
        active = self.env['reema.material.issuance'].search([
            ('production_id', 'in', self.ids),
            ('state', '!=', 'cancelled'),
        ], limit=1)
        if active:
            raise UserError(
                f"Cannot cancel or delete {active.production_id.name} — it has active "
                f"material issuance authorization(s). Withdraw all authorizations first."
            )

    def unlink(self):
        self._check_no_active_issuances()
        return super().unlink()

    def action_cancel(self):
        self._check_no_active_issuances()
        return super().action_cancel()

    def _sync_packing_qty(self):
        for production in self:
            packing_wos = production.workorder_ids.filtered(
                lambda w: w.workcenter_id.is_packing
            )
            production.qty_producing = sum(packing_wos.mapped('qty_batch_completed'))

    def action_confirm(self):
        res = super().action_confirm()
        # Material is issued physically via reema.material.issuance (RMI).
        # Odoo must never lock stock via reservation — clear any auto-reservation
        # that the base confirm or scheduler may have applied to raw material moves.
        self.move_raw_ids.filtered(
            lambda m: m.state not in ('done', 'cancel')
        )._do_unreserve()
        # qty_producing should start at 0 and climb only when packing batches are logged.
        self.write({'qty_producing': 0.0})
        return res

    def action_open_status_info(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'MO Status Reference',
            'res_model': 'reema.mo.status.info.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {},
        }


class ReemaMoStatusInfoWizard(models.TransientModel):
    _name = 'reema.mo.status.info.wizard'
    _description = 'MO Status Reference'


class StockMoveReema(models.Model):
    _inherit = 'stock.move'

    reema_batch_entry_id = fields.Many2one(
        'reema.wo.batch.entry', string='Batch Entry', readonly=True, index=True,
        help='Set on backflush moves created from a batch progress entry. '
             'Used to link the move back to its batch without relying on the '
             'origin text, which breaks if MO/batch numbering is ever reformatted.')

    backflush_qty = fields.Float(
        string='Consumed', digits=(16, 6),
        compute='_compute_backflush_qty',
        help='Sum of backflush moves from currently existing batch entries only. '
             'Orphan moves (from deleted batches) are excluded.')

    def _compute_backflush_qty(self):
        # Group by MO so we query batch entries once per MO, not once per row.
        by_mo = {}
        for move in self:
            mo = move.raw_material_production_id
            if mo:
                by_mo.setdefault(mo, []).append(move)
            else:
                move.backflush_qty = 0.0

        for mo, moves in by_mo.items():
            # Existing batch entries for this MO — orphan moves (from batches
            # later deleted) are excluded since their entry no longer exists.
            batches = self.env['reema.wo.batch.entry'].search([
                ('workorder_id.production_id', '=', mo.id)
            ])
            if not batches:
                for m in moves:
                    m.backflush_qty = 0.0
                continue

            # Sum all valid backflush moves for this MO, grouped by product.
            # Linked via the FK, not a reconstructed origin string — the latter
            # breaks silently if MO/WO/batch numbering is ever reformatted.
            backflush_moves = self.env['stock.move'].search([
                ('reema_batch_entry_id', 'in', batches.ids),
                ('state', 'not in', ['draft', 'cancel']),
            ])
            by_product = {}
            for bm in backflush_moves:
                by_product[bm.product_id.id] = (
                    by_product.get(bm.product_id.id, 0.0) + bm.quantity
                )
            for m in moves:
                m.backflush_qty = by_product.get(m.product_id.id, 0.0)

    def _action_assign(self, force_qty=False):
        # Hard guarantee: MO component (raw-material) moves are NEVER reserved,
        # regardless of the Manufacturing operation type's reservation method.
        # Even if someone flips it back to "At Confirmation", these moves are
        # filtered out before reservation runs. Material availability is governed
        # by on-hand stock and the custom store-issuance flow, not Odoo's
        # reserve-at-confirm mechanism.
        movable = self.filtered(lambda m: not m.raw_material_production_id)
        return super(StockMoveReema, movable)._action_assign(force_qty=force_qty)
