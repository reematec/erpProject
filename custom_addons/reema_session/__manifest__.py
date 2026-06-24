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
    'depends': ['base', 'web'],
    'data': [],
    'installable': True,
    'application': False,
    'auto_install': True,
    'license': 'LGPL-3',
}
