from markupsafe import Markup
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ReemaMaterialIssuance(models.Model):
    _name = 'reema.material.issuance'
    _description = 'Raw Material Issuance Authorization'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name desc'

    name = fields.Char(string='Reference', readonly=True, copy=False,
                       default=lambda self: _('New'), tracking=True)
    production_id = fields.Many2one('mrp.production', string='Manufacturing Order',
                                    required=True, readonly=True, tracking=True)
    raw_move_id = fields.Many2one('stock.move', string='Component Move',
                                  required=True, readonly=True)
    product_id = fields.Many2one('product.product', related='raw_move_id.product_id',
                                 store=True, readonly=True, string='Product')
    product_uom_id = fields.Many2one('uom.uom', related='raw_move_id.product_uom',
                                     store=True, readonly=True, string='UOM')
    authorized_qty = fields.Float(string='Authorized Qty', readonly=True)
    total_issued_qty = fields.Float(compute='_compute_totals', store=True,
                                    string='Total Issued')
    total_returned_qty = fields.Float(compute='_compute_totals', store=True,
                                      string='Total Returned')
    net_issued_qty = fields.Float(compute='_compute_totals', store=True,
                                  string='Net Issued')
    remaining_qty = fields.Float(compute='_compute_totals', store=True,
                                 string='Remaining')
    state = fields.Selection([
        ('authorized', 'Authorized'),
        ('partial', 'Partially Issued'),
        ('fully_issued', 'Fully Issued'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='authorized', required=True, tracking=True)
    authorized_by = fields.Many2one('res.users', string='Authorized By', readonly=True)
    date_authorized = fields.Date(string='Authorized On', readonly=True,
                                  default=fields.Date.context_today)
    line_ids = fields.One2many('reema.material.issuance.line', 'issuance_id',
                               string='Issue Log')
    return_line_ids = fields.One2many('reema.material.return.line', 'issuance_id',
                                      string='Return Log')
    has_any_issue = fields.Boolean(compute='_compute_has_any_issue')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'reema.material.issuance') or _('New')
        return super().create(vals_list)

    @api.depends('line_ids')
    def _compute_has_any_issue(self):
        for rec in self:
            rec.has_any_issue = bool(rec.line_ids)

    @api.depends('line_ids.issued_qty', 'return_line_ids.returned_qty')
    def _compute_totals(self):
        for rec in self:
            total_issued = sum(rec.line_ids.mapped('issued_qty'))
            total_returned = sum(rec.return_line_ids.mapped('returned_qty'))
            net = total_issued - total_returned
            rec.total_issued_qty = total_issued
            rec.total_returned_qty = total_returned
            rec.net_issued_qty = net
            rec.remaining_qty = rec.authorized_qty - net

    def _recompute_state(self):
        for rec in self:
            net = rec.net_issued_qty
            if net <= 0:
                rec.state = 'authorized'
            elif net < rec.authorized_qty - 0.001:
                rec.state = 'partial'
            else:
                rec.state = 'fully_issued'

    def action_cancel(self):
        for rec in self:
            rec.state = 'cancelled'

    def action_issue_wizard(self):
        self.ensure_one()
        if self.state not in ('authorized', 'partial'):
            raise UserError('This authorization has already been fully issued or cancelled.')
        dest_location_id = False
        for wo in self.production_id.workorder_ids:
            if wo.workcenter_id.location_id:
                dest_location_id = wo.workcenter_id.location_id.id
                break
        wizard = self.env['reema.material.issue.wizard'].create({
            'issuance_id': self.id,
            'issued_qty': max(self.remaining_qty, 0),
            'destination_location_id': dest_location_id,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': 'Issue Materials',
            'res_model': 'reema.material.issue.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_return_wizard(self):
        self.ensure_one()
        if self.state not in ('partial', 'fully_issued'):
            raise UserError('No issued quantity to return.')
        last_dest = self.line_ids[:1].destination_location_id.id if self.line_ids else False
        wizard = self.env['reema.material.return.wizard'].create({
            'issuance_id': self.id,
            'return_from_location_id': last_dest,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': 'Return Materials',
            'res_model': 'reema.material.return.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_open_issuance(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'reema.material.issuance',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_print(self):
        return self.env.ref('reema_mrp.action_report_material_issuance').report_action(self)


class ReemaMaterialIssuanceLine(models.Model):
    _name = 'reema.material.issuance.line'
    _description = 'Material Issue Log Entry'
    _order = 'date desc'

    issuance_id = fields.Many2one('reema.material.issuance', string='Issuance',
                                  required=True, ondelete='cascade')
    product_uom_id = fields.Many2one('uom.uom', related='issuance_id.product_uom_id',
                                     string='UOM', readonly=True)
    issued_qty = fields.Float(string='Issued Qty', required=True)
    destination_location_id = fields.Many2one('stock.location', string='Issued To',
                                              readonly=True)
    contractor_id = fields.Many2one('res.partner', string='Contractor', readonly=True)
    carried_by = fields.Char(string='Carried By', readonly=True)
    move_id = fields.Many2one('stock.move', string='Stock Move', readonly=True)
    date = fields.Datetime(string='Date', readonly=True)
    issued_by = fields.Many2one('res.users', string='Issued By', readonly=True)
    notes = fields.Char(string='Notes')
    is_reversal = fields.Boolean(string='Is Reversal', readonly=True, default=False)
    reversal_of_id = fields.Many2one('reema.material.issuance.line', string='Reversal Of',
                                     readonly=True)

    def action_reverse_issue_line(self):
        self.ensure_one()
        if self.is_reversal:
            raise UserError('Cannot reverse a reversal entry.')
        existing = self.env['reema.material.issuance.line'].search(
            [('reversal_of_id', '=', self.id)], limit=1)
        if existing:
            raise UserError('This entry has already been reversed.')
        issuance = self.issuance_id
        uom_name = self.product_uom_id.name or ''
        date_str = fields.Datetime.to_string(self.date) if self.date else '—'

        rev_move = False
        if self.move_id and self.move_id.state == 'done':
            rev_move = self.env['stock.move'].create({
                'name': f'RMI Reversal: {issuance.product_id.name}',
                'product_id': issuance.product_id.id,
                'product_uom': issuance.product_uom_id.id,
                'product_uom_qty': abs(self.issued_qty),
                'location_id': self.destination_location_id.id,
                'location_dest_id': issuance.production_id.location_src_id.id,
                'origin': f'Reversal: {issuance.name}',
                'company_id': issuance.production_id.company_id.id,
            })
            rev_move._action_confirm()
            rev_move.quantity = abs(self.issued_qty)
            rev_move._action_done()

        self.env['reema.material.issuance.line'].create({
            'issuance_id': issuance.id,
            'issued_qty': -abs(self.issued_qty),
            'destination_location_id': self.destination_location_id.id,
            'contractor_id': self.contractor_id.id,
            'carried_by': self.carried_by,
            'move_id': rev_move.id if rev_move else False,
            'date': fields.Datetime.now(),
            'issued_by': self.env.uid,
            'is_reversal': True,
            'reversal_of_id': self.id,
            'notes': f'Reversal of entry dated {date_str}',
        })

        issuance.message_post(body=Markup(
            f'<b>Issue entry reversed</b><br/>'
            f'Original qty: <b>{abs(self.issued_qty):.3f} {uom_name}</b><br/>'
            f'Issued to: {self.destination_location_id.name or "—"}<br/>'
            f'Original date: {date_str}<br/>'
            f'<b>Reversed by: {self.env.user.name}</b>'
        ))
        issuance._recompute_state()


class ReemaMaterialReturnLine(models.Model):
    _name = 'reema.material.return.line'
    _description = 'Material Return Entry'
    _order = 'date desc'

    issuance_id = fields.Many2one('reema.material.issuance', string='Issuance',
                                  required=True, ondelete='cascade')
    product_uom_id = fields.Many2one('uom.uom', related='issuance_id.product_uom_id',
                                     string='UOM', readonly=True)
    returned_qty = fields.Float(string='Returned Qty', required=True)
    return_from_location_id = fields.Many2one('stock.location', string='Returned From',
                                              readonly=True)
    fault_description = fields.Char(string='Reason', readonly=True)
    move_id = fields.Many2one('stock.move', string='Stock Move', readonly=True)
    date = fields.Datetime(string='Date', readonly=True)
    returned_by = fields.Many2one('res.users', string='Returned By', readonly=True)
    notes = fields.Char(string='Notes')
    is_reversal = fields.Boolean(string='Is Reversal', readonly=True, default=False)
    reversal_of_id = fields.Many2one('reema.material.return.line', string='Reversal Of',
                                     readonly=True)

    def action_reverse_return_line(self):
        self.ensure_one()
        if self.is_reversal:
            raise UserError('Cannot reverse a reversal entry.')
        existing = self.env['reema.material.return.line'].search(
            [('reversal_of_id', '=', self.id)], limit=1)
        if existing:
            raise UserError('This entry has already been reversed.')
        issuance = self.issuance_id
        uom_name = self.product_uom_id.name or ''
        date_str = fields.Datetime.to_string(self.date) if self.date else '—'

        rev_move = False
        if self.move_id and self.move_id.state == 'done':
            rev_move = self.env['stock.move'].create({
                'name': f'RMI Return Reversal: {issuance.product_id.name}',
                'product_id': issuance.product_id.id,
                'product_uom': issuance.product_uom_id.id,
                'product_uom_qty': abs(self.returned_qty),
                'location_id': issuance.production_id.location_src_id.id,
                'location_dest_id': self.return_from_location_id.id,
                'origin': f'Return Reversal: {issuance.name}',
                'company_id': issuance.production_id.company_id.id,
            })
            rev_move._action_confirm()
            rev_move.quantity = abs(self.returned_qty)
            rev_move._action_done()

        self.env['reema.material.return.line'].create({
            'issuance_id': issuance.id,
            'returned_qty': -abs(self.returned_qty),
            'return_from_location_id': self.return_from_location_id.id,
            'fault_description': f'Reversal of entry dated {date_str}',
            'move_id': rev_move.id if rev_move else False,
            'date': fields.Datetime.now(),
            'returned_by': self.env.uid,
            'is_reversal': True,
            'reversal_of_id': self.id,
            'notes': self.notes,
        })

        issuance.message_post(body=Markup(
            f'<b>Return entry reversed</b><br/>'
            f'Original qty: <b>{abs(self.returned_qty):.3f} {uom_name}</b><br/>'
            f'Returned from: {self.return_from_location_id.name or "—"}<br/>'
            f'Original date: {date_str}<br/>'
            f'<b>Reversed by: {self.env.user.name}</b>'
        ))
        issuance._recompute_state()


class ReemaMaterialReturnWizard(models.TransientModel):
    _name = 'reema.material.return.wizard'
    _description = 'Return Materials Wizard'

    issuance_id = fields.Many2one('reema.material.issuance', required=True, readonly=True)
    product_id = fields.Many2one('product.product', related='issuance_id.product_id',
                                 readonly=True, string='Product')
    product_uom_id = fields.Many2one('uom.uom', related='issuance_id.product_uom_id',
                                     readonly=True, string='UOM')
    total_issued_qty = fields.Float(related='issuance_id.total_issued_qty',
                                    readonly=True, string='Total Issued')
    total_returned_qty = fields.Float(related='issuance_id.total_returned_qty',
                                      readonly=True, string='Already Returned')
    returnable_qty = fields.Float(related='issuance_id.net_issued_qty',
                                  readonly=True, string='Max Returnable')
    returned_qty = fields.Float(string='Qty to Return')
    return_from_location_id = fields.Many2one(
        'stock.location', string='Return From (Hall)',
        domain="[('usage', '=', 'internal')]"
    )
    fault_description = fields.Char(string='Reason')
    notes = fields.Char(string='Notes')

    def action_confirm(self):
        self.ensure_one()
        issuance = self.issuance_id
        if self.returned_qty <= 0:
            raise UserError('Return quantity must be greater than zero.')
        if not self.return_from_location_id:
            raise UserError('Please select the hall location you are returning from.')
        if not self.fault_description:
            raise UserError('Please enter the fault / reason for the return.')
        if self.returned_qty > issuance.net_issued_qty + 0.001:
            raise UserError(
                f'Cannot return {self.returned_qty:.3f} {issuance.product_uom_id.name}.\n\n'
                f'Maximum returnable quantity: {issuance.net_issued_qty:.3f}.'
            )
        move = self.env['stock.move'].create({
            'name': f'RMI Return: {issuance.product_id.name}',
            'product_id': issuance.product_id.id,
            'product_uom': issuance.product_uom_id.id,
            'product_uom_qty': self.returned_qty,
            'location_id': self.return_from_location_id.id,
            'location_dest_id': issuance.production_id.location_src_id.id,
            'origin': f'Return: {issuance.name}',
            'company_id': issuance.production_id.company_id.id,
        })
        move._action_confirm()
        move.quantity = self.returned_qty
        move._action_done()

        self.env['reema.material.return.line'].create({
            'issuance_id': issuance.id,
            'returned_qty': self.returned_qty,
            'return_from_location_id': self.return_from_location_id.id,
            'fault_description': self.fault_description,
            'move_id': move.id,
            'date': fields.Datetime.now(),
            'returned_by': self.env.uid,
            'notes': self.notes,
        })

        issuance.message_post(body=Markup(
            f'<b>Material returned to store</b><br/>'
            f'Qty: <b>{self.returned_qty:.3f} {issuance.product_uom_id.name}</b><br/>'
            f'Returned from: {self.return_from_location_id.name}<br/>'
            f'Reason: {self.fault_description}<br/>'
            f'<b>Returned by: {self.env.user.name}</b>'
        ))

        issuance._recompute_state()


class ReemaMaterialIssueWizard(models.TransientModel):
    _name = 'reema.material.issue.wizard'
    _description = 'Issue Materials Wizard'

    issuance_id = fields.Many2one('reema.material.issuance', required=True, readonly=True)
    product_id = fields.Many2one('product.product', related='issuance_id.product_id',
                                 readonly=True, string='Product')
    product_uom_id = fields.Many2one('uom.uom', related='issuance_id.product_uom_id',
                                     readonly=True, string='UOM')
    authorized_qty = fields.Float(related='issuance_id.authorized_qty',
                                  readonly=True, string='Total Authorized')
    remaining_qty = fields.Float(related='issuance_id.remaining_qty',
                                 readonly=True, string='Remaining to Issue')
    issued_qty = fields.Float(string='Qty to Issue Now')
    destination_location_id = fields.Many2one(
        'stock.location', string='Issue To (Hall)',
        domain="[('usage', '=', 'internal')]"
    )
    available_contractor_ids = fields.Many2many(
        'res.partner',
        compute='_compute_available_contractors'
    )
    contractor_id = fields.Many2one(
        'res.partner', string='Contractor',
        domain="[('id', 'in', available_contractor_ids)]"
    )
    carried_by = fields.Char(string='Carried By')
    notes = fields.Char(string='Notes')

    @api.depends('issuance_id')
    def _compute_available_contractors(self):
        for wiz in self:
            contractors = wiz.issuance_id.production_id.workorder_ids.mapped('contractor_ids')
            wiz.available_contractor_ids = contractors

    @api.onchange('contractor_id')
    def _onchange_contractor_id(self):
        if self.contractor_id:
            self.carried_by = self.contractor_id.name

    def action_confirm(self):
        self.ensure_one()
        issuance = self.issuance_id
        if self.issued_qty <= 0:
            raise UserError('Quantity to issue must be greater than zero.')
        if not self.destination_location_id:
            raise UserError('Please select a destination location.')
        if not self.contractor_id:
            raise UserError('Please select a contractor.')
        if self.issued_qty > issuance.remaining_qty + 0.001:
            raise UserError(
                f'Cannot issue {self.issued_qty:.3f} {issuance.product_uom_id.name}.\n\n'
                f'Remaining authorized quantity: {issuance.remaining_qty:.3f}.'
            )
        source_location = issuance.production_id.location_src_id
        quants = self.env['stock.quant'].search([
            ('product_id', '=', issuance.product_id.id),
            ('location_id', 'child_of', source_location.id),
        ])
        available_qty = sum(q.quantity - q.reserved_quantity for q in quants)
        if self.issued_qty > available_qty + 0.001:
            raise UserError(
                f'Insufficient stock for {issuance.product_id.name}.\n\n'
                f'Available at {source_location.complete_name}: '
                f'{max(available_qty, 0):.3f} {issuance.product_uom_id.name}\n'
                f'Requested: {self.issued_qty:.3f} {issuance.product_uom_id.name}'
            )
        move = self.env['stock.move'].create({
            'name': f'RMI: {issuance.product_id.name}',
            'product_id': issuance.product_id.id,
            'product_uom': issuance.product_uom_id.id,
            'product_uom_qty': self.issued_qty,
            'location_id': source_location.id,
            'location_dest_id': self.destination_location_id.id,
            'origin': f'{issuance.name} / {issuance.production_id.name}',
            'company_id': issuance.production_id.company_id.id,
        })
        move._action_confirm()
        move.quantity = self.issued_qty
        move._action_done()

        self.env['reema.material.issuance.line'].create({
            'issuance_id': issuance.id,
            'issued_qty': self.issued_qty,
            'destination_location_id': self.destination_location_id.id,
            'contractor_id': self.contractor_id.id,
            'carried_by': self.carried_by,
            'move_id': move.id,
            'date': fields.Datetime.now(),
            'issued_by': self.env.uid,
            'notes': self.notes,
        })

        issuance._recompute_state()


class StockMoveReemaExt(models.Model):
    _inherit = 'stock.move'

    has_issuance = fields.Boolean(compute='_compute_has_issuance', string='Has Issuance')

    def _compute_has_issuance(self):
        if not self.ids:
            for move in self:
                move.has_issuance = False
            return
        issuances = self.env['reema.material.issuance'].search([
            ('raw_move_id', 'in', self.ids),
            ('state', '!=', 'cancelled'),
        ])
        issued_move_ids = set(issuances.mapped('raw_move_id').ids)
        for move in self:
            move.has_issuance = move.id in issued_move_ids

    def action_authorize_issuance(self):
        """Authorize button — create issuance silently and stay on the MO page."""
        self.ensure_one()
        if not self.raw_material_production_id:
            raise UserError('This move is not linked to a Manufacturing Order component.')
        existing = self.env['reema.material.issuance'].search(
            [('raw_move_id', '=', self.id), ('state', '!=', 'cancelled')], limit=1
        )
        if existing:
            return False
        self.env['reema.material.issuance'].create({
            'production_id': self.raw_material_production_id.id,
            'raw_move_id': self.id,
            'authorized_qty': self.product_uom_qty,
            'authorized_by': self.env.uid,
            'state': 'authorized',
        })
        return False

    def action_view_issuance(self):
        """View Auth button — open the existing issuance as a full page."""
        self.ensure_one()
        existing = self.env['reema.material.issuance'].search(
            [('raw_move_id', '=', self.id), ('state', '!=', 'cancelled')], limit=1
        )
        if not existing:
            raise UserError('No authorization found for this component.')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Material Issuance',
            'res_model': 'reema.material.issuance',
            'res_id': existing.id,
            'view_mode': 'form',
            'target': 'current',
        }


class MrpProductionIssuanceExt(models.Model):
    _inherit = 'mrp.production'

    issuance_ids = fields.One2many('reema.material.issuance', 'production_id',
                                   string='Material Issuances')
    issuance_count = fields.Integer(compute='_compute_issuance_count', string='Issuances')
    pending_issuance_count = fields.Integer(
        compute='_compute_pending_issuance_count', store=True,
        string='Pending Issuances'
    )

    def _compute_issuance_count(self):
        for rec in self:
            rec.issuance_count = len(rec.issuance_ids)

    @api.depends('issuance_ids.state')
    def _compute_pending_issuance_count(self):
        for rec in self:
            rec.pending_issuance_count = len(
                rec.issuance_ids.filtered(lambda i: i.state in ('authorized', 'partial'))
            )

    def action_view_issuances(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Material Issuances',
            'res_model': 'reema.material.issuance',
            'view_mode': 'list,form',
            'domain': [('production_id', '=', self.id)],
            'context': {'default_production_id': self.id},
        }
