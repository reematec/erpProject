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
    'depends': ['product', 'mrp'],
    'data': [
        'security/ir.model.access.csv',
        'data/reema_sampling_data.xml',
        'views/reema_sampling_blueprint_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
