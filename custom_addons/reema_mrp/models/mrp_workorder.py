import math

from markupsafe import Markup
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_round, float_is_zero


class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    workforce_type = fields.Selection(
        related='workcenter_id.workforce_type', store=True, readonly=True
    )
    contractor_ids = fields.Many2many(
        'res.partner',
        'mrp_workorder_contractor_rel',
        'workorder_id', 'partner_id',
        string='Contractors',
        domain="[('supplier_rank', '>', 0), ('is_contractor', '=', True)]",
    )
    # Batch progress tracking
    batch_entry_ids = fields.One2many('reema.wo.batch.entry', 'workorder_id', string='Batch Entries')
    qty_batch_completed = fields.Float(string='Completed So Far', compute='_compute_qty_batch_completed', store=True)
    batch_released = fields.Boolean(string='Released to Next Hall', default=False)
    hall_qty = fields.Float(string='Target', compute='_compute_hall_qty', store=True)
    qty_balls_completed = fields.Float(string='Balls Done', compute='_compute_qty_balls_completed')
    is_ball_receive_point = fields.Boolean(
        related='workcenter_id.is_ball_receive_point', string='Ball Receive Point',
        store=True, readonly=True,
    )
    scrap_ids = fields.One2many('reema.production.scrap', 'workorder_id', string='Scrap Entries')
    qty_scrap_balls = fields.Float(string='Scrapped Balls', compute='_compute_qty_scrap_balls', store=True)
    hall_uom_name = fields.Char(related='operation_id.piece_rate_id.uom_id.name', string='UOM', readonly=True)
    hall_unit_label = fields.Selection(related='workcenter_id.hall_unit', string='Logging Unit', readonly=True)
    state = fields.Selection(selection=[
        ('pending', 'WO Waiting'),
        ('waiting', 'No Stock'),
        ('ready', 'Ready'),
        ('progress', 'In Progress'),
        ('done', 'Done'),
        ('cancel', 'Cancelled'),
    ])

    @api.depends('batch_entry_ids.qty', 'batch_entry_ids.ilo_dispatch_type')
    def _compute_qty_batch_completed(self):
        # Repair-return entries (ilo_dispatch_type='repair') at the Ball Receive
        # Point are the same physical balls as an earlier stitching receive coming
        # back through that same work order a second time — counting them again
        # would let its target/completion be inflated by rework loops instead of
        # reflecting distinct balls actually received. Repair-outstanding is already
        # gated separately on the Initial QC work order (_ilo_repair_outstanding).
        # Final QC has no such duplicate: a repair-return entry there is the ONLY
        # record of those balls being back (the Fail qty never created a batch
        # entry at all), so it must count normally, not be excluded.
        for wo in self:
            entries = wo.batch_entry_ids
            if wo.workcenter_id.is_ball_receive_point:
                entries = entries.filtered(lambda e: e.ilo_dispatch_type != 'repair')
            wo.qty_batch_completed = sum(entries.mapped('qty'))

    def action_view_ilo_flow(self):
        """Balls Done click-through for a Ball Receive Point row. Opens as a new
        browser tab rather than navigating in-place — an act_window action dict
        can't do that (Odoo's action service only opens act_url as a new tab), so
        this addresses the stored, active_id-scoped variant of the ILO Flow action
        by its real numeric id via the /odoo/<active_id>/action-<id> URL form."""
        self.ensure_one()
        action_id = self.env.ref('reema_mrp.action_reema_ilo_flow_from_workorder').id
        return {
            'type': 'ir.actions.act_url',
            'url': f'/odoo/{self.production_id.id}/action-{action_id}',
            'target': 'new',
        }

    def action_view_batch_log(self):
        """Balls Done click-through for every non-Ball-Receive-Point hall (see
        action_view_ilo_flow above for that one) — the plain batch entries
        logged at this specific work order, so a supervisor can see exactly
        which submissions add up to the figure they clicked, in a new browser
        tab (see action_view_ilo_flow for why act_url/active_id is used instead
        of a plain act_window dict). Uses the stripped-down progress-log list
        (one Qty column, no payment columns) — this is for verifying production
        history in case of a dispute, not for payment review."""
        self.ensure_one()
        action_id = self.env.ref('reema_mrp.reema_batch_entry_action_from_workorder').id
        return {
            'type': 'ir.actions.act_url',
            'url': f'/odoo/{self.id}/action-{action_id}',
            'target': 'new',
        }

    @api.depends('qty_production', 'operation_id.balls_per_unit',
                 'workcenter_id.hall_unit',
                 'production_id.reema_po_line_ids.sample_id.total_panels')
    def _compute_hall_qty(self):
        for wo in self:
            wo.hall_qty = wo._balls_to_units(wo.qty_production)

    def _get_total_panels(self):
        """Panels per ball for this work order's product, read from the
        sampling blueprint (constant per ball design). 0 if not resolvable."""
        self.ensure_one()
        mo = self.production_id
        if not mo:
            return 0
        po_line = self.env['reema.production.order.line'].search(
            [('mo_id', '=', mo.id)], limit=1
        )
        if po_line and po_line.sample_id:
            return po_line.sample_id.total_panels
        return 0

    def _units_to_balls(self, qty_units):
        """Convert a quantity logged in this hall's unit into balls."""
        self.ensure_one()
        unit = self.workcenter_id.hall_unit or 'ball'
        if unit == 'panel':
            panels = self._get_total_panels()
            return qty_units / panels if panels else 0.0
        if unit == 'sheet':
            return qty_units * (self.operation_id.balls_per_unit or 1.0)
        return qty_units

    def _balls_to_units(self, qty_balls):
        """Convert a ball quantity back into this hall's logging unit."""
        self.ensure_one()
        unit = self.workcenter_id.hall_unit or 'ball'
        if unit == 'panel':
            panels = self._get_total_panels()
            return qty_balls * panels
        if unit == 'sheet':
            bpu = self.operation_id.balls_per_unit or 1.0
            return qty_balls / bpu if bpu else qty_balls
        return qty_balls

    @api.depends('batch_entry_ids.qty_balls', 'batch_entry_ids.ilo_dispatch_type',
                 'is_ball_receive_point', 'production_id')
    def _compute_qty_balls_completed(self):
        # Same base reasoning as _compute_qty_batch_completed (exclude repair-return
        # entries to avoid double-counting a ball's original arrival and its later
        # repair round-trip) — but ALSO, at the Ball Receive Point only, net out
        # balls currently dispatched out for an Initial-QC-sourced repair: they
        # already contributed to a prior stitching receipt here, so while they're
        # away being fixed they should not still read as "done". This is a live
        # balance, not a one-way deduction — it comes back up on its own once the
        # repair is received (dispatched - received nets back to 0), which is why
        # this field is intentionally NOT stored: a repair dispatch is created on a
        # different model from a different work order (Initial QC), so a stored
        # value here would go stale with no dependency path to trigger recompute.
        #
        # qty_batch_completed (Completed) is deliberately left alone — it keeps
        # meaning "total ever received from stitching", not "currently on hand".
        # The two are expected to diverge whenever a repair is outstanding; that
        # gap is itself the signal something is out being fixed (see the ILO Flow
        # link on this column).
        #
        # Final QC has no such duplicate: a repair-return entry there is the ONLY
        # record of those balls being back (the Fail qty never created a batch
        # entry at all there), so it must count normally, not be excluded/netted.
        Dispatch = self.env['reema.ilo.dispatch']
        for wo in self:
            entries = wo.batch_entry_ids
            if wo.is_ball_receive_point:
                entries = entries.filtered(lambda e: e.ilo_dispatch_type != 'repair')
            total = sum(entries.mapped('qty_balls'))
            if wo.is_ball_receive_point and wo.production_id:
                contractors = Dispatch._ilo_contractors_for_mo(wo.production_id.id)
                repair_outstanding = sum(
                    Dispatch._ilo_ledger_balance_by_type(wo.production_id.id, c.id, 'repair')
                    for c in contractors
                )
                total -= repair_outstanding
            wo.qty_balls_completed = total

    @api.depends('scrap_ids.qty_balls')
    def _compute_qty_scrap_balls(self):
        for wo in self:
            wo.qty_scrap_balls = sum(wo.scrap_ids.mapped('qty_balls'))

    # Extend state computation: a work order blocked by a predecessor is also unblocked
    # when the predecessor sets batch_released=True (partial completion released to next hall).
    @api.depends('blocked_by_workorder_ids.batch_released')
    def _compute_state(self):
        super()._compute_state()
        for wo in self:
            if self._context.get('no_recursion'):
                continue
            if wo.state != 'pending':
                continue
            predecessors = wo.blocked_by_workorder_ids.with_context(no_recursion=True)
            if not predecessors:
                continue
            all_released = all(
                p.state in ('done', 'cancel') or p.batch_released
                for p in predecessors
            )
            if all_released:
                wo.state = 'ready' if wo.production_availability == 'assigned' else 'waiting'

    def _set_qty_producing(self):
        # Odoo's default inverse propagates wo.qty_producing back to production_id.qty_producing.
        # We suppress that here: the MO's qty_producing is driven exclusively by packing
        # batch entries via reema_wo_batch._sync_mo_qty_producing.
        pass

    @api.constrains('contractor_ids')
    def _check_contractor_batch_entries(self):
        for wo in self:
            assigned = wo.contractor_ids
            for entry in wo.batch_entry_ids:
                if entry.contractor_id and entry.contractor_id not in assigned:
                    raise ValidationError(
                        "Cannot remove contractor '%s' — batch logs have already been "
                        "recorded under them on this work order." % entry.contractor_id.name
                    )

    def write(self, vals):
        if 'contractor_ids' in vals:
            old_contractors = {wo: set(wo.contractor_ids.mapped('name')) for wo in self}
        res = super().write(vals)
        if 'contractor_ids' in vals:
            for wo in self:
                new_names = set(wo.contractor_ids.mapped('name'))
                old_names = old_contractors[wo]
                added = new_names - old_names
                removed = old_names - new_names
                if added or removed:
                    parts = []
                    if added:
                        parts.append(f"Added: {', '.join(sorted(added))}")
                    if removed:
                        parts.append(f"Removed: {', '.join(sorted(removed))}")
                    wo.production_id._message_log(
                        body=Markup(f'Contractors updated on <b>{wo.name}</b> ({wo.workcenter_id.name}): {" | ".join(parts)}.'),
                    )
        return res

    def button_start(self, raise_on_invalid_state=False):
        for wo in self:
            if not wo.operation_id:
                continue
            required_moves = wo.production_id.move_raw_ids.filtered(
                lambda m: m.operation_id == wo.operation_id and m.state not in ('done', 'cancel')
            )
            if not required_moves:
                continue
            unissued = [
                move.product_id.display_name
                for move in required_moves
                if not wo.production_id.issuance_ids.filtered(
                    lambda i: i.raw_move_id == move
                    and i.state in ('partial', 'fully_issued', 'over_issued')
                )
            ]
            if unissued:
                raise UserError(
                    f'Cannot start "{wo.name}" — the following materials have not been issued to this hall:\n'
                    + '\n'.join(f'• {n}' for n in unissued)
                )
        res = super().button_start(raise_on_invalid_state=raise_on_invalid_state)
        for wo in self.filtered(lambda w: w.state == 'progress'):
            wo.production_id._message_log(
                body=Markup(f'▶ Work order <b>{wo.name}</b> ({wo.workcenter_id.name}) started by {self.env.user.name}.'),
            )
        return res

    def action_open_parent_mo(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.production',
            'res_id': self.production_id.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }

    def action_log_batch(self):
        self.ensure_one()
        if self.state != 'progress':
            raise UserError(
                'The work order must be started before logging batch progress.\n\n'
                'Click the Start button on this work order first. '
                'Starting requires: material issued by the store, '
                'and output received from the previous hall (if applicable).'
            )
        if self.workcenter_id.is_ball_receive_point:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Log ILO Balls Received',
                'res_model': 'reema.ilo.receive.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {'default_workorder_id': self.id},
            }
        if self.workcenter_id.is_initial_qc:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Initial QC',
                'res_model': 'reema.ilo.qc.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {'default_workorder_id': self.id},
            }
        # Final QC's own repair/scrap loop only applies to HS/ILO construction —
        # other construction types keep the plain generic batch-log wizard, since
        # there's no original-contractor lineage to charge repair/scrap against.
        if self.workcenter_id.is_final_qc and self.production_id.construction_type == 'hs':
            return {
                'type': 'ir.actions.act_window',
                'name': 'Final QC',
                'res_model': 'reema.final.qc.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {'default_workorder_id': self.id},
            }
        return {
            'type': 'ir.actions.act_window',
            'name': 'Log Batch Progress',
            'res_model': 'reema.batch.entry.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_workorder_id': self.id},
        }

    final_qc_repair_outstanding = fields.Boolean(
        compute='_compute_final_qc_repair_outstanding',
        help='True when this Final QC work order has a repair dispatch (sent from '
             'Final QC itself) not yet received back — shows the Receive Repaired '
             'Ball button.',
    )

    def _compute_final_qc_repair_outstanding(self):
        Dispatch = self.env['reema.ilo.dispatch']
        for wo in self:
            if not wo.workcenter_id.is_final_qc:
                wo.final_qc_repair_outstanding = False
                continue
            dispatches = Dispatch.search([
                ('mo_id', '=', wo.production_id.id),
                ('dispatch_type', '=', 'repair'),
                ('repair_source', '=', 'final_qc'),
            ])
            wo.final_qc_repair_outstanding = any(
                Dispatch._final_qc_repair_outstanding(
                    wo.production_id.id, d.contractor_id.id, d.original_contractor_id.id
                ) > 0
                for d in dispatches
            )

    def action_final_qc_receive(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Receive Repaired Ball',
            'res_model': 'reema.final.qc.receive.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_workorder_id': self.id},
        }

    def button_pending(self):
        for wo in self:
            if wo.state in ('done', 'cancel'):
                raise UserError(f'Work order "{wo.name}" is already {wo.state} and cannot be paused.')
        return super().button_pending()

    def button_finish(self):
        for wo in self:
            if wo.state in ('done', 'cancel'):
                continue
            if wo.state != 'progress':
                raise UserError(
                    f'Work order "{wo.name}" must be started before it can be marked done.\n\n'
                    'Click the Start button first. Starting requires a contractor assigned, '
                    'material issued by the store, and output received from the previous hall (if applicable).'
                )
            # Ball Receive Point: block completion until every ILO contractor who
            # dispatched to this MO has a fully reconciled ledger balance (dispatched
            # minus logged received). Contractor identity is read off the dispatch
            # records themselves, not this work order's own contractor_ids — Ball
            # Receive is an employee-type hall with no contractor assignment of its
            # own. (Issuance itself is no longer gated this way — new batches can
            # keep going out regardless of whether earlier ones are back yet.)
            if wo.workcenter_id.is_ball_receive_point:
                contractors = self.env['reema.ilo.dispatch']._ilo_contractors_for_mo(wo.production_id.id)
                outstanding = [
                    (contractor, self.env['reema.ilo.dispatch']._ilo_ledger_balance(
                        wo.production_id.id, contractor.id
                    ))
                    for contractor in contractors
                ]
                outstanding = [(c, bal) for c, bal in outstanding if bal > 0]
                if outstanding:
                    detail = ', '.join(f'{c.name}: {bal:.0f} balls' for c, bal in outstanding)
                    raise UserError(
                        f'Work order "{wo.name}" cannot be completed yet.\n\n'
                        f'Balls still outstanding — {detail}. '
                        f'Log all ILO receives before finishing this step.'
                    )
            # Initial QC: block completion while any original contractor still has
            # balls out at repair (the generic qty_batch_completed>=target check
            # below already covers "did enough balls actually pass" — this covers
            # "is nothing still missing out at repair").
            if wo.workcenter_id.is_initial_qc:
                contractors = self.env['reema.ilo.dispatch']._ilo_original_contractors_for_mo(wo.production_id.id)
                outstanding = [
                    (contractor, self.env['reema.ilo.dispatch']._ilo_repair_outstanding(
                        wo.production_id.id, contractor.id
                    ))
                    for contractor in contractors
                ]
                outstanding = [(c, bal) for c, bal in outstanding if bal > 0]
                if outstanding:
                    detail = ', '.join(f'{c.name}: {bal} balls' for c, bal in outstanding)
                    raise UserError(
                        f'Work order "{wo.name}" cannot be completed yet.\n\n'
                        f'Balls still out for repair — {detail}. '
                        f'Log all repair returns before finishing this step.'
                    )
            if not wo.batch_entry_ids:
                raise UserError(
                    f'Work order "{wo.name}": log at least one batch before marking it as done.'
                )
            min_required = math.floor(wo.hall_qty)
            if min_required > 0 and wo.qty_batch_completed < min_required:
                raise UserError(
                    f'Work order "{wo.name}": not enough quantity logged.\n\n'
                    f'Target: {wo.hall_qty:.2f} — minimum required: {min_required} — '
                    f'logged so far: {wo.qty_batch_completed:.2f}.'
                )
        wos_finishing = self.filtered(lambda w: w.state == 'progress')
        res = super().button_finish()
        for wo in wos_finishing:
            wo.production_id._message_log(
                body=Markup(f'✓ Work order <b>{wo.name}</b> ({wo.workcenter_id.name}) marked done by {self.env.user.name}.'),
            )
        for wo in self:
            wc = wo.workcenter_id
            if not wc.sfg_product_id or not wc.location_id:
                continue
            # Batch entries already created SFG moves per log entry — skip double-creation
            if wo.batch_entry_ids:
                continue
            rounding = wc.sfg_product_id.uom_id.rounding
            qty = float_round(wo.qty_produced, precision_rounding=rounding)
            if float_is_zero(qty, precision_rounding=rounding):
                continue
            # Move SFG product from virtual production location into this hall's stock location.
            production_loc = self.env['stock.location'].search([('usage', '=', 'production')], limit=1)
            if not production_loc:
                continue
            move = self.env['stock.move'].create({
                'name': f'SFG: {wc.sfg_product_id.name}',
                'product_id': wc.sfg_product_id.id,
                'product_uom': wc.sfg_product_id.uom_id.id,
                'product_uom_qty': qty,
                'location_id': production_loc.id,
                'location_dest_id': wc.location_id.id,
                'origin': wo.production_id.name,
                'company_id': wo.company_id.id,
            })
            move._action_confirm()
            move.quantity = qty
            move._action_done()
        return res
