from odoo import models, fields, api, tools, _
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
    repair_source = fields.Selection(
        [('initial_qc', 'Initial QC'), ('final_qc', 'Final QC')],
        string='Repair Source',
        help='Repair dispatches only: which QC stage sent this ball out for repair — '
             'Initial QC (routes back to Initial QC once returned) or Final QC (Final '
             'QC handles its own repair loop end-to-end, never routes back to Initial QC).',
    )
    repair_count = fields.Integer(
        string='Number of Repairs', default=0,
        help='Repair dispatches only: total individual repair marks across the balls '
             'in this dispatch — a single ball can need more than one repair. Drives '
             'the original contractor\'s deduction (charged immediately at dispatch '
             'time) and the repair contractor\'s eventual payment (realized at Initial '
             'QC Pass) — both at repair-count × rate, not ball count.',
    )
    repair_count_consumed = fields.Boolean(
        string='Repair Count Consumed', default=False, copy=False,
        help='True once this dispatch\'s repair_count has been pulled into a payable '
             'Initial QC Pass entry for the repair contractor — prevents it being '
             'counted into pay twice.',
    )
    qty_lost = fields.Integer(
        string='Balls Lost', default=0,
        help='Balls from this dispatch the contractor has reported as lost — never '
             'coming back. Declared via Stitching Center Receive, not here directly. '
             'Subtracted from every outstanding-balance calculation (same as a receipt '
             'would be) so a lost ball does not block the rest of the batch forever; '
             'generates a deduction charged to whoever lost it (the repair contractor '
             'for a repair dispatch, the original contractor themselves for a '
             'stitching dispatch) rather than reducing what was already charged for '
             'the repair/stitching work itself.',
    )
    qty_scrap = fields.Integer(
        string='Balls Scrapped', default=0,
        help='Final-QC-sourced repair dispatches only: balls from this dispatch that '
             'came back unrepairable and were written off at ReemaFinalQcReceiveWizard. '
             'Subtracted from _final_qc_repair_outstanding same as qty_lost — a '
             'scrapped ball is accounted for (surrendered, not kept by the repair '
             'contractor to keep trying), unlike a rejected one, which stays outstanding. '
             'Initial-QC-sourced repairs never set this: their receive step already '
             'counts a physically-returned ball as accounted for regardless of the '
             'later Pass/Fail/Scrap decision, so no separate netting is needed there.',
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
        never tracked per individual dispatch record.

        Excludes Final-QC-sourced repairs — those are dispatched and returned
        entirely within Final QC's own loop (see is_final_qc), never through a
        Ball Receive Point hall, so they can never appear as 'received' here.

        Nets out qty_lost — a ball reported lost is neither received nor still
        genuinely awaiting return, so it must stop counting as outstanding (or a
        single lost ball would block this work order from ever completing)."""
        dispatches = self.search([
            ('mo_id', '=', mo_id), ('contractor_id', '=', contractor_id),
            ('repair_source', '!=', 'final_qc'),
        ])
        dispatched = sum(dispatches.mapped('qty_balls')) - sum(dispatches.mapped('qty_lost'))
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
        independent numbers instead of one pooled total.

        Excludes Final-QC-sourced repairs — see _ilo_ledger_balance. Nets out
        qty_lost — see _ilo_ledger_balance for why."""
        dispatches = self.search([
            ('mo_id', '=', mo_id), ('contractor_id', '=', contractor_id),
            ('dispatch_type', '=', dispatch_type),
            ('repair_source', '!=', 'final_qc'),
        ])
        dispatched = sum(dispatches.mapped('qty_balls')) - sum(dispatches.mapped('qty_lost'))
        received = sum(self.env['reema.wo.batch.entry'].search([
            ('workorder_id.production_id', '=', mo_id),
            ('workorder_id.workcenter_id.is_ball_receive_point', '=', True),
            ('contractor_id', '=', contractor_id),
            ('ilo_dispatch_type', '=', dispatch_type),
        ]).mapped('qty'))
        return dispatched - received

    @api.model
    def _ilo_repair_balance_by_original(self, mo_id, contractor_id, original_contractor_id):
        """Outstanding repair balance for one specific (repair contractor,
        original contractor) pairing on this MO. A repair contractor can do
        jobs for more than one original contractor on the same MO — once one
        pairing is fully settled, its original contractor must stop being a
        valid target for a NEW receipt, otherwise a receipt can be logged
        against the wrong (already-closed) pairing while it still passes the
        pooled per-contractor balance check. Excludes Final-QC-sourced repairs
        — see _ilo_ledger_balance. Nets out qty_lost — see _ilo_ledger_balance
        for why (this is also what lets the "fully received" QC-visibility gate
        in _ilo_qc_pending_balance_repair ever clear when a ball has been
        declared lost instead of physically returned)."""
        dispatches = self.search([
            ('mo_id', '=', mo_id), ('contractor_id', '=', contractor_id),
            ('original_contractor_id', '=', original_contractor_id),
            ('dispatch_type', '=', 'repair'),
            ('repair_source', '!=', 'final_qc'),
        ])
        dispatched = sum(dispatches.mapped('qty_balls')) - sum(dispatches.mapped('qty_lost'))
        received = sum(self.env['reema.wo.batch.entry'].search([
            ('workorder_id.production_id', '=', mo_id),
            ('workorder_id.workcenter_id.is_ball_receive_point', '=', True),
            ('contractor_id', '=', contractor_id),
            ('original_contractor_id', '=', original_contractor_id),
            ('ilo_dispatch_type', '=', 'repair'),
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
        # Scoped to Initial QC's own leg only — a Final-QC-sourced repair or
        # scrap happens to a ball that already passed Initial QC long ago, so
        # it must not reduce this balance (mirrors the repair_source filter
        # already used in _ilo_repair_outstanding below).
        sent_to_repair = sum(self.search([
            ('mo_id', '=', mo_id), ('dispatch_type', '=', 'repair'),
            ('original_contractor_id', '=', original_contractor_id),
            ('repair_source', '!=', 'final_qc'),
        ]).mapped('qty_balls'))
        scrapped = sum(self.env['reema.ilo.qc.scrap'].search([
            ('mo_id', '=', mo_id), ('contractor_id', '=', original_contractor_id),
            ('workorder_id.workcenter_id.is_initial_qc', '=', True),
        ]).mapped('qty'))
        return received - qc_processed - sent_to_repair - scrapped

    @api.model
    def _ilo_qc_pending_balance_stitching(self, mo_id, original_contractor_id):
        """Same ledger shape as _ilo_qc_pending_balance, scoped to first-time
        (never-repaired) balls only. Historical rows predate the purpose split
        on Initial QC decisions (ilo_dispatch_type left blank) — every one of
        them was, by construction, a first-time decision (repair-purpose
        decisions never existed before this split), so blank folds into this
        bucket rather than being dropped or double-counted."""
        received = sum(self.env['reema.wo.batch.entry'].search([
            ('workorder_id.production_id', '=', mo_id),
            ('workorder_id.workcenter_id.is_ball_receive_point', '=', True),
            ('original_contractor_id', '=', original_contractor_id),
            ('ilo_dispatch_type', 'in', ('stitching', False)),
        ]).mapped('qty'))
        qc_processed = sum(self.env['reema.wo.batch.entry'].search([
            ('workorder_id.production_id', '=', mo_id),
            ('workorder_id.workcenter_id.is_initial_qc', '=', True),
            ('contractor_id', '=', original_contractor_id),
            ('ilo_dispatch_type', 'in', ('stitching', False)),
        ]).mapped('qty'))
        sent_to_repair = sum(self.search([
            ('mo_id', '=', mo_id), ('dispatch_type', '=', 'repair'),
            ('original_contractor_id', '=', original_contractor_id),
            ('repair_source', '!=', 'final_qc'),
            ('batch_entry_id.ilo_dispatch_type', 'in', ('stitching', False)),
        ]).mapped('qty_balls'))
        scrapped = sum(self.env['reema.ilo.qc.scrap'].search([
            ('mo_id', '=', mo_id), ('contractor_id', '=', original_contractor_id),
            ('workorder_id.workcenter_id.is_initial_qc', '=', True),
            ('batch_entry_id.ilo_dispatch_type', 'in', ('stitching', False)),
        ]).mapped('qty'))
        return received - qc_processed - sent_to_repair - scrapped

    @api.model
    def _ilo_qc_pending_balance_repair(self, mo_id, original_contractor_id, repair_contractor_id):
        """Same ledger shape as _ilo_qc_pending_balance, scoped to one specific
        repair contractor's returned work for one original contractor — this
        is what lets Initial QC pay the repair contractor only for balls it
        actually confirms are good, instead of at receive time. No blank
        fallback here: a blank ilo_dispatch_type row can never belong to a
        specific repair contractor (see _ilo_qc_pending_balance_stitching).

        Nothing becomes visible to QC until this repair contractor has brought
        back EVERYTHING dispatched to them for this original contractor on this
        MO — partial receives are allowed and accumulate normally, they just
        stay invisible to QC (and therefore unpayable) until the pair is fully
        settled. User-confirmed design (2026-07-13): receive must stay
        partial-friendly, the gate belongs here instead. Known accepted gap: a
        new dispatch landing on this same pair while an earlier fully-received
        batch is still unprocessed will re-lock the whole pool — intentionally
        not handled, revisit only if it causes a real problem."""
        if self._ilo_repair_balance_by_original(mo_id, repair_contractor_id, original_contractor_id) > 0:
            return 0
        received = sum(self.env['reema.wo.batch.entry'].search([
            ('workorder_id.production_id', '=', mo_id),
            ('workorder_id.workcenter_id.is_ball_receive_point', '=', True),
            ('original_contractor_id', '=', original_contractor_id),
            ('contractor_id', '=', repair_contractor_id),
            ('ilo_dispatch_type', '=', 'repair'),
        ]).mapped('qty'))
        qc_processed = sum(self.env['reema.wo.batch.entry'].search([
            ('workorder_id.production_id', '=', mo_id),
            ('workorder_id.workcenter_id.is_initial_qc', '=', True),
            ('original_contractor_id', '=', original_contractor_id),
            ('contractor_id', '=', repair_contractor_id),
            ('ilo_dispatch_type', '=', 'repair'),
        ]).mapped('qty'))
        sent_to_repair_again = sum(self.search([
            ('mo_id', '=', mo_id), ('dispatch_type', '=', 'repair'),
            ('original_contractor_id', '=', original_contractor_id),
            ('repair_source', '!=', 'final_qc'),
            ('batch_entry_id.ilo_dispatch_type', '=', 'repair'),
            ('batch_entry_id.contractor_id', '=', repair_contractor_id),
        ]).mapped('qty_balls'))
        scrapped = sum(self.env['reema.ilo.qc.scrap'].search([
            ('mo_id', '=', mo_id), ('contractor_id', '=', original_contractor_id),
            ('workorder_id.workcenter_id.is_initial_qc', '=', True),
            ('batch_entry_id.ilo_dispatch_type', '=', 'repair'),
            ('batch_entry_id.contractor_id', '=', repair_contractor_id),
        ]).mapped('qty'))
        return received - qc_processed - sent_to_repair_again - scrapped

    @api.model
    def _ilo_repair_outstanding(self, mo_id, original_contractor_id):
        """Balls of original_contractor_id's production currently out at a
        repair contractor, not yet back. Zero = fully reconciled.

        Excludes Final-QC-sourced repairs — see _ilo_ledger_balance. Those are
        tracked separately by _final_qc_repair_outstanding, scoped to Final
        QC's own gate rather than Initial QC's."""
        sent = sum(self.search([
            ('mo_id', '=', mo_id), ('dispatch_type', '=', 'repair'),
            ('original_contractor_id', '=', original_contractor_id),
            ('repair_source', '!=', 'final_qc'),
        ]).mapped('qty_balls'))
        returned = sum(self.env['reema.wo.batch.entry'].search([
            ('workorder_id.production_id', '=', mo_id),
            ('workorder_id.workcenter_id.is_ball_receive_point', '=', True),
            ('original_contractor_id', '=', original_contractor_id),
            ('ilo_dispatch_type', '=', 'repair'),
        ]).mapped('qty'))
        return sent - returned

    @api.model
    def _final_qc_repair_outstanding(self, mo_id, repair_contractor_id, original_contractor_id):
        """Balls currently out at a Final-QC-sourced repair job for this exact
        (repair contractor, original contractor) pair on this MO, not yet received
        back at Final QC. Unambiguous — dispatch and receive are both tagged with
        both contractor ids, unlike the pending-balance helper below.

        Nets out qty_lost AND qty_scrap — a ball reported lost or scrapped as
        unrepairable is neither received nor still genuinely awaiting return, so
        both must stop counting as outstanding (or a single such ball would
        block this pair from ever reconciling). A rejected/still-defective
        ball is deliberately NOT netted here — it stays with the repair
        contractor to keep working, so it must remain outstanding. Mirrors
        _ilo_repair_balance_by_original."""
        dispatches = self.search([
            ('mo_id', '=', mo_id), ('dispatch_type', '=', 'repair'),
            ('repair_source', '=', 'final_qc'),
            ('contractor_id', '=', repair_contractor_id),
            ('original_contractor_id', '=', original_contractor_id),
        ])
        sent = (
            sum(dispatches.mapped('qty_balls'))
            - sum(dispatches.mapped('qty_lost'))
            - sum(dispatches.mapped('qty_scrap'))
        )
        returned = sum(self.env['reema.wo.batch.entry'].search([
            ('workorder_id.production_id', '=', mo_id),
            ('workorder_id.workcenter_id.is_final_qc', '=', True),
            ('ilo_dispatch_type', '=', 'repair'),
            ('contractor_id', '=', repair_contractor_id),
            ('original_contractor_id', '=', original_contractor_id),
        ]).mapped('qty'))
        return sent - returned

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
                    WHERE repair_source IS DISTINCT FROM 'final_qc'
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


class ReemaIloFlow(models.Model):
    """Combined, chronological feed of every ILO Dispatch AND every ILO
    Received row for the same (MO, contractor, flow type) — so the full
    story (sent → received) is visible in one place instead of needing to
    cross-reference the two separate lists. Read-only, doesn't replace
    either source: reema.ilo.dispatch and reema.wo.batch.entry stay the
    system of record for their own workflows."""
    _name = 'reema.ilo.flow'
    _description = 'ILO Combined Dispatch/Receive Flow'
    _auto = False
    _order = 'date desc'

    reference = fields.Char(string='Reference', readonly=True)
    date = fields.Datetime(string='Date', readonly=True)
    mo_id = fields.Many2one('mrp.production', string='Manufacturing Order', readonly=True)
    contractor_id = fields.Many2one('res.partner', string='Contractor', readonly=True)
    original_contractor_id = fields.Many2one('res.partner', string='Original Contractor', readonly=True)
    dispatch_type = fields.Selection(
        [('stitching', 'Stitching'), ('repair', 'Repair')],
        string='ILO Flow', readonly=True,
    )
    direction = fields.Selection(
        [('dispatched', 'Dispatched'), ('received', 'Received')],
        string='Direction', readonly=True,
    )
    process = fields.Selection(
        [('initial_qc', 'Initial QC'), ('final_qc', 'Final QC')],
        string='Process', readonly=True,
        help='Which QC stage this event belongs to — Initial QC (Stitching Center '
             'Issuance/Receive and its repair loop) or Final QC (its own '
             'self-contained repair loop).',
    )
    qty_sent = fields.Float(string='Sent', readonly=True)
    qty_received = fields.Float(string='Received', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW reema_ilo_flow AS (
                SELECT row_number() OVER (ORDER BY combined.date DESC) AS id,
                       combined.reference,
                       combined.date,
                       combined.mo_id,
                       combined.contractor_id,
                       combined.original_contractor_id,
                       combined.dispatch_type,
                       combined.direction,
                       combined.process,
                       combined.qty_sent,
                       combined.qty_received
                FROM (
                    SELECT
                        d.name                AS reference,
                        d.date::timestamp     AS date,
                        d.mo_id,
                        d.contractor_id,
                        d.original_contractor_id,
                        d.dispatch_type,
                        'dispatched'           AS direction,
                        CASE WHEN d.dispatch_type = 'repair'
                             THEN d.repair_source
                             ELSE 'initial_qc' END AS process,
                        d.qty_balls            AS qty_sent,
                        0                      AS qty_received
                    FROM reema_ilo_dispatch d

                    UNION ALL

                    SELECT
                        be.name                AS reference,
                        be.date                 AS date,
                        be.mo_id,
                        be.contractor_id,
                        be.original_contractor_id,
                        be.ilo_dispatch_type    AS dispatch_type,
                        'received'              AS direction,
                        CASE WHEN wc.is_final_qc
                             THEN 'final_qc'
                             ELSE 'initial_qc' END AS process,
                        0                       AS qty_sent,
                        be.qty                  AS qty_received
                    FROM reema_wo_batch_entry be
                    JOIN mrp_workorder  wo ON wo.id = be.workorder_id
                    JOIN mrp_workcenter wc ON wc.id = wo.workcenter_id
                    WHERE wc.is_ball_receive_point = TRUE
                       OR (wc.is_final_qc = TRUE AND be.ilo_dispatch_type = 'repair')
                ) combined
            )
        """)


class ReemaIloContractorDeduction(models.Model):
    """Repair charge or scrap material-cost charge against the ORIGINAL
    stitching contractor — created at Final QC. Deliberately separate from
    the repair contractor's own payment: the repair contractor gets paid via
    a normal reema.wo.batch.entry (its own is_billed tracks that side), while
    this record tracks whether the deduction has been applied to the
    original contractor's bill yet. The two settle on independent schedules,
    linked here via repair_batch_entry_id for one-place traceability."""
    _name = 'reema.ilo.contractor.deduction'
    _description = 'ILO Contractor Deduction (Repair Charge / Scrap Material Cost)'
    _order = 'date desc'

    name = fields.Char(string='Reference', readonly=True, copy=False, default='New')
    original_contractor_id = fields.Many2one(
        'res.partner', string='Original Contractor', required=True,
        domain="[('is_contractor', '=', True)]",
        help='Whose batch/production this charge traces back to — for repair and '
             'scrap charges this is also who pays it. For a lost-ball charge it is '
             'kept as the true original contractor for accounting-trail purposes '
             'even though charged_contractor_id (not this field) is who actually '
             'pays, since a repair contractor can lose balls belonging to more than '
             'one original contractor and the two must not be conflated.',
    )
    charged_contractor_id = fields.Many2one(
        'res.partner', string='Charged To (if different)',
        domain="[('is_contractor', '=', True)]",
        help='Lost-ball charges only — the contractor actually responsible for the '
             'loss and who pays it, when that differs from original_contractor_id '
             '(a repair contractor losing another contractor\'s ball). Leave blank '
             'for repair/scrap charges, where the original contractor always pays.',
    )
    billed_to_id = fields.Many2one(
        'res.partner', string='Billed To', compute='_compute_billed_to_id', store=True,
        help='charged_contractor_id if set, otherwise original_contractor_id — the '
             'single field bill preparation actually searches on, so repair/scrap '
             'and lost-ball charges can be looked up the same way regardless of '
             'which contractor ends up paying.',
    )
    deduction_type = fields.Selection(
        [('repair', 'Repair Charge'), ('scrap', 'Scrap Material Cost'), ('lost', 'Lost Ball')],
        string='Type', required=True,
    )
    mo_id = fields.Many2one('mrp.production', string='Manufacturing Order')
    reema_product_id = fields.Many2one('product.product', related='mo_id.product_id',
                                       string='Product', store=True)
    reema_po_id = fields.Many2one('reema.production.order', related='mo_id.reema_po_id',
                                  string='PO', store=True)
    qty = fields.Integer(string='Qty', required=True)
    construction_type = fields.Selection(
        [('hs', 'HS'), ('hyb', 'HYB'), ('ms', 'MS'), ('thb', 'THB')],
        string='Construction Type',
        help='Shown for scrap so whoever prices the material cost later knows what '
             'they are pricing.',
    )
    rate = fields.Float(
        string='Rate (PKR)', digits=(10, 2),
        help='Repair only — the ILO Repair piece rate at the time of the charge.',
    )
    amount = fields.Float(
        string='Amount (PKR)', digits=(10, 2),
        help='Repair: computed automatically (qty x rate). Scrap: left blank here — '
             'entered manually when the contractor bill is prepared.',
    )
    state = fields.Selection(
        [('pending', 'Pending'), ('applied', 'Applied')],
        string='Status', default='pending', readonly=True, copy=False,
    )
    bill_id = fields.Many2one(
        'account.move', string='Applied to Bill', readonly=True, copy=False,
        help='The original contractor\'s vendor bill this deduction was added to.',
    )
    account_id = fields.Many2one(
        'account.account', string='Expense Account', readonly=True, copy=False,
        help='Set from the billed work center\'s Labor Expense Account at billing '
             'time (action_create_contractor_bill) — this deduction has no work '
             'center of its own to derive it from. Used to post the actual negative '
             'invoice line at bill confirmation (see AccountMoveDeductionExt.action_post).',
    )
    repair_dispatch_id = fields.Many2one(
        'reema.ilo.dispatch', string='Repair Dispatch', readonly=True,
        help='Repair only — the dispatch this charge is for.',
    )
    scrap_id = fields.Many2one(
        'reema.ilo.qc.scrap', string='Scrap Record', readonly=True,
        help='Scrap only — the scrap record this charge is for.',
    )
    repair_batch_entry_id = fields.Many2one(
        'reema.wo.batch.entry', string='Repair Contractor Payable Entry', readonly=True,
        help='Repair only — the repair contractor\'s own payable batch entry for this '
             'job. Tracked independently via its own Billed status; kept here purely '
             'for cross-reference ("charged to X because Y did this repair, which is '
             '[billed/unbilled] as entry Z").',
    )
    batch_entry_id = fields.Many2one(
        'reema.wo.batch.entry', string='Originating Batch Entry', readonly=True,
        help='Lost-ball charges only — the receive-side batch entry logged in the same '
             'session this charge was created in. Repair/scrap charges are already '
             'traceable via repair_dispatch_id/scrap_id, so this is only set for "lost" '
             'deductions, letting deletion of that batch entry detect and block on it '
             '(the Balls Lost adjustment it triggered on the dispatch record cannot be '
             'auto-reversed).',
    )
    date = fields.Date(string='Date', default=fields.Date.today)
    recorded_by = fields.Many2one('res.users', string='Recorded By', default=lambda self: self.env.user)
    notes = fields.Char(string='Notes')

    @api.depends('charged_contractor_id', 'original_contractor_id')
    def _compute_billed_to_id(self):
        for ded in self:
            ded.billed_to_id = ded.charged_contractor_id or ded.original_contractor_id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('reema.ilo.contractor.deduction') or 'New'
        return super().create(vals_list)

    def action_return_to_pending(self):
        for ded in self:
            if ded.bill_id and (ded.bill_id.state != 'draft' or ded.bill_id.reema_bill_state != 'pending'):
                raise UserError(
                    f'Cannot remove {ded.name} from its bill: the bill is no '
                    'longer in the drafting stage.'
                )
            ded.bill_id.message_post(body=_(
                'ILO deduction removed: %(name)s — PKR %(amount).2f'
            ) % {'name': ded.name, 'amount': ded.amount})
        self.write({'state': 'pending', 'bill_id': False})

    def action_apply_selected_to_bill(self):
        bill = self.env['account.move'].browse(self.env.context.get('reema_pick_bill_id', []))
        if not bill:
            raise UserError('No bill to add these deductions to.')
        if not self:
            raise UserError('Select at least one deduction to add.')
        if bill.state != 'draft' or bill.reema_bill_state != 'pending':
            raise UserError('This bill is no longer in the drafting stage.')
        account = bill.batch_entry_ids[:1]._reema_expense_account()
        for ded in self:
            ded.write({
                'state': 'applied',
                'bill_id': bill.id,
                'account_id': ded.account_id.id or account.id,
            })
        bill.message_post(body=_(
            'ILO deduction(s) added: %(lines)s'
        ) % {'lines': ', '.join(f'{d.name} — PKR {d.amount:.2f}' for d in self)})
        return {'type': 'ir.actions.act_window_close'}


class ReemaIloQcScrap(models.Model):
    _name = 'reema.ilo.qc.scrap'
    _description = 'ILO Initial QC Scrap / Write-off'
    _order = 'date desc'

    mo_id = fields.Many2one('mrp.production', string='Manufacturing Order', required=True)
    workorder_id = fields.Many2one('mrp.workorder', string='Work Order', required=True)
    workcenter_id = fields.Many2one(
        'mrp.workcenter', related='workorder_id.workcenter_id', string='Hall', store=True,
        help='Which hall logged this scrap — Initial QC and Final QC both write to this '
             'model, so this is the only way to tell them apart in the combined list.',
    )
    batch_entry_id = fields.Many2one(
        'reema.wo.batch.entry', string='Batch Entry',
        help='The pass-qty entry created in the same QC decision this scrap was '
             'logged alongside — lets that entry\'s own scrap qty be shown '
             'per-decision instead of only as a cumulative MO/contractor total.',
    )
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
