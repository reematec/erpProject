from odoo import api, SUPERUSER_ID

CONTRACTOR_PAYABLE_CODE = '2-1-2-01'


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    # 1. Ensure the shared "Contractors Payable" account carries its code 2-1-2-01.
    #    The account exists but was created without a code, so the auto-assign
    #    lookup (by code) could not find it.
    payable = env['account.account'].search(
        [('code', '=', CONTRACTOR_PAYABLE_CODE)], limit=1
    )
    if not payable:
        payable = env['account.account'].search([
            ('account_type', '=', 'liability_payable'),
            ('name', '=', 'Contractors Payable'),
        ], limit=1)
        if payable:
            payable.code = CONTRACTOR_PAYABLE_CODE

    if not payable:
        return

    # 2. Backfill: link every contractor without a payable to the shared account.
    contractors = env['res.partner'].search([
        ('is_contractor', '=', True),
        ('property_account_payable_id', '=', False),
    ])
    for contractor in contractors:
        contractor.property_account_payable_id = payable
