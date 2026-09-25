# Part of Odoo DevOps Bridge. See LICENSE file for full copyright and licensing details.

{
    'name': "DevOps Project Bridge",
    'category': 'Toasty Software',
    'sequence': 200,
    'website': 'https://www.toastysoftware.co.uk',
    'summary': "Bidirectional sync with DevOps providers to mange issues, PRs, Merges, Teams, Comments, and more.",
    'version': '0.2.0',
    'depends': ['base', 'web', 'project', 'mail'],

    'currency': 'EUR',
    'price': 0.00,
    'description': """
DevOps Project Bridge for Odoo
==============================
Seamlessly connects Odoo Project Management with GitHub, GitLab, and JetBrains YouTrack.
Works with both Cloud/SaaS versions and Self-Hosted / On-Premise instances.

Key Capabilities:
-----------------
* **Admin-Defined Servers**: Centralized configuration of GitHub, GitLab, and YouTrack endpoints.
* **Internal User-Level Auth**: Each internal Odoo user links their own personal credentials (PATs),
  ensuring actions are attributed to the individual developer.
* **Automated Bot Accounts**: Configurable fallback bot/service accounts handle background sync,
  webhooks, and automated updates.
* **2-Way Synchronization**:
  - Tasks / Issues (create, update, stage transition, assignees, tags, priority)
  - Pull Requests / Merge Requests (branches, commits, merge status, reviews, diff links)
  - Comments / Discussions (Odoo chatter synced with external issue & PR comment threads)
  - Milestones & Releases (target dates, progress, status)
  - Teams & Organizations (mapping repos and projects to teams)
* **Real-time Webhook Ingestion**: Universal webhook controller with HMAC / Secret token verification.
* **Audit & Telemetry**: Full sync log tracking with error inspection and one-click replay.

Supported Platforms:
--------------------
* **GitHub**: GitHub.com and GitHub Enterprise Server.
* **GitLab**: GitLab.com and GitLab CE/EE Self-Hosted instances.
* **YouTrack**: JetBrains YouTrack Cloud and YouTrack Standalone Server.
    """,

    # always loaded
    'data': [
        'security/odoo_devops_bridge_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/ir_cron_data.xml',
        'views/odoo_devops_bridge_server_views.xml',
        'views/odoo_devops_bridge_account_views.xml',
        'views/odoo_devops_bridge_team_views.xml',
        'views/odoo_devops_bridge_repository_views.xml',
        'views/odoo_devops_bridge_pull_request_views.xml',
        'views/odoo_devops_bridge_sync_log_views.xml',
        'views/project_project_views.xml',
        'views/project_task_views.xml',
        'views/project_milestone_views.xml',
        'views/res_users_views.xml',
        'views/res_config_settings_views.xml',
        'wizards/odoo_devops_bridge_sync_wizard_views.xml',
        'views/odoo_devops_bridge_menu_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'odoo_devops_bridge/static/src/scss/odoo_devops_bridge.scss',
        ],
    },
    'images': ['static/description/banner.png'],
    'author': 'All Things Toasty Software Ltd',
    'maintainer': 'All Things Toasty Software Ltd',
    'license': 'LGPL-3',
    'installable': True,
    'application': True,
    'auto_install': False,
}
