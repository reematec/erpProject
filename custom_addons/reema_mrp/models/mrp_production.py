from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    responsible_name = fields.Char(related='user_id.name', string='Responsible', readonly=True)
    reema_po_line_ids = fields.One2many('reema.production.order.line', 'mo_id')
    # Single-value lookup of the Production Order this MO belongs to, for models
    # (scrap, ILO deductions, ...) that only carry mo_id and need "which PO" —
    # a plain related field can't cross a one2many, hence a compute here.
    reema_po_id = fields.Many2one(
        'reema.production.order', string='PO',
        compute='_compute_reema_po_id', store=True,
    )

    @api.depends('reema_po_line_ids.order_id')
    def _compute_reema_po_id(self):
        for mo in self:
            mo.reema_po_id = mo.reema_po_line_ids[:1].order_id

    # "Printed Together With" — lets the Production Manager declare that this
    # order's Printing-hall output is physically combined into one print run
    # with one or more other orders (same article/variation only). The combined
    # ball total across the group decides flat-per-ball vs per-impression pay —
    # see reema.wo.batch.entry._pay_rate_and_qty(grouped=True), evaluated once
    # at contractor-bill time, never live during production.
    reema_printing_group_ids = fields.Many2many(
        'mrp.production', 'reema_mrp_printing_group_rel', 'mo_id', 'group_mo_id',
        string='Printed Together With',
        help='Production Manager only. Other Manufacturing Orders whose Printing-hall '
             'output is physically combined with this one into a single print run. '
             'Only orders for the exact same article/variation can be linked. Locked '
             'once any batch anywhere in the group has been billed — remove it from '
             'its draft bill first to make changes.')

    @api.constrains('reema_printing_group_ids')
    def _check_reema_printing_group_same_product(self):
        for mo in self:
            mismatched = mo.reema_printing_group_ids.filtered(
                lambda o: o.product_id != mo.product_id
            )
            if mismatched:
                raise ValidationError(
                    f"{mo.name} can only be \"Printed Together With\" orders producing "
                    f"the exact same article/variation. These don't match: "
                    f"{', '.join(mismatched.mapped('name'))}"
                )

    def _reema_printing_group_touched_ids(self, commands):
        """This MO's id, its current group members, and every id referenced by an
        add/remove/set command — the full set that must be checked for billed
        Printing batches before a "Printed Together With" change is allowed."""
        self.ensure_one()
        ids = set(self.reema_printing_group_ids.ids) | {self.id}
        for cmd in commands:
            if cmd[0] in (2, 3, 4) and len(cmd) > 1:
                ids.add(cmd[1])
            elif cmd[0] == 6:
                ids.update(cmd[2])
        return ids

    def _reema_printing_group_has_billed(self, mo_ids):
        return bool(self.env['reema.wo.batch.entry'].search_count([
            ('workorder_id.production_id', 'in', list(mo_ids)),
            ('workorder_id.workcenter_id.is_printing', '=', True),
            ('is_billed', '=', True),
        ]))

    def write(self, vals):
        if 'reema_printing_group_ids' in vals:
            for mo in self:
                touched = mo._reema_printing_group_touched_ids(vals['reema_printing_group_ids'])
                if mo._reema_printing_group_has_billed(touched):
                    raise UserError(
                        f'Cannot change "Printed Together With" for {mo.name} — one or '
                        f'more orders in this group already have billed Printing '
                        f'batches. Remove those batches from their draft bill first, or '
                        f'if the bill is already finalized, the grouping can no longer '
                        f'be changed.'
                    )
        return super().write(vals)

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
    # HS: outstanding ILO repair-dispatch balls. Hybrid/MS: outstanding
    # reema.repair.job balls. Same smart button either way — an MO is one
    # construction type or the other, never both, so there's no overlap.
    repair_qty_balls = fields.Integer(compute='_compute_ilo_repair_scrap_qty', string='Repair Balls')
    ilo_scrap_qty = fields.Integer(compute='_compute_ilo_repair_scrap_qty', string='ILO Scrapped Balls')
    production_scrap_qty = fields.Integer(compute='_compute_scrap_qty', string='Production Scrapped Balls')
    total_scrap_qty = fields.Integer(compute='_compute_scrap_qty', string='Total Scrapped Balls')
    ilo_lost_qty = fields.Integer(compute='_compute_ilo_lost_qty', string='Lost Balls')

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
        Job = self.env['reema.repair.job']
        for rec in self:
            if rec.construction_type == 'hs':
                rec.repair_qty_balls = sum(Dispatch.search([
                    ('mo_id', '=', rec.id), ('dispatch_type', '=', 'repair'),
                ]).mapped('qty_balls'))
            else:
                rec.repair_qty_balls = sum(Job.search([
                    ('mo_id', '=', rec.id), ('state', '=', 'pending'),
                ]).mapped('qty_remaining'))
            rec.ilo_scrap_qty = sum(Scrap.search([('mo_id', '=', rec.id)]).mapped('qty'))

    def _compute_scrap_qty(self):
        ProdScrap = self.env['reema.production.scrap']
        for rec in self:
            rec.production_scrap_qty = sum(ProdScrap.search([('mo_id', '=', rec.id)]).mapped('qty'))
            rec.total_scrap_qty = rec.ilo_scrap_qty + rec.production_scrap_qty

    def _compute_ilo_lost_qty(self):
        Dispatch = self.env['reema.ilo.dispatch']
        for rec in self:
            rec.ilo_lost_qty = sum(Dispatch.search([
                ('mo_id', '=', rec.id), ('dispatch_type', '=', 'repair'),
            ]).mapped('qty_lost'))

    def _action_view_url_new_tab(self, action_xmlid):
        # Smart buttons open in a new browser tab rather than navigating away from
        # the MO in-place — a plain act_window action dict can't do that (Odoo's
        # action service only opens act_url as a new tab), so this targets the
        # active_id-scoped variant of the action by its real numeric id via the
        # /odoo/<active_id>/action-<id> URL form. Same pattern as
        # mrp_workorder.action_view_ilo_flow / action_view_batch_log.
        self.ensure_one()
        action_id = self.env.ref(action_xmlid).id
        return {
            'type': 'ir.actions.act_url',
            'url': f'/odoo/{self.id}/action-{action_id}',
            'target': 'new',
        }

    def action_view_ilo_dispatches(self):
        return self._action_view_url_new_tab('reema_mrp.action_reema_ilo_dispatch_from_mo')

    def action_view_repairs(self):
        if self.construction_type == 'hs':
            return self._action_view_url_new_tab('reema_mrp.action_reema_ilo_repair_dispatch_from_mo')
        return self._action_view_url_new_tab('reema_mrp.action_reema_repair_job_from_mo')

    def action_view_scrap_report(self):
        return self._action_view_url_new_tab('reema_mrp.action_reema_scrap_report_from_mo')

    def action_view_lost_balls(self):
        return self._action_view_url_new_tab('reema_mrp.action_reema_lost_balls_from_mo')

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
        # Start Date reflects when the MO was actually confirmed and work began —
        # not the creation-time default or a user-typed guess. Set once here, then
        # locked read-only in the view so it can't be edited afterward.
        self.write({'date_start': fields.Datetime.now()})
        return res


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
