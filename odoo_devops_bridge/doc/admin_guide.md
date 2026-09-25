# Administrator Guide

This guide is for anyone in the **DevOps Bridge / Administrator** group who is
responsible for registering servers, generating webhook secrets, and
configuring bot accounts.

## 1. Prerequisites

- You are a member of **DevOps Bridge → Administrator** (members of
  `base.group_system` are added automatically on install).
- Odoo's `web.base.url` system parameter is set to a URL reachable from the
  public internet (or from your GitHub Enterprise / GitLab / YouTrack
  instance) so that webhooks can reach Odoo. For local testing, use a tunnel
  such as `ngrok` and override it via **Settings → General Settings → DevOps
  Bridge → Custom Webhook Base URL**.

## 2. Registering a Server

1. Go to **DevOps Bridge → Configuration → DevOps Servers → New**.
2. Fill in:
    - **Server Name** - a human-readable label, e.g. "GitHub Production" or
      "GitLab Internal CE".
    - **Provider** - GitHub, GitLab, or JetBrains YouTrack.
    - **Deployment Type** - Cloud/SaaS or Self-Hosted/On-Premise. Changing this
      auto-fills a sensible default **API / Server URL**.
    - **API / Server URL**:
      | Provider | SaaS default | Self-Hosted example |
      |---|---|---|
      | GitHub | `https://api.github.com` | `https://git.corp.com` (the client appends `/api/v3`
      automatically) |
      | GitLab | `https://gitlab.com` | `https://gitlab.internal` (the client appends `/api/v4`
      automatically) |
      | YouTrack | `https://your-company.youtrack.cloud` | `https://youtrack.internal` (the client
      appends `/api` automatically) |
    - **Sync Direction** - Two-Way (default), Import Only, or Export Only.
3. Save the record. A **Webhook Endpoint Identifier** and **Webhook Secret
   Token** are generated automatically - you'll use these in
   [`webhook_setup.md`](webhook_setup.md).

## 3. Configuring a Bot / Automation Account

Background sync (webhook ingestion when the acting external user has no
linked Odoo account, and the fallback cron poller) needs a service account:

1. On the server form, open the **User Accounts & Bot Credentials** tab.
2. Add a new line, set **Account Type** to *System Bot / Service Account*,
   and paste a token generated from a dedicated service/bot user on the
   external platform (recommended over reusing a real person's token).
3. Click **Verify** to confirm the token authenticates correctly. The **External Username /
   Handle** field is auto-populated on success.
4. Back on the server form, set **Default Bot / Automation Account** to this
   record.

> **Tip:** Create the bot account *before* testing the connection on the
> server itself. `Test Connection` will use your own personal token if you
> have one, or fall back to the default bot account otherwise.

## 4. Testing the Connection

Click **Test Connection** on the server form. On success the **Connection
Status** badge turns green and **Last Tested** is updated. On failure, the **Connection Error
Details** panel shows the raw error returned by the
provider (invalid token, wrong base URL, network/firewall issue, etc.).

## 5. Discovering & Mapping Repositories

Click **Discover Repositories** (visible once the server is Connected). This:

- Fetches every repository/project the acting account can see.
- Creates (or matches by name) a corresponding `project.project` in Odoo.
- Creates a `odoo_devops_bridge.repository` binding record for each one.

You can also add bindings manually under **DevOps Bridge → Operations →
Repositories & Trackers**, which is useful if you want to map a repository to
an *existing* Odoo project rather than auto-creating a new one, or if you only
want to sync a subset of repositories.

For each repository binding, configure:

- **Open Stage / Closed Stage** - which Odoo Kanban stage a task should move
  to when the remote issue/PR is opened or closed.
- **Sync toggles** - Issues, Pull Requests, Comments, Milestones can each be
  enabled/disabled independently per repository.

## 6. Registering the Webhook

See [`webhook_setup.md`](webhook_setup.md) for the exact steps per provider.
In short: copy the **Webhook Target URL** and **Secret Token** from the
server's **Webhook Endpoint & Security** tab into the corresponding settings
page on GitHub/GitLab/YouTrack.

## 7. Fallback Polling (Optional)

A scheduled action, **DevOps Bridge: Fallback Polling Synchronization**, is
installed disabled by default (hourly). Enable it under **Settings →
Technical → Scheduled Actions** if you want Odoo to periodically re-pull open
issues/PRs/milestones as a safety net in case a webhook delivery is missed.
A second scheduled action, **DevOps Bridge: Cleanup Expired Sync Logs**, runs
daily and is enabled by default; adjust retention under **Settings → General
Settings → DevOps Bridge → Sync Log Retention (Days)**.

## 8. Multi-Company

`odoo_devops_bridge.server` is company-scoped via the standard `company_id` field and an
`ir.rule`. Set the company on each server if you operate more than one
company in this database; leave it empty to make a server visible to all
companies.

## 9. Troubleshooting

| Symptom                                          | Likely Cause                                                | Fix                                                                                                                                                                                                    |
|--------------------------------------------------|-------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Webhook returns 401                              | Secret mismatch, or header name typo'd on the provider side | Regenerate the secret with **Regenerate Webhook Secret** and re-paste it on the provider                                                                                                               |
| Webhook returns 404                              | Wrong URL, or server was archived                           | Confirm **Active** is checked and the URL matches exactly, including the UUID segment                                                                                                                  |
| Tasks not syncing outbound                       | User has no personal token and no bot account is configured | Add a personal `odoo_devops_bridge.account`, or configure a **Default Bot Account** on the server                                                                                                      |
| Duplicate comments appear                        | A comment was manually re-posted after being synced         | This should not happen automatically; the loop-prevention guard checks `devops_synced` / `devops_external_id` before creating duplicates. Check `odoo_devops_bridge.sync.log` for the underlying event |
| GitLab/GitHub Enterprise self-signed cert issues | Corporate CA not trusted by the Odoo host                   | Install your corporate CA certificate in the Odoo server's system trust store                                                                                                                          |
