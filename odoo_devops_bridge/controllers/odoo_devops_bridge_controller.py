# Part of Odoo Devops Bridge. See LICENSE file for full copyright and licensing details.

import json
import logging
from odoo import http, _
from odoo.http import request, Response

from ..services.odoo_devops_bridge_github_client import OdooDevOpsBridgeGitHubClient
from ..services.odoo_devops_bridge_gitlab_client import OdooDevOpsBridgeGitLabClient
from ..services.odoo_devops_bridge_sync_manager import OdooDevOpsBridgeSyncManager
from ..services.odoo_devops_bridge_youtrack_client import OdooDevOpsBridgeYouTrackClient

_logger = logging.getLogger(__name__)


class OdooDevOpsBridgeController(http.Controller):

    @http.route('/api/v1/devops/webhook/<string:server_uuid>', type='http', auth='public',
                methods=['POST'], csrf=False)
    def handle_devops_webhook(self, server_uuid, **kwargs):
        """
        Universal webhook receiver for GitHub, GitLab, and YouTrack events.
        Authenticates payloads using cryptographic HMAC / secret tokens,
        creates an audit log entry, and dispatches to OdooDevOpsBridgeSyncManager.
        """
        raw_payload = request.httprequest.get_data()
        headers = request.httprequest.headers

        # Find matching server by webhook_uuid
        server = request.env['odoo_devops_bridge.server'].sudo().search([
            ('webhook_uuid', '=', server_uuid),
            ('active', '=', True),
        ], limit=1)

        if not server:
            _logger.warning("Webhook rejected: Unknown or inactive server UUID '%s'", server_uuid)
            return Response(json.dumps({'error': 'Server not found or disabled'}), status=404,
                            content_type='application/json')

        # Verify authentication signature based on provider
        is_authenticated = False
        event_type = 'unknown'

        if server.provider == 'github':
            event_type = headers.get('X-GitHub-Event', 'unknown')
            signature = headers.get('X-Hub-Signature-256')
            is_authenticated = OdooDevOpsBridgeGitHubClient.verify_webhook_signature(raw_payload,
                                                                                     signature,
                                                                                     server.webhook_secret)

        elif server.provider == 'gitlab':
            event_type = headers.get('X-Gitlab-Event', 'unknown')
            token_header = headers.get('X-Gitlab-Token')
            is_authenticated = OdooDevOpsBridgeGitLabClient.verify_webhook_token(token_header,
                                                                                 server.webhook_secret)

        elif server.provider == 'youtrack':
            event_type = headers.get('X-YouTrack-Event', 'issue')
            auth_header = headers.get('Authorization') or kwargs.get('token')
            is_authenticated = OdooDevOpsBridgeYouTrackClient.verify_webhook_token(auth_header,
                                                                                   server.webhook_secret)

        if not is_authenticated:
            _logger.warning("Webhook authentication failed for server '%s' (%s)", server.name,
                            server.provider)
            return Response(json.dumps({'error': 'Invalid webhook signature or token'}), status=401,
                            content_type='application/json')

        # Parse JSON payload
        try:
            payload = json.loads(raw_payload.decode('utf-8'))
        except Exception as e:
            _logger.warning("Invalid JSON received on webhook for server '%s' : %s", server.name,
                            str(e))
            return Response(json.dumps({'error': 'Invalid JSON body'}), status=400,
                            content_type='application/json')

        # Create audit log record
        payload_str = json.dumps(payload, indent=2)
        summary = f"{server.provider.upper()} event '{event_type}'"
        log = request.env['odoo_devops_bridge.sync.log'].sudo().create({
            'server_id': server.id,
            'direction': 'inbound',
            'event_type': event_type,
            'status': 'pending',
            'payload_preview': summary[:100],
            'payload_full': payload_str,
        })

        # Process the event
        result = {}
        try:
            if server.provider == 'github':
                result = OdooDevOpsBridgeSyncManager.process_github_event(request.env, server,
                                                                          event_type, payload)
            elif server.provider == 'gitlab':
                result = OdooDevOpsBridgeSyncManager.process_gitlab_event(request.env, server,
                                                                          event_type, payload)
            elif server.provider == 'youtrack':
                result = OdooDevOpsBridgeSyncManager.process_youtrack_event(request.env, server,
                                                                            payload)

            log_status = 'success' if result.get('status') == 'success' else (
                'skipped' if result.get('status') == 'skipped' else 'success')
            log.sudo().write({
                'status': log_status,
                'response_preview': json.dumps(result),
            })
        except Exception as e:
            _logger.exception("Error processing webhook for server '%s' : %s", server.name, str(e))
            log.sudo().write({
                'status': 'failed',
                'error_message': str(e),
            })
            return Response(json.dumps({'status': 'error', 'details': str(e)}), status=500,
                            content_type='application/json')

        return Response(json.dumps({'status': 'ok', 'result': result}), status=200,
                        content_type='application/json')
