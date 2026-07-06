from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


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
        string='Date',
        required=True, tracking=True,
    )
    gate_pass_id = fields.Many2one(
        'reema.gate.pass', string='Inward Gate Pass', tracking=True,
    )
    po_id = fields.Many2one(
        'reema.purchase.order', string='Purchase Order',
        compute='_compute_po_id', store=True, readonly=False,
        domain=[('state', 'in', ('confirmed', 'approved'))],
        tracking=True,
    )
    partner_id = fields.Many2one(
        'res.partner', string='Supplier',
        compute='_compute_partner_id', store=True, readonly=False,
        tracking=True,
    )
    received_by = fields.Many2one(
        'res.users', string='Received By (Store)',
        default=lambda self: self.env.user, required=True,
    )
    state = fields.Selection([
        ('draft',    'Draft'),
        ('verified', 'Verified'),
    ], default='draft', required=True, tracking=True, copy=False)

    line_ids = fields.One2many('reema.grn.line', 'grn_id', string='Receipt Lines')
    inspection_ids = fields.One2many('reema.grn.inspection', 'grn_id', string='Inspection Items')

    move_id = fields.Many2one(
        'account.move', string='Interim Journal Entry', readonly=True,
    )
    has_journal_entry = fields.Boolean(
        compute='_compute_has_journal_entry', store=True, compute_sudo=True,
    )

    total_accepted_value = fields.Float(
        string='Total Accepted Value (PKR)',
        compute='_compute_total_value', store=True,
    )
    total_accepted_qty = fields.Float(
        string='Total Accepted Qty',
        compute='_compute_total_qty', store=True,
    )
    total_received_qty = fields.Float(
        string='Total Received Qty',
        compute='_compute_total_qty', store=True,
    )
    total_rejected_qty = fields.Float(
        string='Total Rejected Qty',
        compute='_compute_total_qty', store=True,
    )

    # ── Compute ──────────────────────────────────────────────────────────

    @api.depends('line_ids.accepted_qty', 'line_ids.received_qty', 'line_ids.rejected_qty')
    def _compute_total_qty(self):
        for rec in self:
            rec.total_accepted_qty = sum(rec.line_ids.mapped('accepted_qty'))
            rec.total_received_qty = sum(rec.line_ids.mapped('received_qty'))
            rec.total_rejected_qty = sum(rec.line_ids.mapped('rejected_qty'))

    @api.depends('gate_pass_id')
    def _compute_po_id(self):
        for rec in self:
            if rec.gate_pass_id:
                rec.po_id = rec.gate_pass_id.po_id

    @api.depends('po_id')
    def _compute_partner_id(self):
        for rec in self:
            if rec.po_id:
                rec.partner_id = rec.po_id.partner_id

    @api.depends('line_ids.accepted_qty', 'line_ids.price_unit')
    def _compute_total_value(self):
        for rec in self:
            rec.total_accepted_value = sum(
                line.accepted_qty * line.price_unit for line in rec.line_ids
            )

    @api.depends('move_id')
    def _compute_has_journal_entry(self):
        for rec in self:
            rec.has_journal_entry = bool(rec.move_id)

    # ── CRUD ─────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('reema.grn') or _('New')
        return super().create(vals_list)

    @api.onchange('gate_pass_id', 'po_id', 'partner_id', 'received_by')
    def _onchange_auto_date(self):
        if not self.date:
            self.date = fields.Date.context_today(self)

    @api.onchange('po_id')
    def _onchange_po_id(self):
        if self.gate_pass_id:
            return
        if self.po_id:
            lines, inspections = [], []
            for po_line in self.po_id.line_ids:
                lines.append((0, 0, {
                    'product_id': po_line.product_id.id,
                    'description': po_line.name,
                    'po_line_id': po_line.id,
                    'ordered_qty': po_line.product_qty,
                    'price_unit': po_line.price_unit,
                    'product_uom_id': po_line.product_uom_id.id,
                    'received_qty': 0.0,
                    'accepted_qty': 0.0,
                }))
                for check in po_line.product_id.reema_inspection_check_ids:
                    inspections.append((0, 0, {
                        'product_id': po_line.product_id.id,
                        'check_name': check.check_name,
                        'expected_value': check.expected_value,
                    }))
            self.line_ids = [(5, 0, 0)] + lines
            self.inspection_ids = [(5, 0, 0)] + inspections

    @api.onchange('gate_pass_id')
    def _onchange_gate_pass_id(self):
        if self.gate_pass_id:
            lines = []
            inspections = []
            for gp_line in self.gate_pass_id.line_ids:
                lines.append((0, 0, {
                    'product_id': gp_line.product_id.id,
                    'product_name': gp_line.product_name,
                    'description': gp_line.description,
                    'po_line_id': gp_line.po_line_id.id,
                    'gate_pass_line_id': gp_line.id,
                    'ordered_qty': gp_line.expected_qty,
                    'received_qty': gp_line.received_qty,
                    'accepted_qty': gp_line.received_qty,
                    'product_uom_id': gp_line.product_uom_id.id,
                    'price_unit': gp_line.po_line_id.price_unit if gp_line.po_line_id else 0.0,
                }))
                pid = gp_line.product_id.id
                for check in gp_line.product_id.reema_inspection_check_ids:
                    inspections.append((0, 0, {
                        'product_id': pid,
                        'check_name': check.check_name,
                        'expected_value': check.expected_value,
                    }))
            self.line_ids = [(5, 0, 0)] + lines
            self.inspection_ids = [(5, 0, 0)] + inspections

    # ── Constraints ──────────────────────────────────────────────────────

    @api.constrains('gate_pass_id')
    def _check_gate_pass_unique(self):
        for rec in self:
            if not rec.gate_pass_id:
                continue
            duplicate = self.search([
                ('gate_pass_id', '=', rec.gate_pass_id.id),
                ('id', '!=', rec.id),
            ], limit=1)
            if duplicate:
                raise ValidationError(
                    _('Inward Gate Pass "%s" is already used in GRN %s.') % (
                        rec.gate_pass_id.name, duplicate.name
                    )
                )

    # ── Actions ──────────────────────────────────────────────────────────

    def action_verify(self):
        warehouse = self.env['stock.warehouse'].search(
            [('company_id', '=', self.env.company.id)], limit=1
        )
        if not warehouse:
            raise UserError(_('No warehouse found for this company.'))
        src_location = self.env.ref('stock.stock_location_suppliers')
        dest_location = warehouse.lot_stock_id

        for rec in self:
            if rec.name == _('New'):
                raise UserError(_('Please save the record first before verifying the GRN.'))
            if not rec.line_ids:
                raise UserError(_('GRN must have at least one line.'))
            if not rec.partner_id:
                raise UserError(_('Please set a supplier before verifying the GRN.'))
            non_storable = [
                line.product_id.display_name
                for line in rec.line_ids
                if line.product_id and line.accepted_qty > 0
                and not line.product_id.is_storable
            ]
            if non_storable:
                raise UserError(_(
                    'The following products are not set as "Storable Product" and cannot be received into stock:\n%s\n\n'
                    'Please open each product and change Product Type to "Storable Product" before verifying.'
                ) % '\n'.join('• ' + p for p in non_storable))
            created_moves = self.env['stock.move']
            for line in rec.line_ids:
                if not line.product_id or line.accepted_qty <= 0:
                    continue
                move = self.env['stock.move'].create({
                    'name': 'GRN: %s' % line.product_id.name,
                    'product_id': line.product_id.id,
                    'product_uom': line.product_uom_id.id or line.product_id.uom_id.id,
                    'product_uom_qty': line.accepted_qty,
                    'location_id': src_location.id,
                    'location_dest_id': dest_location.id,
                    'origin': rec.name,
                    'company_id': self.env.company.id,
                    'price_unit': line.po_line_id.price_unit if line.po_line_id else (line.price_unit or 0.0),
                })
                move._action_confirm()
                move.quantity = line.accepted_qty
                move.move_line_ids.write({'picked': True})
                move._action_done()
                created_moves |= move
            svl = self.env['stock.valuation.layer'].sudo().search(
                [('stock_move_id', 'in', created_moves.ids)], limit=1
            )
            move_id = svl.account_move_id.id if svl and svl.account_move_id else False
            if not move_id and created_moves:
                move_id = self._create_interim_journal_entry(rec)
            rec.with_context(mail_notrack=True).write({
                'state': 'verified',
                'move_id': move_id or False,
            })
            rec.sudo().message_post(
                body=_('GRN verified by %s. Stock and accounting updated.') % self.env.user.name,
                subtype_xmlid='mail.mt_note',
            )

    def _create_interim_journal_entry(self, rec):
        journal = self.env['account.journal'].sudo().search(
            [('code', '=', 'STK'), ('company_id', '=', self.env.company.id)], limit=1
        )
        if not journal:
            return False
        lines = []
        for line in rec.line_ids:
            if not line.product_id or line.accepted_qty <= 0:
                continue
            categ = line.product_id.categ_id
            stock_account = categ.property_stock_valuation_account_id
            input_account = categ.property_stock_account_input_categ_id
            if not stock_account or not input_account:
                continue
            amount = line.accepted_qty * line.price_unit
            label = line.product_id.display_name
            lines += [
                (0, 0, {'account_id': stock_account.id, 'name': label,
                        'debit': amount, 'credit': 0.0}),
                (0, 0, {'account_id': input_account.id, 'name': label,
                        'debit': 0.0, 'credit': amount}),
            ]
        if not lines:
            return False
        move = self.env['account.move'].sudo().create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': rec.date or fields.Date.context_today(self),
            'ref': rec.name,
            'line_ids': lines,
        })
        move.sudo().action_post()
        return move.id

    def action_view_journal_entry(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Interim Journal Entry'),
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.move_id.id,
        }

    def action_print_grn(self):
        # Open the GRN as an HTML preview in a new browser tab. The user prints
        # with Ctrl+P and closes the tab (no PDF/wkhtmltopdf round-trip).
        url = '/report/html/reema_purchase.report_grn_template/%s' % self.id
        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'new',
        }



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
        'product.product', string='Product',
    )
    product_name = fields.Char(string='Custom Product')
    display_product = fields.Char(
        string='Product', compute='_compute_display_product', store=False,
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
    price_unit = fields.Float(string='Unit Price (PKR)')

    @api.depends('product_id', 'product_name')
    def _compute_display_product(self):
        for rec in self:
            rec.display_product = rec.product_id.display_name or rec.product_name or ''

    @api.constrains('product_id', 'product_name')
    def _check_product(self):
        for rec in self:
            if not rec.product_id and not rec.product_name:
                raise ValidationError(_('Each line must have either a product selected or a custom product name.'))

    @api.depends('received_qty', 'accepted_qty')
    def _compute_rejected(self):
        for line in self:
            line.rejected_qty = max(0.0, line.received_qty - line.accepted_qty)


class ReemaGRNInspection(models.Model):
    _name = 'reema.grn.inspection'
    _description = 'GRN Inspection Item'
    _order = 'grn_id, sequence, id'

    grn_id = fields.Many2one(
        'reema.grn', required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one('product.product', string='Product')
    check_name = fields.Char(string='Check', required=True)
    sample_qty = fields.Float(string='Sample Size', default=0.0)
    expected_value = fields.Char(string='Expected')
    actual_value = fields.Char(string='Actual')
    result = fields.Selection([
        ('pass', 'Pass'),
        ('fail', 'Fail'),
        ('na',   'N/A'),
    ], string='Result')
    notes = fields.Text(string='Notes')
