from . import models
from . import wizards
from . import controllers


def post_init_hook(env):
    # Cancel the pending generic_coa auto-install so it doesn't wipe our COA
    if hasattr(env.registry, '_auto_install_template'):
        del env.registry._auto_install_template
    # Mark the company so future upgrades don't re-trigger auto-install
    company = env.company
    if not company.chart_template:
        company.write({'chart_template': 'generic_coa'})

    # Create standard journals if they don't exist
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

    # Ensure exactly one "Current Year Earnings" account exists (required by Trial Balance)
    unaffected = Account.search([
        ('account_type', '=', 'equity_unaffected'),
        ('company_ids', 'in', [company.id]),
    ], limit=1)
    if not unaffected:
        Account.create({
            'name': 'Current Year Earnings',
            'code': '3-3-1-01',
            'account_type': 'equity_unaffected',
            'reconcile': False,
        })
