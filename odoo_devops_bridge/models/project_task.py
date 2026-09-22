# Part of Odoo DevOps Bridge. See LICENSE file for full copyright and licensing details.

import logging
import re
from odoo import models, fields, api, _
from odoo.exceptions import UserError

from ..services.odoo_devops_bridge_sync_manager import OdooDevOpsBridgeSyncManager

_logger = logging.getLogger(__name__)


class ProjectTask(models.Model):
    _inherit = 'project.task'

    devops_server_id = fields.Many2one('odoo_devops_bridge.server', string='DevOps Server',
                                       ondelete='set null')
    devops_repo_id = fields.Many2one(
        'odoo_devops_bridge.repository',
        string='DevOps Repository / Project',
        domain="[('project_id', '=', project_id)]",
        ondelete='set null'
    )
    devops_external_id = fields.Char(string='DevOps Issue ID', copy=False, index=True)
    devops_issue_number = fields.Char(string='Issue # / Key', copy=False, index=True)
    devops_provider = fields.Selection(related='devops_server_id.provider', store=True,
                                       readonly=True)
    devops_web_url = fields.Char(string='Issue Web URL', copy=False)
    devops_issue_type = fields.Selection([
        ('task', 'Task'),
        ('bug', 'Bug'),
        ('feature', 'Feature'),
        ('recommendation', 'Recommendation'),
        ('documentation', 'Documentation'),
        ('question', 'Question'),
    ], string='DevOps Issue Type', default='task', tracking=True)

    devops_sync_status = fields.Selection([
        ('not_synced', 'Not Synced'),
        ('synced', 'Synced'),
        ('error', 'Sync Error'),
    ], string='DevOps Sync Status', default='not_synced', copy=False)

    devops_pull_request_ids = fields.One2many('odoo_devops_bridge.pull.request', 'task_id',
                                              string='Pull Requests')
    devops_pull_request_count = fields.Integer(string='PR Count',
                                               compute='_compute_devops_pr_count')
    devops_branch_ref = fields.Char(string='Suggested Branch', compute='_compute_devops_branch_ref')

    @api.onchange('project_id')
    def _onchange_project_id_devops(self):
        if self.project_id and self.project_id.devops_repo_ids:
            repo = self.project_id.devops_repo_ids[0]
            self.devops_repo_id = repo.id
            self.devops_server_id = repo.server_id.id

    def _compute_devops_pr_count(self):
        for task in self:
            task.devops_pull_request_count = len(task.devops_pull_request_ids)

    @api.depends('name', 'devops_issue_number')
    def _compute_devops_branch_ref(self):
        for task in self:
            key = task.devops_issue_number or f"task-{task.id}"
            clean_name = re.sub(r'[^a-zA-Z0-9]+', '-', (task.name or '').lower()).strip('-')[:35]
            task.devops_branch_ref = f"feature/{key}-{clean_name}" if clean_name else f"feature/{key}"

    @api.model_create_multi
    def create(self, vals_list):
        tasks = super().create(vals_list)
        if not self.env.context.get('syncing_from_devops'):
            for task in tasks:
                if not task.devops_repo_id and task.project_id and task.project_id.devops_repo_ids:
                    task.devops_repo_id = task.project_id.devops_repo_ids[0].id
                    task.devops_server_id = task.devops_repo_id.server_id.id
                if task.devops_repo_id:
                    OdooDevOpsBridgeSyncManager.sync_task_outbound(task)
        return tasks

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get('syncing_from_devops'):
            sync_fields = {'name', 'description', 'stage_id', 'user_ids', 'milestone_id', 'tag_ids',
                           'devops_issue_type', 'depend_on_ids', 'dependent_ids'}
            if sync_fields.intersection(vals.keys()):
                for task in self:
                    if task.devops_repo_id:
                        OdooDevOpsBridgeSyncManager.sync_task_outbound(task)
        return res

    def action_sync_to_devops(self):
        """Manually push this task to the remote issue tracker."""
        self.ensure_one()
        if not self.devops_repo_id:
            if self.project_id.devops_repo_ids:
                self.devops_repo_id = self.project_id.devops_repo_ids[0].id
                self.devops_server_id = self.devops_repo_id.server_id.id
            else:
                raise UserError(
                    _("Please configure a DevOps Repository on this task or its project first."))
        OdooDevOpsBridgeSyncManager.sync_task_outbound(self)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Sync Dispatched'),
                'message': _("Task synchronized with %s.") % (
                        self.devops_server_id.name or 'DevOps'),
                'type': 'success',
            }
        }

    def action_open_external_url(self):
        self.ensure_one()
        if not self.devops_web_url:
            return False
        return {
            'type': 'ir.actions.act_url',
            'url': self.devops_web_url,
            'target': 'new',
        }

    def action_close_devops_issue(self):
        """Close the issue on remote tracker (GitHub/GitLab/YouTrack) and update task stage in Odoo."""
        self.ensure_one()
        OdooDevOpsBridgeSyncManager.close_task(self)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Issue Closed'),
                'message': _("Issue #%s was closed on %s.") % (self.devops_issue_number or self.id,
                                                               self.devops_server_id.name or 'DevOps'),
                'type': 'info',
            }
        }

    def action_reopen_devops_issue(self):
        """Reopen the issue on remote tracker (GitHub/GitLab/YouTrack) and update task stage in Odoo."""
        self.ensure_one()
        OdooDevOpsBridgeSyncManager.reopen_task(self)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Issue Reopened'),
                'message': _("Issue #%s was reopened on %s.") % (
                    self.devops_issue_number or self.id, self.devops_server_id.name or 'DevOps'),
                'type': 'info',
            }
        }

    def action_view_devops_prs(self):
        self.ensure_one()
        return {
            'name': _('Pull Requests for Task: %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'odoo_devops_bridge.pull.request',
            'view_mode': 'list,form,kanban',
            'domain': [('task_id', '=', self.id)],
            'context': {'default_task_id': self.id, 'default_project_id': self.project_id.id},
        }
