{
    'name': 'Reema Group MRP',
    'version': '2.0',
    'category': 'Manufacturing',
    'summary': 'Integrated MRP flow for Football Production (Reema Group Logic)',
    'description': """
        Integrates the 17-Hall production flow into Odoo's standard Manufacturing Orders.
        Includes piece-rate labor tracking, contractor assignment, and SFG inventory movement.
    """,
    'author': 'Gemini CLI',
    'depends': ['mrp', 'stock', 'account', 'analytic'],
    'data': [
        'security/ir.model.access.csv',
        'views/mrp_views.xml',
        'views/reema_piece_rate_views.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
