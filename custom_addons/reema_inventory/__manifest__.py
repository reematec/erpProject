{
    'name': 'Reema Inventory',
    'version': '18.0.1.0.0',
    'category': 'Inventory',
    'summary': 'Bladder Winding and Bladder Filling Issue/Receive tracking',
    'description': """
        Tracks bladders sent out to external vendors and the processed bladders
        received back, per Manufacturing Order:
        - Bladder Winding: raw SR/NR/Butyl bladder, target winding weight, for
          MS/HYB/THB balls.
        - Bladder Filling: raw bladder, target polyester fiber filling weight,
          for futsal balls.
        In both cases payment is against quantity actually processed, not
        quantity sent — issues stay open until fully reconciled (processed +
        damaged + lost = sent).
    """,
    'depends': ['stock', 'mrp', 'reema_mrp', 'reema_purchase'],
    'data': [
        'security/reema_inventory_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/stock_location_data.xml',
        'views/reema_bladder_winding_views.xml',
        'views/reema_bladder_winding_issue_report.xml',
        'views/reema_bladder_winding_receipt_report.xml',
        'views/reema_bladder_winding_balance_report.xml',
        'views/reema_bladder_filling_views.xml',
        'views/reema_bladder_filling_issue_report.xml',
        'views/reema_bladder_filling_receipt_report.xml',
        'views/reema_bladder_filling_balance_report.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
