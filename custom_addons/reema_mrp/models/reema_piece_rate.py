from odoo import models, fields


class ReemaPieceRate(models.Model):
    _name = 'reema.piece.rate'
    _description = 'Piece Rate'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'work_type'
    _order = 'workcenter_id, work_type'

    workcenter_id = fields.Many2one('mrp.workcenter', string='Work Center', required=True, tracking=True)
    work_type     = fields.Char(string='Type of Work', required=True, tracking=True)
    description   = fields.Char(string='Description / Notes', tracking=True)
    rate          = fields.Float(string='Rate (PKR)', required=True, digits=(10, 2), tracking=True)
    uom_id        = fields.Many2one('uom.uom', string='UOM', required=True, tracking=True)
    active        = fields.Boolean(default=True, tracking=True)

    def action_print_piece_rate_report(self):
        # Open the report preview in a new browser tab. The user previews it,
        # prints with the browser (the in-page Print button / Ctrl+P), and simply
        # closes the tab to return to the Piece Rates overview.
        return {
            'type': 'ir.actions.act_url',
            'url': '/report/html/reema_mrp.report_piece_rate_list',
            'target': 'new',
        }
