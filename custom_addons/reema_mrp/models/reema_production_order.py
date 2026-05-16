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
        for rec in self:
            active_mos = rec.line_ids.mapped('mo_id').filtered(
                lambda mo: mo.state != 'cancel'
            )
            if active_mos:
                mo_names = ', '.join(active_mos.mapped('name'))
                raise UserError(
                    f"Cannot cancel this Production Order while Manufacturing Orders are still active.\n"
                    f"Please cancel the following MOs first: {mo_names}"
                )
        self.write({'state': 'cancelled'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})

    def action_delete_draft(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError("Only draft Production Orders can be deleted.")
        if any(line.mo_id for line in self.line_ids):
            raise UserError(
                "Cannot delete this Production Order because Manufacturing Orders have already been generated. "
                "Cancel all linked MOs first, then cancel this PO before deleting."
            )
        invoice_id = self.invoice_id.id
        self.unlink()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'reema.invoice',
            'res_id': invoice_id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_create_mos(self):
        self.ensure_one()
        # Resync: restore any invoice lines that were removed from the PO
        existing_inv_line_ids = self.line_ids.mapped('invoice_line_id').ids
        for inv_line in self.invoice_id.line_ids:
            if not inv_line.sample_id:
                continue
            if inv_line.id not in existing_inv_line_ids:
                bom = self.env['mrp.bom'].search(
                    [('product_tmpl_id', '=', inv_line.sample_id.product_tmpl_id.id)], limit=1
                )
                self.env['reema.production.order.line'].create({
                    'order_id': self.id,
                    'invoice_line_id': inv_line.id,
                    'sample_id': inv_line.sample_id.id,
                    'size': inv_line.size or '',
                    'qty': inv_line.qty,
                    'bom_id': bom.id if bom else False,
                })
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
            'res_model': 'reema.production.order',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
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
    bom_reference = fields.Char(related='bom_id.reema_reference', string='BOM', readonly=True)
    mo_id = fields.Many2one('mrp.production', string='Manufacturing Order', readonly=True)
    mo_state = fields.Selection(related='mo_id.state', string='MO Status', readonly=True)

    def unlink(self):
        for line in self:
            if not line.mo_id:
                continue
            if line.mo_id.state in ('progress', 'done'):
                raise UserError(
                    f"Cannot delete line for '{line.sample_id.name}' — MO "
                    f"{line.mo_id.name} has already started or is completed."
                )
            # Cancel and delete the linked MO so it doesn't become an orphan
            mo = line.mo_id
            if mo.state != 'cancel':
                mo.action_cancel()
            mo.unlink()
        return super().unlink()

    def action_delete_line(self):
        self.ensure_one()
        self.unlink()

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
    has_active_production_order = fields.Boolean(
        compute='_compute_has_active_production_order',
    )

    def _compute_production_order_count(self):
        for rec in self:
            rec.production_order_count = len(rec.production_order_ids)

    def _compute_has_active_production_order(self):
        for rec in self:
            active = rec.production_order_ids.filtered(lambda po: po.state != 'cancelled')
            if not active:
                active = rec.production_order_ids.mapped('line_ids').mapped('mo_id').filtered(
                    lambda mo: mo.state != 'cancel'
                )
            rec.has_active_production_order = bool(active)

    def action_close(self):
        for rec in self:
            active_pos = rec.production_order_ids.filtered(lambda po: po.state != 'cancelled')
            if active_pos:
                not_done = active_pos.filtered(lambda po: po.state != 'done')
                if not_done:
                    po_names = ', '.join(not_done.mapped('name'))
                    raise UserError(
                        f"Cannot mark {rec.name} as Shipped.\n\n"
                        f"The following Production Orders are not yet completed:\n"
                        f"{po_names}\n\n"
                        f"Mark all Production Orders as Done before shipping."
                    )
        return super().action_close()

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
        pos = self.production_order_ids
        if len(pos) == 1:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Production Order',
                'res_model': 'reema.production.order',
                'view_mode': 'form',
                'res_id': pos.id,
                'target': 'current',
            }
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
            # Block 1: contractor required only for contractor-type work centers.
            if wo.workcenter_id.workforce_type != 'employee' and not wo.contractor_ids:
                raise UserError(
                    f'Cannot start "{wo.workcenter_id.name}".\n\n'
                    f'No contractor assigned to this work order. '
                    f'Assign at least one contractor before starting production.'
                )
            # Block 2: Store Keeper must have physically issued at least some material.
            # Checked via reema.material.issuance.line — NOT mo.move_raw_ids, which stay
            # in 'confirmed' state in our flow (issuance creates its own separate stock.move).
            mo = wo.production_id
            has_issued = self.env['reema.material.issuance.line'].search_count(
                [('issuance_id.production_id', '=', mo.id)]
            ) > 0
            if mo.move_raw_ids.filtered(lambda m: m.state != 'cancel') and not has_issued:
                raise UserError(
                    f'Cannot start "{wo.workcenter_id.name}" on {mo.name}.\n\n'
                    f'No materials have been issued from the Raw Material Store yet.\n\n'
                    f'The Store Keeper must issue material via the Material Issuance form '
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
    # Use the reference number as display name so bom_id Many2one fields show
    # "BOM/2026/0001" instead of the product template name everywhere.
    _rec_name = 'reema_reference'
    # Every BOM created in this company must have operation dependencies enabled.
    # Overriding default so Waleed never has to remember to tick the checkbox.
    allow_operation_dependencies = fields.Boolean(default=True)
    reema_reference = fields.Char(string='BOM Reference', readonly=True, copy=False,
                                   default=lambda self: _('New'))
    has_active_mo = fields.Boolean(compute='_compute_has_active_mo', string='Has Active MO')

    # Fields that must not change once a confirmed MO exists for this BOM.
    _BOM_PROTECTED_FIELDS = {
        'product_tmpl_id', 'product_id', 'product_qty', 'product_uom_id',
        'bom_line_ids', 'operation_ids', 'byproduct_ids',
    }

    def _compute_has_active_mo(self):
        for bom in self:
            bom.has_active_mo = bool(self.env['mrp.production'].search([
                ('bom_id', '=', bom.id),
                ('state', '!=', 'cancel'),
            ], limit=1))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('reema_reference', _('New')) == _('New'):
                vals['reema_reference'] = (
                    self.env['ir.sequence'].next_by_code('reema.bom') or _('New')
                )
        return super().create(vals_list)

    def write(self, vals):
        if self._BOM_PROTECTED_FIELDS & vals.keys():
            for bom in self:
                bom._compute_has_active_mo()
                if bom.has_active_mo:
                    raise UserError(
                        f"BOM {bom.reema_reference} is locked — a Manufacturing Order exists for it. "
                        f"Cancel the MO first, then make your changes."
                    )
        return super().write(vals)

    def unlink(self):
        for bom in self:
            line = self.env['reema.production.order.line'].search(
                [('bom_id', '=', bom.id)], limit=1
            )
            if line:
                raise UserError(
                    f"BOM {bom.reema_reference} cannot be deleted — it is referenced in "
                    f"Production Order {line.order_id.name}. Remove the reference first."
                )
        return super().unlink()


class MrpRoutingWorkcenterReema(models.Model):
    _inherit = 'mrp.routing.workcenter'

    balls_per_unit = fields.Float(
        string='Balls per Unit', default=1.0, required=True,
        digits=(16, 4),
        help='How many finished balls 1 unit of this hall\'s work represents. '
             'E.g. ~6 for Lamination (1 sheet ≈ 6 balls), 0.0417 for Cutting (1 panel = 1/24 ball), '
             '1 for Stitching.'
    )
    piece_rate_id = fields.Many2one(
        'reema.piece.rate',
        string='Piece Rate',
        domain="[('workcenter_id', '=', workcenter_id)]",
    )

    def action_delete_operation(self):
        self.unlink()


class StockPickingTypeReema(models.Model):
    _inherit = 'stock.picking.type'

    @api.model
    def fix_mo_sequence_prefix(self):
        """Change the default WH/MO/ prefix on Manufacturing picking types to MO/YEAR/ format."""
        manuf_types = self.search([('code', '=', 'mrp_operation')])
        for pt in manuf_types:
            if pt.sequence_id and pt.sequence_id.prefix in ('WH/MO/', 'WH/MO/%(year)s/'):
                pt.sequence_id.write({'prefix': 'MO/%(year)s/', 'padding': 5})
