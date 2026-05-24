from odoo import models, fields, api


class ResUsersReema(models.Model):
    _inherit = 'res.users'

    reema_role_note = fields.Text(
        string='Reema Role', compute='_compute_reema_role_note'
    )

    @api.depends('groups_id')
    def _compute_reema_role_note(self):
        try:
            g_mgr = self.env.ref('reema_mrp.group_reema_production_manager')
            g_sup = self.env.ref('reema_mrp.group_reema_supervisor')
            g_hal = self.env.ref('reema_mrp.group_reema_hall_incharge')
            g_sto = self.env.ref('reema_mrp.group_reema_store')
        except Exception:
            for user in self:
                user.reema_role_note = False
            return

        descriptions = [
            (g_mgr, (
                "Production Manager — Full Access\n"
                "✓  Manage Work Centers, Piece Rates, and Production Orders\n"
                "✓  Start and complete work orders in all halls\n"
                "✓  Log batch progress, approve and void contractor bills\n"
                "✗  Cannot post (record) bills in accounting"
            )),
            (g_sup, (
                "Production Supervisor — Review & Approve\n"
                "✓  View all batch logs and contractor bills\n"
                "✓  Approve contractor bills so accounting can post them\n"
                "✓  Void a previously approved bill if a mistake is found\n"
                "✗  Cannot manage Work Centers or Piece Rates\n"
                "✗  Cannot post bills in accounting"
            )),
            (g_hal, (
                "Hall Incharge — Operations Only\n"
                "✓  Log batch progress on assigned work orders\n"
                "✓  View Manufacturing work orders\n"
                "✗  Cannot view or approve contractor bills\n"
                "✗  Cannot manage Work Centers or Piece Rates"
            )),
            (g_sto, (
                "Store Keeper — Inventory Operations\n"
                "✓  Issue materials from store\n"
                "✓  Record material returns\n"
                "✓  Manage consumable transactions\n"
                "✗  No access to Manufacturing orders or billing"
            )),
        ]

        for user in self:
            note = False
            for group, text in descriptions:
                if group in user.groups_id:
                    note = text
                    break
            user.reema_role_note = note
