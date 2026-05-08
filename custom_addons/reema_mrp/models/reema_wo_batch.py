from odoo import models, fields, api
from odoo.exceptions import UserError


class ReemaWoBatchEntry(models.Model):
    _name = 'reema.wo.batch.entry'
    _description = 'Work Order Batch Progress Entry'
    _order = 'date desc'

    workorder_id = fields.Many2one('mrp.workorder', string='Work Order',
                                   required=True, ondelete='cascade')
    contractor_id = fields.Many2one('res.partner', string='Contractor',
                                    required=True, domain=[('supplier_rank', '>', 0)])
    date = fields.Datetime(string='Date', default=fields.Datetime.now, readonly=True)
    qty = fields.Float(string='Qty Completed', required=True)
    labor_cost = fields.Float(string='Labor Cost', compute='_compute_labor_cost', store=True)
    notes = fields.Char(string='Notes')
    sfg_move_id = fields.Many2one('stock.move', string='Stock Move', readonly=True)
    logged_by = fields.Many2one('res.users', string='Logged By',
                                default=lambda self: self.env.uid, readonly=True)
    qty_balls = fields.Float(string='Balls Equivalent', compute='_compute_qty_balls', store=True)

    @api.depends('qty', 'workorder_id.operation_id.balls_per_unit')
    def _compute_qty_balls(self):
        for entry in self:
            bpu = entry.workorder_id.operation_id.balls_per_unit or 1.0
            entry.qty_balls = entry.qty * bpu

    @api.depends('qty', 'workorder_id.piece_rate_id')
    def _compute_labor_cost(self):
        for entry in self:
            rate = entry.workorder_id.piece_rate_id.rate if entry.workorder_id.piece_rate_id else 0.0
            entry.labor_cost = entry.qty * rate

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for entry in records:
            entry._create_sfg_move()
            # First batch logged on this WO → auto-release so the next hall's
            # Start button becomes available without any manual action.
            if not entry.workorder_id.batch_released:
                entry.workorder_id.batch_released = True
        return records

    def _create_sfg_move(self):
        wo = self.workorder_id
        wc = wo.workcenter_id
        if not wc.sfg_product_id or not wc.location_id:
            return
        if not self.qty:
            return
        production_loc = self.env.ref('stock.location_production')
        move = self.env['stock.move'].create({
            'name': f'SFG Batch: {wc.sfg_product_id.name}',
            'product_id': wc.sfg_product_id.id,
            'product_uom': wc.sfg_product_id.uom_id.id,
            'product_uom_qty': self.qty,
            'location_id': production_loc.id,
            'location_dest_id': wc.location_id.id,
            'origin': f'{wo.production_id.name} / {wo.name}',
            'company_id': wo.company_id.id,
        })
        move._action_confirm()
        move.quantity = self.qty
        move._action_done()
        self.sfg_move_id = move


class ReemaBatchEntryWizard(models.TransientModel):
    _name = 'reema.batch.entry.wizard'
    _description = 'Log Batch Progress'

    workorder_id = fields.Many2one('mrp.workorder', string='Work Order',
                                   required=True, readonly=True)
    workcenter_name = fields.Char(related='workorder_id.workcenter_id.name',
                                  string='Hall', readonly=True)
    hall_qty = fields.Float(related='workorder_id.hall_qty',
                            string='Target', readonly=True)
    qty_batch_completed = fields.Float(related='workorder_id.qty_batch_completed',
                                       string='Completed So Far', readonly=True)
    # Restrict contractor dropdown to only those assigned to this work order
    available_contractor_ids = fields.Many2many(related='workorder_id.contractor_ids',
                                                string='Assigned Contractors')
    contractor_id = fields.Many2one('res.partner', string='Contractor', required=True,
                                    domain="[('id', 'in', available_contractor_ids)]")
    qty = fields.Float(string='Qty Completed Now', required=True)
    notes = fields.Char(string='Notes')

    def action_confirm(self):
        self.ensure_one()
        wo = self.workorder_id
        if self.qty <= 0:
            raise UserError('Quantity must be greater than zero.')
        # Cap: cannot log more than what has physically arrived from the previous hall.
        # Comparison is normalized to balls so different hall units (sheets vs panels) work correctly.
        for pred in wo.blocked_by_workorder_ids:
            if pred.state in ('done', 'cancel'):
                continue
            bpu = wo.operation_id.balls_per_unit or 1.0
            self_balls = self.qty * bpu
            available_balls = pred.qty_balls_completed - wo.qty_balls_completed
            available_units = available_balls / bpu if bpu else available_balls
            if self_balls > available_balls + 0.001:
                uom_label = wo.piece_rate_id.uom_id.name or 'units'
                raise UserError(
                    f'Cannot log {self.qty:.1f} {uom_label}.\n\n'
                    f'{pred.workcenter_id.name} has completed '
                    f'{pred.qty_balls_completed:.1f} balls equivalent.\n\n'
                    f'{wo.qty_balls_completed:.1f} balls equivalent already processed here.\n\n'
                    f'Maximum you can log now: {available_units:.1f} {uom_label}.'
                )
        self.env['reema.wo.batch.entry'].create({
            'workorder_id': wo.id,
            'contractor_id': self.contractor_id.id,
            'qty': self.qty,
            'notes': self.notes,
        })
