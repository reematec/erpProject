from odoo import api, SUPERUSER_ID

PESSI_PAYABLE_CODE = '2-1-3-04'


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    Account = env['account.account']
    if Account.search([('code', '=', PESSI_PAYABLE_CODE)], limit=1):
        return

    Account.create({
        'name': 'PESSI Payable',
        'code': PESSI_PAYABLE_CODE,
        'account_type': 'liability_current',
    })
