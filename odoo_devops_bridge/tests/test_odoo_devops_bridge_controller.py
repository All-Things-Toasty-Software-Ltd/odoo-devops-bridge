# Part of Odoo DevOps Bridge. See LICENSE file for full copyright and licensing details.

import hashlib
import hmac
import json

from odoo.tests.common import HttpCase, tagged


@tagged('post_install', '-at_install', 'odoo_devops_bridge')
class TestOdooDevOpsBridgeController(HttpCase):
    """End-to-end tests for the universal webhook endpoint: signature
    verification, unknown-server handling, and audit log creation."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({'name': 'Webhook Controller Test Project'})
        cls.server = cls.env['odoo_devops_bridge.server'].create({
            'name': 'Webhook Controller Test Server',
            'provider': 'github',
            'base_url': 'https://api.github.com',
            'webhook_secret': 'super-secret-value',
        })
        cls.repo = cls.env['odoo_devops_bridge.repository'].create({
            'name': 'acme/widgets',
            'server_id': cls.server.id,
            'project_id': cls.project.id,
            'external_id': '2002',
            'external_slug': 'acme/widgets',
        })

    def _sign(self, secret, raw_body):
        mac = hmac.new(secret.encode('utf-8'), msg=raw_body, digestmod=hashlib.sha256)
        return f"sha256={mac.hexdigest()}"

    def test_01_valid_signature_is_accepted_and_logged(self):
        """A correctly-signed GitHub 'issues' payload should be accepted
        (HTTP 200), processed, and recorded in the sync log."""
        payload = {
            'action': 'opened',
            'repository': {'full_name': 'acme/widgets'},
            'issue': {'id': 900001, 'number': 7, 'title': 'From webhook', 'state': 'open'},
        }
        raw_body = json.dumps(payload).encode('utf-8')
        signature = self._sign(self.server.webhook_secret, raw_body)

        response = self.url_open(
            f'/api/v1/devops/webhook/{self.server.webhook_uuid}',
            data=raw_body,
            headers={
                'Content-Type': 'application/json',
                'X-GitHub-Event': 'issues',
                'X-Hub-Signature-256': signature,
            },
        )
        self.assertEqual(response.status_code, 200)

        log = self.env['odoo_devops_bridge.sync.log'].search([
            ('server_id', '=', self.server.id),
            ('event_type', '=', 'issues'),
        ], limit=1)
        self.assertTrue(log, "A sync log entry should be created for the inbound webhook")
        self.assertEqual(log.status, 'success')

        task = self.env['project.task'].search([('devops_external_id', '=', '900001')], limit=1)
        self.assertTrue(task)
        self.assertEqual(task.name, 'From webhook')

    def test_02_invalid_signature_is_rejected(self):
        """A payload signed with the wrong secret must be rejected with 401
        and must not create any task or successful sync log."""
        payload = {
            'action': 'opened',
            'repository': {'full_name': 'acme/widgets'},
            'issue': {'id': 900002, 'number': 8, 'title': 'Forged payload', 'state': 'open'},
        }
        raw_body = json.dumps(payload).encode('utf-8')
        bad_signature = self._sign('completely-wrong-secret', raw_body)

        response = self.url_open(
            f'/api/v1/devops/webhook/{self.server.webhook_uuid}',
            data=raw_body,
            headers={
                'Content-Type': 'application/json',
                'X-GitHub-Event': 'issues',
                'X-Hub-Signature-256': bad_signature,
            },
        )
        self.assertEqual(response.status_code, 401)

        task = self.env['project.task'].search([('devops_external_id', '=', '900002')])
        self.assertFalse(task)

    def test_03_unknown_server_uuid_returns_404(self):
        """Posting to a UUID that does not match any devops.server should
        return 404 without raising a server error."""
        response = self.url_open(
            '/api/v1/devops/webhook/00000000-0000-0000-0000-000000000000',
            data=json.dumps({'issue': {}}).encode('utf-8'),
            headers={'Content-Type': 'application/json', 'X-GitHub-Event': 'issues'},
        )
        self.assertEqual(response.status_code, 404)
