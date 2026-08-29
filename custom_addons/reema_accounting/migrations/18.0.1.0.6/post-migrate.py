from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Split the shared "Cash & Bank" (1-1-1) group/account into separate
    Bank and Cash parents, and give each of the 2 real banks (Bank Al
    Habib, Meezan Bank) its own GL account/journal instead of both posting
    through one shared "Main Bank Account". The 2 pre-existing move lines
    on 1-1-1-01 both belong to Al Habib (confirmed with the user), so that
    account just gets renamed/re-grouped in place — no line reassignment
    needed. Petty Cash is recoded off 1-1-1-02 first to free that code for
    the new Meezan Bank account.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    Group = env['account.group']
    Account = env['account.account']
    Journal = env['account.journal']
    BankAccount = env['reema.bank.account']

    bank_group = Group.search([('code_prefix_start', '=', '1-1-1')], limit=1)
    if bank_group and bank_group.name != 'Bank':
        bank_group.name = 'Bank'

    cash_group = Group.search([('code_prefix_start', '=', '1-1-8')], limit=1)
    if not cash_group:
        current_assets = Group.search([('code_prefix_start', '=', '1-1')], limit=1)
        cash_group = Group.create({
            'name': 'Cash',
            'code_prefix_start': '1-1-8',
            'code_prefix_end': '1-1-8',
            'parent_id': current_assets.id if current_assets else False,
        })

    petty_cash = Account.search([('code', '=', '1-1-1-02'), ('name', '=', 'Petty Cash')], limit=1)
    if petty_cash:
        petty_cash.write({'code': '1-1-8-01', 'group_id': cash_group.id})

    main_bank = Account.search([('code', '=', '1-1-1-01')], limit=1)
    if main_bank:
        vals = {'name': 'Bank Al Habib'}
        if bank_group:
            vals['group_id'] = bank_group.id
        main_bank.write(vals)

    meezan_account = Account.search([('code', '=', '1-1-1-02'), ('name', '=', 'Meezan Bank')], limit=1)
    if not meezan_account:
        meezan_account = Account.create({
            'name': 'Meezan Bank',
            'code': '1-1-1-02',
            'account_type': 'asset_cash',
            'reconcile': False,
            'group_id': bank_group.id if bank_group else False,
        })

    bank_journal = Journal.search([('code', '=', 'BNK'), ('type', '=', 'bank')], limit=1)
    if bank_journal:
        bank_journal.name = 'Bank Al Habib'

    meezan_journal = Journal.search([('name', '=', 'Meezan Bank'), ('type', '=', 'bank')], limit=1)
    if not meezan_journal:
        meezan_journal = Journal.create({
            'name': 'Meezan Bank',
            'type': 'bank',
            'code': 'MZN',
            'default_account_id': meezan_account.id,
        })

    habib_label = BankAccount.search([('name', 'like', 'Al Habib')], limit=1)
    if habib_label and bank_journal and not habib_label.journal_id:
        habib_label.journal_id = bank_journal.id
    meezan_label = BankAccount.search([('name', 'like', 'Meezan')], limit=1)
    if meezan_label and meezan_journal and not meezan_label.journal_id:
        meezan_label.journal_id = meezan_journal.id
