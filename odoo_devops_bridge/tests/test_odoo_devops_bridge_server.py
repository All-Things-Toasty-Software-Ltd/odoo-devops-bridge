# Part of Odoo DevOps Bridge. See LICENSE file for full copyright and licensing details.

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged
from unittest.mock import patch

from ..services.odoo_devops_bridge_base_client import OdooDevOpsBridgeAuthError
from ..services.odoo_devops_bridge_sync_manager import OdooDevOpsBridgeSyncManager


@tagged('post_install', '-at_install', 'odoo_devops_bridge')
class TestOdooDevOpsBridgeServer(TransactionCase):
    """Tests for the odoo_devops_bridge.server model: defaults, webhook URL computation,
    secret rotation, and credential resolution priority."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_str('web.base.url', 'https://odoo.example.com')

    def setUp(self):
        super().setUp()
        self.Server = self.env['odoo_devops_bridge.server']
        self.Account = self.env['odoo_devops_bridge.account']

    def test_01_defaults_and_webhook_url(self):
        """A newly created server auto-generates a webhook UUID/secret and
        computes a target URL that embeds both the base URL and UUID."""
        server = self.Server.create({
            'name': 'GitHub Test Server',
            'provider': 'github',
            'server_type': 'saas',
            'base_url': 'https://api.github.com',
        })
        self.assertTrue(server.webhook_uuid, "webhook_uuid should be auto-generated")
        self.assertTrue(server.webhook_secret, "webhook_secret should be auto-generated")
        self.assertIn(server.webhook_uuid, server.webhook_url)
        self.assertTrue(
            server.webhook_url.startswith('https://odoo.example.com/api/v1/devops/webhook/'))
        self.assertEqual(server.state, 'draft')

    def test_02_generate_webhook_secret_rotates_values(self):
        """Regenerating the webhook secret must produce a different UUID and
        secret than before, so old credentials stop working immediately."""
        server = self.Server.create({
            'name': 'GitLab Test Server',
            'provider': 'gitlab',
            'server_type': 'saas',
            'base_url': 'https://gitlab.com',
        })
        old_uuid, old_secret = server.webhook_uuid, server.webhook_secret
        server.action_generate_webhook_secret()
        self.assertNotEqual(server.webhook_uuid, old_uuid)
        self.assertNotEqual(server.webhook_secret, old_secret)

    def test_03_onchange_provider_sets_default_base_url(self):
        """Switching provider/deployment type should propose a sensible
        default base URL for SaaS deployments and clear it for self-hosted."""
        server = self.Server.new({'provider': 'gitlab', 'server_type': 'saas'})
        server._onchange_provider_defaults()
        self.assertEqual(server.base_url, 'https://gitlab.com')

        server.server_type = 'self_hosted'
        server._onchange_provider_defaults()
        self.assertEqual(server.base_url, '')

    def test_04_get_client_prefers_personal_over_bot(self):
        """OdooDevOpsBridgeSyncManager.get_client must prefer a valid personal token over the
        server's default bot account when both are available."""
        server = self.Server.create({
            'name': 'Priority Test Server',
            'provider': 'github',
            'base_url': 'https://api.github.com',
        })
        bot_account = self.Account.create({
            'server_id': server.id,
            'account_type': 'bot',
            'user_id': False,
            'token': 'bot-token-xyz',
            'state': 'valid',
        })
        server.default_bot_account_id = bot_account.id

        personal_account = self.Account.create({
            'server_id': server.id,
            'account_type': 'personal',
            'user_id': self.env.user.id,
            'token': 'personal-token-abc',
            'state': 'valid',
        })

        client = OdooDevOpsBridgeSyncManager.get_client(server, user=self.env.user)
        self.assertEqual(client.token, 'personal-token-abc')

    def test_05_get_client_falls_back_to_bot_account(self):
        """When the acting user has no personal token, OdooDevOpsBridgeSyncManager must fall
        back to the server's default bot account."""
        server = self.Server.create({
            'name': 'Fallback Test Server',
            'provider': 'gitlab',
            'base_url': 'https://gitlab.com',
        })
        bot_account = self.Account.create({
            'server_id': server.id,
            'account_type': 'bot',
            'user_id': False,
            'token': 'bot-token-only',
            'state': 'valid',
        })
        server.default_bot_account_id = bot_account.id

        client = OdooDevOpsBridgeSyncManager.get_client(server, user=self.env.user)
        self.assertEqual(client.token, 'bot-token-only')

    def test_06_get_client_raises_without_any_credentials(self):
        """With neither a personal token nor a bot account configured,
        OdooDevOpsBridgeSyncManager.get_client must raise OdooDevOpsBridgeAuthError rather than
        silently returning an unauthenticated client."""
        server = self.Server.create({
            'name': 'No Credentials Server',
            'provider': 'youtrack',
            'base_url': 'https://example.youtrack.cloud',
        })
        with self.assertRaises(OdooDevOpsBridgeAuthError):
            OdooDevOpsBridgeSyncManager.get_client(server, user=self.env.user)

    def test_07_action_test_connection_success_updates_state(self):
        """A successful test_connection() call should flip the server state
        to 'connected' and clear any prior error message."""
        server = self.Server.create({
            'name': 'Connection Test Server',
            'provider': 'github',
            'base_url': 'https://api.github.com',
        })
        self.Account.create({
            'server_id': server.id,
            'account_type': 'personal',
            'user_id': self.env.user.id,
            'token': 'valid-token',
            'state': 'valid',
        })
        with patch(
                'odoo.addons.odoo_devops_bridge.services.odoo_devops_bridge_github_client.OdooDevOpsBridgeGitHubClient.test_connection',
                return_value={'login': 'octocat'},
        ):
            server.action_test_connection()
        self.assertEqual(server.state, 'connected')
        self.assertFalse(server.error_message)

    def test_08_action_test_connection_failure_raises_and_records_error(self):
        """A failing connection test should raise UserError to the caller and
        persist the error message on the server record for diagnostics."""
        server = self.Server.create({
            'name': 'Broken Server',
            'provider': 'github',
            'base_url': 'https://api.github.com',
        })
        self.Account.create({
            'server_id': server.id,
            'account_type': 'personal',
            'user_id': self.env.user.id,
            'token': 'bad-token',
            'state': 'untested',
        })
        with patch(
                'odoo.addons.odoo_devops_bridge.services.odoo_devops_bridge_github_client.OdooDevOpsBridgeGitHubClient.test_connection',
                side_effect=Exception('401 Unauthorized'),
        ):
            raised = False
            try:
                server.action_test_connection()
            except UserError:
                raised = True
            self.assertTrue(raised, "action_test_connection should raise UserError on failure")
        self.assertEqual(server.state, 'error')
        self.assertIn('401', server.error_message)
