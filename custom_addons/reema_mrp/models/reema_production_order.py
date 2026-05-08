from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ReemaProductionOrder(models.Model):
    _name = 'reema.production.order'
    _description = 'Production Order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name desc'

    name = fields.Char(string='PO Reference', readonly=True, copy=False,
                       default=lambda self: _('New'), tracking=True)
    invoice_id = fields.Many2one('reema.invoice', string='Pro Forma Invoice',
                                 required=True, ondelete='restrict', tracking=True)
    partner_id = fields.Many2one('res.partner', string='Customer',
                                 related='invoice_id.partner_id', store=True, readonly=True)
    state = fields.Selection([
        ('draft',     'Draft'),
        ('confirmed', 'Confirmed'),
        ('done',      'Done'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True)
    date_planned = fields.Date(string='Planned Date', tracking=True)
    line_ids = fields.One2many('reema.production.order.line', 'order_id', string='Lines')
    mo_count = fields.Integer(string='MO Count', compute='_compute_mo_count')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('reema.production.order') or _('New')
        return super().create(vals_list)

    def _compute_mo_count(self):
        for rec in self:
            rec.mo_count = len(rec.line_ids.filtered('mo_id').mapped('mo_id'))

    def action_confirm(self):
        self.write({'state': 'confirmed'})

    def action_done(self):
        self.write({'state': 'done'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})

    def action_create_mos(self):
        self.ensure_one()
        pending = self.line_ids.filtered(lambda l: l.bom_id and not l.mo_id)
        if not pending:
            raise UserError(
                'No lines to process. Either all MOs are already created, '
                'or remaining lines have no BOM assigned yet.'
            )
        # Validate operation dependency chain before creating anything.
        # Only block if nobody defined any dependency at all (clear oversight).
        # Multiple roots are allowed — valid for parallel-track workflows.
        for line in pending:
            ops = line.bom_id.operation_ids
            if len(ops) > 1:
                has_any_dep = any(op.blocked_by_operation_ids for op in ops)
                if not has_any_dep:
                    raise UserError(
                        f'BOM for "{line.sample_id.name}" has {len(ops)} operations '
                        f'but none have "Blocked By" defined.\n\n'
                        f'Open the BOM → Operations tab → define the hall sequence '
                        f'using the "Blocked By" column before creating MOs.'
                    )
        created_mos = self.env['mrp.production']
        for line in pending:
            # product_id must be product.product (variant), not product.template.
            # Use bom's specific variant if set, otherwise take the single variant from template.
            product = line.bom_id.product_id or line.bom_id.product_tmpl_id.product_variant_id
            if not product:
                raise UserError(
                    f'Blueprint "{line.sample_id.name}" BOM has no product variant. '
                    f'Please ensure the BOM product is properly configured.'
                )
            mo = self.env['mrp.production'].create({
                'product_id': product.id,
                'product_qty': line.qty,
                'bom_id': line.bom_id.id,
                'origin': self.name,
                'date_deadline': fields.Datetime.to_datetime(self.date_planned) if self.date_planned else False,
            })
            line.mo_id = mo
            created_mos |= mo
        return {
            'type': 'ir.actions.act_window',
            'name': 'Manufacturing Orders',
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': [('id', 'in', created_mos.ids)],
        }

    def action_view_mos(self):
        self.ensure_one()
        mo_ids = self.line_ids.filtered('mo_id').mapped('mo_id').ids
        return {
            'type': 'ir.actions.act_window',
            'name': 'Manufacturing Orders',
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': [('id', 'in', mo_ids)],
        }


class ReemaProductionOrderLine(models.Model):
    _name = 'reema.production.order.line'
    _description = 'Production Order Line'

    order_id = fields.Many2one('reema.production.order', string='Production Order',
                                ondelete='cascade', required=True)
    invoice_line_id = fields.Many2one('reema.invoice.line', string='Invoice Line',
                                      ondelete='set null')
    sample_id = fields.Many2one('reema.sampling.blueprint', string='Blueprint', required=True)
    product_tmpl_id = fields.Many2one('product.template', related='sample_id.product_tmpl_id')
    size = fields.Char(string='Size')
    qty = fields.Float(string='Quantity', default=1.0)
    bom_id = fields.Many2one('mrp.bom', string='Bill of Materials')
    mo_id = fields.Many2one('mrp.production', string='Manufacturing Order', readonly=True)

    def action_reset_mo(self):
        self.ensure_one()
        mo = self.mo_id
        if not mo:
            return
        if mo.state in ('progress', 'done'):
            raise UserError(
                f'Cannot reset: {mo.name} has already started or is completed.\n\n'
                f'Work orders have been recorded against it. '
                f'Coordinate with the production team before making changes.'
            )
        # Cancel first (works for both draft and confirmed states)
        if mo.state != 'cancel':
            mo.action_cancel()
        # Delete the cancelled MO — it was wrong due to incomplete BOM, no work was done
        mo.unlink()
        self.mo_id = False


class ReemaInvoiceProductionExt(models.Model):
    _inherit = 'reema.invoice'

    production_order_ids = fields.One2many('reema.production.order', 'invoice_id',
                                            string='Production Orders')
    production_order_count = fields.Integer(string='Production Orders',
                                             compute='_compute_production_order_count')

    def _compute_production_order_count(self):
        for rec in self:
            rec.production_order_count = len(rec.production_order_ids)

    def action_create_production_order(self):
        self.ensure_one()
        lines = []
        for inv_line in self.line_ids:
            if not inv_line.sample_id:
                continue
            bom = self.env['mrp.bom'].search(
                [('product_tmpl_id', '=', inv_line.sample_id.product_tmpl_id.id)], limit=1
            )
            lines.append((0, 0, {
                'invoice_line_id': inv_line.id,
                'sample_id': inv_line.sample_id.id,
                'size': inv_line.size or '',
                'qty': inv_line.qty,
                'bom_id': bom.id if bom else False,
            }))
        po = self.env['reema.production.order'].create({
            'invoice_id': self.id,
            'date_planned': self.shipping_date or fields.Date.context_today(self),
            'line_ids': lines,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': 'Production Order',
            'res_model': 'reema.production.order',
            'view_mode': 'form',
            'res_id': po.id,
        }

    def action_view_production_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Production Orders',
            'res_model': 'reema.production.order',
            'view_mode': 'list,form',
            'domain': [('invoice_id', '=', self.id)],
            'context': {'default_invoice_id': self.id},
        }


class MrpWorkorderReema(models.Model):
    _inherit = 'mrp.workorder'

    def button_start(self, raise_on_invalid_state=False):
        for wo in self:
            # Block 1: at least one contractor must be assigned before work can start.
            if not wo.contractor_ids:
                raise UserError(
                    f'Cannot start "{wo.workcenter_id.name}".\n\n'
                    f'No contractor assigned to this work order. '
                    f'Assign at least one contractor before starting production.'
                )
            # Block 2: Store Keeper must have issued at least some materials.
            # Partial issue is fine — halls process what is available.
            # But if nothing has been issued at all, the store entry was skipped.
            mo = wo.production_id
            raw_moves = mo.move_raw_ids.filtered(lambda m: m.state != 'cancel')
            if raw_moves and not any(m.state == 'done' for m in raw_moves):
                raise UserError(
                    f'Cannot start "{wo.workcenter_id.name}" on {mo.name}.\n\n'
                    f'No materials have been issued from the Raw Material Store yet.\n\n'
                    f'The Store Keeper must validate the material transfer in Inventory '
                    f'before production can begin.'
                )
            # Block 3: subsequent halls need SFG output from the previous hall.
            # Even 1 unit is enough — cutting can start on whatever lamination has ready.
            # Skip this check if the predecessor is already fully done or cancelled.
            for pred in wo.blocked_by_workorder_ids:
                if pred.state in ('done', 'cancel'):
                    continue
                if pred.qty_batch_completed == 0:
                    raise UserError(
                        f'Cannot start "{wo.workcenter_id.name}".\n\n'
                        f'No output received from {pred.workcenter_id.name} yet.\n\n'
                        f'The {pred.workcenter_id.name} supervisor must log at least one '
                        f'batch before this work order can start.'
                    )
        return super().button_start(raise_on_invalid_state=raise_on_invalid_state)


class MrpBomReemaExt(models.Model):
    _inherit = 'mrp.bom'
    # Every BOM created in this company must have operation dependencies enabled.
    # Overriding default so Waleed never has to remember to tick the checkbox.
    allow_operation_dependencies = fields.Boolean(default=True)


class MrpRoutingWorkcenterReema(models.Model):
    _inherit = 'mrp.routing.workcenter'

    balls_per_unit = fields.Float(
        string='Balls per Unit', default=1.0, required=True,
        digits=(16, 4),
        help='How many finished balls 1 unit of this hall\'s work represents. '
             'E.g. ~6 for Lamination (1 sheet ≈ 6 balls), 0.0417 for Cutting (1 panel = 1/24 ball), '
             '1 for Stitching.'
    )

    def action_delete_operation(self):
        self.unlink()
