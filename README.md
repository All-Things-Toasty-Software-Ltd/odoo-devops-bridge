# DevOps Project Bridge for Odoo

A bidirectional sync module to connect Odoo with various DevOps tools such as GitHub, GitLab, and
JetBrains YouTrack.

## About

This module bridges issue tracking and project management across different platforms.

## Features

- **Bidirectional Sync** - Tasks, Pull/Merge Requests, comments, and milestones flow both ways,
  with a recursion guard that prevents update loops.
- **Admin-Defined Servers, User-Owned Credentials** — DevOps Administrators register server
  endpoints once; every internal Odoo user links their own Personal Access Token so their actions
  are attributed to *them*, not a shared bot.
- **Bot / Service Account Fallback** - Configure a default automation account per server to handle
  webhook ingestion and background sync when no personal token is available.
- **Real-Time Webhooks + Fallback Polling** - A single universal webhook endpoint authenticates and
  routes GitHub, GitLab, and YouTrack payloads; an optional hourly cron job fills the gaps if a
  webhook is missed.
- **Pull Request / Merge Request Tracking** - Dedicated Kanban, list, and form views with branch,
  review, and diff-stat information, auto-linked to Odoo tasks via `#123` / `closes PROJ-456` style
  references.
- **Full Audit Trail** - Every inbound and outbound event is logged with payload, response, and
  one-click replay for troubleshooting.
- **Self-Hosted Friendly** - Works out of the box with GitHub Enterprise Server, GitLab CE/EE, and
  YouTrack Standalone Server, in addition to the SaaS/Cloud offerings.

## Requirements

The module depends only on `base`, `web`, `project`, and `mail`

## Installation

1. Copy (or clone) the `odoo_devops_bridge` folder into your Odoo `addons` path.
2. Restart the Odoo service and update the Apps List (**Settings → Apps → Update Apps List**).
3. Search for **"DevOps Project Bridge"** and click **Install**.

## Usage

1. **Admin:** Go to **DevOps Bridge → Configuration → DevOps Servers** and create a server record
   (choose provider, deployment type, and base URL).
2. **Admin:** Click **Test Connection** once a bot account or your own token is attached, then
   **Discover Repositories** to auto-map remote repos/projects to Odoo projects.
3. **Admin:** Open the **Webhook Endpoint & Security** tab, copy the **Webhook Target URL** and
   **Secret Token**, and register them on GitHub/GitLab/YouTrack.
4. **Every user:** Go to your **Profile → DevOps Access Tokens** and add your own Personal Access
   Token per server so actions you take in Odoo are attributed to you.
5. Create or update a task in a linked project. It will sync out automatically. Comments posted on
   the task chatter sync to the remote issue thread, and vice versa.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution and development guidelines.

## Project status

**Status:** In development

Planned supported platforms:

| Provider | Cloud / SaaS       | Self-Hosted                | Auth Method                                       |
|----------|--------------------|----------------------------|---------------------------------------------------|
| GitHub   | github.com         | GitHub Enterprise Server   | Classic & Fine-Grained PAT (Bearer)               |
| GitLab   | gitlab.com         | GitLab CE/EE Self-Hosted   | Personal / Project Access Token (`PRIVATE-TOKEN`) |
| YouTrack | `*.youtrack.cloud` | YouTrack Standalone Server | Permanent Bearer Token                            |

## License

This project is licensed under the terms described in [LICENSE](LICENSE).

## Security

For information about reporting security vulnerabilities, see [SECURITY.md](SECURITY.md).

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for a history of notable changes.

---

Made by **Toasty Software**
