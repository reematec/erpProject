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

    ilo_dispatch_count = fields.Integer(compute='_compute_ilo_dispatch_count', string='ILO Dispatches')

    has_active_issuance = fields.Boolean(compute='_compute_has_active_issuance')

    def _compute_has_active_issuance(self):
        for rec in self:
            rec.has_active_issuance = bool(
                rec.issuance_ids.filtered(lambda i: i.state != 'cancelled')
            )

    # WIP Evaluation — material cost (AVCO × net issued) + labor cost (batch piece rates)
    wip_material_cost = fields.Float(string='Material Cost (PKR)', compute='_compute_wip_costs', digits=(16, 2))
    wip_labor_cost = fields.Float(string='Labor Cost (PKR)', compute='_compute_wip_costs', digits=(16, 2))
    wip_total_cost = fields.Float(string='Total WIP (PKR)', compute='_compute_wip_costs', digits=(16, 2))
    wip_balls_in_process = fields.Float(string='Balls In Process', compute='_compute_wip_costs', digits=(16, 2))

    def _compute_wip_costs(self):
        Issuance = self.env['reema.material.issuance']
        for rec in self:
            if rec.state in ('done', 'cancel'):
                rec.wip_material_cost = 0.0
                rec.wip_labor_cost = 0.0
                rec.wip_total_cost = 0.0
                rec.wip_balls_in_process = 0.0
                continue
            # Material: net issued qty × current AVCO standard_price per product
            issuances = Issuance.search([('production_id', '=', rec.id)])
            material_cost = sum(
                iss.net_issued_qty * iss.product_id.standard_price
                for iss in issuances
            )
            # Labor: sum of all batch entry piece-rate amounts across all halls
            labor_cost = sum(rec.workorder_ids.mapped('wip_labor_cost'))
            # Balls: furthest-progressed hall's ball-equivalent output
            balls = max(rec.workorder_ids.mapped('qty_balls_completed'), default=0.0)
            rec.wip_material_cost = max(material_cost, 0.0)
            rec.wip_labor_cost = labor_cost
            rec.wip_total_cost = rec.wip_material_cost + labor_cost
            rec.wip_balls_in_process = balls

    def _compute_ilo_dispatch_count(self):
        for rec in self:
            rec.ilo_dispatch_count = self.env['reema.ilo.dispatch'].search_count([('mo_id', '=', rec.id)])

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
            # Build the exact set of valid origins from EXISTING batch entries.
            # This excludes orphan backflush moves whose batch was later deleted.
            batches = self.env['reema.wo.batch.entry'].search([
                ('workorder_id.production_id', '=', mo.id)
            ])
            valid_origins = [
                f'{mo.name} / {b.workorder_id.name} / {b.name}'
                for b in batches
            ]
            if not valid_origins:
                for m in moves:
                    m.backflush_qty = 0.0
                continue

            # Sum all valid backflush moves for this MO, grouped by product.
            backflush_moves = self.env['stock.move'].search([
                ('origin', 'in', valid_origins),
                ('state', 'not in', ['draft', 'cancel']),
            ])
            by_product = {}
            for bm in backflush_moves:
                by_product[bm.product_id.id] = (
                    by_product.get(bm.product_id.id, 0.0) + bm.quantity
                )
            for m in moves:
                m.backflush_qty = by_product.get(m.product_id.id, 0.0)
