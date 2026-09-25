# Part of Odoo DevOps Bridge. See LICENSE file for full copyright and licensing details.

import logging
from odoo import models, fields, api

from ..services.odoo_devops_bridge_sync_manager import OdooDevOpsBridgeSyncManager

_logger = logging.getLogger(__name__)


class MailMessage(models.Model):
    _inherit = 'mail.message'

    devops_synced = fields.Boolean(
        string='DevOps Synced',
        default=False,
        copy=False,
        help='Flag to prevent infinite ping-pong synchronization loops.'
    )
    devops_external_id = fields.Char(
        string='DevOps Comment ID',
        copy=False,
        index=True
    )

    @api.model_create_multi
    def create(self, vals_list):
        messages = super().create(vals_list)
        if not self.env.context.get('syncing_from_devops'):
            for msg in messages:
                if msg.model in ('project.task',
                                 'odoo_devops_bridge.pull.request') and msg.message_type == 'comment' and not msg.devops_synced:
                    OdooDevOpsBridgeSyncManager.sync_comment_outbound(msg)
        return messages
