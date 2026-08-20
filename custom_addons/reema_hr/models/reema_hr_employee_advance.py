import math

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ReemaHrEmployeeAdvance(models.Model):
    _name = 'reema.hr.employee.advance'
    _description = 'Employee Advance / Loan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Voucher No.', readonly=True, copy=False,
        default=lambda self: _('New'), tracking=True,
    )
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, tracking=True)
    date = fields.Date(string='Date', required=True, default=fields.Date.context_today)
    journal_id = fields.Many2one(
        'account.journal', string='Payment Method', required=True,
        domain=[('type', 'in', ('cash', 'bank'))],
    )
    purpose = fields.Char(
        string='Description', required=True,
        help='Reason for the advance/loan — used as the journal entry label.',
    )
    advance_type = fields.Selection([
        ('advance', 'Advance Against Salary'),
        ('loan', 'Loan (Installments)'),
    ], string='Type', default='advance', required=True, tracking=True,
        help='Advance Against Salary: recovered in full on the next payslip.\n'
             'Loan: recovered in fixed installments over several payslips.')
    amount = fields.Float(string='Amount', digits=(12, 2), required=True)
    installment_amount = fields.Float(
        string='Installment Amount', digits=(12, 2),
        help='Amount deducted per payslip until this loan is fully recovered. '
             'Required for Loans — ignored for a plain Advance, which is always recovered in full.',
    )
    installments_count = fields.Integer(string='No. of Installments', compute='_compute_installments_count')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('closed', 'Closed'),
        ('cancelled', 'Cancelled'),
    ], default='draft', required=True, copy=False, tracking=True)
    move_id = fields.Many2one('account.move', string='Journal Entry', readonly=True, copy=False)
    reversal_move_id = fields.Many2one('account.move', string='Reversal Entry', readonly=True, copy=False)
    line_ids = fields.One2many('reema.hr.employee.advance.line', 'advance_id', string='Installments')
    advance_account_id = fields.Many2one(
        'account.account', string='Advances & Loans Account', compute='_compute_advance_account_id',
    )
    outstanding_advance_loan = fields.Float(
        string='Outstanding Balance', digits=(12, 2), compute='_compute_outstanding',
        help='Employee\'s current unrecovered advances/loans balance, before this voucher.',
    )
    balance_remaining = fields.Float(
        string='Balance Remaining', digits=(12, 2), compute='_compute_balance_remaining',
    )
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)

    @api.depends('amount', 'installment_amount', 'advance_type')
    def _compute_installments_count(self):
        for rec in self:
            if rec.advance_type == 'advance' or not rec.installment_amount:
                rec.installments_count = 1
            else:
                rec.installments_count = math.ceil(rec.amount / rec.installment_amount)

    @api.depends('employee_id')
    def _compute_advance_account_id(self):
        for rec in self:
            rec.advance_account_id = rec.employee_id.reema_advance_loan_account_id

    @api.depends('employee_id')
    def _compute_outstanding(self):
        for rec in self:
            rec.outstanding_advance_loan = (
                rec.employee_id._get_outstanding_advance_loan() if rec.employee_id else 0.0
            )

    @api.depends('line_ids.amount', 'line_ids.state')
    def _compute_balance_remaining(self):
        for rec in self:
            rec.balance_remaining = sum(rec.line_ids.filtered(lambda l: l.state == 'due').mapped('amount'))

    @api.constrains('amount', 'advance_type', 'installment_amount')
    def _check_amounts(self):
        for rec in self:
            if rec.amount <= 0:
                raise UserError(_('Amount must be greater than zero.'))
            if rec.advance_type == 'loan' and rec.installment_amount <= 0:
                raise UserError(_('Please enter an Installment Amount for a Loan.'))

    def unlink(self):
        if any(rec.state in ('posted', 'closed') for rec in self):
            raise UserError(_('A posted advance/loan cannot be deleted — reverse it instead.'))
        return super().unlink()

    def action_confirm(self):
        for rec in self:
            if rec.amount <= 0:
                raise UserError(_('Amount must be greater than zero.'))
            if rec.name == _('New'):
                rec.name = self.env['ir.sequence'].next_by_code('reema.hr.employee.advance') or _('New')
            advance_account = rec.employee_id._get_or_create_advance_loan_account()
            liquidity_account = rec.journal_id.default_account_id
            if not liquidity_account:
                raise UserError(_('Selected payment method has no default account configured.'))
            type_label = dict(rec._fields['advance_type'].selection).get(rec.advance_type)
            line_name = f'{type_label} — {rec.purpose}'
            move = self.env['account.move'].create({
                'move_type': 'entry',
                'journal_id': rec.journal_id.id,
                'date': rec.date,
                'line_ids': [
                    (0, 0, {
                        'account_id': advance_account.id,
                        'name': line_name,
                        'debit': rec.amount,
                        'credit': 0.0,
                    }),
                    (0, 0, {
                        'account_id': liquidity_account.id,
                        'name': line_name,
                        'debit': 0.0,
                        'credit': rec.amount,
                    }),
                ],
            })
            move.action_post()
            rec._generate_installment_lines()
            rec.write({'move_id': move.id, 'state': 'posted'})
            rec._message_log(
                body=_('%s of %s posted to %s via %s.') % (
                    dict(rec._fields['advance_type'].selection).get(rec.advance_type),
                    rec.amount, advance_account.display_name, rec.journal_id.name,
                ),
            )

    def _generate_installment_lines(self):
        self.ensure_one()
        if self.advance_type == 'advance':
            self.line_ids = [(0, 0, {'sequence': 1, 'amount': self.amount, 'state': 'due'})]
            return
        n = math.ceil(self.amount / self.installment_amount)
        lines = []
        allocated = 0.0
        for seq in range(1, n + 1):
            amount = self.installment_amount
            if seq == n:
                amount = round(self.amount - allocated, 2)
            allocated += amount
            lines.append((0, 0, {'sequence': seq, 'amount': amount, 'state': 'due'}))
        self.line_ids = lines

    def action_void(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only a draft voucher can be voided.'))
            rec.write({'state': 'cancelled'})

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state != 'cancelled':
                raise UserError(_('Only a cancelled voucher can be reset to draft.'))
            rec.write({'state': 'draft'})

    def action_reverse(self):
        for rec in self:
            if rec.state != 'posted':
                raise UserError(_('Only a posted, unrecovered voucher can be reversed.'))
            if any(line.state == 'paid' for line in rec.line_ids):
                raise UserError(_('Cannot reverse — one or more installments have already been recovered against a payslip.'))
            reversal = rec.move_id._reverse_moves(default_values_list=[{
                'ref': _('Reversal of %s') % rec.name,
                'date': fields.Date.context_today(rec),
            }])
            reversal.action_post()
            rec.write({'reversal_move_id': reversal.id, 'state': 'cancelled'})
            rec._message_log(body=_('Advance/loan reversed by %s.') % self.env.user.name)

    @api.model
    def action_open_account_ledger(self, account_id):
        """Opens an account's Journal Items in a new browser tab. Called directly
        via RPC from a client-side widget (not a type="object" button) — a
        button click always saves the record first (core Odoo behavior), which
        would silently persist a still-being-filled-in draft voucher just from
        clicking this informational link. @api.model + a plain account_id
        (not self) means it works identically whether the voucher has been
        saved yet or not.

        A plain act_window with target='new' only opens a dialog in the same
        tab, so this creates a one-off act_window record with the domain
        baked in and redirects to it via act_url (target='new'), which the
        web client opens with window.open — a genuine new tab."""
        account = self.env['account.account'].browse(account_id)
        if not account.exists():
            raise UserError(_('Account not found.'))
        # ir.actions.act_window create is restricted to group_system by default —
        # sudo() only covers creating this throwaway navigation record; the
        # account.move.line data itself is still access-checked normally when
        # the new tab loads.
        action = self.env['ir.actions.act_window'].sudo().create({
            'name': _('Ledger — %s') % account.display_name,
            'res_model': 'account.move.line',
            'view_mode': 'list,form',
            'domain': [('account_id', '=', account.id)],
            'context': {'search_default_posted': 1},
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/odoo/action-{action.id}',
            'target': 'new',
        }


class ReemaHrEmployeeAdvanceLine(models.Model):
    _name = 'reema.hr.employee.advance.line'
    _description = 'Employee Advance/Loan Installment'
    _order = 'advance_id, sequence'

    advance_id = fields.Many2one('reema.hr.employee.advance', required=True, ondelete='cascade')
    employee_id = fields.Many2one(related='advance_id.employee_id', store=True, string='Employee')
    advance_type = fields.Selection(related='advance_id.advance_type', store=True, string='Type')
    sequence = fields.Integer(string='#')
    amount = fields.Float(string='Amount', digits=(12, 2))
    state = fields.Selection([
        ('due', 'Due'),
        ('paid', 'Paid'),
    ], default='due', required=True)
    payslip_id = fields.Many2one('reema.hr.payslip', string='Recovered In Payslip', readonly=True, copy=False)
