from odoo import _, api, fields, models

from odoo.addons.reema_mrp.models.reema_repair import DEFECT_TYPE_SELECTION


class ReemaBillDeduction(models.Model):
    _name = 'reema.bill.deduction'
    _description = 'Contractor Bill Advance Deduction'

    bill_id = fields.Many2one('account.move', required=True, ondelete='cascade')
    description = fields.Char(required=True)
    amount = fields.Float(digits=(12, 2), required=True)
    deduction_account_id = fields.Many2one(
        'account.account',
        string='Recovery Account',
        required=True,
        domain=[('account_type', 'in', ['asset_current', 'asset_receivable'])],
    )

    @api.model_create_multi
    def create(self, vals_list):
        # The Advances tab's default_deduction_account_id context only has a
        # value once the contractor has an advance account (created the first
        # time an Advance Voucher is posted for them). A contractor who's
        # never had one yet arrives here with no default and the field is
        # readonly in the view, so without this the line fails to save with
        # a bare "mandatory field not set" error. Auto-provision the account
        # here instead — same lazy on-first-use creation the Advance Voucher
        # itself relies on (see _get_or_create_advance_account).
        for vals in vals_list:
            if not vals.get('deduction_account_id') and vals.get('bill_id'):
                bill = self.env['account.move'].browse(vals['bill_id'])
                vals['deduction_account_id'] = bill.partner_id._get_or_create_advance_account().id
        records = super().create(vals_list)
        for rec in records:
            rec.bill_id._message_log(body=_(
                'Advance deduction added: %(desc)s — PKR %(amount).2f'
            ) % {'desc': rec.description, 'amount': rec.amount})
        return records

    def unlink(self):
        for rec in self:
            rec.bill_id._message_log(body=_(
                'Advance deduction removed: %(desc)s — PKR %(amount).2f'
            ) % {'desc': rec.description, 'amount': rec.amount})
        return super().unlink()


class ReemaBillCharge(models.Model):
    """One ad-hoc adjustment per row — description + account + amount, sign
    decides direction. Positive adds to what the contractor is paid (bonus,
    reimbursement, urgent-job premium); negative subtracts (a quick deduction
    that doesn't fit ILO/Scrap/Advance). Kept separate from Advance Deductions
    (always a subtraction, always against the contractor's own Advance
    Account) and Production Deductions (computed from production activity,
    never typed in) — this is the free-form catch-all for everything else."""
    _name = 'reema.bill.charge'
    _description = 'Contractor Bill Additional Charge'

    bill_id = fields.Many2one('account.move', required=True, ondelete='cascade')
    name = fields.Char(string='Description', required=True)
    account_id = fields.Many2one('account.account', string='Account', required=True)
    amount = fields.Float(
        digits=(12, 2), required=True,
        help='Positive adds to Net Payable, negative subtracts.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            rec.bill_id._message_log(body=_(
                'Misc charge added: %(desc)s — PKR %(amount).2f'
            ) % {'desc': rec.name, 'amount': rec.amount})
        return records

    def unlink(self):
        for rec in self:
            rec.bill_id._message_log(body=_(
                'Misc charge removed: %(desc)s — PKR %(amount).2f'
            ) % {'desc': rec.name, 'amount': rec.amount})
        return super().unlink()


class AccountMoveLineDeductionExt(models.Model):
    _inherit = 'account.move.line'

    reema_is_deduction_line = fields.Boolean(default=False)


class AccountMoveDeductionExt(models.Model):
    _inherit = 'account.move'

    # Core account.move defines invoice_line_ids with
    # domain=[('display_type', 'in', ('product', 'line_section', 'line_note'))]
    # — a *field-level* domain, which the ORM enforces on every read (unlike a
    # view-level domain, which only shapes the "Add" dialog and never hides
    # already-linked rows). Narrowing it further to exclude
    # reema_is_deduction_line keeps the injected deduction lines out of the
    # Bill Lines tab everywhere, automatically — they're still real
    # account.move.line rows (still in line_ids, still display_type=
    # 'product'), so amount_total (computed from line_ids, not
    # invoice_line_ids — see AccountMove._compute_amount) is unaffected.
    invoice_line_ids = fields.One2many(
        domain=[
            ('display_type', 'in', ('product', 'line_section', 'line_note')),
            ('reema_is_deduction_line', '=', False),
        ],
    )

    reema_deduction_ids = fields.One2many(
        'reema.bill.deduction', 'bill_id', string='Advance Deductions'
    )
    reema_total_deductions = fields.Float(
        string='Total Deductions',
        compute='_compute_reema_deductions',
        store=True,
        digits=(12, 2),
    )
    # ILO repair/lost charges and shop-floor scrap charges — pulled in
    # automatically at bill creation (action_create_contractor_bill), not
    # entered here. Kept as their own tab, separate from Advance Deductions
    # (a manual, accountant-entered recovery of an unrelated prior advance):
    # these trace back to a specific dispatch/scrap record and are computed
    # from production activity, not typed in from scratch.
    reema_ilo_deduction_ids = fields.One2many(
        'reema.ilo.contractor.deduction', 'bill_id', string='ILO Deductions',
    )
    reema_scrap_deduction_ids = fields.One2many(
        'reema.production.scrap', 'bill_id', string='Scrap Deductions',
    )
    # Hybrid/machine-stitched repair penalties — same "pulled in automatically,
    # not typed in here" reasoning as the two fields above. See reema_repair.py.
    reema_repair_penalty_ids = fields.One2many(
        'reema.repair.penalty', 'bill_id', string='Repair Penalties',
    )
    reema_total_production_deductions = fields.Float(
        string='Total Production Deductions',
        compute='_compute_reema_deductions',
        store=True,
        digits=(12, 2),
    )
    reema_charge_ids = fields.One2many(
        'reema.bill.charge', 'bill_id', string='Additional Charges',
    )
    reema_total_charges = fields.Float(
        string='Total Charges',
        compute='_compute_reema_deductions',
        store=True,
        digits=(12, 2),
    )
    reema_net_payable = fields.Float(
        string='Net Payable',
        compute='_compute_reema_deductions',
        store=True,
        digits=(12, 2),
    )
    reema_can_edit_deductions = fields.Boolean(
        compute='_compute_reema_can_edit_deductions',
    )
    reema_price_editable = fields.Boolean(
        compute='_compute_reema_price_editable',
    )
    reema_contractor_advance_account_id = fields.Many2one(
        'account.account',
        compute='_compute_reema_contractor_advance_account_id',
        string='Contractor Advance Account',
    )
    # Shown on the Advances tab so the accountant can see what the contractor
    # currently owes back to the company before typing a deduction line —
    # previously this meant leaving the bill, checking the ledger, and coming
    # back. Not stored: it's a live balance, not a fact about this bill.
    reema_outstanding_advance = fields.Float(
        string='Outstanding Advance (PKR)',
        compute='_compute_reema_outstanding_advance',
        digits=(12, 2),
    )
    # Informational only — never applied automatically. Long Term Advances
    # carry a suggested per-bill recovery amount (set on the voucher); this
    # surfaces that as a hint on the Advances tab so the accountant remembers
    # to enter it, without the system silently adding a deduction line itself.
    reema_suggested_deduction_note = fields.Char(
        string='Suggested Deduction',
        compute='_compute_reema_suggested_deduction_note',
    )
    # Cash/Bank Voucher list columns (reema_cash_bank_voucher_views.xml) need a
    # single "amount moved" figure — amount_total is 0 for plain journal
    # entries (move_type='entry') since it's computed from invoice lines only,
    # which these don't have. Sum of the debit side always equals the total
    # value of a balanced entry, regardless of how many lines it has.
    reema_voucher_amount = fields.Monetary(
        string='Voucher Amount',
        compute='_compute_reema_voucher_amount',
        currency_field='currency_id',
    )

    @api.depends('line_ids.debit')
    def _compute_reema_voucher_amount(self):
        for move in self:
            move.reema_voucher_amount = sum(move.line_ids.mapped('debit'))

    @api.depends(
        'reema_deduction_ids.amount', 'reema_ilo_deduction_ids.amount',
        'reema_scrap_deduction_ids.amount', 'reema_repair_penalty_ids.amount',
        'reema_charge_ids.amount', 'invoice_line_ids.price_subtotal',
    )
    def _compute_reema_deductions(self):
        for move in self:
            # Deliberately NOT move.amount_total: action_post() injects these
            # same deductions as negative reema_is_deduction_line rows at
            # posting time, which would make amount_total already-net —
            # subtracting the deductions from it a second time here would
            # double-count them post-posting. invoice_line_ids' domain already
            # excludes reema_is_deduction_line rows (see field override
            # above), so summing it stays correct in both draft (no deduction
            # lines exist yet) and posted (they exist, but in line_ids only) states.
            gross = sum(move.invoice_line_ids.mapped('price_subtotal'))
            advance = sum(move.reema_deduction_ids.mapped('amount'))
            production = (
                sum(move.reema_ilo_deduction_ids.mapped('amount'))
                + sum(move.reema_scrap_deduction_ids.mapped('amount'))
                + sum(move.reema_repair_penalty_ids.mapped('amount'))
            )
            # Charges already carry their own sign per row (positive adds,
            # negative subtracts), so a plain sum nets them correctly.
            charges = sum(move.reema_charge_ids.mapped('amount'))
            move.reema_total_deductions = advance
            move.reema_total_production_deductions = production
            move.reema_total_charges = charges
            move.reema_net_payable = gross - advance - production + charges

    @api.depends_context('uid')
    def _compute_reema_can_edit_deductions(self):
        is_accountant = self.env.user.has_group('account.group_account_manager')
        for move in self:
            move.reema_can_edit_deductions = is_accountant

    @api.depends_context('uid')
    def _compute_reema_price_editable(self):
        # Supervisor prepares the bill and enters the scrap/deduction cost
        # (the common case); production manager mostly just validates, but
        # can also enter it — and covers for the supervisor when absent.
        can_edit = (
            self.env.user.has_group('reema_mrp.group_reema_supervisor')
            or self.env.user.has_group('reema_mrp.group_reema_production_manager')
        )
        for move in self:
            move.reema_price_editable = can_edit

    @api.depends('partner_id')
    def _compute_reema_contractor_advance_account_id(self):
        for move in self:
            move.reema_contractor_advance_account_id = (
                move.partner_id.reema_advance_account_id
                if move.partner_id else False
            )

    @api.depends('partner_id')
    def _compute_reema_outstanding_advance(self):
        for move in self:
            move.reema_outstanding_advance = (
                move.partner_id._get_outstanding_advance() if move.partner_id else 0.0
            )

    @api.depends('partner_id')
    def _compute_reema_suggested_deduction_note(self):
        for move in self:
            move.reema_suggested_deduction_note = False
            if not move.partner_id:
                continue
            outstanding = move.partner_id._get_outstanding_advance()
            if outstanding <= 0:
                continue
            advances = self.env['reema.contractor.advance'].sudo().search([
                ('partner_id', '=', move.partner_id.id),
                ('advance_type', '=', 'long_term'),
                ('state', '=', 'posted'),
            ])
            per_bill = sum(advances.mapped('deduction_per_bill'))
            if per_bill:
                move.reema_suggested_deduction_note = _(
                    'Long Term Advance active — suggested deduction this bill: '
                    'PKR %(per_bill)s (Outstanding: PKR %(outstanding)s)'
                ) % {'per_bill': '%.2f' % per_bill, 'outstanding': '%.2f' % outstanding}

    def action_view_advance_ledger(self):
        """Open the posted journal items on this contractor's advance account
        in a new browser tab — for when the accountant wants the actual
        transaction trail behind the Outstanding Advance figure shown on the
        Advances tab, not just the total. A plain 'ir.actions.act_window'
        opens in-place (dialog or breadcrumb), never a real new tab, so this
        redirects to the stored action's URL via 'ir.actions.act_url' instead
        — the same trick action_print_contractor_bill uses for reports."""
        self.ensure_one()
        account = self.reema_contractor_advance_account_id
        if not account:
            return False
        return {
            'type': 'ir.actions.act_url',
            'url': '/odoo/%s/action-reema_accounting.action_reema_advance_ledger' % account.id,
            'target': 'new',
        }

    def action_print_contractor_bill(self):
        # Open the Contractor Bill HTML preview in a new browser tab (works for
        # a single bill from the form, or several selected bills from the
        # list). The user prints with the browser (Ctrl+P) and closes the tab.
        if not self:
            return False
        return {
            'type': 'ir.actions.act_url',
            'url': '/report/html/reema_accounting.report_contractor_bill/%s' % ','.join(str(i) for i in self.ids),
            'target': 'new',
        }

    def _get_starting_sequence(self):
        # EXTENDS account (sequence.mixin) — core always uses a 4-digit year
        # (see account_move.py's "%04d" % move_date.year). Accountant
        # explicitly wants a 2-digit year on every journal (Journal Vouchers,
        # Vendor Bills, Customer Invoices, Stock Valuation, Bank, Cash), not
        # just Bank/Cash where this was first fixed. Only called when
        # there's no matching previous entry to derive the format from
        # (first entry ever for that journal, or a new year) — mid-year
        # continuations already match the 2-digit-year regex from a prior
        # entry and don't hit this method. For journals that already have
        # 2026 entries in the old 4-digit format (Customer Invoices, Stock
        # Valuation), this only takes effect starting 2027 unless those
        # existing entries are renamed to the new format first.
        starting_sequence = super()._get_starting_sequence()
        move_date = self.date or self.invoice_date or fields.Date.context_today(self)
        parts = starting_sequence.split('/')
        if len(parts) >= 2:
            parts[1] = move_date.strftime('%y')
            starting_sequence = '/'.join(parts)
        return starting_sequence

    def action_force_register_payment(self):
        # Both the bill form's Pay button and the Ready to Pay list's Pay
        # buttons (row-level and bulk) funnel through this method before
        # opening the account.payment.register wizard. Contractor bills get
        # a dedicated wizard view (view_account_payment_register_form_
        # reema_contractor in account_menu_views.xml): Amount/Memo locked,
        # no Currency picker, no Recipient Bank — once a bill is approved
        # and posted, the payable amount shouldn't change at payment time;
        # any correction has to happen before that, through the approval
        # flow. Other vendor bills / customer invoices keep opening the
        # standard core wizard, untouched.
        action = super().action_force_register_payment()
        if isinstance(action, dict) and self.filtered('batch_entry_ids'):
            view = self.env.ref(
                'reema_accounting.view_account_payment_register_form_reema_contractor',
                raise_if_not_found=False,
            )
            if view:
                action['views'] = [(view.id, 'form')]
        return action

    def action_post(self):
        for move in self:
            if not (move.reema_deduction_ids or move.reema_ilo_deduction_ids
                    or move.reema_scrap_deduction_ids or move.reema_repair_penalty_ids
                    or move.reema_charge_ids):
                continue
            # Remove any lines injected by a previous post (reset-to-draft → re-post).
            # Must search line_ids, not invoice_line_ids — its domain now excludes
            # these rows (see the field override above), so it would never find them.
            move.line_ids.filtered('reema_is_deduction_line').unlink()
            # Inject one negative journal line per deduction — Advance Deductions,
            # then the Production Deductions tab (ILO repair/lost + shop-floor
            # scrap), so the actual posted bill amount is reduced by all of them
            # even though none of these ever show in the visible Bill Lines list.
            # Written to line_ids (not invoice_line_ids) since that field's
            # domain would otherwise exclude these on create too.
            new_lines = [
                (0, 0, {
                    'name': d.description,
                    'account_id': d.deduction_account_id.id,
                    'quantity': 1.0,
                    'price_unit': -d.amount,
                    'reema_is_deduction_line': True,
                })
                for d in move.reema_deduction_ids
            ]
            new_lines += [
                (0, 0, {
                    'name': f'{d.name} — {dict(d._fields["deduction_type"].selection)[d.deduction_type]}',
                    'account_id': d.account_id.id,
                    'quantity': 1.0,
                    'price_unit': -d.amount,
                    'reema_is_deduction_line': True,
                })
                for d in move.reema_ilo_deduction_ids
            ]
            new_lines += [
                (0, 0, {
                    'name': f'{s.name} — Scrap Material Cost ({s.reason_id.name})',
                    # workcenter_id.expense_account_id needs sudo: posting a bill is an
                    # accounting action, but the accountant/approver posting it may not
                    # have Manufacturing access to read mrp.workcenter directly.
                    'account_id': s.sudo().workcenter_id.expense_account_id.id,
                    'quantity': 1.0,
                    'price_unit': -s.amount,
                    'reema_is_deduction_line': True,
                })
                for s in move.reema_scrap_deduction_ids
            ]
            new_lines += [
                (0, 0, {
                    'name': f'{p.name} — Repair Penalty ({dict(DEFECT_TYPE_SELECTION)[p.defect_type]})',
                    'account_id': p.account_id.id,
                    'quantity': 1.0,
                    'price_unit': -p.amount,
                    'reema_is_deduction_line': True,
                })
                for p in move.reema_repair_penalty_ids
            ]
            # Charges already carry their own sign (positive adds, negative
            # subtracts) — unlike the deduction lines above, not negated here.
            new_lines += [
                (0, 0, {
                    'name': c.name,
                    'account_id': c.account_id.id,
                    'quantity': 1.0,
                    'price_unit': c.amount,
                    'reema_is_deduction_line': True,
                })
                for c in move.reema_charge_ids
            ]
            move.write({'line_ids': new_lines})
            move._message_log(body=_(
                'Bill posted with deductions/charges applied — Total: PKR %(total).2f, '
                'Advances: PKR %(adv).2f, QC Charges: PKR %(qc).2f, Misc: PKR %(misc).2f, '
                'Net Payable: PKR %(net).2f'
            ) % {
                'total': move.amount_total,
                'adv': move.reema_total_deductions,
                'qc': move.reema_total_production_deductions,
                'misc': move.reema_total_charges,
                'net': move.reema_net_payable,
            })
        res = super().action_post()
        # Odoo's own auto-generated "Contractors Payable" balancing line
        # (display_type='payment_term') is left with an empty name — on the
        # General Ledger that shows up as a row with no label at all telling
        # the reader what the entry is for. Only computed to its final form
        # once actually posted, hence after super().action_post() rather
        # than alongside the deduction lines above.
        for move in self.filtered('batch_entry_ids'):
            term_line = move.line_ids.filtered(lambda l: l.display_type == 'payment_term')
            if not term_line:
                continue
            workcenters = []
            for wc in move.invoice_line_ids.mapped('reema_batch_entry_id.workorder_id.workcenter_id.name'):
                if wc and wc not in workcenters:
                    workcenters.append(wc)
            suffix = '/'.join(workcenters) if workcenters else 'Contractor Bill'
            term_line.write({'name': '%s — %s' % (move.partner_id.name, suffix)})
        return res
