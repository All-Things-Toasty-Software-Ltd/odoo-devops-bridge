# Part of Odoo DevOps Bridge. See LICENSE file for full copyright and licensing details.

import json
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

from ..services.odoo_devops_bridge_sync_manager import OdooDevOpsBridgeSyncManager

_logger = logging.getLogger(__name__)


class OdooDevOpsBridgeSyncLog(models.Model):
    _name = 'odoo_devops_bridge.sync.log'
    _description = 'DevOps Synchronization Audit Log'
    _order = 'id desc'

    name = fields.Char(string='Log Reference', required=True, copy=False, readonly=True,
                       default=lambda self: _('New'))
    server_id = fields.Many2one('odoo_devops_bridge.server', string='DevOps Server', required=True,
                                ondelete='cascade')
    provider = fields.Selection(related='server_id.provider', store=True, readonly=True)

    direction = fields.Selection([
        ('inbound', 'Inbound (DevOps -> Odoo)'),
        ('outbound', 'Outbound (Odoo -> DevOps)'),
    ], string='Direction', required=True, default='inbound')

    event_type = fields.Char(string='Event / Action', required=True)

    status = fields.Selection([
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('skipped', 'Skipped'),
        ('failed', 'Failed'),
    ], string='Execution Status', default='pending', required=True, index=True)

    payload_preview = fields.Char(string='Payload Summary')
    payload_full = fields.Text(string='Complete Payload (JSON)')
    response_preview = fields.Text(string='Response / Outcome')
    error_message = fields.Text(string='Error Details')

    created_at = fields.Datetime(string='Timestamp', default=fields.Datetime.now, readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'odoo_devops_bridge.sync.log') or _('New')
        return super().create(vals_list)

    def action_retry(self):
        """Replay an inbound webhook payload."""
        self.ensure_one()
        if not self.payload_full:
            raise UserError(_("No full payload recorded to replay."))

        try:
            payload = json.loads(self.payload_full)
        except Exception as e:
            raise UserError(_("Payload JSON parsing failed: %s") % str(e))

        server = self.server_id
        res = None
        try:
            if server.provider == 'github':
                res = OdooDevOpsBridgeSyncManager.process_github_event(self.env, server,
                                                                       self.event_type, payload)
            elif server.provider == 'gitlab':
                res = OdooDevOpsBridgeSyncManager.process_gitlab_event(self.env, server,
                                                                       self.event_type, payload)
            elif server.provider == 'youtrack':
                res = OdooDevOpsBridgeSyncManager.process_youtrack_event(self.env, server, payload)

            self.write({
                'status': 'success' if res and res.get('status') == 'success' else 'skipped',
                'response_preview': str(res),
                'error_message': False,
            })
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Replay Succeeded'),
                    'message': _("Sync event successfully processed."),
                    'type': 'success',
                }
            }
        except Exception as e:
            self.write({
                'status': 'failed',
                'error_message': str(e),
            })
            raise UserError(_("Replay failed: %s") % str(e))

    @api.model
    def _cron_cleanup_logs(self):
        """Clean up logs older than configured retention days."""
        from datetime import timedelta
        days = self.env['ir.config_parameter'].sudo().get_int(
            'odoo_devops_bridge.log_retention_days',
            30)
        limit_date = fields.Datetime.now() - timedelta(days=days)
        old_logs = self.search([('created_at', '<', limit_date)])
        if old_logs:
            _logger.info("DevOps Bridge: Cleaning up %s expired sync logs.", len(old_logs))
            old_logs.unlink()
