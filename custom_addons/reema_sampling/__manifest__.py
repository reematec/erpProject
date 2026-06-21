{
    'name': 'Reema Sampling',
    'version': '1.0',
    'category': 'Manufacturing',
    'summary': 'Football Sampling and Blueprint Management',
    'description': """
        Module for sampling department to develop new football models.
        Includes blueprint creation with technical specifications and material requirements.
    """,
    'author': 'Gemini CLI',
    'depends': ['product', 'mrp', 'mail'],
    'data': [
        'security/reema_sampling_security.xml',
        'security/ir.model.access.csv',
        'data/reema_sampling_data.xml',
        'views/reema_sampling_blueprint_views.xml',
        'reports/reema_sampling_report.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'reema_sampling/static/src/components/secure_preview/secure_preview.js',
            'reema_sampling/static/src/components/secure_preview/secure_preview.xml',
            'reema_sampling/static/src/components/pending_bom_list.js',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
