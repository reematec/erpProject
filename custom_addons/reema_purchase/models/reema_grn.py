from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ReemaGRN(models.Model):
    _name = 'reema.grn'
    _description = 'Goods Receipt Note'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name desc'

    name = fields.Char(
        string='GRN No.', readonly=True, copy=False,
        default=lambda self: _('New'), tracking=True,
    )
    date = fields.Date(
        string='Date', default=fields.Date.context_today,
        required=True, tracking=True,
    )
    gate_pass_id = fields.Many2one(
        'reema.gate.pass', string='Inward Gate Pass',
        required=True, tracking=True,
    )
    po_id = fields.Many2one(
        'reema.purchase.order', string='Purchase Order',
        related='gate_pass_id.po_id', store=True,
    )
    partner_id = fields.Many2one(
        'res.partner', string='Supplier',
        related='po_id.partner_id', store=True,
    )
    received_by = fields.Many2one(
        'res.users', string='Received By (Store)',
        default=lambda self: self.env.user, required=True,
    )
    approved_by = fields.Many2one(
        'res.users', string='Approved By (PM)', readonly=True,
    )
    state = fields.Selection([
        ('draft',     'Draft'),
        ('verified',  'Verified'),
        ('approved',  'Approved'),
        ('accounted', 'Accounted'),
    ], default='draft', required=True, tracking=True, copy=False)

    line_ids = fields.One2many('reema.grn.line', 'grn_id', string='Receipt Lines')

    move_id = fields.Many2one(
        'account.move', string='Interim Journal Entry', readonly=True,
    )

    total_accepted_value = fields.Float(
        string='Total Accepted Value (PKR)',
        compute='_compute_total_value', store=True,
    )

    # ── Compute ──────────────────────────────────────────────────────────

    @api.depends('line_ids.accepted_qty', 'line_ids.price_unit')
    def _compute_total_value(self):
        for rec in self:
            rec.total_accepted_value = sum(
                line.accepted_qty * line.price_unit for line in rec.line_ids
            )

    # ── CRUD ─────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('reema.grn') or _('New')
        return super().create(vals_list)

    @api.onchange('gate_pass_id')
    def _onchange_gate_pass_id(self):
        if self.gate_pass_id:
            lines = []
            for gp_line in self.gate_pass_id.line_ids:
                lines.append((0, 0, {
                    'product_id': gp_line.product_id.id,
                    'description': gp_line.description,
                    'po_line_id': gp_line.po_line_id.id,
                    'gate_pass_line_id': gp_line.id,
                    'ordered_qty': gp_line.expected_qty,
                    'received_qty': gp_line.received_qty,
                    'accepted_qty': gp_line.received_qty,
                    'product_uom_id': gp_line.product_uom_id.id,
                    'price_unit': gp_line.po_line_id.price_unit if gp_line.po_line_id else 0.0,
                    'color': gp_line.color,
                    'thickness': gp_line.thickness,
                }))
            self.line_ids = [(5, 0, 0)] + lines

    # ── Actions ──────────────────────────────────────────────────────────

    def action_verify(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError(_('GRN must have at least one line.'))
            rec.write({'state': 'verified'})
            rec.message_post(body=_('GRN verified by store keeper %s.') % self.env.user.name)

    def action_approve(self):
        for rec in self:
            if rec.state != 'verified':
                raise UserError(_('GRN must be verified before approval.'))
            move = rec._create_interim_entry()
            rec.write({
                'state': 'approved',
                'approved_by': self.env.uid,
                'move_id': move.id,
            })
            rec.message_post(
                body=_('GRN approved by %s. Interim journal entry %s created.') % (
                    self.env.user.name, move.name
                )
            )

    def action_print_grn(self):
        return self.env.ref('reema_purchase.report_grn').report_action(self)

    # ── Accounting ────────────────────────────────────────────────────────

    def _create_interim_entry(self):
        self.ensure_one()
        journal = self.env['account.journal'].search(
            [('type', '=', 'general'), ('company_id', '=', self.env.company.id)], limit=1
        )
        if not journal:
            raise UserError(_('No general journal found. Please configure one.'))

        grni_account = self.env.ref('reema_purchase.account_grni_clearing', raise_if_not_found=False)
        if not grni_account:
            raise UserError(_('GRNI Clearing account not found. Please install the module properly.'))

        move_lines = []
        for line in self.line_ids:
            if line.accepted_qty <= 0:
                continue

            stock_account = line.product_id.categ_id.property_stock_valuation_account_id
            if not stock_account:
                raise UserError(
                    _('Product category "%s" has no stock valuation account configured.')
                    % line.product_id.categ_id.name
                )

            amount = line.accepted_qty * line.price_unit
            label = '%s — %s' % (line.product_id.display_name, self.name)

            # Dr: Stock (current asset)
            move_lines.append((0, 0, {
                'account_id': stock_account.id,
                'debit': amount,
                'credit': 0.0,
                'name': label,
            }))
            # Cr: GRNI Clearing (interim liability)
            move_lines.append((0, 0, {
                'account_id': grni_account.id,
                'debit': 0.0,
                'credit': amount,
                'name': label,
            }))

        if not move_lines:
            raise UserError(_('No lines with accepted quantity > 0 found.'))

        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': self.date,
            'ref': self.name,
            'journal_id': journal.id,
            'line_ids': move_lines,
        })
        move.action_post()
        return move


class ReemaGRNLine(models.Model):
    _name = 'reema.grn.line'
    _description = 'GRN Line'
    _order = 'grn_id, sequence, id'

    grn_id = fields.Many2one(
        'reema.grn', string='GRN', required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(default=10)
    po_line_id = fields.Many2one(
        'reema.purchase.order.line', string='PO Line',
    )
    gate_pass_line_id = fields.Many2one(
        'reema.gate.pass.line', string='Gate Pass Line',
    )
    product_id = fields.Many2one(
        'product.product', string='Product', required=True,
    )
    description = fields.Char(string='Description')
    product_uom_id = fields.Many2one('uom.uom', string='Unit')
    ordered_qty = fields.Float(string='PO Qty', readonly=True)
    received_qty = fields.Float(string='Physically Received')
    accepted_qty = fields.Float(string='Accepted Qty', required=True)
    rejected_qty = fields.Float(
        string='Rejected Qty', compute='_compute_rejected', store=True,
    )
    rejection_reason = fields.Text(string='Rejection Reason')
    color_ok = fields.Boolean(string='Color Match', default=True)
    thickness_ok = fields.Boolean(string='Thickness OK', default=True)
    price_unit = fields.Float(string='Unit Price (PKR)')
    color = fields.Char(string='Color (PO Spec)')
    thickness = fields.Char(string='Thickness (PO Spec)')

    @api.depends('received_qty', 'accepted_qty')
    def _compute_rejected(self):
        for line in self:
            line.rejected_qty = max(0.0, line.received_qty - line.accepted_qty)
