# Part of Odoo Devops Bridge. See LICENSE file for full copyright and licensing details.

from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    devops_webhook_base_url = fields.Char(
        string='Custom Webhook Base URL',
        config_parameter='odoo_devops_bridge.webhook_base_url',
        help='Override base URL if Odoo is behind a reverse proxy or ngrok tunnel for webhook testing.'
    )
    devops_auto_retry_failed_sync = fields.Boolean(
        string='Auto-Retry Failed Syncs',
        config_parameter='odoo_devops_bridge.auto_retry',
        default=True,
        help='Automatically retry failed inbound or outbound sync events via scheduled cron job.'
    )
    devops_log_retention_days = fields.Integer(
        string='Sync Log Retention (Days)',
        config_parameter='odoo_devops_bridge.log_retention_days',
        default=30,
        help='Number of days to keep synchronization audit logs before automatic cleanup.'
    )
