from odoo import api, fields, models


class ReemaContractorBillApproval(models.Model):
    _name = 'reema.contractor.bill.approval'
    _description = 'Contractor Bill Approval'
    _rec_name = 'name'
    _order = 'id desc'

    move_id = fields.Many2one(
        'account.move',
        required=True,
        ondelete='cascade',
        index=True,
        readonly=True,
        string='Bill',
    )

    # ── Computed from move (all via sudo — no account.move access needed) ──

    name = fields.Char(compute='_compute_from_move', string='Reference')
    partner_id = fields.Many2one('res.partner', compute='_compute_from_move', string='Contractor')
    invoice_date = fields.Date(compute='_compute_from_move', string='Date')
    currency_id = fields.Many2one('res.currency', compute='_compute_from_move')
    amount_total = fields.Monetary(
        compute='_compute_from_move',
        string='Total Amount',
        currency_field='currency_id',
    )
    reema_total_deductions = fields.Monetary(
        compute='_compute_from_move',
        string='Total Deductions',
        currency_field='currency_id',
    )
    reema_net_payable = fields.Monetary(
        compute='_compute_from_move',
        string='Net Payable',
        currency_field='currency_id',
    )
    reema_bill_state = fields.Selection(
        [('pending', 'Pending'), ('confirmed', 'Confirmed')],
        compute='_compute_from_move',
        string='Approval',
    )
    state = fields.Selection(
        [('draft', 'Draft'), ('posted', 'Posted'), ('cancel', 'Cancelled')],
        compute='_compute_from_move',
        string='Bill Status',
    )
    narration = fields.Html(compute='_compute_from_move', string='Notes')

    # ── Batch entries (production staff already have read access to this model) ──

    batch_entry_ids = fields.Many2many(
        comodel_name='reema.wo.batch.entry',
        compute='_compute_batch_entries',
        string='Bill Lines',
    )

    @api.depends('move_id')
    def _compute_from_move(self):
        for rec in self:
            move = rec.move_id.sudo()
            rec.name = move.name or '/'
            rec.partner_id = move.partner_id
            rec.invoice_date = move.invoice_date
            rec.currency_id = move.currency_id
            rec.amount_total = move.amount_total
            rec.reema_total_deductions = move.reema_total_deductions
            rec.reema_net_payable = move.reema_net_payable
            rec.reema_bill_state = move.reema_bill_state
            rec.state = move.state
            rec.narration = move.narration

    @api.depends('move_id')
    def _compute_batch_entries(self):
        for rec in self:
            rec.batch_entry_ids = self.env['reema.wo.batch.entry'].search([
                ('bill_id', '=', rec.move_id.id)
            ])

    def action_approve(self):
        self.ensure_one()
        self.move_id.sudo().action_reema_confirm()

    def action_void(self):
        self.ensure_one()
        self.move_id.sudo().action_reema_reset_to_pending()

    def action_delete(self):
        self.ensure_one()
        action = self.env.ref('reema_accounting.action_contractor_bill_approval').read()[0]
        self.move_id.sudo().action_delete_contractor_bill()
        return action


class ReemaWoBatchEntryBillHook(models.Model):
    _inherit = 'reema.wo.batch.entry'

    def write(self, vals):
        result = super().write(vals)
        if vals.get('bill_id'):
            existing = self.env['reema.contractor.bill.approval'].sudo().search(
                [('move_id', '=', vals['bill_id'])], limit=1
            )
            if not existing:
                self.env['reema.contractor.bill.approval'].sudo().create(
                    {'move_id': vals['bill_id']}
                )
        return result
