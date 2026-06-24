from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class ReemaGatePass(models.Model):
    _name = 'reema.gate.pass'
    _description = 'Inward Gate Pass'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name desc'

    name = fields.Char(
        string='Inward Gate Pass No.', readonly=True, copy=False,
        default=lambda self: _('New'), tracking=True,
    )
    date = fields.Datetime(
        string='Arrival Date & Time', default=fields.Datetime.now,
        required=True, tracking=True,
    )
    po_id = fields.Many2one(
        'reema.purchase.order', string='Purchase Order',
        tracking=True,
        domain=[('state', 'in', ('confirmed', 'approved'))],
    )
    partner_id = fields.Many2one(
        'res.partner', string='Supplier', tracking=True,
    )
    vehicle_no = fields.Char(string='Vehicle No.', tracking=True)
    driver_name = fields.Char(string='Driver Name')
    carrier = fields.Char(string='Carrier / Transporter')
    no_of_packages = fields.Integer(string='No. of Packages / Cartons')
    security_guard = fields.Char(string='Security Guard Name')
    remarks = fields.Text(string='Remarks')
    state = fields.Selection([
        ('draft',     'Arrived'),
        ('confirmed', 'Forwarded to Store'),
    ], default='draft', required=True, tracking=True, copy=False)

    line_ids = fields.One2many('reema.gate.pass.line', 'gate_pass_id', string='Items Arrived')

    grn_ids = fields.One2many('reema.grn', 'gate_pass_id', string='GRNs')
    grn_count = fields.Integer(compute='_compute_grn_count')
    total_arrived_qty = fields.Float(string='Arrived Qty', compute='_compute_total_arrived_qty', store=True)
    product_summary = fields.Char(string='Products', compute='_compute_product_summary')
    custom_product_summary = fields.Char(string='Custom Products', compute='_compute_product_summary')

    # ── Compute ──────────────────────────────────────────────────────────

    def _compute_grn_count(self):
        for rec in self:
            rec.grn_count = self.env['reema.grn'].sudo().search_count(
                [('gate_pass_id', '=', rec.id)]
            )

    @api.depends('line_ids.received_qty')
    def _compute_total_arrived_qty(self):
        for rec in self:
            rec.total_arrived_qty = sum(rec.line_ids.mapped('received_qty'))

    @api.depends('line_ids.product_id', 'line_ids.product_name')
    def _compute_product_summary(self):
        for rec in self:
            rec.product_summary = ', '.join(filter(None, rec.line_ids.mapped('product_id.display_name')))
            rec.custom_product_summary = ', '.join(filter(None, rec.line_ids.mapped('product_name')))

    # ── CRUD ─────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('reema.gate.pass') or _('New')
        return super().create(vals_list)

    def write(self, vals):
        if 'name' not in vals:
            for rec in self:
                if rec.name == _('New'):
                    vals = dict(vals, name=self.env['ir.sequence'].next_by_code('reema.gate.pass') or _('New'))
                    break
        return super().write(vals)

    @api.onchange('po_id')
    def _onchange_po_id(self):
        self.partner_id = self.po_id.partner_id
        if not self.po_id:
            for line in self.line_ids:
                line.update({'po_line_id': False, 'expected_qty': 0.0})
            return
        existing_by_product = {line.product_id.id: line for line in self.line_ids if line.product_id}
        new_lines = []
        for po_line in self.po_id.line_ids:
            if po_line.product_id.id in existing_by_product:
                existing_by_product[po_line.product_id.id].update({
                    'po_line_id': po_line.id,
                    'expected_qty': po_line.product_qty,
                    'product_uom_id': po_line.product_uom_id.id,
                })
            else:
                new_lines.append((0, 0, {
                    'product_id': po_line.product_id.id,
                    'description': po_line.name or po_line.product_id.display_name,
                    'po_line_id': po_line.id,
                    'expected_qty': po_line.product_qty,
                    'product_uom_id': po_line.product_uom_id.id,
                    'color': po_line.color,
                    'thickness': po_line.thickness,
                }))
        if new_lines:
            self.line_ids = list(self.line_ids) + new_lines

    # ── Actions ──────────────────────────────────────────────────────────

    def unlink(self):
        if any(rec.state == 'confirmed' for rec in self):
            raise UserError(_('A forwarded gate pass cannot be deleted.'))
        return super().unlink()

    def action_reset_to_draft(self):
        for rec in self:
            rec.write({'state': 'draft'})
            rec.message_post(body=_('Inward Gate Pass reversed to Arrived by %s.') % self.env.user.name)

    def action_confirm(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError(_('Please record at least one item before forwarding.'))
            if rec.name == _('New'):
                rec.name = self.env['ir.sequence'].next_by_code('reema.gate.pass') or _('New')
            rec.write({'state': 'confirmed'})
            rec.message_post(body=_('Inward Gate Pass confirmed and forwarded to store by %s.') % self.env.user.name)

    def action_view_grn(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('GRN'),
            'res_model': 'reema.grn',
            'view_mode': 'list,form',
            'domain': [('gate_pass_id', '=', self.id)],
            'context': {'default_gate_pass_id': self.id, 'default_po_id': self.po_id.id},
        }


class ReemaGatePassLine(models.Model):
    _name = 'reema.gate.pass.line'
    _description = 'Inward Gate Pass Line'
    _order = 'gate_pass_id, sequence, id'

    gate_pass_id = fields.Many2one(
        'reema.gate.pass', string='Inward Gate Pass',
        required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(default=10)
    po_line_id = fields.Many2one(
        'reema.purchase.order.line', string='PO Line',
    )
    product_id = fields.Many2one(
        'product.product', string='Product',
    )
    product_name = fields.Char(string='Custom Product')
    display_product = fields.Char(
        string='Product', compute='_compute_display_product', store=False,
    )
    description = fields.Char(string='Description')
    expected_qty = fields.Float(string='Expected Qty (from PO)')
    received_qty = fields.Float(string='Physically Arrived Qty', required=True)
    product_uom_id = fields.Many2one('uom.uom', string='Unit')
    color = fields.Char(string='Color')
    thickness = fields.Char(string='Thickness / Spec')
    attribute_ids = fields.One2many(
        'reema.gate.pass.line.attribute', 'line_id', string='Attributes',
    )
    attribute_summary = fields.Char(
        string='Attributes', compute='_compute_attribute_summary',
    )

    def _compute_attribute_summary(self):
        for rec in self:
            parts = ['%s: %s' % (a.attribute_name, a.attribute_value) for a in rec.attribute_ids]
            rec.attribute_summary = ' | '.join(parts) if parts else ''

    @api.depends('product_id', 'product_name')
    def _compute_display_product(self):
        for rec in self:
            rec.display_product = rec.product_id.display_name or rec.product_name or ''

    @api.constrains('product_id', 'product_name')
    def _check_product(self):
        for rec in self:
            if not rec.product_id and not rec.product_name:
                raise ValidationError(_('Each line must have either a product selected or a custom product name.'))


class ReemaGatePassLineAttribute(models.Model):
    _name = 'reema.gate.pass.line.attribute'
    _description = 'Gate Pass Line Attribute'
    _order = 'line_id, sequence, id'

    line_id = fields.Many2one(
        'reema.gate.pass.line', string='Gate Pass Line',
        required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(default=10)
    attribute_name = fields.Char(string='Attribute', required=True)
    attribute_value = fields.Char(string='Value', required=True)
