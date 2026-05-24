from odoo import api, fields, models


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


class AccountMoveLineDeductionExt(models.Model):
    _inherit = 'account.move.line'

    reema_is_deduction_line = fields.Boolean(default=False)


class AccountMoveDeductionExt(models.Model):
    _inherit = 'account.move'

    reema_deduction_ids = fields.One2many(
        'reema.bill.deduction', 'bill_id', string='Advance Deductions'
    )
    reema_total_deductions = fields.Float(
        string='Total Deductions',
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
    reema_contractor_advance_account_id = fields.Many2one(
        'account.account',
        compute='_compute_reema_contractor_advance_account_id',
        string='Contractor Advance Account',
    )

    @api.depends('reema_deduction_ids.amount', 'amount_total')
    def _compute_reema_deductions(self):
        for move in self:
            total = sum(move.reema_deduction_ids.mapped('amount'))
            move.reema_total_deductions = total
            move.reema_net_payable = move.amount_total - total

    @api.depends_context('uid')
    def _compute_reema_can_edit_deductions(self):
        is_accountant = self.env.user.has_group('account.group_account_manager')
        for move in self:
            move.reema_can_edit_deductions = is_accountant

    @api.depends('partner_id')
    def _compute_reema_contractor_advance_account_id(self):
        for move in self:
            move.reema_contractor_advance_account_id = (
                move.partner_id.reema_advance_account_id
                if move.partner_id else False
            )

    def action_post(self):
        for move in self:
            if not move.reema_deduction_ids:
                continue
            # Remove any lines injected by a previous post (reset-to-draft → re-post)
            move.invoice_line_ids.filtered('reema_is_deduction_line').unlink()
            # Inject one negative invoice line per deduction
            move.write({'invoice_line_ids': [
                (0, 0, {
                    'name': d.description,
                    'account_id': d.deduction_account_id.id,
                    'quantity': 1.0,
                    'price_unit': -d.amount,
                    'reema_is_deduction_line': True,
                })
                for d in move.reema_deduction_ids
            ]})
        return super().action_post()
