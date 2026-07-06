from odoo import models, fields, api, tools
from odoo.exceptions import UserError



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
        domain="[('is_contractor', '=', True)]",
        options={'no_create': True, 'no_edit': True},
        tracking=True,
    )
    date = fields.Date(string='Dispatch Date', required=True, default=fields.Date.today)
    dispatched_by = fields.Many2one(
        'res.users', string='Dispatched By', required=True,
        default=lambda self: self.env.user,
    )
    product_id = fields.Many2one(
        related='mo_id.product_id', string='Item', store=True, readonly=True,
    )
    ball_size = fields.Char(string='Ball Size', required=True)
    construction_type = fields.Selection(
        [('hs', 'HS'), ('hyb', 'HYB'), ('ms', 'MS'), ('thb', 'THB')],
        string='Construction Type', required=True,
    )
    qty_balls = fields.Integer(string='Balls Sent', required=True)
    rate = fields.Float(string='Rate per Ball (PKR)', digits=(10, 2))
    batch_entry_id = fields.Many2one(
        'reema.wo.batch.entry', string='Batch Log Entry', readonly=True,
        help='The batch log entry on the Stitching Center Issuance work order that created this pass.',
    )
    notes = fields.Text(string='Notes')
    state = fields.Selection(
        [('dispatched', 'Pending Return'), ('sent', 'Sent'), ('closed', 'Closed')],
        string='Status', default='dispatched', tracking=True,
    )
    dispatch_type = fields.Selection(
        [('stitching', 'Stitching'), ('repair', 'Repair')],
        string='Dispatch Type', default='stitching', required=True, tracking=True,
    )
    original_contractor_id = fields.Many2one(
        'res.partner', string='Original Contractor',
        domain="[('is_contractor', '=', True)]",
        help='The contractor who ultimately gets production credit and any repair '
             'deduction for these balls. Equals Contractor for stitching dispatches; '
             'for repair dispatches this is the ORIGINAL stitcher, not the repair '
             'contractor performing the fix.',
    )
    defect_type = fields.Selection(
        [('bad_stitching', 'Bad Stitching'), ('missing_panel', 'Missing Panel'),
         ('missing_bladder', 'Missing Bladder'), ('other', 'Other')],
        string='Defect Type',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('reema.ilo.dispatch') or 'New'
            if vals.get('dispatch_type', 'stitching') == 'stitching' and not vals.get('original_contractor_id'):
                vals['original_contractor_id'] = vals.get('contractor_id')
        return super().create(vals_list)

    @api.model
    def _ilo_contractors_for_mo(self, mo_id):
        """ILO contractors relevant to this MO, read directly off their dispatch
        records — not off any work order's contractor_ids. Ball Receive is an
        employee-type hall with no contractor assignment of its own; contractor
        identity for that step always traces back to who was dispatched to at
        Stitching Center Issuance."""
        return self.search([('mo_id', '=', mo_id)]).mapped('contractor_id')

    @api.model
    def _ilo_ledger_balance(self, mo_id, contractor_id):
        """Outstanding balls for (MO, contractor): total dispatched to ILO minus
        total logged back in at any 'Ball Receive Point' work center. Ledger-style —
        never tracked per individual dispatch record."""
        dispatched = sum(self.search([
            ('mo_id', '=', mo_id), ('contractor_id', '=', contractor_id),
        ]).mapped('qty_balls'))
        received = sum(self.env['reema.wo.batch.entry'].search([
            ('workorder_id.production_id', '=', mo_id),
            ('workorder_id.workcenter_id.is_ball_receive_point', '=', True),
            ('contractor_id', '=', contractor_id),
        ]).mapped('qty'))
        return dispatched - received

    @api.model
    def _ilo_ledger_balance_by_type(self, mo_id, contractor_id, dispatch_type):
        """Same ledger as _ilo_ledger_balance but scoped to one dispatch type
        (stitching or repair), so a contractor who is both doing their own
        stitching AND repairing someone else's balls on the same MO gets two
        independent numbers instead of one pooled total."""
        dispatched = sum(self.search([
            ('mo_id', '=', mo_id), ('contractor_id', '=', contractor_id),
            ('dispatch_type', '=', dispatch_type),
        ]).mapped('qty_balls'))
        received = sum(self.env['reema.wo.batch.entry'].search([
            ('workorder_id.production_id', '=', mo_id),
            ('workorder_id.workcenter_id.is_ball_receive_point', '=', True),
            ('contractor_id', '=', contractor_id),
            ('ilo_dispatch_type', '=', dispatch_type),
        ]).mapped('qty'))
        return dispatched - received

    @api.model
    def _ilo_original_contractors_for_mo(self, mo_id):
        """Original-production-credit contractors for this MO, read off
        original_contractor_id (not contractor_id) — covers both stitching
        dispatches (where the two are equal) and repair dispatches (where
        contractor_id is the repair contractor instead)."""
        return self.search([('mo_id', '=', mo_id)]).mapped('original_contractor_id')

    @api.model
    def _ilo_qc_pending_balance(self, mo_id, original_contractor_id):
        """Balls of original_contractor_id's production sitting at Initial QC
        awaiting a Pass/Fail/Scrap decision — first-time deliveries and repair
        returns combined."""
        received = sum(self.env['reema.wo.batch.entry'].search([
            ('workorder_id.production_id', '=', mo_id),
            ('workorder_id.workcenter_id.is_ball_receive_point', '=', True),
            ('original_contractor_id', '=', original_contractor_id),
        ]).mapped('qty'))
        qc_processed = sum(self.env['reema.wo.batch.entry'].search([
            ('workorder_id.production_id', '=', mo_id),
            ('workorder_id.workcenter_id.is_initial_qc', '=', True),
            ('contractor_id', '=', original_contractor_id),
        ]).mapped('qty'))
        sent_to_repair = sum(self.search([
            ('mo_id', '=', mo_id), ('dispatch_type', '=', 'repair'),
            ('original_contractor_id', '=', original_contractor_id),
        ]).mapped('qty_balls'))
        scrapped = sum(self.env['reema.ilo.qc.scrap'].search([
            ('mo_id', '=', mo_id), ('contractor_id', '=', original_contractor_id),
        ]).mapped('qty'))
        return received - qc_processed - sent_to_repair - scrapped

    @api.model
    def _ilo_repair_outstanding(self, mo_id, original_contractor_id):
        """Balls of original_contractor_id's production currently out at a
        repair contractor, not yet back. Zero = fully reconciled."""
        sent = sum(self.search([
            ('mo_id', '=', mo_id), ('dispatch_type', '=', 'repair'),
            ('original_contractor_id', '=', original_contractor_id),
        ]).mapped('qty_balls'))
        returned = sum(self.env['reema.wo.batch.entry'].search([
            ('workorder_id.production_id', '=', mo_id),
            ('workorder_id.workcenter_id.is_ball_receive_point', '=', True),
            ('original_contractor_id', '=', original_contractor_id),
            ('ilo_dispatch_type', '=', 'repair'),
        ]).mapped('qty'))
        return sent - returned

    @api.model
    def _ilo_stitching_payable(self, mo_id, original_contractor_id):
        """Net payable for the original stitching contractor: gross on every
        ball that ultimately passed QC, minus the repair deduction for every
        ball that needed fixing. 'finalized' means nothing is still pending
        inspection or stuck out at repair — safe to actually pay."""
        qty_passed = sum(self.env['reema.wo.batch.entry'].search([
            ('workorder_id.production_id', '=', mo_id),
            ('workorder_id.workcenter_id.is_initial_qc', '=', True),
            ('contractor_id', '=', original_contractor_id),
        ]).mapped('qty'))
        stitch_dispatches = self.search([
            ('mo_id', '=', mo_id), ('dispatch_type', '=', 'stitching'),
            ('contractor_id', '=', original_contractor_id),
        ])
        rate = stitch_dispatches[:1].rate or 0.0
        repair_dispatches = self.search([
            ('mo_id', '=', mo_id), ('dispatch_type', '=', 'repair'),
            ('original_contractor_id', '=', original_contractor_id),
        ])
        qty_repaired = sum(repair_dispatches.mapped('qty_balls'))
        deduction = sum(d.qty_balls * d.rate for d in repair_dispatches)
        gross = qty_passed * rate
        finalized = (
            self._ilo_qc_pending_balance(mo_id, original_contractor_id) == 0
            and self._ilo_repair_outstanding(mo_id, original_contractor_id) == 0
        )
        return {
            'qty_passed': qty_passed, 'qty_repaired': qty_repaired,
            'gross': gross, 'deduction': deduction, 'net': gross - deduction,
            'finalized': finalized,
        }

    @api.model
    def _ilo_repair_payable(self, mo_id, repair_contractor_id):
        """Fee owed to whoever performed repair work, independent of whose
        original production it was — based on repaired balls actually
        physically returned (Ball Receive), not merely dispatched for repair."""
        returned_qty = sum(self.env['reema.wo.batch.entry'].search([
            ('workorder_id.production_id', '=', mo_id),
            ('workorder_id.workcenter_id.is_ball_receive_point', '=', True),
            ('contractor_id', '=', repair_contractor_id),
            ('ilo_dispatch_type', '=', 'repair'),
        ]).mapped('qty'))
        repair_dispatches = self.search([
            ('mo_id', '=', mo_id), ('dispatch_type', '=', 'repair'),
            ('contractor_id', '=', repair_contractor_id),
        ])
        rate = repair_dispatches[:1].rate or 0.0
        return {'qty': returned_qty, 'amount': returned_qty * rate}

    def action_close(self):
        # Fulfillment is no longer tracked per dispatch — the (MO, contractor)
        # ledger balance (dispatched vs. logged at the ILO receiving step) is
        # the source of truth. "Closed" here is an advisory manual marker only.
        self.ensure_one()
        self.state = 'closed'


class ReemaIloBalance(models.Model):
    """Dispatched vs. Received ledger, one row per (MO, Contractor, Stitching/
    Repair) — dispatch.state (dispatched/sent/closed) is never updated after
    creation, so it can't tell you what's actually still outstanding. This
    view recomputes the real balance on every read, same ledger logic as
    _ilo_ledger_balance_by_type, so 'Pending' always reflects reality."""
    _name = 'reema.ilo.balance'
    _description = 'ILO Dispatched vs Received Balance'
    _auto = False
    _order = 'contractor_id, mo_id, dispatch_type'

    mo_id = fields.Many2one('mrp.production', string='Manufacturing Order', readonly=True)
    contractor_id = fields.Many2one('res.partner', string='Contractor', readonly=True)
    dispatch_type = fields.Selection(
        [('stitching', 'Stitching'), ('repair', 'Repair')],
        string='ILO Flow', readonly=True,
    )
    qty_dispatched = fields.Integer(string='Qty Dispatched', readonly=True)
    qty_received = fields.Integer(string='Qty Received', readonly=True)
    qty_outstanding = fields.Integer(string='Qty Outstanding', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW reema_ilo_balance AS (
                SELECT
                    row_number() OVER (ORDER BY rp.name, mp.name, d.dispatch_type) AS id,
                    d.mo_id,
                    d.contractor_id,
                    d.dispatch_type,
                    d.qty_dispatched,
                    COALESCE(r.qty_received, 0)                             AS qty_received,
                    d.qty_dispatched - COALESCE(r.qty_received, 0)          AS qty_outstanding
                FROM (
                    SELECT mo_id, contractor_id, dispatch_type, SUM(qty_balls) AS qty_dispatched
                    FROM reema_ilo_dispatch
                    GROUP BY mo_id, contractor_id, dispatch_type
                ) d
                JOIN mrp_production mp ON mp.id = d.mo_id
                JOIN res_partner    rp ON rp.id = d.contractor_id
                LEFT JOIN (
                    SELECT
                        rwo.production_id    AS mo_id,
                        wbe.contractor_id,
                        wbe.ilo_dispatch_type AS dispatch_type,
                        SUM(wbe.qty)          AS qty_received
                    FROM reema_wo_batch_entry wbe
                    JOIN mrp_workorder  rwo ON rwo.id = wbe.workorder_id
                    JOIN mrp_workcenter rwc ON rwc.id = rwo.workcenter_id
                    WHERE rwc.is_ball_receive_point = TRUE
                    GROUP BY rwo.production_id, wbe.contractor_id, wbe.ilo_dispatch_type
                ) r ON r.mo_id = d.mo_id
                   AND r.contractor_id = d.contractor_id
                   AND r.dispatch_type = d.dispatch_type
            )
        """)


class ReemaIloQcScrap(models.Model):
    _name = 'reema.ilo.qc.scrap'
    _description = 'ILO Initial QC Scrap / Write-off'
    _order = 'date desc'

    mo_id = fields.Many2one('mrp.production', string='Manufacturing Order', required=True)
    workorder_id = fields.Many2one('mrp.workorder', string='Work Order', required=True)
    contractor_id = fields.Many2one(
        'res.partner', string='Original Contractor', required=True,
        domain="[('is_contractor', '=', True)]",
        help='The contractor whose production this scrap is charged against.',
    )
    qty = fields.Integer(string='Balls Scrapped', required=True)
    defect_type = fields.Selection(
        [('bad_stitching', 'Bad Stitching'), ('missing_panel', 'Missing Panel'),
         ('missing_bladder', 'Missing Bladder'), ('other', 'Other')],
        string='Defect Type',
    )
    date = fields.Date(string='Date', default=fields.Date.today)
    recorded_by = fields.Many2one('res.users', string='Recorded By', default=lambda self: self.env.user)
    notes = fields.Text(string='Notes')


class ReemaIloReceipt(models.Model):
    _name = 'reema.ilo.receipt'
    _description = 'ILO Receipt'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, name desc'

    name = fields.Char(string='Reference', readonly=True, copy=False, default='New')
    dispatch_id = fields.Many2one(
        'reema.ilo.dispatch', string='Dispatch', required=True,
        domain=[('state', 'in', ('dispatched', 'sent'))],
        options={'no_create': True, 'no_edit': True},
        tracking=True,
    )
    contractor_id = fields.Many2one(
        related='dispatch_id.contractor_id', string='Contractor', store=True, readonly=True,
    )
    mo_id = fields.Many2one(
        related='dispatch_id.mo_id', string='Manufacturing Order', store=True, readonly=True,
    )
    ball_size = fields.Char(related='dispatch_id.ball_size', store=True, readonly=True)
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
        'reema.piece.rate', string='Piece Rate',
        domain="[('workcenter_id.is_ilo', '=', True)]",
        options={'no_create': True, 'no_edit': True},
    )
    rate_full = fields.Float(string='Rate per Ball (PKR)', digits=(10, 2))
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

    @api.onchange('dispatch_id')
    def _onchange_dispatch_id(self):
        if not self.dispatch_id:
            return
        wo = self.env['mrp.workorder'].search([
            ('production_id', '=', self.dispatch_id.mo_id.id),
            ('workcenter_id.is_ilo', '=', True),
        ], limit=1)
        if wo and wo.operation_id.piece_rate_id:
            self.piece_rate_id = wo.operation_id.piece_rate_id
            self.rate_full = wo.operation_id.piece_rate_id.rate

    @api.onchange('piece_rate_id')
    def _onchange_piece_rate_id(self):
        if self.piece_rate_id:
            self.rate_full = self.piece_rate_id.rate

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
        sibling_receipts = self.env['reema.ilo.receipt'].search([
            ('dispatch_id', '=', self.dispatch_id.id),
            ('state', '=', 'received'),
            ('id', '!=', self.id),
        ])
        already_returned = sum(
            r.qty_full + r.qty_no_bladder + r.qty_damaged
            for r in sibling_receipts
        )
        if already_returned + total_returned > self.dispatch_id.qty_balls:
            raise UserError(
                f'Total returned ({already_returned + total_returned}) would exceed balls originally sent '
                f'({self.dispatch_id.qty_balls}). Please check the quantities.'
            )
        self.state = 'received'
        self._message_log(
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
        domain="[('is_contractor', '=', True)]",
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
        self._message_log(body=f'Payment of PKR {self.amount:,.2f} confirmed ({self.payment_type}).')
