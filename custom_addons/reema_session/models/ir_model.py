from odoo import fields, models


class IrModel(models.Model):
    _inherit = 'ir.model'

    reema_bottom_chatter = fields.Boolean(
        string="Chatter at Bottom",
        help="Show the chatter below the form instead of aside on wide "
             "screens, so the form itself gets the full width.",
    )
