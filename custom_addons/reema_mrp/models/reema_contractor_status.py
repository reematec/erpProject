from odoo import models, fields, tools


class ReemaContractorWoStatus(models.Model):
    _name = 'reema.contractor.wo.status'
    _description = 'Contractor Work Status'
    _auto = False
    _log_access = False
    _order = 'contractor_id, mo_id, workorder_id'

    contractor_id = fields.Many2one('res.partner', string='Contractor', readonly=True)
    workorder_id = fields.Many2one('mrp.workorder', string='Work Order', readonly=True)
    mo_id = fields.Many2one('mrp.production', string='Manufacturing Order', readonly=True)
    workcenter_id = fields.Many2one('mrp.workcenter', string='Process', readonly=True)
    wo_state = fields.Selection([
        ('pending', 'WO Waiting'),
        ('waiting', 'No Stock'),
        ('ready', 'Ready'),
        ('progress', 'In Progress'),
        ('done', 'Done'),
        ('cancel', 'Cancelled'),
    ], string='WO Status', readonly=True)
    qty_target = fields.Float(string='Target', readonly=True)
    hall_unit = fields.Selection([
        ('sheet', 'Sheet'),
        ('panel', 'Panel'),
        ('ball', 'Ball'),
    ], string='Unit', readonly=True)
    qty_logged = fields.Float(string='Logged', readonly=True)
    qty_balls_logged = fields.Float(string='Balls Logged', readonly=True)
    total_entries = fields.Integer(string='Total Entries', readonly=True)
    unbilled_entries = fields.Integer(string='Unbilled', readonly=True)
    is_ilo = fields.Boolean(string='ILO', readonly=True)
    ilo_qty_dispatched = fields.Integer(string='ILO Dispatched', readonly=True)
    ilo_qty_pending = fields.Integer(string='ILO Pending', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW reema_contractor_wo_status AS (
                SELECT
                    row_number() OVER (ORDER BY rp.name, mp.name, wo.id) AS id,
                    rel.partner_id                  AS contractor_id,
                    rel.workorder_id,
                    wo.production_id                AS mo_id,
                    wo.workcenter_id,
                    wo.state                        AS wo_state,
                    wo.hall_qty                     AS qty_target,
                    wc.hall_unit,
                    wc.is_ilo,
                    COALESCE(be.qty_logged,     0.0) AS qty_logged,
                    COALESCE(be.qty_balls,      0.0) AS qty_balls_logged,
                    COALESCE(be.total_count,    0)   AS total_entries,
                    COALESCE(be.unbilled_count, 0)   AS unbilled_entries,
                    COALESCE(ilo.qty_dispatched, 0)  AS ilo_qty_dispatched,
                    COALESCE(ilo.qty_pending,    0)  AS ilo_qty_pending
                FROM mrp_workorder_contractor_rel rel
                JOIN mrp_workorder  wo  ON wo.id  = rel.workorder_id
                JOIN mrp_production mp  ON mp.id  = wo.production_id
                JOIN mrp_workcenter wc  ON wc.id  = wo.workcenter_id
                JOIN res_partner    rp  ON rp.id  = rel.partner_id
                LEFT JOIN (
                    SELECT
                        workorder_id,
                        contractor_id,
                        SUM(qty)       AS qty_logged,
                        SUM(qty_balls) AS qty_balls,
                        COUNT(*)       AS total_count,
                        SUM(CASE WHEN is_billed = FALSE
                                  AND payment_excluded = FALSE
                                 THEN 1 ELSE 0 END) AS unbilled_count
                    FROM reema_wo_batch_entry
                    GROUP BY workorder_id, contractor_id
                ) be  ON be.workorder_id  = rel.workorder_id
                     AND be.contractor_id  = rel.partner_id
                LEFT JOIN (
                    SELECT
                        mo_id,
                        contractor_id,
                        SUM(qty_panels)  AS qty_dispatched,
                        SUM(qty_pending) AS qty_pending
                    FROM reema_ilo_dispatch
                    WHERE state IN ('dispatched', 'closed')
                    GROUP BY mo_id, contractor_id
                ) ilo ON ilo.mo_id        = wo.production_id
                     AND ilo.contractor_id = rel.partner_id
                     AND wc.is_ilo         = TRUE
                WHERE mp.state NOT IN ('done', 'cancel')
            )
        """)

    def action_open_mo(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.production',
            'res_id': self.mo_id.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }
