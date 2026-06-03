{
    'name': 'Reema Invoice',
    'version': '1.0',
    'category': 'Sales',
    'summary': 'Pro Forma Invoice Management for Reema Group',
    'author': 'Reema Group',
    'depends': ['reema_sampling', 'account'],
    'data': [
        'security/reema_invoice_security.xml',
        'security/ir.model.access.csv',
        'data/reema_invoice_data.xml',
        'views/reema_invoice_views.xml',
        'reports/reema_invoice_report.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'reema_invoice/static/src/components/invoice_form_patch.js',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
