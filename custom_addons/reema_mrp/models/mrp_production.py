from odoo import models, fields, api
from odoo.exceptions import UserError


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

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

    def action_confirm(self):
        res = super().action_confirm()
        # Material is issued physically via reema.material.issuance (RMI).
        # Odoo must never lock stock via reservation — clear any auto-reservation
        # that the base confirm or scheduler may have applied to raw material moves.
        self.move_raw_ids.filtered(
            lambda m: m.state not in ('done', 'cancel')
        )._do_unreserve()
        return res
