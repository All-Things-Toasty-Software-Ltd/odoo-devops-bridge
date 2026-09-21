# Part of Odoo App. See LICENSE file for full copyright and licensing details.

{
    'name': "Odoo App",
    'category': 'Toasty Software',
    'sequence': 200,
    'website': 'https://www.toastysoftware.co.uk',
    'summary': "Short (1 phrase/line) summary of the module's purpose",
    'version': '0.1.0',
    'depends': ['base'],

    'currency': 'EUR',
    'price': 0.00,
    'description': """
Odoo App
========

Long description of module's purpose
    """,

    # always loaded
    'data': [
        'views/odoo_app_models_views.xml',
        'views/odoo_app_templates.xml',

        'wizard/odoo_app_wizard_views.xml',

        'security/odoo_app_security.xml',
        'security/ir.model.access.csv',
    ],
    # only loaded in demonstration mode
    'demo': [
        'demo/odoo_app_demo.xml',
    ],
    # 'assets': {
    #    'web.assets_backend': [
    #       ],
    #   'web.assets_frontend': [
    #       ],
    #   'website.assets_editor': [
    #       ],
    #   'website.website_builder_assets': [
    #       ],
    # },
    # 'images': ['images/main.png'],
    'author': 'All Things Toasty Software Ltd',
    'maintainer': 'All Things Toasty Software Ltd',
    'license': 'OPL-1',
    'installable': True,
    'application': True,
}
