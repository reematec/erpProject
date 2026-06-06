from odoo import models, fields, api, _
from odoo.exceptions import UserError


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
    security_guard = fields.Char(string='Security Guard Name')
    remarks = fields.Text(string='Remarks')
    state = fields.Selection([
        ('draft',     'Arrived'),
        ('confirmed', 'Forwarded to Store'),
    ], default='draft', required=True, tracking=True, copy=False)

    line_ids = fields.One2many('reema.gate.pass.line', 'gate_pass_id', string='Items')

    grn_count = fields.Integer(compute='_compute_grn_count')

    # ── Compute ──────────────────────────────────────────────────────────

    def _compute_grn_count(self):
        for rec in self:
            rec.grn_count = self.env['reema.grn'].search_count(
                [('gate_pass_id', '=', rec.id)]
            )

    # ── CRUD ─────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('reema.gate.pass') or _('New')
        return super().create(vals_list)

    @api.onchange('po_id')
    def _onchange_po_id(self):
        self.partner_id = self.po_id.partner_id
        if self.po_id:
            lines = []
            for po_line in self.po_id.line_ids:
                lines.append((0, 0, {
                    'product_id': po_line.product_id.id,
                    'description': po_line.name or po_line.product_id.display_name,
                    'expected_qty': po_line.product_qty,
                    'product_uom_id': po_line.product_uom_id.id,
                    'po_line_id': po_line.id,
                    'color': po_line.color,
                    'thickness': po_line.thickness,
                }))
            self.line_ids = [(5, 0, 0)] + lines

    # ── Actions ──────────────────────────────────────────────────────────

    def action_confirm(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError(_('Inward Gate Pass must have at least one item.'))
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
        'product.product', string='Product', required=True,
    )
    description = fields.Char(string='Description')
    expected_qty = fields.Float(string='Expected Qty (from PO)')
    received_qty = fields.Float(string='Physically Received Qty', required=True)
    product_uom_id = fields.Many2one('uom.uom', string='Unit')
    color = fields.Char(string='Color (PO)')
    thickness = fields.Char(string='Thickness (PO)')
