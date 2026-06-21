{
    'name': 'Reema DB Backup',
    'version': '1.0',
    'category': 'Administration',
    'summary': 'Take and track database backups from within the app',
    'author': 'Reema Tec',
    'depends': ['base'],
    'data': [
        'security/ir.model.access.csv',
        'views/reema_db_backup_views.xml',
        'views/reema_backup_menus.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
