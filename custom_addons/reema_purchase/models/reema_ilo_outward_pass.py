from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class ReemaIloOutwardPass(models.Model):
    _name = 'reema.ilo.outward.pass'
    _description = 'ILO Outward Gate Pass'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name desc'

    name = fields.Char(
        string='ILO Outward Pass No.', readonly=True, copy=False,
        default=lambda self: _('New'), tracking=True,
    )
    date = fields.Datetime(
        string='Exit Date & Time',
        required=True, tracking=True,
    )
    contractor_id = fields.Many2one(
        'res.partner', string='Contractor', required=True,
        domain="[('is_contractor', '=', True)]",
        tracking=True,
    )
    vehicle_no = fields.Char(string='Vehicle No.', required=True, tracking=True)
    driver_name = fields.Char(string='Driver Name', required=True)
    created_by = fields.Char(
        string='Created By', readonly=True, copy=False, tracking=True,
        default=lambda self: self.env.user.name,
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Sent'),
    ], default='draft', required=True, tracking=True, copy=False)

    line_ids = fields.One2many('reema.ilo.outward.pass.line', 'outward_pass_id', string='Dispatches')
    remarks = fields.Text(string='Remarks')

    total_qty_balls = fields.Integer(string='Total Balls', compute='_compute_total_qty_balls', store=True)

    @api.depends('line_ids.qty_balls')
    def _compute_total_qty_balls(self):
        for rec in self:
            rec.total_qty_balls = sum(rec.line_ids.mapped('qty_balls'))

    @api.constrains('line_ids')
    def _check_has_lines(self):
        for rec in self:
            if not rec.line_ids:
                raise ValidationError(_(
                    'An ILO Outward Pass must have at least one attached ILO Dispatch before it can be saved.'
                ))

    @api.constrains('line_ids', 'contractor_id')
    def _check_single_contractor(self):
        for rec in self:
            line_contractors = set(rec.line_ids.mapped('dispatch_id.contractor_id.id'))
            line_contractors.discard(False)
            if len(line_contractors) > 1:
                raise ValidationError(_(
                    'All attached ILO Dispatches must belong to the same contractor. '
                    'This pass currently has dispatches from more than one contractor.'
                ))
            if rec.contractor_id and line_contractors and rec.contractor_id.id not in line_contractors:
                raise ValidationError(_(
                    'The selected Contractor (%s) does not match the contractor of the attached ILO Dispatch(es).'
                ) % rec.contractor_id.name)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('reema.ilo.outward.pass') or _('New')
        return super().create(vals_list)

    @api.onchange('vehicle_no', 'driver_name', 'contractor_id')
    def _onchange_auto_exit_time(self):
        if not self.date:
            self.date = fields.Datetime.now()

    @api.onchange('line_ids')
    def _onchange_line_ids_contractor(self):
        if not self.contractor_id:
            first_dispatch = next((l.dispatch_id for l in self.line_ids if l.dispatch_id), False)
            if first_dispatch:
                self.contractor_id = first_dispatch.contractor_id

    def unlink(self):
        if any(rec.state == 'confirmed' for rec in self):
            raise UserError(_('A confirmed ILO Outward Pass cannot be deleted.'))
        return super().unlink()

    def action_reset_to_draft(self):
        for rec in self:
            rec.line_ids.mapped('dispatch_id').filtered(
                lambda d: d.state == 'sent'
            ).write({'state': 'dispatched'})
            rec.with_context(mail_notrack=True).write({'state': 'draft'})
            rec.sudo().message_post(
                body=_('ILO Outward Pass reversed to Draft by %s.') % self.env.user.name,
                subtype_xmlid='mail.mt_note',
            )

    def action_confirm(self):
        for rec in self:
            if rec.name == _('New'):
                raise UserError(_('Please save the record first before confirming.'))
            if not rec.line_ids:
                raise UserError(_('Please attach at least one dispatch before confirming.'))
            rec.line_ids.mapped('dispatch_id').filtered(
                lambda d: d.state == 'dispatched'
            ).write({'state': 'sent'})
            rec.with_context(mail_notrack=True).write({'state': 'confirmed'})
            rec.sudo().message_post(
                body=_('ILO Outward Pass confirmed and vehicle exited by %s.') % self.env.user.name,
                subtype_xmlid='mail.mt_note',
            )


class ReemaIloOutwardPassLine(models.Model):
    _name = 'reema.ilo.outward.pass.line'
    _description = 'ILO Outward Gate Pass Line'
    _order = 'outward_pass_id, sequence, id'
    _sql_constraints = [
        ('dispatch_id_unique', 'unique(dispatch_id)',
         'This ILO Dispatch is already attached to another ILO Outward Pass.'),
    ]

    outward_pass_id = fields.Many2one(
        'reema.ilo.outward.pass', string='ILO Outward Pass',
        required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(default=10)
    dispatch_id = fields.Many2one(
        'reema.ilo.dispatch', string='ILO Dispatch', required=True,
        domain="[('state', '=', 'dispatched'), ('is_outward_passed', '=', False)]",
    )
    mo_id = fields.Many2one(related='dispatch_id.mo_id', string='Manufacturing Order', store=True, readonly=True)
    ball_size = fields.Char(related='dispatch_id.ball_size', store=True, readonly=True)
    construction_type = fields.Selection(related='dispatch_id.construction_type', store=True, readonly=True)
    qty_balls = fields.Integer(related='dispatch_id.qty_balls', string='Balls Sent', store=True, readonly=True)

    @api.constrains('dispatch_id')
    def _check_dispatch_state(self):
        for rec in self:
            if rec.dispatch_id and rec.dispatch_id.state != 'dispatched':
                raise ValidationError(_(
                    'ILO Dispatch %s is not in "Pending Return" status and cannot be added to an ILO Outward Pass.'
                ) % rec.dispatch_id.name)
