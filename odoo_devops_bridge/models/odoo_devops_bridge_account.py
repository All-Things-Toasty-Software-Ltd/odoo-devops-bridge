# Part of Odoo DevOps Bridge. See LICENSE file for full copyright and licensing details.

import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

from ..services.odoo_devops_bridge_base_client import OdooDevOpsBridgeAPIError
from ..services.odoo_devops_bridge_github_client import OdooDevOpsBridgeGitHubClient
from ..services.odoo_devops_bridge_gitlab_client import OdooDevOpsBridgeGitLabClient
from ..services.odoo_devops_bridge_youtrack_client import OdooDevOpsBridgeYouTrackClient

_logger = logging.getLogger(__name__)


class OdooDevOpsBridgeAccount(models.Model):
    _name = 'odoo_devops_bridge.account'
    _description = 'DevOps User & Bot Account Credentials'
    _order = 'account_type asc, name asc'

    name = fields.Char(string='Account Label', compute='_compute_name', store=True, readonly=False)
    server_id = fields.Many2one('odoo_devops_bridge.server', string='DevOps Server', required=True,
                                ondelete='cascade')
    provider = fields.Selection(related='server_id.provider', store=True, readonly=True)

    account_type = fields.Selection([
        ('personal', 'Internal User Account'),
        ('bot', 'System Bot / Service Account'),
    ], string='Account Type', default='personal', required=True)

    user_id = fields.Many2one(
        'res.users',
        string='Odoo Internal User',
        default=lambda self: self.env.user,
        help='The internal Odoo user who owns this credential.'
    )

    external_username = fields.Char(
        string='External Username / Handle',
        help='Username on the external platform (e.g. GitHub login, GitLab username, YouTrack login).'
    )
    external_user_id = fields.Char(string='External User ID', readonly=True)

    token = fields.Char(
        string='Personal Access Token / API Token',
        required=True,
        help='API Token, Personal Access Token (PAT), or Permanent Bearer Token.'
    )

    state = fields.Selection([
        ('untested', 'Untested'),
        ('valid', 'Valid / Connected'),
        ('invalid', 'Invalid / Expired'),
    ], string='Credential Status', default='untested', readonly=True, copy=False)

    active = fields.Boolean(string='Active', default=True)
    last_verified_at = fields.Datetime(string='Last Verified', readonly=True)
    error_message = fields.Text(string='Verification Details', readonly=True)

    _sql_constraints = [
        ('server_user_unique',
         'unique(server_id, user_id, account_type)',
         'A user can only have one personal account per DevOps server!')
    ]

    @api.depends('server_id', 'user_id', 'account_type', 'external_username')
    def _compute_name(self):
        for acc in self:
            server_name = acc.server_id.name or 'Server'
            if acc.account_type == 'bot':
                acc.name = f"Bot: {acc.external_username or 'Automation'} ({server_name})"
            else:
                user_name = acc.user_id.name or 'User'
                handle = f" (@{acc.external_username})" if acc.external_username else ''
                acc.name = f"{user_name}{handle} - {server_name}"

    def action_verify(self):
        """Test authentication token with provider API."""
        self.ensure_one()
        provider = self.provider
        base_url = self.server_id.base_url
        token = self.token

        try:
            if provider == 'github':
                client = OdooDevOpsBridgeGitHubClient(base_url=base_url, token=token)
                res = client.test_connection()
                login = res.get('login')
                user_id = str(res.get('id', ''))
            elif provider == 'gitlab':
                client = OdooDevOpsBridgeGitLabClient(base_url=base_url, token=token)
                res = client.test_connection()
                login = res.get('username')
                user_id = str(res.get('id', ''))
            elif provider == 'youtrack':
                client = OdooDevOpsBridgeYouTrackClient(base_url=base_url, token=token)
                res = client.test_connection()
                login = res.get('login') or res.get('name')
                user_id = str(res.get('id', ''))
            else:
                raise UserError(_("Unknown provider: %s") % provider)

            self.write({
                'state': 'valid',
                'external_username': login,
                'external_user_id': user_id,
                'last_verified_at': fields.Datetime.now(),
                'error_message': False,
            })

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Token Verified'),
                    'message': _("Successfully authenticated as external user: %s") % login,
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            err = str(e)
            self.write({
                'state': 'invalid',
                'last_verified_at': fields.Datetime.now(),
                'error_message': err,
            })
            raise UserError(_("Credential verification failed: %s") % err)
