# Part of Odoo Devops Bridge. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api, _


class ProjectMilestone(models.Model):
    _inherit = 'project.milestone'

    devops_server_id = fields.Many2one('odoo_devops_bridge.server', string='DevOps Server',
                                       ondelete='set null')
    devops_repo_id = fields.Many2one('odoo_devops_bridge.repository', string='DevOps Repository',
                                     ondelete='set null')
    devops_external_id = fields.Char(string='Remote Milestone ID', copy=False, index=True)
    devops_state = fields.Selection([
        ('open', 'Open'),
        ('closed', 'Closed'),
    ], string='DevOps Status', default='open')
