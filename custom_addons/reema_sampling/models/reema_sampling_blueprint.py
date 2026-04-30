from odoo import models, fields, api, _

# The 'ReemaSamplingBlueprint' model acts as the core definition for a new ball design.
# We use '_inherits' to link it with 'product.template', which allows us to reuse 
# standard Odoo product functionality (like name, description, etc.) while extending 
# it with our specific sampling requirements.
class ReemaSamplingBlueprint(models.Model):
    _name = 'reema.sampling.blueprint'
    _inherits = {'product.template': 'product_tmpl_id'}
    _description = 'Football Blueprint'

    # The connection to the standard product template. 
    # 'ondelete=cascade' ensures that if the sample is deleted, the product template record is removed too.
    product_tmpl_id = fields.Many2one('product.template', string='Product Template', required=True, ondelete='cascade')
    
    # Automatic reference generation using Odoo's sequence system.
    # 'copy=False' prevents the reference from being duplicated when a record is copied.
    reference = fields.Char(string='Reference', required=True, copy=False, readonly=True, default=lambda self: _('New'))

    # These fields collect specific production details required for the sample.
    model_alias = fields.Char(string='Model Alias')
    customer_id = fields.Many2one('res.partner', string='Customer')
    sampling_date = fields.Date(string='Date', default=fields.Date.context_today)
    
    # Fields for status tracking of the sample production lifecycle.
    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('shipped', 'Shipped'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='draft', required=True)
    
    completion_date = fields.Date(string='Ready Till Date')
    shipping_date = fields.Date(string='Shipping Date')
    reference_piece_kept = fields.Boolean(string='Reference Piece Kept', default=False)
    
    # Fields for file uploads. Odoo uses 'Binary' for the file content 
    # and a 'Char' field to store the filename for correct downloading/display.
    layout_file = fields.Binary(string='Layout Image/PDF')
    layout_filename = fields.Char(string='Layout Filename')
    
    # 'Many2many' to 'ir.attachment' allows uploading multiple files (images/docs) 
    # for the final samples, providing a flexible way to document the result.
    final_sample_images = fields.Many2many('ir.attachment', string='Final Sample Images')

    # 'Selection' fields provide predefined choices, enforcing data integrity 
    # instead of allowing users to type arbitrary, inconsistent text.
    construction_type = fields.Selection([
        ('machine_stitched', 'Machine Stitched'),
        ('hybrid', 'Hybrid'),
        ('thermo_bonded', 'Thermo Bonded'),
        ('hand_stitched', 'Hand Stitched')
    ], string='Construction Type')
    
    ball_type = fields.Selection([
        ('football', 'Football'),
        ('futsal', 'Futsal'),
        ('handball', 'Handball'),
        ('volleyball', 'Volleyball'),
        ('freestyle', 'Freestyle Ball'),
        ('training', 'Training Ball')
    ], string='Type')
    
    number_of_panels = fields.Integer(string='Number of Panels')
    weight_range = fields.Char(string='Weight Range (g)')
    circumference = fields.Char(string='Circumference (cm)')
    bounce_requirement = fields.Char(string='Bounce Requirement')
    
    notes = fields.Text(string='Notes')
    
    # One2many relationships allow us to manage child records (Sizes and Materials)
    # directly within the parent sample form.
    size_line_ids = fields.One2many('reema.sampling.size.line', 'blueprint_id', string='Size Details')
    material_line_ids = fields.One2many('reema.sampling.material.line', 'blueprint_id', string='Material Lines')

    # This 'create' method override is how we automate the reference numbering.
    # Before the record is saved to the database, we fetch the next sequence value.
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('reference', _('New')) == _('New'):
                vals['reference'] = self.env['ir.sequence'].next_by_code('reema.sampling.blueprint') or _('New')
        return super().create(vals_list)

    # Placeholder for the print action. This will be connected to a QWeb report later.
    def action_print_sampling(self):
        """ This method will be used to trigger the PDF report generation. """
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Print Action'),
                'message': _('Printing functionality is being prepared.'),
                'sticky': False,
            }
        }

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
