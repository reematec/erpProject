from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    company = env.company
    Journal = env['account.journal']
    Account = env['account.account']

    def find_account(code):
        return Account.search([('code', '=', code)], limit=1)

    journals_to_create = [
        {'name': 'Journal Vouchers',  'type': 'general',  'code': 'JV'},
        {'name': 'Vendor Bills',      'type': 'purchase', 'code': 'BILL'},
        {'name': 'Customer Invoices', 'type': 'sale',     'code': 'INV'},
        {'name': 'Main Bank',         'type': 'bank',     'code': 'BANK',
         'default_account_id': find_account('1-1-1-01').id},
        {'name': 'Petty Cash',        'type': 'cash',     'code': 'CASH',
         'default_account_id': find_account('1-1-1-02').id},
    ]

    for vals in journals_to_create:
        exists = Journal.search([('code', '=', vals['code']), ('company_id', '=', company.id)], limit=1)
        if not exists:
            Journal.create(vals)
