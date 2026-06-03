from odoo import models, fields, api
from odoo.exceptions import UserError


class ReemaIloPieceRate(models.Model):
    _name = 'reema.ilo.piece.rate'
    _description = 'ILO Piece Rate'
    _order = 'contractor_id, construction_type, ball_size'

    contractor_id = fields.Many2one(
        'res.partner', string='Contractor', required=True,
        domain=[('is_contractor', '=', True)],
        options={'no_create': True, 'no_edit': True},
    )
    ball_size = fields.Selection(
        [('3', 'Size 3'), ('4', 'Size 4'), ('5', 'Size 5')],
        string='Ball Size', required=True,
    )
    construction_type = fields.Selection(
        [('hs', 'HS'), ('hyb', 'HYB'), ('ms', 'MS'), ('thb', 'THB')],
        string='Construction Type', required=True,
    )
    rate = fields.Float(string='Rate per Ball (PKR)', required=True, digits=(10, 2))
    bladder_deduction = fields.Float(
        string='Bladder Deduction (PKR)',
        digits=(10, 2),
        help='Fixed PKR deduction per no-bladder ball. Leave 0 to always enter manually.',
    )

    _sql_constraints = [
        ('unique_ilo_rate', 'unique(contractor_id, ball_size, construction_type)',
         'A piece rate for this contractor / size / type combination already exists.'),
    ]


class ReemaIloDispatch(models.Model):
    _name = 'reema.ilo.dispatch'
    _description = 'ILO Dispatch'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, name desc'

    name = fields.Char(string='Reference', readonly=True, copy=False, default='New')
    mo_id = fields.Many2one(
        'mrp.production', string='Manufacturing Order', required=True,
        options={'no_create': True, 'no_edit': True},
        tracking=True,
    )
    contractor_id = fields.Many2one(
        'res.partner', string='ILO Contractor', required=True,
        domain=[('is_contractor', '=', True)],
        options={'no_create': True, 'no_edit': True},
        tracking=True,
    )
    date = fields.Date(string='Dispatch Date', required=True, default=fields.Date.today)
    dispatched_by = fields.Many2one(
        'res.users', string='Dispatched By', required=True,
        default=lambda self: self.env.user,
    )
    verified_by = fields.Many2one(
        'res.users', string='Verified By (Ali Shan)',
        help='Person who counted and verified the outgoing quantity.',
    )
    ball_size = fields.Selection(
        [('3', 'Size 3'), ('4', 'Size 4'), ('5', 'Size 5')],
        string='Ball Size', required=True,
    )
    construction_type = fields.Selection(
        [('hs', 'HS'), ('hyb', 'HYB'), ('ms', 'MS'), ('thb', 'THB')],
        string='Construction Type', required=True,
    )
    qty_panels = fields.Integer(string='Panels Sent', required=True)
    qty_bladders = fields.Integer(string='Bladders Sent')
    qty_thread = fields.Float(string='Thread Sent (spools)', digits=(10, 2))
    notes = fields.Text(string='Notes')
    state = fields.Selection(
        [('draft', 'Draft'), ('dispatched', 'Dispatched'), ('closed', 'Closed')],
        string='Status', default='draft', tracking=True,
    )
    receipt_ids = fields.One2many('reema.ilo.receipt', 'dispatch_id', string='Receipts')
    qty_returned = fields.Integer(
        string='Returned', compute='_compute_qty_returned', store=True,
    )
    qty_pending = fields.Integer(
        string='Pending at ILO', compute='_compute_qty_returned', store=True,
    )

    @api.depends('receipt_ids.qty_full', 'receipt_ids.qty_no_bladder', 'receipt_ids.qty_damaged')
    def _compute_qty_returned(self):
        for rec in self:
            returned = sum(
                r.qty_full + r.qty_no_bladder + r.qty_damaged
                for r in rec.receipt_ids
                if r.state == 'received'
            )
            rec.qty_returned = returned
            rec.qty_pending = rec.qty_panels - returned

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('reema.ilo.dispatch') or 'New'
        return super().create(vals_list)

    def action_dispatch(self):
        self.ensure_one()
        if self.qty_panels <= 0:
            raise UserError('Panels sent must be greater than 0 before dispatching.')
        if not self.verified_by:
            raise UserError('Please select the person who verified and counted the outgoing quantity.')
        self.state = 'dispatched'
        self.message_post(
            body=f'Dispatched {self.qty_panels} panels, {self.qty_bladders} bladders to ILO center. '
                 f'Verified by {self.verified_by.name}.'
        )

    def action_close(self):
        self.ensure_one()
        if self.qty_pending > 0:
            raise UserError(
                f'Cannot close this dispatch — {self.qty_pending} balls are still pending at the ILO center.\n'
                'Record all receipts before closing.'
            )
        self.state = 'closed'



class ReemaIloReceipt(models.Model):
    _name = 'reema.ilo.receipt'
    _description = 'ILO Receipt'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, name desc'

    name = fields.Char(string='Reference', readonly=True, copy=False, default='New')
    dispatch_id = fields.Many2one(
        'reema.ilo.dispatch', string='Dispatch', required=True,
        domain=[('state', '=', 'dispatched')],
        options={'no_create': True, 'no_edit': True},
        tracking=True,
    )
    contractor_id = fields.Many2one(
        related='dispatch_id.contractor_id', string='Contractor', store=True, readonly=True,
    )
    mo_id = fields.Many2one(
        related='dispatch_id.mo_id', string='Manufacturing Order', store=True, readonly=True,
    )
    ball_size = fields.Selection(related='dispatch_id.ball_size', store=True, readonly=True)
    construction_type = fields.Selection(related='dispatch_id.construction_type', store=True, readonly=True)
    date = fields.Date(string='Receipt Date', required=True, default=fields.Date.today)
    received_by = fields.Many2one(
        'res.users', string='Received By (ILO Manager)', required=True,
        default=lambda self: self.env.user,
    )
    verified_by = fields.Many2one(
        'res.users', string='Verified By (Ali Shan)',
        help='Person who counted and confirmed the returned quantity.',
    )
    qty_full = fields.Integer(string='Fully Stitched (with Bladder)')
    qty_no_bladder = fields.Integer(string='Stitched (No Bladder)')
    qty_damaged = fields.Integer(string='Damaged / Unusable')
    piece_rate_id = fields.Many2one(
        'reema.ilo.piece.rate', string='Piece Rate',
        domain="[('contractor_id', '=', contractor_id), ('ball_size', '=', ball_size), ('construction_type', '=', construction_type)]",
        options={'no_create': True, 'no_edit': True},
    )
    rate_full = fields.Float(string='Rate per Ball (PKR)', digits=(10, 2))
    deduction_type = fields.Selection(
        [('fixed', 'Fixed (from rate card)'), ('manual', 'Manual (enter amount)')],
        string='No-Bladder Deduction', default='fixed',
    )
    deduction_per_ball = fields.Float(string='Deduction per No-Bladder Ball (PKR)', digits=(10, 2))
    notes = fields.Text(string='Notes')
    state = fields.Selection(
        [('draft', 'Draft'), ('received', 'Received')],
        string='Status', default='draft', tracking=True,
    )
    repair_charge_ids = fields.One2many('reema.ilo.repair.charge', 'receipt_id', string='QC Repair Charges')
    amount_full = fields.Float(string='Amount (Full)', compute='_compute_amounts', store=True, digits=(10, 2))
    amount_no_bladder = fields.Float(string='Amount (No Bladder)', compute='_compute_amounts', store=True, digits=(10, 2))
    repair_deduction = fields.Float(string='Repair Deductions', compute='_compute_amounts', store=True, digits=(10, 2))
    amount_due = fields.Float(string='Amount Due (PKR)', compute='_compute_amounts', store=True, digits=(10, 2))

    @api.onchange('piece_rate_id')
    def _onchange_piece_rate_id(self):
        if self.piece_rate_id:
            self.rate_full = self.piece_rate_id.rate
            if self.deduction_type == 'fixed':
                self.deduction_per_ball = self.piece_rate_id.bladder_deduction

    @api.onchange('deduction_type')
    def _onchange_deduction_type(self):
        if self.deduction_type == 'fixed' and self.piece_rate_id:
            self.deduction_per_ball = self.piece_rate_id.bladder_deduction
        elif self.deduction_type == 'manual':
            self.deduction_per_ball = 0.0

    @api.depends('qty_full', 'qty_no_bladder', 'rate_full', 'deduction_per_ball', 'repair_charge_ids.total_deduction')
    def _compute_amounts(self):
        for rec in self:
            rec.amount_full = rec.qty_full * rec.rate_full
            effective_rate = max(rec.rate_full - rec.deduction_per_ball, 0)
            rec.amount_no_bladder = rec.qty_no_bladder * effective_rate
            rec.repair_deduction = sum(rec.repair_charge_ids.mapped('total_deduction'))
            rec.amount_due = rec.amount_full + rec.amount_no_bladder - rec.repair_deduction

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('reema.ilo.receipt') or 'New'
        return super().create(vals_list)

    def action_receive(self):
        self.ensure_one()
        total_returned = self.qty_full + self.qty_no_bladder + self.qty_damaged
        if total_returned <= 0:
            raise UserError('Enter at least one ball quantity before confirming receipt.')
        if not self.verified_by:
            raise UserError('Please select the person who counted and verified the returned quantity.')
        # Check that this receipt does not exceed panels originally sent
        already_returned = sum(
            r.qty_full + r.qty_no_bladder + r.qty_damaged
            for r in self.dispatch_id.receipt_ids
            if r.state == 'received' and r.id != self.id
        )
        if already_returned + total_returned > self.dispatch_id.qty_panels:
            raise UserError(
                f'Total returned ({already_returned + total_returned}) would exceed panels originally sent '
                f'({self.dispatch_id.qty_panels}). Please check the quantities.'
            )
        self.state = 'received'
        self.message_post(
            body=f'Received: {self.qty_full} full, {self.qty_no_bladder} no-bladder, '
                 f'{self.qty_damaged} damaged. Verified by {self.verified_by.name}. '
                 f'Amount due: PKR {self.amount_due:,.2f}'
        )


class ReemaIloRepairCharge(models.Model):
    _name = 'reema.ilo.repair.charge'
    _description = 'ILO QC Repair Charge'
    _order = 'date desc'

    dispatch_id = fields.Many2one(
        'reema.ilo.dispatch', string='Dispatch', required=True,
        options={'no_create': True, 'no_edit': True},
    )
    receipt_id = fields.Many2one(
        'reema.ilo.receipt', string='Receipt Batch',
        domain="[('dispatch_id', '=', dispatch_id), ('state', '=', 'received')]",
        options={'no_create': True, 'no_edit': True},
        help='The receipt batch these failed balls came back in.',
    )
    contractor_id = fields.Many2one(related='dispatch_id.contractor_id', string='Contractor', store=True, readonly=True)
    date = fields.Date(string='QC Date', required=True, default=fields.Date.today)
    recorded_by = fields.Many2one('res.users', string='Recorded By (QC Staff)', default=lambda self: self.env.user)
    qty_failed = fields.Integer(string='Balls Failed QC', required=True)
    repair_charge_per_ball = fields.Float(string='Repair Charge per Ball (PKR)', required=True, digits=(10, 2))
    total_deduction = fields.Float(string='Total Deduction (PKR)', compute='_compute_total', store=True, digits=(10, 2))
    notes = fields.Text(string='Failure Reason')

    @api.depends('qty_failed', 'repair_charge_per_ball')
    def _compute_total(self):
        for rec in self:
            rec.total_deduction = rec.qty_failed * rec.repair_charge_per_ball


class ReemaIloPayment(models.Model):
    _name = 'reema.ilo.payment'
    _description = 'ILO Contractor Payment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, name desc'

    name = fields.Char(string='Reference', readonly=True, copy=False, default='New')
    contractor_id = fields.Many2one(
        'res.partner', string='Contractor', required=True,
        domain=[('is_contractor', '=', True)],
        options={'no_create': True, 'no_edit': True},
        tracking=True,
    )
    date = fields.Date(string='Payment Date', required=True, default=fields.Date.today)
    amount = fields.Float(string='Amount (PKR)', required=True, digits=(10, 2))
    payment_type = fields.Selection(
        [('weekly', 'Weekly'), ('advance', 'Advance'), ('immediate', 'Immediate'), ('other', 'Other')],
        string='Payment Type', required=True, default='weekly',
    )
    notes = fields.Text(string='Notes')
    state = fields.Selection(
        [('draft', 'Draft'), ('confirmed', 'Confirmed')],
        string='Status', default='draft', tracking=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('reema.ilo.payment') or 'New'
        return super().create(vals_list)

    def action_confirm(self):
        self.ensure_one()
        if self.amount <= 0:
            raise UserError('Payment amount must be greater than 0.')
        self.state = 'confirmed'
        self.message_post(body=f'Payment of PKR {self.amount:,.2f} confirmed ({self.payment_type}).')
