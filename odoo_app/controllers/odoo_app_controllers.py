# Part of Odoo App. See LICENSE file for full copyright and licensing details.

# from odoo import http


# class OdooAppControllers(http.Controller):
#     @http.route('/odoo_app/models', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/odoo_app/models/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('odoo_app.listing', {
#             'root': '/odoo_app/models',
#             'objects': http.request.env['odoo_app.models'].search([]),
#         })

#     @http.route('/odoo_app/models/objects/<model("odoo_app.models"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('odoo_app.object', {
#             'object': obj
#         })
