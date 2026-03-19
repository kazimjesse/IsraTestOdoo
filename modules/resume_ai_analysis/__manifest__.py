{
    'name': 'Resume AI Analysis',
    'version': '18.0.1.0.0',
    'summary': 'Análisis de CVs con Inteligencia Artificial (Gemini)',
    'description': 'Sube CVs en PDF, clasifícalos por área y consulta con Gemini de Google para encontrar los mejores candidatos.',
    'author': 'Demo',
    'category': 'Human Resources',
    'depends': ['base'],
    'data': [
        'security/ir.model.access.csv',
        'views/resume_cv_views.xml',
        'views/resume_consulta_views.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
