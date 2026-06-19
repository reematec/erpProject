from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    # One-time removal: strip account.group_account_invoice from the supervisor's
    # implied groups. The group was there so supervisors could open account.move
    # records for contractor bill approval, but the proxy model (reema.contractor.
    # bill.approval) now handles that without needing the invoicing right at all.
    supervisor = env.ref('reema_mrp.group_reema_supervisor', raise_if_not_found=False)
    invoice_group = env.ref('account.group_account_invoice', raise_if_not_found=False)
    if supervisor and invoice_group and invoice_group in supervisor.implied_ids:
        supervisor.write({'implied_ids': [(3, invoice_group.id)]})

    # Create proxy records for any existing contractor bills that don't have one yet
    existing_move_ids = env['reema.contractor.bill.approval'].search([]).mapped('move_id').ids
    bills = env['account.move'].search([
        ('move_type', '=', 'in_invoice'),
        ('batch_entry_ids', '!=', False),
        ('id', 'not in', existing_move_ids),
    ])
    for bill in bills:
        env['reema.contractor.bill.approval'].create({'move_id': bill.id})
