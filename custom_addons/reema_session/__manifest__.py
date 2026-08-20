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
    'data': [
        'views/ir_model_chatter_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'reema_session/static/src/js/list_column_widths.js',
            'reema_session/static/src/js/leave_with_unsaved_changes_dialog.js',
            'reema_session/static/src/js/no_autosave_forms.js',
            'reema_session/static/src/js/bottom_chatter_models.js',
            'reema_session/static/src/scss/bottom_chatter_models.scss',
            'reema_session/static/src/js/chatter_layout_list.js',
            'reema_session/static/src/scss/chatter_layout_list.scss',
            'reema_session/static/src/xml/leave_with_unsaved_changes_dialog.xml',
            'reema_session/static/src/xml/discuss_inbox_order.xml',
            'reema_session/static/src/xml/form_status_indicator.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': True,
    'license': 'LGPL-3',
}
