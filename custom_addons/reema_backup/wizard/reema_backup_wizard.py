from odoo import models


class ReemaBackupWizard(models.TransientModel):
    _name = 'reema.backup.wizard'
    _description = 'Confirm Database Backup'

    def action_confirm(self):
        self.env['reema.db.backup'].action_take_backup()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Backup Log',
            'res_model': 'reema.db.backup',
            'view_mode': 'list,form',
            'target': 'main',
        }
