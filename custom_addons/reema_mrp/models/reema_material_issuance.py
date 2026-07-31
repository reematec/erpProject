from markupsafe import Markup
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class ReemaMaterialIssuance(models.Model):
    _name = 'reema.material.issuance'
    _description = 'Raw Material Issuance Authorization'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name desc'

    name = fields.Char(string='Reference', readonly=True, copy=False,
                       default=lambda self: _('New'), tracking=True)
    production_id = fields.Many2one('mrp.production', string='Manufacturing Order',
                                    required=False, ondelete='set null', readonly=True, tracking=True)
    production_name = fields.Char(string='MO', readonly=True)
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
        ('over_issued', 'Over Issued'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='authorized', required=True, tracking=True)
    authorized_by = fields.Many2one('res.users', string='Authorized By', readonly=True)
    date_authorized = fields.Date(string='Authorized On', readonly=True,
                                  default=fields.Date.context_today)
    line_ids = fields.One2many('reema.material.issuance.line', 'issuance_id',
                               string='Issue Log')
    return_line_ids = fields.One2many('reema.material.return.line', 'issuance_id',
                                      string='Return Log')
    production_order_id = fields.Many2one(
        'reema.production.order', string='Production Order',
        compute='_compute_production_order_id', store=True,
    )
    has_any_issue = fields.Boolean(compute='_compute_has_any_issue')
    can_withdraw = fields.Boolean(compute='_compute_can_withdraw')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'reema.material.issuance') or _('New')
            if vals.get('production_id') and not vals.get('production_name'):
                vals['production_name'] = self.env['mrp.production'].browse(
                    vals['production_id']).name
        return super().create(vals_list)

    @api.depends('line_ids')
    def _compute_has_any_issue(self):
        for rec in self:
            rec.has_any_issue = bool(rec.line_ids)

    def _compute_can_withdraw(self):
        user = self.env.user
        is_manager = user.has_group('reema_mrp.group_reema_production_manager')
        is_admin = user.has_group('base.group_system')
        for rec in self:
            rec.can_withdraw = is_manager or is_admin or (user == rec.authorized_by)

    @api.depends('production_id')
    def _compute_production_order_id(self):
        for rec in self:
            line = rec.production_id.sudo().reema_po_line_ids[:1]
            rec.production_order_id = line.order_id if line else False

    @api.constrains('production_id', 'state')
    def _check_production_id_required(self):
        for rec in self:
            if not rec.production_id and rec.state != 'cancelled':
                raise ValidationError(
                    "Manufacturing Order is required for non-cancelled authorizations."
                )

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
            elif net > rec.authorized_qty + 0.001:
                rec.state = 'over_issued'
            elif net < rec.authorized_qty - 0.001:
                rec.state = 'partial'
            else:
                rec.state = 'fully_issued'

    def unlink(self):
        for rec in self:
            if rec.has_any_issue:
                raise UserError(
                    f"Cannot delete {rec.name} — material has already been physically "
                    f"issued against it. Return all issued material first."
                )
        return super().unlink()

    def action_cancel(self):
        for rec in self:
            rec.state = 'cancelled'
            if rec.production_id:
                rec.production_id._message_log(
                    body=Markup(f'Material issuance <b>{rec.name}</b> ({rec.product_id.display_name}) cancelled.'),
                )

    def action_bulk_withdraw(self):
        eligible = self.filtered(lambda r: not r.has_any_issue and r.state not in ('cancelled', 'fully_issued'))
        if not eligible:
            raise UserError("No eligible authorizations to withdraw. Records with issued material or already cancelled cannot be withdrawn in bulk.")
        eligible.action_cancel()

    def action_issue_wizard(self):
        self.ensure_one()
        extra = self.production_id.extra_material_issuance or 'warning'
        if self.state == 'cancelled':
            raise UserError('This authorization has been cancelled and cannot be issued against.')
        if self.state in ('fully_issued', 'over_issued') and extra == 'strict':
            raise UserError('This authorization has already been fully issued. Extra issuance is not allowed for this Manufacturing Order.')
        # The component is consumed at a specific operation/work center. Match
        # the work order(s) for that operation so the destination hall and
        # contractor list reflect THAT hall only — not every WO of the MO.
        operation = self.raw_move_id.operation_id
        workorders = self.production_id.sudo().workorder_ids
        matched = workorders.filtered(lambda w: w.operation_id == operation) if operation else workorders
        if not matched:
            matched = workorders
        dest_location_id = False
        contractor_ids = []
        for wo in matched:
            if wo.workcenter_id.location_id and not dest_location_id:
                dest_location_id = wo.workcenter_id.location_id.id
            contractor_ids += wo.contractor_ids.ids
        if not dest_location_id:
            raise UserError(
                "Cannot issue materials: no Hall Location is configured on any "
                "work center of this Manufacturing Order. Please set a Hall "
                "Location on the work center first."
            )
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
            'context': {'allowed_contractor_ids': contractor_ids},
        }

    def action_return_wizard(self):
        self.ensure_one()
        if self.state not in ('partial', 'fully_issued', 'over_issued'):
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
        return {
            'type': 'ir.actions.act_url',
            'url': '/report/html/reema_mrp.report_material_issuance_slip/%s' % ','.join(str(i) for i in self.ids),
            'target': 'new',
        }


class ReemaMaterialIssuanceLine(models.Model):
    _name = 'reema.material.issuance.line'
    _description = 'Material Issue Log Entry'
    _order = 'date desc'

    name = fields.Char(string='Reference', readonly=True, copy=False, default='New')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'reema.material.issuance.line') or 'New'
        return super().create(vals_list)

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

        issuance._message_log(body=Markup(
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

    name = fields.Char(string='Reference', readonly=True, copy=False, default='New')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'reema.material.return.line') or 'New'
        return super().create(vals_list)

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

        issuance._message_log(body=Markup(
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

        was_over_issued = issuance.state == 'over_issued'

        return_body = Markup(
            f'<b>Material returned to store</b> — {issuance.name}<br/>'
            f'Product: <b>{issuance.product_id.display_name}</b><br/>'
            f'Qty: <b>{self.returned_qty:.3f} {issuance.product_uom_id.name}</b><br/>'
            f'MO: {issuance.production_id.name} | '
            f'Returned from: {self.return_from_location_id.name}<br/>'
            f'Reason: {self.fault_description}<br/>'
            f'Returned by: {self.env.user.name}'
        )
        issuance._message_log(body=return_body)
        issuance.production_id._message_log(body=return_body)

        issuance._recompute_state()

        if was_over_issued:
            manager_group = self.env.ref('reema_mrp.group_reema_production_manager', raise_if_not_found=False)
            admin_group = self.env.ref('base.group_system', raise_if_not_found=False)
            notify_users = (manager_group.users if manager_group else self.env['res.users'])
            notify_users |= (admin_group.users if admin_group else self.env['res.users'])
            notify_users -= self.env.user
            notify_partners = notify_users.mapped('partner_id')
            if notify_partners:
                issuance.sudo().with_context(
                    mail_notify_force_send=False,
                    mail_auto_delete=False,
                ).message_post(
                    body=return_body,
                    message_type='comment',
                    subtype_xmlid='mail.mt_note',
                    partner_ids=notify_partners.ids,
                )


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
    contractor_id = fields.Many2one(
        'res.partner', string='Contractor',
    )
    carried_by = fields.Char(string='Carried By')
    notes = fields.Char(string='Notes')
    over_qty = fields.Float(compute='_compute_over_qty')

    @api.depends('issued_qty', 'remaining_qty')
    def _compute_over_qty(self):
        for rec in self:
            rec.over_qty = max(rec.issued_qty - rec.remaining_qty, 0.0)

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
            mode = issuance.production_id.extra_material_issuance or 'warning'
            if mode == 'strict':
                raise UserError(
                    f'Cannot issue {self.issued_qty:.3f} {issuance.product_uom_id.name}.\n\n'
                    f'Remaining authorized quantity: {issuance.remaining_qty:.3f}.\n'
                    f'Extra material issuance is blocked for this Manufacturing Order.'
                )
            elif mode == 'warning':
                extra = self.issued_qty - issuance.remaining_qty
                warning_body = Markup(
                    f'<b>Extra material issued</b> — {issuance.name}<br/>'
                    f'Product: <b>{issuance.product_id.display_name}</b><br/>'
                    f'Issued: <b>{self.issued_qty:.3f} {issuance.product_uom_id.name}</b> '
                    f'(exceeds authorized by <b>{extra:.3f} {issuance.product_uom_id.name}</b>)<br/>'
                    f'MO: {issuance.production_id.name} | '
                    f'Authorized: {issuance.authorized_qty:.3f} | '
                    f'Remaining before this issue: {issuance.remaining_qty:.3f}<br/>'
                    f'Issued by: {self.env.user.name}'
                )
                # Log to both RMI and MO chatters
                issuance._message_log(body=warning_body)
                issuance.production_id._message_log(body=warning_body)
                # Inbox notification to production managers + system admins
                manager_group = self.env.ref('reema_mrp.group_reema_production_manager', raise_if_not_found=False)
                admin_group = self.env.ref('base.group_system', raise_if_not_found=False)
                notify_users = (manager_group.users if manager_group else self.env['res.users'])
                notify_users |= (admin_group.users if admin_group else self.env['res.users'])
                # exclude the person who just issued (no point notifying yourself)
                notify_users -= self.env.user
                notify_partners = notify_users.mapped('partner_id')
                if notify_partners:
                    issuance.sudo().with_context(
                        mail_notify_force_send=False,
                        mail_auto_delete=False,
                    ).message_post(
                        body=warning_body,
                        message_type='comment',
                        subtype_xmlid='mail.mt_note',
                        partner_ids=notify_partners.ids,
                    )
            # flexible: silent, no chatter post
        source_location = issuance.production_id.location_src_id
        quants = self.env['stock.quant'].search([
            ('product_id', '=', issuance.product_id.id),
            ('location_id', 'child_of', source_location.id),
        ])
        # Check against ON-HAND quantity, not unreserved. The stock reserved
        # here is the MO's own component demand (standard MRP reservation on
        # confirmation) — the very requirement this issuance fulfills. Counting
        # it as unavailable would make the issuance fight its own MO.
        available_qty = sum(q.quantity for q in quants)
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
        issuance.production_id._message_log(
            body=Markup(
                f'Material issued — <b>{issuance.name}</b>: '
                f'{self.issued_qty:.3f} {issuance.product_uom_id.name} of {issuance.product_id.display_name} '
                f'→ {self.destination_location_id.name} (by {self.env.user.name})'
            ),
        )


class StockMoveReemaExt(models.Model):
    _inherit = 'stock.move'

    has_issuance = fields.Boolean(compute='_compute_has_issuance', string='Has Issuance')
    move_net_issued_qty = fields.Float(compute='_compute_move_net_issued_qty', string='Issued')

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

    def _compute_move_net_issued_qty(self):
        if not self.ids:
            for move in self:
                move.move_net_issued_qty = 0.0
            return
        issuances = self.env['reema.material.issuance'].search([
            ('raw_move_id', 'in', self.ids),
            ('state', '!=', 'cancelled'),
        ])
        net_by_move = {}
        for iss in issuances:
            mid = iss.raw_move_id.id
            net_by_move[mid] = net_by_move.get(mid, 0.0) + iss.net_issued_qty
        for move in self:
            move.move_net_issued_qty = net_by_move.get(move.id, 0.0)

    def action_authorize_issuance(self):
        """Authorize button — create issuance silently and stay on the MO page."""
        self.ensure_one()
        if not self.raw_material_production_id:
            raise UserError('This move is not linked to a Manufacturing Order component.')
        if self.raw_material_production_id.state not in ('confirmed', 'progress', 'to_close'):
            raise UserError(
                "The Manufacturing Order must be confirmed before creating a material issuance authorization."
            )
        existing = self.env['reema.material.issuance'].search(
            [('raw_move_id', '=', self.id), ('state', '!=', 'cancelled')], limit=1
        )
        if existing:
            return False
        issuance = self.env['reema.material.issuance'].create({
            'production_id': self.raw_material_production_id.id,
            'raw_move_id': self.id,
            'authorized_qty': self.product_uom_qty,
            'authorized_by': self.env.uid,
            'state': 'authorized',
        })
        # Inbox notification to store keepers — new authorization ready to issue
        store_group = self.env.ref('reema_mrp.group_reema_store', raise_if_not_found=False)
        notify_users = (store_group.users if store_group else self.env['res.users'])
        notify_users -= self.env.user
        notify_partners = notify_users.mapped('partner_id')
        if notify_partners:
            issuance.sudo().with_context(
                mail_notify_force_send=False,
                mail_auto_delete=False,
            ).message_post(
                body=Markup(
                    f'<b>New material issuance authorized</b> — {issuance.name}<br/>'
                    f'Product: <b>{issuance.product_id.display_name}</b><br/>'
                    f'Qty: <b>{issuance.authorized_qty:.3f} {issuance.product_uom_id.name}</b><br/>'
                    f'MO: {issuance.production_id.name}<br/>'
                    f'Authorized by: {self.env.user.name}'
                ),
                message_type='comment',
                subtype_xmlid='mail.mt_note',
                partner_ids=notify_partners.ids,
            )
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
        return self._action_view_url_new_tab('reema_mrp.reema_material_issuance_action_from_mo')
