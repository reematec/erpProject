{
    'name': 'Reema Group MRP',
    'version': '2.0',
    'category': 'Manufacturing',
    'summary': 'Integrated MRP flow for Football Production (Reema Group Logic)',
    'description': """
        Integrates the 17-Hall production flow into Odoo's standard Manufacturing Orders.
        Includes contractor assignment, batch progress tracking, and SFG inventory movement.
    """,
    'author': 'Gemini CLI',
    'depends': ['mrp', 'stock', 'account', 'analytic', 'reema_invoice'],
    'data': [
        'security/reema_mrp_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'views/mrp_views.xml',
        'views/reema_piece_rate_views.xml',
        'views/reema_production_order_views.xml',
        'views/reema_wo_batch_views.xml',
        'views/reema_material_issuance_views.xml',
        'views/reema_material_issuance_report.xml',
        'views/reema_consumable_issuance_views.xml',
        'views/reema_consumable_return_views.xml',
        'views/res_users_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'reema_mrp/static/src/components/wo_list_dropdown_patch.xml',
            'reema_mrp/static/src/components/many2one_no_create_patch.js',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
