# Part of Odoo App. See LICENSE file for full copyright and licensing details.

# from odoo import models, fields, api


# class OdooAppModels(models.Model):
#     _name = 'odoo_app.models'
#     _description = 'odoo_app.models'

#     name = fields.Char()
#     value = fields.Integer()
#     value2 = fields.Float(compute="_value_pc", store=True)
#     description = fields.Text()
#
#     @api.depends('value')
#     def _value_pc(self):
#         for record in self:
#             record.value2 = float(record.value) / 100
