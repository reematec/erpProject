from odoo import models, fields, api
from odoo.exceptions import UserError


class ReemaWoBatchEntry(models.Model):
    _name = 'reema.wo.batch.entry'
    _description = 'Work Order Batch Progress Entry'
    _order = 'date desc'

    name = fields.Char(string='Reference', readonly=True, copy=False, default='New')
    workorder_id = fields.Many2one('mrp.workorder', string='Work Order',
                                   required=True, ondelete='cascade')
    reema_po_id = fields.Many2one('reema.production.order', string='Production Order',
                                  compute='_compute_reema_po_id', store=True)
    mo_id = fields.Many2one(related='workorder_id.production_id',
                            string='Manufacturing Order', store=True)
    process_name = fields.Char(related='workorder_id.name', string='Process', store=True)
    workforce_type = fields.Selection(
        related='workorder_id.workcenter_id.workforce_type', store=True, readonly=True
    )
    contractor_id = fields.Many2one('res.partner', string='Contractor',
                                    required=False, domain=[('supplier_rank', '>', 0)])
    date = fields.Datetime(string='Date', default=fields.Datetime.now, readonly=True)
    qty = fields.Float(string='Qty Completed', required=True)
    notes = fields.Char(string='Notes')
    sfg_move_id = fields.Many2one('stock.move', string='Stock Move', readonly=True)
    logged_by = fields.Many2one('res.users', string='Logged By',
                                default=lambda self: self.env.uid, readonly=True)
    qty_balls = fields.Float(string='Balls Equivalent', compute='_compute_qty_balls', store=True)
    piece_rate_id = fields.Many2one('reema.piece.rate', string='Piece Rate')
    piece_rate_value = fields.Float(related='piece_rate_id.rate', string='Rate (PKR)', digits=(10, 2))
    amount_earned = fields.Float(string='Amount (PKR)', compute='_compute_amount_earned', store=True, digits=(10, 2))

    @api.depends('workorder_id.production_id')
    def _compute_reema_po_id(self):
        POLine = self.env['reema.production.order.line']
        for entry in self:
            mo = entry.workorder_id.production_id
            if mo:
                line = POLine.search([('mo_id', '=', mo.id)], limit=1)
                entry.reema_po_id = line.order_id
            else:
                entry.reema_po_id = False

    @api.depends('qty', 'workorder_id.operation_id.balls_per_unit')
    def _compute_qty_balls(self):
        for entry in self:
            bpu = entry.workorder_id.operation_id.balls_per_unit or 1.0
            entry.qty_balls = entry.qty * bpu

    @api.depends('piece_rate_id.rate', 'qty')
    def _compute_amount_earned(self):
        for entry in self:
            entry.amount_earned = (entry.piece_rate_id.rate or 0.0) * entry.qty

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('reema.production.batch') or 'New'
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
        production_loc = self.env['stock.location'].search([('usage', '=', 'production')], limit=1)
        if not production_loc:
            raise UserError('No production location found. Please configure a location with usage "Production".')
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
    workcenter_id = fields.Many2one(related='workorder_id.workcenter_id', readonly=True)
    workforce_type = fields.Selection(
        related='workorder_id.workcenter_id.workforce_type', readonly=True
    )
    hall_qty = fields.Float(related='workorder_id.hall_qty',
                            string='Target', readonly=True)
    qty_batch_completed = fields.Float(related='workorder_id.qty_batch_completed',
                                       string='Completed So Far', readonly=True)
    # Restrict contractor dropdown to only those assigned to this work order
    available_contractor_ids = fields.Many2many(related='workorder_id.contractor_ids',
                                                string='Assigned Contractors')
    contractor_id = fields.Many2one('res.partner', string='Contractor', required=False,
                                    domain="[('id', 'in', available_contractor_ids)]")
    qty = fields.Float(string='Qty Completed Now', required=True)
    notes = fields.Char(string='Notes')
    piece_rate_id = fields.Many2one(
        related='workorder_id.operation_id.piece_rate_id',
        string='Piece Rate',
        readonly=True,
    )

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
                uom_label = 'units'
                raise UserError(
                    f'Cannot log {self.qty:.1f} {uom_label}.\n\n'
                    f'{pred.workcenter_id.name} has completed '
                    f'{pred.qty_balls_completed:.1f} balls equivalent.\n\n'
                    f'{wo.qty_balls_completed:.1f} balls equivalent already processed here.\n\n'
                    f'Maximum you can log now: {available_units:.1f} {uom_label}.'
                )
        vals = {
            'workorder_id': wo.id,
            'qty': self.qty,
            'notes': self.notes,
        }
        if self.workforce_type != 'employee':
            if not self.contractor_id:
                raise UserError('Please select a contractor before saving.')
            vals['contractor_id'] = self.contractor_id.id
            vals['piece_rate_id'] = wo.operation_id.piece_rate_id.id or False
        self.env['reema.wo.batch.entry'].create(vals)
