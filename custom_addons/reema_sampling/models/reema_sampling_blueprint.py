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
    # sample_approved: client has physically signed off the sample →
    #   Sameer can invoice, Waleed gets notified to define the BOM.
    # production_ready: Waleed has completed the BOM (quantities, routing,
    #   wastage) → the blueprint is safe to include in invoices for bulk orders.
    state = fields.Selection([
        ('draft',            'Draft'),
        ('in_progress',      'In Progress'),
        ('completed',        'Completed'),
        ('sample_approved',  'Sample Approved'),
        ('sample_rejected',  'Sample Rejected'),
        ('production_ready', 'Production Ready'),
        ('shipped',          'Shipped'),
        ('cancelled',        'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True)
    
    completion_date = fields.Date(string='Ready Till Date', tracking=True)
    shipping_date = fields.Date(string='Shipping Date', tracking=True)
    reference_piece_kept = fields.Boolean(string='Reference Piece Kept', default=False, tracking=True)
    
    # Fields for file uploads. Odoo uses 'Binary' for the file content 
    # and a 'Char' field to store the filename for correct downloading/display.
    layout_file = fields.Binary(string='Layout Image/PDF')
    layout_filename = fields.Char(string='Layout Filename')
    
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

    # This 'create' method override is how we automate the reference numbering.
    # Before the record is saved to the database, we fetch the next sequence value.
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Force the product type to 'consu' (Consumable) so it doesn't track inventory.
            vals['type'] = 'consu'
            if vals.get('reference', _('New')) == _('New'):
                vals['reference'] = self.env['ir.sequence'].next_by_code('reema.sampling.blueprint') or _('New')
        return super().create(vals_list)

    def write(self, vals):
        # Prevent changing the type away from 'consu'.
        if 'type' in vals and vals['type'] != 'consu':
            vals['type'] = 'consu'
        return super().write(vals)

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
                'default_type': 'normal',
                'default_bom_line_ids': [
                    (0, 0, {'product_id': line.product_id.id, 'product_qty': 1.0})
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

    def action_sample_rejected(self):
        self.write({'state': 'sample_rejected'})

    def action_sample_approved(self):
        self.write({'state': 'sample_approved'})
        # Notify Waleed to define the BOM for this blueprint
        self.activity_schedule(
            'mail.mail_activity_data_todo',
            summary='Define BOM for approved sample',
            note=f'Sample <b>{self.reference} – {self.name}</b> has been approved. '
                 f'Please define the Bill of Materials so this design can be used in bulk production orders.',
        )

    def action_production_ready(self):
        self.write({'state': 'production_ready'})

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
            'in_progress':      'draft',
            'completed':        'in_progress',
            'sample_approved':  'completed',
            'sample_rejected':  'completed',
            'production_ready': 'sample_approved',
            'shipped':          'production_ready',
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
        # Looks up the registered report action by its full XML name and triggers PDF generation.
        return self.env.ref('reema_sampling.action_report_reema_sampling').report_action(self)


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
        self.blueprint_id.write({
            'state': 'shipped',
            'reference_piece_kept': self.reference_piece_kept == 'yes',
        })


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
