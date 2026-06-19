from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    company = env.company

    stock_journal = env['account.journal'].search(
        [('code', '=', 'STK'), ('company_id', '=', company.id)], limit=1
    )
    if not stock_journal:
        stock_journal = env['account.journal'].create({
            'name': 'Stock Valuation',
            'type': 'general',
            'code': 'STK',
            'company_id': company.id,
        })

    cats = env['product.category'].search([('property_valuation', '=', 'real_time')])
    for cat in cats:
        if not cat.property_stock_journal:
            cat.write({'property_stock_journal': stock_journal.id})

    acct_user_group = env.ref('account.group_account_user', raise_if_not_found=False)
    if acct_user_group:
        # uid=2 is the Administrator login user (SUPERUSER_ID=1 is OdooBot, not the login admin)
        login_admin = env['res.users'].search([('login', '=', 'admin')], limit=1)
        if login_admin and login_admin not in acct_user_group.users:
            acct_user_group.write({'users': [(4, login_admin.id)]})
