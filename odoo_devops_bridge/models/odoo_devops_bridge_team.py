# Part of Odoo DevOps Bridge. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api, _


class OdooDevOpsBridgeTeam(models.Model):
    _name = 'odoo_devops_bridge.team'
    _description = 'DevOps Organization / Group / Team'
    _order = 'name asc'

    name = fields.Char(string='Team / Org Name', required=True)
    server_id = fields.Many2one('odoo_devops_bridge.server', string='DevOps Server', required=True,
                                ondelete='cascade')
    provider = fields.Selection(related='server_id.provider', store=True, readonly=True)

    external_id = fields.Char(string='External ID / Org Slug')
    slug = fields.Char(string='Slug / Path')
    description = fields.Text(string='Description')
    web_url = fields.Char(string='Web URL')

    member_ids = fields.Many2many(
        'res.users',
        'devops_team_res_users_rel',
        'team_id',
        'user_id',
        string='Assigned Odoo Members'
    )
    repository_ids = fields.One2many('odoo_devops_bridge.repository', 'team_id',
                                     string='Connected Repositories')
