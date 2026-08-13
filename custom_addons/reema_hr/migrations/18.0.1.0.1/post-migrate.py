from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    group = env.ref('reema_hr.group_reema_hr_manager', raise_if_not_found=False)
    if not group:
        return

    users = env['res.users'].search([('login', 'in', ['admin', 'irfan'])])
    new_users = users - group.users
    if new_users:
        group.write({'users': [(4, u.id) for u in new_users]})
