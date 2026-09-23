# Part of Odoo DevOps Bridge. See LICENSE file for full copyright and licensing details.

import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

from ..services.odoo_devops_bridge_sync_manager import OdooDevOpsBridgeSyncManager

_logger = logging.getLogger(__name__)


class DevOpsSyncWizard(models.TransientModel):
    _name = 'odoo_devops_bridge.sync.wizard'
    _description = 'Manual DevOps Synchronization Wizard'

    server_id = fields.Many2one('odoo_devops_bridge.server', string='DevOps Server', required=True)
    provider = fields.Selection(related='server_id.provider', readonly=True)
    repository_id = fields.Many2one(
        'odoo_devops_bridge.repository',
        string='Target Repository',
        domain="[('server_id', '=', server_id)]",
        help='Leave empty to sync all repositories configured for this server.'
    )

    sync_scope = fields.Selection([
        ('all', 'Everything (Issues, Pull Requests, Comments, Milestones)'),
        ('issues', 'Issues / Tasks Only'),
        ('pull_requests', 'Pull Requests / Merge Requests Only'),
        ('milestones', 'Milestones / Releases Only'),
    ], string='Sync Scope', default='all', required=True)

    state_filter = fields.Selection([
        ('all', 'All States (Open and Closed)'),
        ('open', 'Open Only'),
        ('closed', 'Closed Only'),
    ], string='State Filter', default='open', required=True)

    limit = fields.Integer(string='Max Records per Entity', default=50)

    def action_execute_sync(self):
        """Execute synchronization across selected repositories."""
        self.ensure_one()
        server = self.server_id
        repos = self.repository_id or server.repository_ids

        if not repos:
            raise UserError(
                _("No repositories selected or configured on server '%s'.") % server.name)

        client = OdooDevOpsBridgeSyncManager.get_client(server, user=self.env.user)
        total_issues = 0
        total_prs = 0
        total_milestones = 0

        for repo in repos:
            slug = repo.external_slug

            # Sync Milestones
            if self.sync_scope in ('all',
                                   'milestones') and repo.sync_milestones and repo.project_id:
                try:
                    if server.provider == 'github':
                        parts = slug.split('/')
                        if len(parts) == 2:
                            milestones = client.get_milestones(parts[0], parts[1],
                                                               state=self.state_filter)
                            for m in milestones:
                                OdooDevOpsBridgeSyncManager._process_github_milestone(self.env,
                                                                                      server, repo,
                                                                                      {
                                                                                          'action': 'sync',
                                                                                          'milestone': m})
                                total_milestones += 1
                    elif server.provider == 'gitlab':
                        # GitLab milestone API states: 'active' / 'closed' (not 'open')
                        gl_state = {'open': 'active', 'closed': 'closed', 'all': 'all'}.get(
                            self.state_filter, 'all')
                        milestones = client.get_milestones(repo.external_id or slug, state=gl_state)
                        for m in milestones:
                            OdooDevOpsBridgeSyncManager._process_gitlab_milestone(self.env, server,
                                                                                  repo, m)
                            total_milestones += 1
                except Exception as e:
                    _logger.warning("Error importing milestones for repo %s: %s", slug, str(e))

            # Sync Issues / Tasks
            if self.sync_scope in ('all', 'issues') and repo.sync_issues:
                try:
                    if server.provider == 'github':
                        parts = slug.split('/')
                        if len(parts) == 2:
                            issues = client.get_issues(parts[0], parts[1], state=self.state_filter,
                                                       per_page=self.limit)
                            for issue in issues:
                                if 'pull_request' in issue:
                                    continue
                                OdooDevOpsBridgeSyncManager._process_github_issue(self.env, server,
                                                                                  repo,
                                                                                  {'action': 'sync',
                                                                                   'issue': issue})
                                total_issues += 1
                    elif server.provider == 'gitlab':
                        # GitLab issues API states: 'opened' / 'closed' (not 'open')
                        gl_issue_state = {'open': 'opened', 'closed': 'closed', 'all': 'all'}.get(
                            self.state_filter, 'all')
                        issues = client.get_issues(repo.external_id or slug, state=gl_issue_state,
                                                   per_page=self.limit)
                        for issue in issues:
                            payload = {'project': {'path_with_namespace': slug},
                                       'object_attributes': issue}
                            OdooDevOpsBridgeSyncManager._process_gitlab_issue(self.env, server,
                                                                              repo, payload)
                            total_issues += 1
                    elif server.provider == 'youtrack':
                        issues = client.get_issues(query=f"project: {slug}", top=self.limit)
                        for issue in issues:
                            payload = {'project': {'shortName': slug}, 'issue': issue}
                            OdooDevOpsBridgeSyncManager.process_youtrack_event(self.env, server,
                                                                               payload)
                            total_issues += 1
                except Exception as e:
                    _logger.warning("Error importing issues for repo %s: %s", slug, str(e))

            # Sync Pull Requests
            if self.sync_scope in ('all', 'pull_requests') and repo.sync_pull_requests:
                try:
                    if server.provider == 'github':
                        parts = slug.split('/')
                        if len(parts) == 2:
                            prs = client.get_pull_requests(parts[0], parts[1],
                                                           state=self.state_filter,
                                                           per_page=self.limit)
                            for pr in prs:
                                OdooDevOpsBridgeSyncManager._process_github_pull_request(self.env,
                                                                                         server,
                                                                                         repo, {
                                                                                             'action': 'sync',
                                                                                             'pull_request': pr})
                                total_prs += 1
                    elif server.provider == 'gitlab':
                        # GitLab merge_requests API states: 'opened' / 'closed' / 'merged' / 'all'
                        gl_mr_state = {'open': 'opened', 'closed': 'closed', 'all': 'all'}.get(
                            self.state_filter, 'all')
                        mrs = client.get_merge_requests(repo.external_id or slug, state=gl_mr_state,
                                                        per_page=self.limit)
                        for mr in mrs:
                            OdooDevOpsBridgeSyncManager._process_gitlab_merge_request(self.env,
                                                                                      server, repo,
                                                                                      {
                                                                                          'object_attributes': mr})
                            total_prs += 1
                except Exception as e:
                    _logger.warning("Error importing PRs for repo %s: %s", slug, str(e))

            repo.sudo().write({'last_sync_date': fields.Datetime.now()})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Synchronization Finished'),
                'message': _("Sync completed: %s tasks, %s PRs/MRs, %s milestones updated.") % (
                    total_issues, total_prs, total_milestones),
                'type': 'success',
                'sticky': False,
            }
        }
