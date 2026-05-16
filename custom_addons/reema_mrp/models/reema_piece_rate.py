from odoo import models, fields


class ReemaPieceRate(models.Model):
    _name = 'reema.piece.rate'
    _description = 'Piece Rate'
    _rec_name = 'work_type'
    _order = 'workcenter_id, work_type'

    workcenter_id = fields.Many2one('mrp.workcenter', string='Work Center', required=True)
    work_type     = fields.Char(string='Type of Work', required=True)
    description   = fields.Char(string='Description / Notes')
    rate          = fields.Float(string='Rate (PKR)', required=True, digits=(10, 2))
    uom_id        = fields.Many2one('uom.uom', string='UOM', required=True)
    active        = fields.Boolean(default=True)
