#  Part of Odoo Devops Bridge. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api, _
from odoo.exceptions import UserError

from ..services.odoo_devops_bridge_sync_manager import OdooDevOpsBridgeSyncManager


class OdooDevOpsBridgePullRequest(models.Model):
    _name = 'odoo_devops_bridge.pull.request'
    _description = 'DevOps Pull Request / Merge Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'number desc, id desc'

    name = fields.Char(string='Title', required=True, tracking=True)
    server_id = fields.Many2one('odoo_devops_bridge.server', string='DevOps Server', required=True,
                                ondelete='cascade')
    provider = fields.Selection(related='server_id.provider', store=True, readonly=True)

    repository_id = fields.Many2one(
        'odoo_devops_bridge.repository',
        string='Repository',
        required=True,
        ondelete='cascade',
        domain="[('server_id', '=', server_id)]"
    )
    project_id = fields.Many2one('project.project', string='Project',
                                 related='repository_id.project_id', store=True, readonly=False)

    task_id = fields.Many2one(
        'project.task',
        string='Linked Task / Issue',
        domain="[('project_id', '=', project_id)]",
        help='Odoo task linked to this pull request / merge request.'
    )

    external_id = fields.Char(string='Remote ID', required=True, copy=False)
    number = fields.Char(string='PR/MR #', required=True)

    state = fields.Selection([
        ('draft', 'Draft / WIP'),
        ('open', 'Open'),
        ('merged', 'Merged'),
        ('closed', 'Closed (Unmerged)'),
    ], string='Status', default='open', required=True, tracking=True)

    is_merged = fields.Boolean(string='Is Merged', default=False, tracking=True)
    merged_at = fields.Datetime(string='Merged On')
    merge_commit_sha = fields.Char(string='Merge Commit SHA')

    source_branch = fields.Char(string='Source Branch', tracking=True)
    target_branch = fields.Char(string='Target Branch', default='main', tracking=True)

    author_username = fields.Char(string='Author Handle')
    web_url = fields.Char(string='View Online (URL)')

    user_ids = fields.Many2many(
        'res.users',
        'devops_pr_assignee_rel',
        'pr_id',
        'user_id',
        string='Assignees',
        tracking=True
    )
    reviewer_ids = fields.Many2many(
        'res.users',
        'devops_pr_reviewer_rel',
        'pr_id',
        'user_id',
        string='Reviewers',
        tracking=True
    )
    tag_ids = fields.Many2many('project.tags', string='Labels / Tags')
    milestone_id = fields.Many2one(
        'project.milestone',
        string='Milestone',
        domain="[('project_id', '=', project_id)]",
        tracking=True
    )

    commits_count = fields.Integer(string='Commits')
    additions = fields.Integer(string='Additions (+)')
    deletions = fields.Integer(string='Deletions (-)')
    changed_files = fields.Integer(string='Files Changed')

    description = fields.Text(string='PR Description / Summary')

    review_status = fields.Selection([
        ('pending', 'Pending Review'),
        ('approved', 'Approved'),
        ('changes_requested', 'Changes Requested'),
        ('commented', 'Reviewed / Commented'),
    ], string='Review Status', default='pending', tracking=True)

    devops_sync_status = fields.Selection([
        ('not_synced', 'Not Synced'),
        ('synced', 'Synced'),
        ('error', 'Sync Error'),
    ], string='DevOps Sync Status', default='synced', copy=False)

    display_name = fields.Char(compute='_compute_display_name', store=True)

    @api.depends('number', 'name', 'repository_id.name')
    def _compute_display_name(self):
        for pr in self:
            repo_name = pr.repository_id.name if pr.repository_id else ''
            pr.display_name = f"#{pr.number or ''} {pr.name} ({repo_name})"

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get('syncing_from_devops'):
            sync_fields = {'name', 'description', 'state', 'user_ids', 'reviewer_ids', 'tag_ids',
                           'milestone_id', 'source_branch', 'target_branch'}
            if sync_fields.intersection(vals.keys()):
                for pr in self:
                    if pr.repository_id:
                        OdooDevopsBridgeSyncManager.sync_pull_request_outbound(pr)
        return res

    def action_merge_pr(self):
        """Merge this pull request / merge request remotely from Odoo."""
        self.ensure_one()
        OdooDevOpsBridgeSyncManager.merge_pull_request(self)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Pull Request Merged'),
                'message': _("Pull request #%s was successfully merged.") % self.number,
                'type': 'success',
            }
        }

    def action_close_pr(self):
        """Close this pull request / merge request remotely from Odoo."""
        self.ensure_one()
        OdooDevOpsBridgeSyncManager.close_pull_request(self)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Pull Request Closed'),
                'message': _("Pull request #%s was closed.") % self.number,
                'type': 'info',
            }
        }

    def action_reopen_pr(self):
        """Reopen this pull request / merge request remotely from Odoo."""
        self.ensure_one()
        OdooDevOpsBridgeSyncManager.reopen_pull_request(self)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Pull Request Reopened'),
                'message': _("Pull request #%s was reopened.") % self.number,
                'type': 'info',
            }
        }

    def action_sync_to_devops(self):
        """Manually push edits on this PR to GitHub/GitLab."""
        self.ensure_one()
        OdooDevOpsBridgeSyncManager.sync_pull_request_outbound(self)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Sync Dispatched'),
                'message': _("Pull request #%s synchronized with %s.") % (self.number,
                                                                          self.server_id.name or 'DevOps'),
                'type': 'success',
            }
        }

    def action_open_external_url(self):
        """Open PR on GitHub/GitLab in a new browser tab."""
        self.ensure_one()
        if not self.web_url:
            return False
        return {
            'type': 'ir.actions.act_url',
            'url': self.web_url,
            'target': 'new',
        }
