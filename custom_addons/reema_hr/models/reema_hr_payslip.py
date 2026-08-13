import calendar

from odoo import _, api, fields, models
from odoo.exceptions import UserError

SALARY_EXPENSE_CODE = '6-1-1-01'
SALARY_PAYABLE_CODE = '2-1-3-01'
EOBI_PAYABLE_CODE = '2-1-3-02'
PESSI_PAYABLE_CODE = '2-1-3-04'


def _default_date_from(self):
    today = fields.Date.context_today(self)
    return today.replace(day=1)


def _default_date_to(self):
    today = fields.Date.context_today(self)
    last_day = calendar.monthrange(today.year, today.month)[1]
    return today.replace(day=last_day)


class ReemaHrPayslip(models.Model):
    _name = 'reema.hr.payslip'
    _description = 'Payslip'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Payslip No.', readonly=True, copy=False,
        default=lambda self: _('New'), tracking=True,
    )
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, tracking=True)
    currency_id = fields.Many2one(related='employee_id.currency_id', string='Currency')
    date_from = fields.Date(string='From', required=True, default=_default_date_from)
    date_to = fields.Date(string='To', required=True, default=_default_date_to)
    daily_rate = fields.Monetary(string='Daily Rate', currency_field='currency_id', related='employee_id.daily_rate')

    present_days = fields.Float(string='Present Days', readonly=True)
    half_days = fields.Float(string='Half Days', readonly=True)
    absent_days = fields.Integer(string='Absent Days', readonly=True)
    leave_days = fields.Integer(string='Leave Days', readonly=True)

    gross_pay = fields.Monetary(string='Gross Pay', currency_field='currency_id', readonly=True)
    late_deduction = fields.Monetary(string='Late Deduction', currency_field='currency_id', readonly=True)
    net_salary_expense = fields.Monetary(string='Net Salary Expense', currency_field='currency_id', readonly=True)
    advance_loan_deduction = fields.Monetary(string='Advance/Loan Deduction', currency_field='currency_id', readonly=True, copy=False)
    eobi_deduction = fields.Monetary(string='EOBI Deduction', currency_field='currency_id', readonly=True, copy=False)
    pessi_deduction = fields.Monetary(string='PESSI Deduction', currency_field='currency_id', readonly=True, copy=False)
    net_pay = fields.Monetary(
        string='Net Pay', currency_field='currency_id', compute='_compute_net_pay', store=True,
    )

    pending_advance_loan_amount = fields.Monetary(
        string='Pending Advances/Loans', currency_field='currency_id',
        compute='_compute_pending_advance_loan', help='Informational preview of what is currently outstanding — actual amount recovered is fixed when this payslip is confirmed.',
    )

    advance_loan_line_recovered_ids = fields.One2many(
        'reema.hr.employee.advance.line', 'payslip_id', string='Advance/Loan Installments Recovered',
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('paid', 'Paid'),
        ('cancelled', 'Cancelled'),
    ], default='draft', required=True, copy=False, tracking=True)
    move_id = fields.Many2one('account.move', string='Accrual Entry', readonly=True, copy=False)
    payment_move_id = fields.Many2one('account.move', string='Payment Entry', readonly=True, copy=False)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)

    _sql_constraints = [
        ('date_check', 'CHECK(date_from <= date_to)', 'From date must be before or equal to the To date.'),
    ]

    @api.depends('net_salary_expense', 'advance_loan_deduction', 'eobi_deduction', 'pessi_deduction')
    def _compute_net_pay(self):
        for rec in self:
            rec.net_pay = (
                rec.net_salary_expense - rec.advance_loan_deduction
                - rec.eobi_deduction - rec.pessi_deduction
            )

    @api.depends('employee_id')
    def _compute_pending_advance_loan(self):
        for rec in self:
            rec.pending_advance_loan_amount = (
                sum(rec.employee_id._get_next_due_advance_lines().mapped('amount'))
                if rec.employee_id else 0.0
            )

    @api.onchange('employee_id', 'date_from', 'date_to')
    def _onchange_recompute_attendance(self):
        for rec in self:
            if rec.employee_id and rec.date_from and rec.date_to:
                rec._recompute_from_attendance()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._recompute_from_attendance()
        return records

    def action_recompute(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only a draft payslip can be recomputed.'))
        self._recompute_from_attendance()

    def _recompute_from_attendance(self):
        for rec in self:
            if rec.state != 'draft' or not rec.employee_id:
                continue
            attendance = self.env['reema.hr.attendance'].search([
                ('employee_id', '=', rec.employee_id.id),
                ('date', '>=', rec.date_from),
                ('date', '<=', rec.date_to),
            ])
            present = len(attendance.filtered(lambda a: a.state == 'present'))
            half = len(attendance.filtered(lambda a: a.state == 'half_day'))
            absent = len(attendance.filtered(lambda a: a.state == 'absent'))
            leave = len(attendance.filtered(lambda a: a.state == 'leave'))
            late_deduction = sum(attendance.mapped('late_deduction'))
            gross_pay = rec.employee_id.daily_rate * (present + 0.5 * half)
            rec.write({
                'present_days': present,
                'half_days': half,
                'absent_days': absent,
                'leave_days': leave,
                'gross_pay': gross_pay,
                'late_deduction': late_deduction,
                'net_salary_expense': gross_pay - late_deduction,
                'eobi_deduction': rec.employee_id.eobi_amount if rec.employee_id.has_eobi else 0.0,
                'pessi_deduction': rec.employee_id.pessi_amount if rec.employee_id.has_pessi else 0.0,
            })

    def _get_salary_expense_account(self):
        account = self.env['account.account'].search([('code', '=', SALARY_EXPENSE_CODE)], limit=1)
        if not account:
            raise UserError(_('Salary Expense account %s not found in the Chart of Accounts.') % SALARY_EXPENSE_CODE)
        return account

    def _get_salary_payable_account(self):
        account = self.env['account.account'].search([('code', '=', SALARY_PAYABLE_CODE)], limit=1)
        if not account:
            raise UserError(_('Salaries Payable account %s not found in the Chart of Accounts.') % SALARY_PAYABLE_CODE)
        return account

    def _get_eobi_payable_account(self):
        account = self.env['account.account'].search([('code', '=', EOBI_PAYABLE_CODE)], limit=1)
        if not account:
            raise UserError(_('EOBI Payable account %s not found in the Chart of Accounts.') % EOBI_PAYABLE_CODE)
        return account

    def _get_pessi_payable_account(self):
        account = self.env['account.account'].search([('code', '=', PESSI_PAYABLE_CODE)], limit=1)
        if not account:
            raise UserError(_('PESSI Payable account %s not found in the Chart of Accounts.') % PESSI_PAYABLE_CODE)
        return account

    def unlink(self):
        if any(rec.state in ('confirmed', 'paid') for rec in self):
            raise UserError(_('A confirmed payslip cannot be deleted — cancel it instead.'))
        return super().unlink()

    def action_confirm(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only a draft payslip can be confirmed.'))
            rec._recompute_from_attendance()
            if rec.net_salary_expense <= 0:
                raise UserError(_('Net salary expense must be greater than zero — record attendance for this period first.'))
            if rec.name == _('New'):
                rec.name = self.env['ir.sequence'].next_by_code('reema.hr.payslip') or _('New')

            eobi_deduction = rec.eobi_deduction
            pessi_deduction = rec.pessi_deduction
            remaining = rec.net_salary_expense - eobi_deduction - pessi_deduction
            if remaining < 0:
                raise UserError(_('EOBI/PESSI deductions exceed this payslip\'s net salary expense — check attendance and statutory amounts.'))

            recovered_lines = self.env['reema.hr.employee.advance.line']
            for line in rec.employee_id._get_next_due_advance_lines():
                if line.amount <= remaining:
                    recovered_lines |= line
                    remaining -= line.amount
                else:
                    break

            advance_loan_deduction = sum(recovered_lines.mapped('amount'))
            net_pay = remaining - advance_loan_deduction

            expense_account = rec._get_salary_expense_account()
            payable_account = rec._get_salary_payable_account()
            move_lines = [(0, 0, {
                'account_id': expense_account.id,
                'name': rec.name,
                'debit': rec.net_salary_expense,
                'credit': 0.0,
            })]
            if advance_loan_deduction > 0:
                advance_account = rec.employee_id.reema_advance_loan_account_id
                move_lines.append((0, 0, {
                    'account_id': advance_account.id,
                    'name': _('Advance/Loan recovery — %s') % rec.name,
                    'debit': 0.0,
                    'credit': advance_loan_deduction,
                }))
            if eobi_deduction > 0:
                move_lines.append((0, 0, {
                    'account_id': rec._get_eobi_payable_account().id,
                    'name': _('EOBI — %s') % rec.name,
                    'debit': 0.0,
                    'credit': eobi_deduction,
                }))
            if pessi_deduction > 0:
                move_lines.append((0, 0, {
                    'account_id': rec._get_pessi_payable_account().id,
                    'name': _('PESSI — %s') % rec.name,
                    'debit': 0.0,
                    'credit': pessi_deduction,
                }))
            move_lines.append((0, 0, {
                'account_id': payable_account.id,
                'name': rec.name,
                'debit': 0.0,
                'credit': net_pay,
            }))
            move = self.env['account.move'].create({
                'move_type': 'entry',
                'journal_id': self.env['account.journal'].search(
                    [('code', '=', 'JV')], limit=1).id,
                'date': rec.date_to,
                'ref': _('Payslip %s') % rec.name,
                'line_ids': move_lines,
            })
            move.action_post()

            recovered_lines.write({'state': 'paid', 'payslip_id': rec.id})
            for voucher in recovered_lines.mapped('advance_id'):
                if all(l.state == 'paid' for l in voucher.line_ids):
                    voucher.state = 'closed'

            rec.write({
                'advance_loan_deduction': advance_loan_deduction,
                'move_id': move.id,
                'state': 'confirmed',
            })
            rec._message_log(body=_('Payslip confirmed. Net pay: %s') % net_pay)

    def action_pay(self, journal_id=None):
        for rec in self:
            if rec.state != 'confirmed':
                raise UserError(_('Only a confirmed payslip can be paid.'))
            journal = self.env['account.journal'].browse(journal_id) if journal_id else False
            if not journal:
                raise UserError(_('Select a payment method to pay this payslip.'))
            liquidity_account = journal.default_account_id
            if not liquidity_account:
                raise UserError(_('Selected payment method has no default account configured.'))
            payable_account = rec._get_salary_payable_account()
            move = self.env['account.move'].create({
                'move_type': 'entry',
                'journal_id': journal.id,
                'date': fields.Date.context_today(rec),
                'ref': _('Payment of %s') % rec.name,
                'line_ids': [
                    (0, 0, {
                        'account_id': payable_account.id,
                        'name': rec.name,
                        'debit': rec.net_pay,
                        'credit': 0.0,
                    }),
                    (0, 0, {
                        'account_id': liquidity_account.id,
                        'name': rec.name,
                        'debit': 0.0,
                        'credit': rec.net_pay,
                    }),
                ],
            })
            move.action_post()
            rec.write({'payment_move_id': move.id, 'state': 'paid'})
            rec._message_log(body=_('Payslip paid via %s.') % journal.name)

    def action_cancel(self):
        for rec in self:
            if rec.state == 'paid':
                raise UserError(_('A paid payslip cannot be cancelled — reverse the payment entry manually first.'))
            if rec.state == 'confirmed':
                if rec.move_id:
                    reversal = rec.move_id._reverse_moves(default_values_list=[{
                        'ref': _('Reversal of %s') % rec.name,
                        'date': fields.Date.context_today(rec),
                    }])
                    reversal.action_post()
                rec.advance_loan_line_recovered_ids.write({'state': 'due', 'payslip_id': False})
                for voucher in rec.advance_loan_line_recovered_ids.mapped('advance_id'):
                    if voucher.state == 'closed':
                        voucher.state = 'posted'
            rec.write({'state': 'cancelled'})

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state != 'cancelled':
                raise UserError(_('Only a cancelled payslip can be reset to draft.'))
            rec.write({
                'state': 'draft',
                'advance_loan_deduction': 0.0,
                'eobi_deduction': 0.0,
                'pessi_deduction': 0.0,
            })

    def action_open_pay_wizard(self):
        if not self:
            raise UserError(_('Select at least one payslip to pay.'))
        if any(rec.state != 'confirmed' for rec in self):
            raise UserError(_('Only confirmed payslips can be paid. Confirm the selected payslips first.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Pay Payslips'),
            'res_model': 'reema.hr.payslip.pay.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_payslip_ids': self.ids},
        }
