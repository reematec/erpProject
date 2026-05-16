{
    'name': 'Reema Accounting',
    'version': '18.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Chart of Accounts, Taxes, and Journals for Reema Tec',
    'depends': ['account', 'account_financial_report', 'reema_mrp', 'reema_invoice'],
    'data': [
        'views/account_menu_views.xml',
        'data/account_account_data.xml',
        'data/account_tax_data.xml',
        'data/account_journal_data.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
