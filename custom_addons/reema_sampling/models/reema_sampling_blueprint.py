from odoo import models, fields, api, _
from odoo.exceptions import UserError

# The 'ReemaSamplingBlueprint' model acts as the core definition for a new ball design.
# We use '_inherits' to link it with 'product.template', which allows us to reuse 
# standard Odoo product functionality (like name, description, etc.) while extending 
# it with our specific sampling requirements.
class ReemaSamplingBlueprint(models.Model):
    _name = 'reema.sampling.blueprint'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _inherits = {'product.template': 'product_tmpl_id'}
    _description = 'Football Blueprint'

    # The connection to the standard product template. 
    # 'ondelete=cascade' ensures that if the sample is deleted, the product template record is removed too.
    product_tmpl_id = fields.Many2one('product.template', string='Product Template', required=True, ondelete='cascade')

    # Automatic reference generation using Odoo's sequence system.
    # 'copy=False' prevents the reference from being duplicated when a record is copied.
    reference = fields.Char(string='Reference', required=True, copy=False, readonly=True, default=lambda self: _('New'), tracking=True)

    # These fields collect specific production details required for the sample.
    model_alias = fields.Char(string='Model Alias', tracking=True)
    customer_id = fields.Many2one(
        'res.partner',
        string='Customer',
        domain=[('customer_rank', '>', 0)],
        tracking=True,
    )
    sampling_date = fields.Date(string='Date', default=fields.Date.context_today, tracking=True)

    # Full lifecycle status for a sampling blueprint.
    # shipped: sample physically sent to customer for review (mid-flow, not end).
    # sample_approved: client has signed off → form locks, Waleed notified to define BOM.
    state = fields.Selection([
        ('draft',            'Draft'),
        ('in_progress',      'In Progress'),
        ('completed',        'Completed'),
        ('shipped',          'Shipped'),
        ('sample_approved',  'Sample Approved'),
        ('sample_rejected',  'Sample Rejected'),
        ('cancelled',        'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True)
    
    completion_date = fields.Date(string='Ready Till Date', tracking=True)
    shipping_date = fields.Date(string='Shipping Date', tracking=True)
    reference_piece_kept = fields.Boolean(string='Reference Piece Kept', default=False, tracking=True)
    
    # Fields for file uploads. Odoo uses 'Binary' for the file content 
    # and a 'Char' field to store the filename for correct downloading/display.
    layout_file = fields.Binary(string='Layout Image/PDF')
    layout_filename = fields.Char(string='Layout Filename')
    # Exposes the stored attachment mimetype so the secure_file_preview widget
    # can decide between an <img> and a pdf.js <canvas> render (no download path).
    layout_file_mimetype = fields.Char(compute='_compute_layout_file_mimetype')

    def _compute_layout_file_mimetype(self):
        Att = self.env['ir.attachment'].sudo()
        for rec in self:
            att = Att.search([
                ('res_model', '=', 'reema.sampling.blueprint'),
                ('res_field', '=', 'layout_file'),
                ('res_id', '=', rec.id),
            ], limit=1) if rec.id else Att.browse()
            rec.layout_file_mimetype = att.mimetype or False
    
    # 'Many2many' to 'ir.attachment' allows uploading multiple files (images/docs)
    # for the final samples, providing a flexible way to document the result.
    final_sample_images = fields.Many2many('ir.attachment', string='Final Sample Images')

    # Force the product type to 'consu' (Consumable) so it doesn't track inventory by default.
    # This addresses the requirement that samples should not show in stock.
    # We use related='product_tmpl_id.type' to ensure it points to the underlying template field.
    type = fields.Selection(related='product_tmpl_id.type', readonly=True)

    # 'Selection' fields provide predefined choices, enforcing data integrity 
    # instead of allowing users to type arbitrary, inconsistent text.
    construction_type = fields.Selection([
        ('ms',  'Machine Stitched'),
        ('hyb', 'Hybrid'),
        ('thb', 'Thermo Bonded'),
        ('hs',  'Hand Stitched'),
    ], string='Construction Type', tracking=True)

    ball_type = fields.Selection([
        ('football', 'Football'),
        ('futsal', 'Futsal'),
        ('handball', 'Handball'),
        ('volleyball', 'Volleyball'),
        ('freestyle', 'Freestyle Ball'),
        ('training', 'Training Ball')
    ], string='Type', tracking=True)

    product_type_id = fields.Many2one(
        'reema.product.type', string='Product Type',
        help='Links this sample to its sales account category (e.g. Balls, Teamwear, Gloves).',
    )

    knife_line_ids = fields.One2many('reema.sampling.knife.line', 'blueprint_id', string='Cutting Knives')
    total_panels = fields.Integer(string='Number of Panels', compute='_compute_total_panels', store=True)
    weight_range = fields.Char(string='Weight Range (g)', tracking=True)
    circumference = fields.Char(string='Circumference (cm)', tracking=True)
    bounce_requirement = fields.Char(string='Bounce Requirement', tracking=True)
    
    # 'color' field captures the primary design color of the sample.
    # This will be used to auto-populate the Invoice later.
    color = fields.Char(string='Primary Color', tracking=True)
    
    hs_code = fields.Char(string='HS Code', tracking=True)

    bom_count = fields.Integer(string='BOM Count', compute='_compute_bom_count', store=True)

    notes = fields.Text(string='Notes', tracking=True)

    # One2many relationships allow us to manage child records (Sizes and Materials)
    # directly within the parent sample form.
    size_line_ids = fields.One2many('reema.sampling.size.line', 'blueprint_id', string='Size Details')
    material_line_ids = fields.One2many('reema.sampling.material.line', 'blueprint_id', string='Material Lines')

    is_sampling_user = fields.Boolean(compute='_compute_is_sampling_user')

    @api.depends_context('uid')
    def _compute_is_sampling_user(self):
        is_editor = self._check_is_sampling_user()
        for rec in self:
            rec.is_sampling_user = is_editor

    def _check_is_sampling_user(self):
        return (
            self.env.user.has_group('reema_sampling.group_reema_sampling')
            or self.env.user.has_group('base.group_erp_manager')
            or self.env.user.has_group('base.group_system')
        )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        res['is_sampling_user'] = self._check_is_sampling_user()
        return res

    # This 'create' method override is how we automate the reference numbering.
    # Before the record is saved to the database, we fetch the next sequence value.
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Force the product type to 'consu' (Consumable) so it doesn't track inventory.
            vals['type'] = 'consu'
            vals.setdefault('product_group', 'finished_good')
            if vals.get('reference', _('New')) == _('New'):
                vals['reference'] = self.env['ir.sequence'].next_by_code('reema.sampling.blueprint') or _('New')
        return super(ReemaSamplingBlueprint, self.sudo()).create(vals_list)

    def write(self, vals):
        # Prevent changing the type away from 'consu'.
        if 'type' in vals and vals['type'] != 'consu':
            vals['type'] = 'consu'
        result = super().write(vals)
        if 'final_sample_images' in vals:
            self._link_sample_images_to_record()
        return result

    def _link_sample_images_to_record(self):
        # Free-floating ir.attachment records (no res_model/res_id) are only
        # readable by their creator. Link them to this record so any user who
        # can read the blueprint can also see the images.
        for rec in self:
            rec.final_sample_images.sudo().filtered(lambda a: not a.res_model).write({
                'res_model': self._name,
                'res_id': rec.id,
            })

    @api.model
    def _name_search(self, name='', domain=None, operator='ilike', limit=100, order=None):
        # _rec_name is 'name' (product name), so the default search already works by name.
        # This override also allows searching by reference code — useful when a user
        # remembers the code and types it in the invoice line Name dropdown.
        domain = domain or []
        if name:
            domain = ['|', ('name', operator, name), ('reference', operator, name)] + domain
        return self._search(domain, limit=limit, order=order)

    @api.depends('knife_line_ids.panel_count')
    def _compute_total_panels(self):
        for rec in self:
            rec.total_panels = sum(rec.knife_line_ids.mapped('panel_count'))

    @api.depends('product_tmpl_id.bom_ids')
    def _compute_bom_count(self):
        BOM = self.env['mrp.bom']
        for rec in self:
            rec.bom_count = BOM.search_count([('product_tmpl_id', '=', rec.product_tmpl_id.id)])

    def action_view_bom(self):
        self.ensure_one()
        action = {
            'type': 'ir.actions.act_window',
            'name': 'Bill of Materials',
            'res_model': 'mrp.bom',
            'domain': [('product_tmpl_id', '=', self.product_tmpl_id.id)],
            'context': {
                'default_product_tmpl_id': self.product_tmpl_id.id,
                'default_product_uom_id': self.product_tmpl_id.uom_id.id,
                'default_type': 'normal',
                'default_bom_line_ids': [
                    (0, 0, {
                        'product_id': line.product_id.id,
                        'product_qty': 1.0,
                        'product_uom_id': line.product_id.uom_id.id,
                    })
                    for line in self.material_line_ids
                ],
            },
        }
        if self.bom_count == 1:
            bom = self.env['mrp.bom'].search(
                [('product_tmpl_id', '=', self.product_tmpl_id.id)], limit=1
            )
            action['view_mode'] = 'form'
            action['res_id'] = bom.id
        elif self.bom_count == 0:
            action['view_mode'] = 'form'
        else:
            action['view_mode'] = 'list,form'
        return action

    def action_start(self):
        self.write({'state': 'in_progress'})

    def action_open_status_info(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Sample Status Reference',
            'res_model': 'reema.sampling.status.info.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {},
        }

    def action_open_rejection_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Sample Rejection',
            'res_model': 'reema.sampling.rejection.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_blueprint_id': self.id},
        }

    def action_sample_approved(self):
        self.write({'state': 'sample_approved'})
        pm_group = self.env.ref('reema_mrp.group_reema_production_manager')
        managers = pm_group.users
        for blueprint in self:
            bom = False
            if blueprint.bom_count == 0:
                bom = self.env['mrp.bom'].sudo().create({
                    'product_tmpl_id': blueprint.product_tmpl_id.id,
                    'product_uom_id': blueprint.product_tmpl_id.uom_id.id,
                    'type': 'normal',
                    'bom_line_ids': [
                        (0, 0, {
                            'product_id': line.product_id.id,
                            'product_qty': 1.0,
                            'product_uom_id': line.product_id.uom_id.id,
                        })
                        for line in blueprint.material_line_ids
                    ],
                })

            if bom:
                summary = 'Review and complete BOM'
                note = (
                    f'Sample <b>{blueprint.reference} – {blueprint.name}</b> has been approved. '
                    f'A draft Bill of Materials (<b>{bom.reema_reference}</b>) has been automatically created. '
                    f'Please review components, set correct quantities, define hall operations, '
                    f'then click <b>Mark Ready</b> before production orders can be raised.'
                )
            else:
                summary = 'Verify BOM is Ready'
                note = (
                    f'Sample <b>{blueprint.reference} – {blueprint.name}</b> has been approved again. '
                    f'A BOM already exists for this sample — ensure it is marked <b>Ready</b> '
                    f'before production can proceed.'
                )

            for manager in managers:
                blueprint.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=summary,
                    note=note,
                    user_id=manager.id,
                )

    def action_completed(self):
        self.write({'state': 'completed'})

    def action_shipped(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Ship Sample',
            'res_model': 'reema.sampling.ship.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_blueprint_id': self.id},
        }

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_step_back(self):
        """Admin-only: revert the sample one step back in the workflow."""
        PREVIOUS = {
            'in_progress':     'draft',
            'completed':       'in_progress',
            'shipped':         'completed',
            'sample_approved': 'completed',
            'sample_rejected': 'completed',
        }
        for rec in self:
            prev = PREVIOUS.get(rec.state)
            if prev:
                rec.write({'state': prev})

    def unlink(self):
        protected = self.filtered(
            lambda r: r.state not in ('draft', 'sample_rejected', 'cancelled')
        )
        if protected:
            names = ', '.join(protected.mapped('reference'))
            raise UserError(
                f"Cannot delete sample(s) {names}. "
                f"Only samples in Draft, Rejected, or Voided state can be deleted."
            )
        return super().unlink()

    def action_reset_draft(self):
        self.write({'state': 'draft'})

    def action_print_sampling(self):
        # Open the sample sheet as an HTML preview in a new browser tab; the user
        # prints with the in-page Print button (or Ctrl+P) and closes the tab to return.
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': '/report/html/reema_sampling.report_reema_sampling_template/%s' % self.id,
            'target': 'new',
        }


class ReemaSamplingStatusInfoWizard(models.TransientModel):
    _name = 'reema.sampling.status.info.wizard'
    _description = 'Sampling Status Reference'


class ReemaSamplingRejectionWizard(models.TransientModel):
    _name = 'reema.sampling.rejection.wizard'
    _description = 'Sample Rejection Wizard'

    blueprint_id = fields.Many2one(
        'reema.sampling.blueprint', string='Sample', required=True, readonly=True
    )
    rejection_reason = fields.Text(string='Rejection Reason', required=True)
    outcome = fields.Selection([
        ('cancel', 'No Further Development — lock this sample permanently'),
        ('remake', 'Revise & Remake — allow changes and restart development'),
    ], string='What should happen next?', required=True)

    def action_confirm(self):
        self.ensure_one()
        bp = self.blueprint_id
        if self.outcome == 'cancel':
            bp.write({'state': 'cancelled'})
            bp.message_post(
                body=f'<b>Sample Rejected — No Further Development</b><br/>'
                     f'Reason: {self.rejection_reason}'
            )
        else:
            bp.write({'state': 'in_progress'})
            bp.message_post(
                body=f'<b>Sample Rejected — Revise &amp; Remake</b><br/>'
                     f'Reason: {self.rejection_reason}'
            )


class ReemaSamplingShipWizard(models.TransientModel):
    _name = 'reema.sampling.ship.wizard'
    _description = 'Ship Sample Confirmation'

    blueprint_id = fields.Many2one(
        'reema.sampling.blueprint', string='Sample', required=True, readonly=True
    )
    # Selection (not Boolean) with no default — forces the user to explicitly pick one.
    # Odoo will block "Confirm Shipment" until a value is chosen.
    reference_piece_kept = fields.Selection([
        ('yes', 'Yes — a reference piece is being kept'),
        ('no',  'No — no piece is being kept'),
    ], string='Is a reference piece kept?', required=True)

    def action_confirm(self):
        self.ensure_one()
        bp = self.blueprint_id
        vals = {'reference_piece_kept': self.reference_piece_kept == 'yes'}
        # Don't downgrade an already-approved sample back to 'shipped' — the
        # customer already approved it (e.g. from photos); this ship just
        # sends the physical piece afterward and shouldn't undo that outcome.
        if bp.state != 'sample_approved':
            vals['state'] = 'shipped'
        bp.write(vals)
        if bp.state == 'sample_approved':
            bp.message_post(body='<b>Sample shipped to customer</b> (sample was already approved).')


class ReemaSamplingKnifeLine(models.Model):
    _name = 'reema.sampling.knife.line'
    _description = 'Cutting Knife Shape'
    _order = 'sequence, id'

    blueprint_id = fields.Many2one('reema.sampling.blueprint', ondelete='cascade', required=True)
    sequence     = fields.Integer(default=10)
    shape_name   = fields.Char(string='Shape', required=True)
    panel_count  = fields.Integer(string='Panels', required=True)


# This model allows defining multiple sizes for a single sample layout.
# It makes the system flexible for multi-size production orders.
class ReemaSamplingSizeLine(models.Model):
    _name = 'reema.sampling.size.line'
    _description = 'Sampling Size Line'
    _order = 'sequence'

    blueprint_id = fields.Many2one('reema.sampling.blueprint', string='Blueprint', ondelete='cascade')
    
    # 'sequence' field is used by Odoo to allow drag-and-drop reordering in lists.
    sequence = fields.Integer(string='Sequence', default=10)
    
    ball_size = fields.Selection([
        ('5', 'Size 5'),
        ('4', 'Size 4'),
        ('3', 'Size 3'),
        ('2', 'Size 2'),
        ('1', 'Size 1')
    ], string='Size', required=True)
    
    cutting_knife_no = fields.Char(string='Cutting Knife Number')
    qty_to_produce = fields.Integer(string='Quantity', default=1)

# This model handles individual material rows that make up the sample.
class ReemaSamplingMaterialLine(models.Model):
    _name = 'reema.sampling.material.line'
    _description = 'Sampling Material Line'
    _order = 'sequence'

    # 'blueprint_id' links this line back to the main blueprint record.
    blueprint_id = fields.Many2one('reema.sampling.blueprint', string='Blueprint', ondelete='cascade')
    
    # 'sequence' field for manual reordering.
    sequence = fields.Integer(string='Sequence', default=10)
    
    # The Material (Product) is now the primary field.
    product_id = fields.Many2one('product.product', string='Material', required=True)
    
    # Additional fields to provide more context for each specific material line.
    description = fields.Char(string='Description')
    notes = fields.Text(string='Individual Notes')
