import os
import subprocess
import logging
from datetime import datetime

from odoo import models, fields, api, tools
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

BACKUP_DIR = '/home/amir/erpProject/backups'


def _human_size(size_bytes):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


class ReemaDbBackup(models.Model):
    _name = 'reema.db.backup'
    _description = 'Database Backup Log'
    _order = 'backup_date desc'
    _rec_name = 'filename'

    filename = fields.Char(string='Filename', readonly=True)
    backup_path = fields.Char(string='File Path', readonly=True)
    backup_date = fields.Datetime(string='Date & Time', readonly=True, default=fields.Datetime.now)
    state = fields.Selection([
        ('success', 'Success'),
        ('failed', 'Failed'),
    ], string='Status', readonly=True, default='success')
    notes = fields.Text(string='Notes / Error', readonly=True)
    taken_by = fields.Many2one('res.users', string='Taken By', readonly=True,
                               default=lambda self: self.env.user, ondelete='set null')
    file_size = fields.Integer(string='Size (bytes)', readonly=True)
    size_human = fields.Char(string='File Size', compute='_compute_size_human', store=True)

    @api.depends('file_size')
    def _compute_size_human(self):
        for rec in self:
            rec.size_human = _human_size(rec.file_size) if rec.file_size else '—'

    def action_take_backup(self):
        """Called by the 'Take Backup Now' button on the list view.

        Bound to a list header button, so Odoo calls it on a recordset
        (empty when no rows are selected). The body does not rely on the
        records in ``self`` — it always creates a fresh log entry.
        """
        db_name = tools.config['db_name']
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'app_{db_name}_{timestamp}.dump'
        filepath = os.path.join(BACKUP_DIR, filename)

        os.makedirs(BACKUP_DIR, exist_ok=True)

        log = self.create({
            'filename': filename,
            'backup_path': filepath,
            'backup_date': fields.Datetime.now(),
            'state': 'failed',
            'taken_by': self.env.uid,
        })

        try:
            cmd = [
                'pg_dump',
                '--no-owner',
                '--format=custom',
                f'--file={filepath}',
                db_name,
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr or 'pg_dump exited with non-zero status')

            size = os.path.getsize(filepath)
            log.write({
                'state': 'success',
                'file_size': size,
                'notes': False,
            })
            _logger.info('DB backup created: %s (%s)', filepath, _human_size(size))

        except Exception as e:
            log.write({'notes': str(e)})
            _logger.error('DB backup failed: %s', e)

        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_delete_file(self):
        """Remove the backup file from disk and delete this log entry."""
        self.ensure_one()
        if self.backup_path and os.path.exists(self.backup_path):
            try:
                os.remove(self.backup_path)
            except OSError as e:
                raise UserError(f"Could not delete file: {e}") from e
        self.unlink()
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }
