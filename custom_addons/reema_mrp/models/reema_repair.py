from odoo import models, fields, api, _
from odoo.exceptions import UserError

# Defect types where the ball still goes through the exact same repair loop
# (out to Shell Closing, redone, back to QC), but the penalty against the
# at-fault contractor is NOT the flat 25 PKR/repair rate — it's priced
# manually later, same as a scrap material cost, since these are rare/
# unusual faults with no fixed formula.
EDGE_CASE_DEFECT_TYPES = {'wrong_stamp_color', 'wrong_lamination'}

DEFECT_TYPE_SELECTION = [
    ('bad_stitching', 'Bad Stitching'),
    ('bad_printing', 'Bad Printing (Few Panels)'),
    ('wrong_bladder_weight', 'Wrong Bladder Weight'),
    ('wrong_panel_printed', 'Wrong Panel Printed'),
    ('wrong_stamp_color', 'Wrong Stamp / Color Printing'),
    ('wrong_lamination', 'Wrong Lamination'),
    ('other', 'Other'),
]


class ReemaRepairJob(models.Model):
    """A ball/batch sent back for rework after a hybrid/machine-stitched QC
    fault — the in-house equivalent of the hand-stitched (ILO) repair
    dispatch. Shell Closing only cuts the shell back open and, once it comes
    back, closes it again (flat 25 PKR for that pair of bookend tasks) — the
    actual defect fix (re-stitching, re-padding, re-printing, whatever
    fault_workcenter_id says) is done by the ORIGINAL/fault contractor, who
    gets a deduction instead of a payment for it."""
    _name = 'reema.repair.job'
    _description = 'Repair Job (Hybrid / Machine-Stitched QC)'
    _order = 'date desc'

    name = fields.Char(string='Reference', readonly=True, copy=False, default='New')
    mo_id = fields.Many2one('mrp.production', string='Manufacturing Order', required=True)
    workorder_id = fields.Many2one(
        'mrp.workorder', string='QC Work Order', required=True,
        help='The Initial QC or Final QC work order that found this fault.',
    )
    repair_source = fields.Selection(
        [('initial_qc', 'Initial QC'), ('final_qc', 'Final QC')],
        string='Found At', required=True,
        help='Which QC stage found this fault — the ball always comes back '
             'to this same stage for the final Pass decision, never the other one.',
    )
    fault_workcenter_id = fields.Many2one(
        'mrp.workcenter', string='Fault Hall', required=True,
        help='Which hall\'s work is at fault (Lamination, Cutting, Printing, '
             'Sorting, Stitching, Padding, Turning, Bladder Pasting, Panel Binding).',
    )
    fault_contractor_id = fields.Many2one(
        'res.partner', string='Fault Contractor', required=True,
        domain="[('id', 'in', available_fault_contractor_ids)]",
        help='The contractor charged for this fault — deducted now, regardless '
             'of outcome, same reasoning as the hand-stitched repair flow.',
    )
    available_fault_contractor_ids = fields.Many2many(
        'res.partner', compute='_compute_available_fault_contractor_ids',
        string='Contractors on this MO',
    )
    repair_contractor_id = fields.Many2one(
        'res.partner', string='Repair Contractor (Shell Closing)', required=True,
        domain="[('id', 'in', available_repair_contractor_ids)]",
        help='The Shell Closing contractor who cuts the shell open and closes '
             'it again once the fault contractor hands it back fixed — paid '
             'the flat rate for that pair of tasks once Received & Paid.',
    )
    available_repair_contractor_ids = fields.Many2many(
        'res.partner', compute='_compute_available_repair_contractor_ids',
        string='Shell Closing Contractors',
    )
    qty_balls = fields.Integer(string='Balls Affected', required=True)
    repair_count = fields.Integer(
        string='Number of Repairs', required=True,
        help='Total individual faulty panels/repair marks across the affected '
             'balls — a ball can need more than one repair. Must be at least '
             'Balls Affected. Drives the fault contractor\'s penalty and the '
             'Shell Closing contractor\'s eventual pay.',
    )
    defect_type = fields.Selection(DEFECT_TYPE_SELECTION, string='Defect Type', required=True)
    is_edge_case = fields.Boolean(
        string='Edge Case', compute='_compute_is_edge_case', store=True,
        help='True for defect types priced manually later (Wrong Stamp/Color, '
             'Wrong Lamination) instead of the flat 25 PKR/repair rate.',
    )
    state = fields.Selection(
        [
            ('pending', 'Pending (Out for Repair)'),
            ('closed', 'Received & Paid'),
            ('scrapped', 'Scrapped (Unrepairable)'),
        ],
        string='Status', default='pending', required=True, tracking=True,
    )
    # Balls trickle back in whatever quantity actually shows up, not necessarily
    # all of qty_balls at once — QC on the shop floor doesn't track which
    # specific repairs belong to which ball, only a running ball count. These
    # two are running totals, updated by the resolve wizard, never entered
    # directly — the job auto-finalizes the moment they add up to qty_balls
    # (see _finalize_if_resolved).
    qty_received = fields.Integer(string='Balls Received', default=0, readonly=True)
    qty_scrapped = fields.Integer(string='Balls Scrapped', default=0, readonly=True)
    qty_remaining = fields.Integer(
        string='Balls Remaining', compute='_compute_qty_remaining',
        help='qty_balls minus whatever has been received or scrapped so far.',
    )
    date = fields.Datetime(string='Date', default=fields.Datetime.now)
    reported_by = fields.Many2one('res.users', string='Reported By', default=lambda self: self.env.user)
    closed_date = fields.Datetime(string='Closed Date', readonly=True)
    batch_entry_id = fields.Many2one(
        'reema.wo.batch.entry', string='Shell Closing Payable Entry', readonly=True,
        help='The payable batch entry created for the Shell Closing contractor '
             'once this job is fully resolved and paid.',
    )
    scrap_ids = fields.One2many(
        'reema.production.scrap', 'repair_job_id', string='Scrap Entries',
        help='One entry per partial Scrap logged against the fault hall while '
             'this job was being resolved — there can be more than one.',
    )
    notes = fields.Char(string='Notes')

    @api.depends('qty_balls', 'qty_received', 'qty_scrapped')
    def _compute_qty_remaining(self):
        for job in self:
            job.qty_remaining = job.qty_balls - job.qty_received - job.qty_scrapped

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('reema.repair.job') or 'New'
            if not vals.get('repair_source') and vals.get('workorder_id'):
                wc = self.env['mrp.workorder'].browse(vals['workorder_id']).workcenter_id
                vals['repair_source'] = 'final_qc' if wc.is_final_qc else 'initial_qc'
        return super().create(vals_list)

    @api.depends('defect_type')
    def _compute_is_edge_case(self):
        for job in self:
            job.is_edge_case = job.defect_type in EDGE_CASE_DEFECT_TYPES

    @api.depends('mo_id')
    def _compute_available_fault_contractor_ids(self):
        for job in self:
            job.available_fault_contractor_ids = self.env['reema.wo.batch.entry'].search([
                ('mo_id', '=', job.mo_id.id),
            ]).mapped('contractor_id') if job.mo_id else self.env['res.partner']

    @api.depends('mo_id')
    def _compute_available_repair_contractor_ids(self):
        for job in self:
            job.available_repair_contractor_ids = job._shell_closing_workorder().contractor_ids

    def _shell_closing_workorder(self):
        self.ensure_one()
        if not self.mo_id:
            return self.env['mrp.workorder']
        return self.env['mrp.workorder'].search([
            ('production_id', '=', self.mo_id.id),
            ('workcenter_id.is_shell_closing', '=', True),
        ], limit=1)

    @api.model
    def _repair_rate(self):
        """The single flat rate used both to deduct the fault contractor and
        to pay the Shell Closing contractor for a normal (non-edge-case)
        repair. Deliberately separate from the ILO Center's own Repair rate —
        the two are unrelated."""
        return self.env['reema.piece.rate'].search([
            ('workcenter_id.is_shell_closing', '=', True), ('work_type', '=ilike', 'Repair'),
        ], limit=1)

    def action_open_resolve_wizard(self):
        """Log balls coming back and/or being written off as scrap, in
        whatever partial quantity actually showed up today — can be called
        more than once until the job is fully accounted for."""
        self.ensure_one()
        if self.state != 'pending':
            raise UserError(f'{self.name} has already been resolved.')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Resolve Repair Job',
            'res_model': 'reema.repair.resolve.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_repair_job_id': self.id},
        }

    def _resolve_partial(self, qty_received, qty_scrapped, scrap_reason_id, notes=None):
        """Adds to the running received/scrapped counts and, if this fully
        accounts for qty_balls, finalizes the job. Called by
        ReemaRepairResolveWizard.action_confirm — kept on the job itself so
        the wizard stays a thin input form."""
        self.ensure_one()
        if self.state != 'pending':
            raise UserError(f'{self.name} has already been resolved.')
        if qty_received < 0 or qty_scrapped < 0:
            raise UserError('Quantities cannot be negative.')
        total_now = qty_received + qty_scrapped
        if total_now <= 0:
            raise UserError('Enter at least one ball received or scrapped.')
        if total_now > self.qty_remaining:
            raise UserError(
                f'Only {self.qty_remaining} ball(s) are still outstanding on {self.name} '
                f'— cannot log {total_now}.'
            )
        if qty_scrapped > 0:
            if not scrap_reason_id:
                raise UserError('Select a scrap reason for the scrapped quantity.')
            # Filed against the QC work order that raised this job (where the
            # ball actually was when it was written off), not the fault hall —
            # the fault hall's own row/ledger is never touched by a repair
            # outcome. Blame stays intact via contractor_id below, which the
            # scrap report shows as "Charged To" independently of which hall
            # the entry is filed under.
            self.env['reema.production.scrap'].create({
                'workorder_id': self.workorder_id.id,
                'contractor_id': self.fault_contractor_id.id,
                'qty': self.workorder_id._balls_to_units(qty_scrapped),
                'reason_id': scrap_reason_id,
                'repair_job_id': self.id,
                'notes': notes or f'Repair job {self.name} — unrepairable.',
            })
        self.write({
            'qty_received': self.qty_received + qty_received,
            'qty_scrapped': self.qty_scrapped + qty_scrapped,
        })
        self.mo_id._message_log(
            body=f'Repair job {self.name} — {qty_received} ball(s) received, '
                 f'{qty_scrapped} ball(s) scrapped '
                 f'({self.qty_remaining} still outstanding).'
        )
        self._finalize_if_resolved()

    def _finalize_if_resolved(self):
        """Once received + scrapped accounts for every ball on this job, pay
        Shell Closing and close it out. QC never tracks which repairs belong
        to which specific ball, so the payout follows the shop-floor
        convention instead of trying to split repair_count precisely:
        - Nothing scrapped: pay the full original repair_count, as if the
          whole batch came back clean.
        - Some scrapped: pay 1 repair credited per ball actually received
          (the minimum every ball must carry), the rest written off — on the
          assumption the balls that never came back were the worst ones.
        - Nothing received at all (100% scrapped): pay nothing, same as a
          fully-scrapped job today.
        """
        self.ensure_one()
        if self.qty_remaining > 0:
            return
        if self.qty_scrapped == 0:
            pay_repairs = self.repair_count
        else:
            pay_repairs = self.qty_received
        if pay_repairs <= 0:
            self.write({'state': 'scrapped', 'closed_date': fields.Datetime.now()})
            self.mo_id._message_log(
                body=f'Repair job {self.name} — fully scrapped, nothing received. '
                     f'No payment to {self.repair_contractor_id.name}.'
            )
            return
        rate = self._repair_rate()
        if not rate:
            raise UserError(
                'No "Repair" piece rate is configured on the Shell Closing work center. '
                'Create one under Manufacturing → Configuration → Piece Rates before confirming.'
            )
        shell_wo = self._shell_closing_workorder()
        if not shell_wo:
            raise UserError(
                f'No Shell Closing work order found on {self.mo_id.name}. '
                'Cannot log the payable entry for the repair contractor.'
            )
        written_off = self.repair_count - pay_repairs
        notes = f'Repair job {self.name} — {dict(DEFECT_TYPE_SELECTION)[self.defect_type]}'
        if written_off > 0:
            notes += f' ({written_off} repair(s) written off against scrapped balls)'
        entry = self.env['reema.wo.batch.entry'].create({
            'workorder_id': shell_wo.id,
            'contractor_id': self.repair_contractor_id.id,
            'qty': pay_repairs,
            'piece_rate_id': rate.id,
            'notes': notes,
        })
        self.write({'state': 'closed', 'closed_date': fields.Datetime.now(), 'batch_entry_id': entry.id})
        self.mo_id._message_log(
            body=f'Repair job {self.name} fully resolved — {self.repair_contractor_id.name} '
                 f'paid for {pay_repairs} repair(s).'
                 + (f' {written_off} repair(s) written off (scrapped balls).' if written_off > 0 else '')
        )


class ReemaRepairResolveWizard(models.TransientModel):
    """Log whatever quantity of a Repair Job's balls actually showed up today
    — received good, scrapped, or a mix of both. Can be opened again on the
    same job as more balls trickle back, until qty_remaining hits 0."""
    _name = 'reema.repair.resolve.wizard'
    _description = 'Resolve Repair Job (partial receive/scrap)'

    repair_job_id = fields.Many2one('reema.repair.job', string='Repair Job', required=True, readonly=True)
    fault_workcenter_id = fields.Many2one(related='repair_job_id.fault_workcenter_id', readonly=True)
    fault_contractor_id = fields.Many2one(related='repair_job_id.fault_contractor_id', readonly=True)
    qty_balls = fields.Integer(related='repair_job_id.qty_balls', string='Balls Affected', readonly=True)
    qty_remaining = fields.Integer(related='repair_job_id.qty_remaining', readonly=True)
    qty_received = fields.Integer(string='Balls Received Now', default=0)
    qty_scrapped = fields.Integer(string='Balls Scrapped Now', default=0)
    scrap_reason_id = fields.Many2one(
        'reema.scrap.reason', string='Scrap Reason',
        options="{'no_create': True, 'no_edit': True}",
        help='Required if logging any scrapped balls.',
    )
    notes = fields.Char(string='Notes')

    def action_confirm(self):
        self.ensure_one()
        self.repair_job_id._resolve_partial(
            self.qty_received, self.qty_scrapped, self.scrap_reason_id.id, self.notes,
        )
        return {'type': 'ir.actions.act_window_close'}


class ReemaRepairPenalty(models.Model):
    """The charge against the at-fault contractor for a hybrid/machine-stitched
    repair job — created the moment the fault is logged, same reasoning as the
    hand-stitched flow (they caused the repair, charged now regardless of
    outcome). Mirrors reema.production.scrap's billing shape."""
    _name = 'reema.repair.penalty'
    _description = 'Repair Penalty (Hybrid / Machine-Stitched QC)'
    _order = 'date desc'

    name = fields.Char(string='Reference', readonly=True, copy=False, default='New')
    repair_job_id = fields.Many2one('reema.repair.job', string='Repair Job', required=True, ondelete='cascade')
    fault_contractor_id = fields.Many2one(
        'res.partner', related='repair_job_id.fault_contractor_id', string='Charged To', store=True,
    )
    mo_id = fields.Many2one('mrp.production', related='repair_job_id.mo_id', string='MO', store=True)
    reema_product_id = fields.Many2one('product.product', related='mo_id.product_id', string='Product', store=True)
    reema_po_id = fields.Many2one('reema.production.order', related='mo_id.reema_po_id', string='PO', store=True)
    defect_type = fields.Selection(
        DEFECT_TYPE_SELECTION, related='repair_job_id.defect_type', string='Defect Type', store=True,
    )
    qty = fields.Integer(string='Repairs', required=True)
    rate = fields.Float(string='Rate (PKR)', digits=(10, 2))
    # Normal defect types: computed immediately (qty x rate). Edge-case defect
    # types: left at 0, entered manually later when the bill is prepared —
    # same pattern as reema.production.scrap.amount.
    amount = fields.Float(string='Amount (PKR)', digits=(10, 2))
    is_billed = fields.Boolean(string='Billed', default=False)
    bill_id = fields.Many2one('account.move', string='Bill', readonly=True, copy=False)
    account_id = fields.Many2one('account.account', string='Expense Account', readonly=True, copy=False)
    date = fields.Date(string='Date', default=fields.Date.today)
    recorded_by = fields.Many2one('res.users', string='Recorded By', default=lambda self: self.env.user)
    notes = fields.Char(string='Notes')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('reema.repair.penalty') or 'New'
        return super().create(vals_list)

    def action_return_to_pending(self):
        for penalty in self:
            if penalty.bill_id and (penalty.bill_id.state != 'draft' or penalty.bill_id.reema_bill_state != 'pending'):
                raise UserError(
                    f'Cannot remove {penalty.name} from its bill: the bill is '
                    'no longer in the drafting stage.'
                )
            penalty.bill_id.message_post(body=_(
                'Repair penalty removed: %(name)s — PKR %(amount).2f'
            ) % {'name': penalty.name, 'amount': penalty.amount})
        self.write({'is_billed': False, 'bill_id': False})

    def action_apply_selected_to_bill(self):
        bill = self.env['account.move'].browse(self.env.context.get('reema_pick_bill_id', []))
        if not bill:
            raise UserError('No bill to add these penalties to.')
        if not self:
            raise UserError('Select at least one penalty to add.')
        if bill.state != 'draft' or bill.reema_bill_state != 'pending':
            raise UserError('This bill is no longer in the drafting stage.')
        self.write({'is_billed': True, 'bill_id': bill.id})
        bill.message_post(body=_(
            'Repair penalty/penalties added: %(lines)s'
        ) % {'lines': ', '.join(f'{p.name} — PKR {p.amount:.2f}' for p in self)})
        return {'type': 'ir.actions.act_window_close'}
