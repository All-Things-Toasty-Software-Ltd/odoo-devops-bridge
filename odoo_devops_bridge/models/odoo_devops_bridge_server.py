# Part of Odoo DevOps Bridge. See LICENSE file for full copyright and licensing details.

import logging
import secrets
import uuid
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

from ..services.odoo_devops_bridge_base_client import OdooDevOpsBridgeAPIError
from ..services.odoo_devops_bridge_sync_manager import OdooDevOpsBridgeSyncManager

_logger = logging.getLogger(__name__)


class OdooDevOpsBridgeServer(models.Model):
    _name = 'odoo_devops_bridge.server'
    _description = 'DevOps Server Instance'
    _order = 'name asc'

    name = fields.Char(string='Server Name', required=True)
    provider = fields.Selection([
        ('github', 'GitHub'),
        ('gitlab', 'GitLab'),
        ('youtrack', 'JetBrains YouTrack'),
    ], string='Provider', required=True, default='github')

    server_type = fields.Selection([
        ('saas', 'Cloud / SaaS'),
        ('self_hosted', 'Self-Hosted / On-Premise'),
    ], string='Deployment Type', required=True, default='saas')

    base_url = fields.Char(
        string='API / Server URL',
        help='Base URL for the server instance. For GitHub SaaS: https://api.github.com. '
             'For GitLab SaaS: https://gitlab.com. '
             'For Self-Hosted instances, specify your complete instance URL (e.g. https://git.toastysoftware.co.uk or https://youtrack.toastysoftware.co.uk)'
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('connected', 'Connected'),
        ('error', 'Connection Error'),
    ], string='Connection Status', default='draft', readonly=True, copy=False)

    active = fields.Boolean(string='Active', default=True)
    sync_direction = fields.Selection([
        ('bidirectional', 'Two-Way Sync (Bidirectional)'),
        ('import_only', 'Import Only (DevOps -> Odoo)'),
        ('export_only', 'Export Only (Odoo -> DevOps)'),
    ], string='Sync Direction', default='bidirectional', required=True)

    webhook_uuid = fields.Char(
        string='Webhook Endpoint Identifier',
        default=lambda self: str(uuid.uuid4()),
        required=True,
        copy=False,
        readonly=True
    )
    webhook_secret = fields.Char(
        string='Webhook Secret Token',
        default=lambda self: secrets.token_hex(20),
        required=True,
        copy=False,
        help='Secret used to cryptographically verify incoming webhook payloads (HMAC SHA-256 for GitHub, X-Gitlab-Token for GitLab, secret token for YouTrack).'
    )
    webhook_url = fields.Char(string='Webhook Target URL', compute='_compute_webhook_url')

    default_bot_account_id = fields.Many2one(
        'odoo_devops_bridge.account',
        string='Default Bot / Automation Account',
        domain="[('server_id', '=', id), ('account_type', '=', 'bot'), ('active', '=', True)]",
        help='Fallback service account used for webhook synchronization and background automated tasks.'
    )

    account_ids = fields.One2many('odoo_devops_bridge.account', 'server_id',
                                  string='User Accounts & Credentials')
    repository_ids = fields.One2many('odoo_devops_bridge.repository', 'server_id',
                                     string='Connected Repositories & Projects')
    team_ids = fields.One2many('odoo_devops_bridge.team', 'server_id',
                               string='Organizations & Teams')

    last_test_date = fields.Datetime(string='Last Tested', readonly=True)
    error_message = fields.Text(string='Connection Error Details', readonly=True)
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company)

    repository_count = fields.Integer(string='Repositories Count', compute='_compute_counts')
    pull_request_count = fields.Integer(string='Pull Requests Count', compute='_compute_counts')
    sync_log_count = fields.Integer(string='Sync Logs Count', compute='_compute_counts')

    @api.depends('webhook_uuid')
    def _compute_webhook_url(self):
        ICP = self.env['ir.config_parameter'].sudo()
        custom_base = ICP.get_str('odoo_devops_bridge.webhook_base_url')
        base_web_url = custom_base or ICP.get_str('web.base.url', 'https://odoo.yourcompany.com')
        for server in self:
            if server.webhook_uuid:
                server.webhook_url = f"{base_web_url.rstrip('/')}/api/v1/devops/webhook/{server.webhook_uuid}"
            else:
                server.webhook_url = False

    def _compute_counts(self):
        for server in self:
            server.repository_count = len(server.repository_ids)
            server.pull_request_count = self.env[
                'odoo_devops_bridge.pull.request'].sudo().search_count(
                [('server_id', '=', server.id)])
            server.sync_log_count = self.env['odoo_devops_bridge.sync.log'].sudo().search_count(
                [('server_id', '=', server.id)])

    @api.onchange('provider', 'server_type')
    def _onchange_provider_defaults(self):
        if self.provider == 'github':
            self.base_url = 'https://api.github.com' if self.server_type == 'saas' else ''
        elif self.provider == 'gitlab':
            self.base_url = 'https://gitlab.com' if self.server_type == 'saas' else ''
        elif self.provider == 'youtrack':
            self.base_url = 'https://your-company.youtrack.cloud' if self.server_type == 'saas' else ''

    def action_generate_webhook_secret(self):
        """Regenerate webhook secret and UUID."""
        for server in self:
            server.write({
                'webhook_uuid': str(uuid.uuid4()),
                'webhook_secret': secrets.token_hex(20),
            })
        return True

    def action_test_connection(self):
        """Verify server connectivity using either the active user token or the default bot account."""
        self.ensure_one()
        try:
            client = OdooDevOpsBridgeSyncManager.get_client(self, user=self.env.user)
            user_info = client.test_connection()
            login_info = user_info.get('login') or user_info.get('username') or user_info.get(
                'name', 'Success')
            self.write({
                'state': 'connected',
                'last_test_date': fields.Datetime.now(),
                'error_message': False,
            })
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Connection Successful'),
                    'message': _("Successfully authenticated as: %s") % login_info,
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            err_msg = str(e)
            self.write({
                'state': 'error',
                'last_test_date': fields.Datetime.now(),
                'error_message': err_msg,
            })
            raise UserError(_("Connection test failed: %s") % err_msg)

    def action_fetch_remote_repositories(self):
        """Fetch remote repositories or projects and open the import wizard."""
        self.ensure_one()
        client = OdooDevOpsBridgeSyncManager.get_client(self, user=self.env.user)
        try:
            if self.provider == 'github':
                repos = client.get_repositories()
                for r in repos:
                    slug = r.get('full_name')
                    ext_id = str(r.get('id'))
                    existing = self.env['odoo_devops_bridge.repository'].search([
                        ('server_id', '=', self.id),
                        ('external_slug', '=', slug),
                    ], limit=1)
                    if not existing:
                        # Find or create linked Odoo project
                        proj = self.env['project.project'].search([('name', '=', r.get('name'))],
                                                                  limit=1)
                        if not proj:
                            proj = self.env['project.project'].create({'name': r.get('name')})
                        self.env['odoo_devops_bridge.repository'].create({
                            'name': r.get('name'),
                            'server_id': self.id,
                            'project_id': proj.id,
                            'external_id': ext_id,
                            'external_slug': slug,
                            'web_url': r.get('html_url'),
                            'default_branch': r.get('default_branch', 'main'),
                        })

            elif self.provider == 'gitlab':
                projects = client.get_projects()
                for p in projects:
                    slug = p.get('path_with_namespace')
                    ext_id = str(p.get('id'))
                    existing = self.env['odoo_devops_bridge.repository'].search([
                        ('server_id', '=', self.id),
                        ('external_id', '=', ext_id),
                    ], limit=1)
                    if not existing:
                        proj = self.env['project.project'].search([('name', '=', p.get('name'))],
                                                                  limit=1)
                        if not proj:
                            proj = self.env['project.project'].create({'name': p.get('name')})
                        self.env['odoo_devops_bridge.repository'].create({
                            'name': p.get('name'),
                            'server_id': self.id,
                            'project_id': proj.id,
                            'external_id': ext_id,
                            'external_slug': slug,
                            'web_url': p.get('web_url'),
                            'default_branch': p.get('default_branch', 'main'),
                        })

            elif self.provider == 'youtrack':
                projects = client.get_projects()
                for p in projects:
                    short_name = p.get('shortName')
                    ext_id = str(p.get('id'))
                    existing = self.env['odoo_devops_bridge.repository'].search([
                        ('server_id', '=', self.id),
                        ('external_id', '=', ext_id),
                    ], limit=1)
                    if not existing:
                        proj = self.env['project.project'].search([('name', '=', p.get('name'))],
                                                                  limit=1)
                        if not proj:
                            proj = self.env['project.project'].create({'name': p.get('name')})
                        self.env['odoo_devops_bridge.repository'].create({
                            'name': p.get('name'),
                            'server_id': self.id,
                            'project_id': proj.id,
                            'external_id': ext_id,
                            'external_slug': short_name,
                        })

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Discovery Completed'),
                    'message': _(
                        "Repositories and projects successfully discovered from %s.") % self.name,
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            raise UserError(_("Failed to fetch remote repositories: %s") % str(e))

    def action_view_repositories(self):
        self.ensure_one()
        return {
            'name': _('Repositories / Projects'),
            'type': 'ir.actions.act_window',
            'res_model': 'odoo_devops_bridge.repository',
            'view_mode': 'list,form',
            'domain': [('server_id', '=', self.id)],
            'context': {'default_server_id': self.id},
        }

    def action_view_pull_requests(self):
        self.ensure_one()
        return {
            'name': _('Pull Requests / Merge Requests'),
            'type': 'ir.actions.act_window',
            'res_model': 'odoo_devops_bridge.pull.request',
            'view_mode': 'list,form,kanban',
            'domain': [('server_id', '=', self.id)],
            'context': {'default_server_id': self.id},
        }

    def action_view_sync_logs(self):
        self.ensure_one()
        return {
            'name': _('Sync Audit Logs'),
            'type': 'ir.actions.act_window',
            'res_model': 'odoo_devops_bridge.sync.log',
            'view_mode': 'list,form',
            'domain': [('server_id', '=', self.id)],
            'context': {'default_server_id': self.id},
        }

    @api.model
    def _cron_sync_servers(self):
        """Background fallback polling for connected servers and repositories."""
        servers = self.search([('state', '=', 'connected'), ('active', '=', True)])
        for server in servers:
            for repo in server.repository_ids:
                try:
                    wizard = self.env['odoo_devops_bridge.sync.wizard'].create({
                        'server_id': server.id,
                        'repository_id': repo.id,
                        'sync_scope': 'all',
                        'state_filter': 'open',
                    })
                    wizard.action_execute_sync()
                except Exception as e:
                    _logger.warning("Cron sync error for repo %s: %s", repo.name, str(e))
