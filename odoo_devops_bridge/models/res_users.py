#  Part of Odoo Devops Bridge. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api


class ResUsers(models.Model):
    _inherit = 'res.users'

    devops_account_ids = fields.One2many(
        'odoo_devops_bridge.account',
        'user_id',
        string='DevOps Personal Accounts',
        domain=[('account_type', '=', 'personal')]
    )
    devops_account_count = fields.Integer(
        string='DevOps Accounts Count',
        compute='_compute_devops_account_count'
    )

    def _compute_devops_account_count(self):
        for user in self:
            user.devops_account_count = len(user.devops_account_ids)
