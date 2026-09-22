# Part of Odoo DevOps Bridge. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api, _


class ProjectProject(models.Model):
    _inherit = 'project.project'

    devops_repo_ids = fields.One2many(
        'odoo_devops_bridge.repository',
        'project_id',
        string='DevOps Repositories / Trackers'
    )
    devops_repo_count = fields.Integer(
        string='Connected Repositories',
        compute='_compute_devops_counts'
    )
    devops_pull_request_count = fields.Integer(
        string='Pull Requests',
        compute='_compute_devops_counts'
    )

    def _compute_devops_counts(self):
        for proj in self:
            proj.devops_repo_count = len(proj.devops_repo_ids)
            proj.devops_pull_request_count = self.env[
                'odoo_devops_bridge.pull.request'].sudo().search_count([
                ('project_id', '=', proj.id)
            ])

    def action_view_devops_repos(self):
        self.ensure_one()
        return {
            'name': _('Connected Repositories: %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'odoo_devops_bridge.repository',
            'view_mode': 'list,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }

    def action_view_devops_prs(self):
        self.ensure_one()
        return {
            'name': _('Pull Requests: %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'odoo_devops_bridge.pull.request',
            'view_mode': 'list,form,kanban',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }
