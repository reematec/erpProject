{
    'name': 'Reema Session',
    'version': '1.0',
    'category': 'Administration',
    'summary': 'Log users out automatically when the browser is closed',
    'description': """
Makes the Odoo `session_id` cookie a browser-session cookie (no Max-Age /
Expires) so that closing the browser discards the cookie and logs the user out.
    """,
    'author': 'Reema Tec',
    'depends': ['base', 'web', 'mail'],
    'data': [],
    'assets': {
        'web.assets_backend': [
            'reema_session/static/src/js/list_column_widths.js',
            'reema_session/static/src/js/no_autosave_new_forms.js',
            'reema_session/static/src/xml/discuss_inbox_order.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': True,
    'license': 'LGPL-3',
}
