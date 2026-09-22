# Part of Odoo DevOps Bridge. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api, _


class OdooDevOpsBridgeRepository(models.Model):
    _name = 'odoo_devops_bridge.repository'
    _description = 'DevOps Repository / External Project Binding'
    _order = 'name asc'

    name = fields.Char(string='Repository / Project Name', required=True)
    server_id = fields.Many2one('odoo_devops_bridge.server', string='DevOps Server', required=True,
                                ondelete='cascade')
    provider = fields.Selection(related='server_id.provider', store=True, readonly=True)

    project_id = fields.Many2one(
        'project.project',
        string='Linked Odoo Project',
        required=True,
        ondelete='cascade',
        help='The Odoo Project that mirrors this external repository or issue tracker.'
    )

    team_id = fields.Many2one('odoo_devops_bridge.team', string='Organization / Team',
                              domain="[('server_id', '=', server_id)]")
    external_id = fields.Char(string='External ID',
                              help='Remote identifier in GitHub/GitLab/YouTrack.')
    external_slug = fields.Char(
        string='Full Path / Slug',
        required=True,
        help='e.g. "odoo/odoo" for GitHub, "gitlab-org/gitlab" for GitLab, or "PRJ" for YouTrack.'
    )
    web_url = fields.Char(string='Repository Web URL')
    default_branch = fields.Char(string='Default Branch', default='main')

    sync_issues = fields.Boolean(string='Sync Issues / Tasks', default=True)
    sync_pull_requests = fields.Boolean(string='Sync Pull Requests / MRs', default=True)
    sync_comments = fields.Boolean(string='Sync Comments & Chatter', default=True)
    sync_milestones = fields.Boolean(string='Sync Milestones / Releases', default=True)

    open_stage_id = fields.Many2one(
        'project.task.type',
        string='Open Stage in Odoo',
        domain="[('project_ids', 'in', project_id)]",
        help='Tasks synced as open/active will be moved to this stage.'
    )
    closed_stage_id = fields.Many2one(
        'project.task.type',
        string='Closed Stage in Odoo',
        domain="[('project_ids', 'in', project_id)]",
        help='Tasks marked as closed or resolved externally will be moved to this stage.'
    )

    last_sync_date = fields.Datetime(string='Last Synchronized', readonly=True)
    pull_request_ids = fields.One2many('odoo_devops_bridge.pull.request', 'repository_id',
                                       string='Pull Requests')
    pull_request_count = fields.Integer(string='PRs Count', compute='_compute_counts')
    task_count = fields.Integer(string='Tasks Count', compute='_compute_counts')

    def _compute_counts(self):
        for repo in self:
            repo.pull_request_count = len(repo.pull_request_ids)
            repo.task_count = self.env['project.task'].sudo().search_count(
                [('devops_repo_id', '=', repo.id)])

    def action_sync_now(self):
        """Open sync wizard for this repository."""
        self.ensure_one()
        return {
            'name': _('Synchronize Repository: %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'odoo_devops_bridge.sync.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_server_id': self.server_id.id,
                'default_repository_id': self.id,
            },
        }

    def action_view_pull_requests(self):
        self.ensure_one()
        return {
            'name': _('Pull Requests: %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'odoo_devops_bridge.pull.request',
            'view_mode': 'list,form,kanban',
            'domain': [('repository_id', '=', self.id)],
            'context': {'default_repository_id': self.id, 'default_server_id': self.server_id.id},
        }

    def action_view_tasks(self):
        self.ensure_one()
        return {
            'name': _('Tasks: %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'project.task',
            'view_mode': 'kanban,list,form',
            'domain': [('devops_repo_id', '=', self.id)],
            'context': {'default_project_id': self.project_id.id,
                        'default_devops_repo_id': self.id},
        }
