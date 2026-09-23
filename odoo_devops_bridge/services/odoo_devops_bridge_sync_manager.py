# Part of Odoo DevOps Bridge. See LICENSE file for full copyright and licensing details.

import html
import logging
import re
from markupsafe import Markup
from odoo import fields, _
from odoo.exceptions import UserError
from odoo.tools.mail import html2plaintext

from .odoo_devops_bridge_base_client import OdooDevOpsBridgeAuthError, OdooDevOpsBridgeAPIError
from .odoo_devops_bridge_github_client import OdooDevOpsBridgeGitHubClient
from .odoo_devops_bridge_gitlab_client import OdooDevOpsBridgeGitLabClient
from .odoo_devops_bridge_youtrack_client import OdooDevOpsBridgeYouTrackClient

_logger = logging.getLogger(__name__)


class OdooDevOpsBridgeSyncManager:
    """
    Core synchronization for DevOps Project Bridge.
    Manages client resolution (Internal User Token vs Bot Account fallback),
    bidirectional mapping, inbound webhook ingestion, and recursion loop guards.
    """

    @classmethod
    def _markdown_to_html(cls, text):
        """Convert markdown formatted text from external providers into clean styled HTML."""
        if not text:
            return ''
        escaped = html.escape(text.strip())
        lines = escaped.split('\n')
        out_lines = []
        in_quote = False
        quote_lines = []
        in_code_block = False
        code_lines = []

        for line in lines:
            stripped = line.strip()
            if stripped.startswith('```'):
                if in_code_block:
                    in_code_block = False
                    out_lines.append(
                        f"<pre class='bg-light p-2 rounded'><code>{chr(10).join(code_lines)}</code></pre>")
                    code_lines = []
                else:
                    if in_quote:
                        in_quote = False
                        out_lines.append(
                            f"<blockquote class='border-start border-3 ps-2 text-muted my-1'>{'<br/>'.join(quote_lines)}</blockquote>")
                        quote_lines = []
                    in_code_block = True
                continue

            if in_code_block:
                code_lines.append(line)
                continue

            if stripped.startswith('&gt;'):
                in_quote = True
                content = re.sub(r'^&gt;\s?', '', stripped)
                quote_lines.append(content)
                continue
            else:
                if in_quote:
                    in_quote = False
                    out_lines.append(
                        f"<blockquote class='border-start border-3 ps-2 text-muted my-1'>{'<br/>'.join(quote_lines)}</blockquote>")
                    quote_lines = []

            if not stripped:
                out_lines.append('<br/>')
                continue

            # Inline formatting
            line = re.sub(r'`([^`]+)`', r'<code class="bg-light px-1 rounded">\1</code>', line)
            line = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
            line = re.sub(r'__(.+?)__', r'<strong>\1</strong>', line)
            line = re.sub(r'\*([^\*]+)\*', r'<em>\1</em>', line)
            line = re.sub(r'_([^_]+)_', r'<em>\1</em>', line)
            line = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank">\1</a>', line)
            line = re.sub(r'(?<!\w)@([a-zA-Z0-9_\-]+)',
                          r'<strong class="text-primary">@\1</strong>', line)

            out_lines.append(line)

        if in_code_block:
            out_lines.append(
                f"<pre class='bg-light p-2 rounded'><code>{chr(10).join(code_lines)}</code></pre>")
        if in_quote:
            out_lines.append(
                f"<blockquote class='border-start border-3 ps-2 text-muted my-1'>{'<br/>'.join(quote_lines)}</blockquote>")

        rendered = '<br/>'.join(out_lines)
        return rendered.replace('<br/><blockquote', '<blockquote').replace('</blockquote><br/>',
                                                                           '</blockquote>').replace(
            '<br/><pre', '<pre').replace('</pre><br/>', '</pre>')

    @classmethod
    def _format_comment_html(cls, provider, author_login, comment_body):
        """Format a synced remote comment into clean Odoo chatter HTML with provider context."""
        body_html = cls._markdown_to_html(comment_body)
        provider_name = {'github': 'GitHub', 'gitlab': 'GitLab', 'youtrack': 'YouTrack'}.get(
            provider, 'DevOps')
        icon = 'github' if provider == 'github' else ('gitlab' if provider == 'gitlab' else 'tasks')
        return Markup(
            f"<div class='o_devops_comment'>"
            f"<div class='d-flex align-items-center text-muted small mb-1'>"
            f"<i class='fa fa-{icon} me-1'></i>"
            f"<span><strong>@{author_login}</strong> via {provider_name}:</span>"
            f"</div>"
            f"<div class='o_devops_comment_body ps-1'>{body_html}</div>"
            f"</div>"
        )

    @classmethod
    def _infer_issue_type_and_sync_tags(cls, env, raw_labels=None, type_str=None):
        """
        Extract tags and classify devops_issue_type ('task', 'bug', 'feature', 'recommendation', 'documentation', 'question').
        Finds or creates project.tags for each label.
        """
        label_names = []
        if raw_labels:
            for l in raw_labels:
                if isinstance(l, dict):
                    label_names.append(l.get('name', '').strip())
                elif isinstance(l, str):
                    label_names.append(l.strip())

        tag_ids = []
        for name in label_names:
            if not name:
                continue
            tag = env['project.tags'].sudo().search([('name', '=ilike', name)], limit=1)
            if not tag:
                tag = env['project.tags'].sudo().create({'name': name})
            tag_ids.append(tag.id)

        inferred_type = 'task'
        combined = ' '.join(label_names + ([type_str] if type_str else [])).lower()
        if any(k in combined for k in ('bug', 'defect', 'error', 'fix', 'failure', 'crash')):
            inferred_type = 'bug'
        elif any(k in combined for k in ('enhancement', 'feature', 'feat', 'new-feature', 'story')):
            inferred_type = 'feature'
        elif any(k in combined for k in
                 ('recommendation', 'suggestion', 'improvement', 'proposal', 'idea', 'refactor')):
            inferred_type = 'recommendation'
        elif any(k in combined for k in ('doc', 'documentation', 'docs')):
            inferred_type = 'documentation'
        elif any(k in combined for k in ('question', 'support', 'help', 'inquiry')):
            inferred_type = 'question'

        return inferred_type, tag_ids

    @classmethod
    def _parse_and_link_dependencies(cls, env, task, repo, text):
        """
        Parse dependency and blocking directives from issue descriptions/comments
        (e.g., 'Depends on #12', 'Blocked by #15', 'Blocks #18') and update
        depend_on_ids and dependent_ids on the task.
        """
        if not text or not repo or not task:
            return

        if repo.project_id and not repo.project_id.allow_task_dependencies:
            repo.project_id.sudo().write({'allow_task_dependencies': True})

        depends_matches = re.findall(
            r'(?i)(?:depends\s+on|blocked\s+by|requires|needed\s+by|needs)\s+#(\d+)', text)
        blocks_matches = re.findall(r'(?i)(?:blocks|blocking)\s+#(\d+)', text)

        vals = {}
        if depends_matches:
            depend_tasks = env['project.task'].sudo().search([
                ('devops_repo_id', '=', repo.id),
                ('devops_issue_number', 'in', depends_matches),
                ('id', '!=', task.id),
            ])
            if depend_tasks:
                existing_depends = set(task.depend_on_ids.ids)
                to_add = [t.id for t in depend_tasks if t.id not in existing_depends]
                if to_add:
                    vals['depend_on_ids'] = [(4, tid) for tid in to_add]

        if blocks_matches:
            block_tasks = env['project.task'].sudo().search([
                ('devops_repo_id', '=', repo.id),
                ('devops_issue_number', 'in', blocks_matches),
                ('id', '!=', task.id),
            ])
            if block_tasks:
                existing_blocks = set(task.dependent_ids.ids)
                to_add = [t.id for t in block_tasks if t.id not in existing_blocks]
                if to_add:
                    vals['dependent_ids'] = [(4, tid) for tid in to_add]

        if vals:
            task.sudo().write(vals)

    @classmethod
    def get_client(cls, server, user=None):
        """
        Resolve the appropriate API client for a server.
        Priority:
        1. If user is provided, check for a personal odoo_devops_bridge.account linked to this server.
        2. Fallback to server's configured default bot account.
        """
        token = None
        account = None

        if user and user.id:
            account = server.env['odoo_devops_bridge.account'].sudo().search([
                ('server_id', '=', server.id),
                ('user_id', '=', user.id),
                ('account_type', '=', 'personal'),
                ('state', '!=', 'invalid'),
                ('active', '=', True),
            ], limit=1)

        if account and account.token:
            token = account.token
        elif server.default_bot_account_id and server.default_bot_account_id.token:
            token = server.default_bot_account_id.token
            account = server.default_bot_account_id

        if not token:
            raise OdooDevOpsBridgeAuthError(
                f"No valid personal token for user '{user.name if user else 'Anonymous'}' "
                f"or default Bot account configured on server '{server.name}'."
            )

        provider = server.provider
        if provider == 'github':
            return OdooDevOpsBridgeGitHubClient(base_url=server.base_url, token=token)
        elif provider == 'gitlab':
            return OdooDevOpsBridgeGitLabClient(base_url=server.base_url, token=token)
        elif provider == 'youtrack':
            return OdooDevOpsBridgeYouTrackClient(base_url=server.base_url, token=token)
        else:
            raise ValueError(f"Unsupported provider: {provider}")

    @classmethod
    def resolve_odoo_user(cls, env, server, external_username):
        """
        Map an external username (GitHub handle, GitLab username, YouTrack login)
        to an internal Odoo res.users record.
        """
        if not external_username:
            return False
        account = env['odoo_devops_bridge.account'].sudo().search([
            ('server_id', '=', server.id),
            ('external_username', '=ilike', external_username.strip()),
            ('active', '=', True),
        ], limit=1)
        return account.user_id if account and account.user_id else False

    @classmethod
    def resolve_remote_username(cls, env, server, user):
        """Map an internal Odoo res.users record to an external username."""
        if not user or not server:
            return False
        account = env['odoo_devops_bridge.account'].sudo().search([
            ('server_id', '=', server.id),
            ('user_id', '=', user.id),
            ('account_type', '=', 'personal'),
            ('active', '=', True),
        ], limit=1)
        if account and account.external_username:
            return account.external_username.strip()
        return user.login

    @classmethod
    def process_github_event(cls, env, server, event_type, payload):
        """Handle incoming GitHub webhook events."""
        ctx = dict(env.context, syncing_from_devops=True)
        env = env(context=ctx)

        repo_info = payload.get('repository', {})
        repo_full_name = repo_info.get('full_name')

        repo = env['odoo_devops_bridge.repository'].sudo().search([
            ('server_id', '=', server.id),
            ('external_slug', '=ilike', repo_full_name),
        ], limit=1)

        if not repo:
            _logger.info("GitHub event '%s' ignored: repository '%s' not mapped in Odoo.",
                         event_type, repo_full_name)
            return {'status': 'skipped', 'reason': f'Repo {repo_full_name} not mapped'}

        if event_type == 'issues':
            if 'pull_request' in payload.get('issue', {}):
                return cls._process_github_pull_request(env, server, repo, payload)
            return cls._process_github_issue(env, server, repo, payload)
        elif event_type == 'issue_comment':
            if 'pull_request' in payload.get('issue', {}):
                return cls._process_github_pr_comment(env, server, repo, payload)
            return cls._process_github_comment(env, server, repo, payload)
        elif event_type in ('pull_request_review_comment',):
            return cls._process_github_pr_comment(env, server, repo, payload)
        elif event_type in ('pull_request_review',):
            return cls._process_github_pr_review(env, server, repo, payload)
        elif event_type == 'pull_request':
            return cls._process_github_pull_request(env, server, repo, payload)
        elif event_type == 'milestone':
            return cls._process_github_milestone(env, server, repo, payload)

        return {'status': 'ignored', 'event': event_type}

    @classmethod
    def _process_github_issue(cls, env, server, repo, payload):
        action = payload.get('action')
        issue_data = payload.get('issue', {})
        issue_id = str(issue_data.get('id'))
        issue_number = issue_data.get('number')
        title = issue_data.get('title')
        body = issue_data.get('body') or ''
        state = issue_data.get('state')  # 'open' or 'closed'
        assignee_data = issue_data.get('assignee') or {}
        assignee_login = assignee_data.get('login')
        html_url = issue_data.get('html_url')

        task = env['project.task'].sudo().search([
            ('devops_repo_id', '=', repo.id),
            ('devops_external_id', '=', issue_id),
        ], limit=1)

        assigned_user = cls.resolve_odoo_user(env, server, assignee_login)
        user_ids = [(6, 0, [assigned_user.id])] if assigned_user else []

        raw_labels = issue_data.get('labels') or []
        issue_type, tag_ids = cls._infer_issue_type_and_sync_tags(env, raw_labels=raw_labels)

        vals = {
            'name': title,
            'description': body,
            'devops_server_id': server.id,
            'devops_repo_id': repo.id,
            'devops_external_id': issue_id,
            'devops_issue_number': str(issue_number),
            'devops_provider': 'github',
            'devops_web_url': html_url,
            'devops_sync_status': 'synced',
            'devops_issue_type': issue_type,
        }
        if user_ids:
            vals['user_ids'] = user_ids
        if tag_ids:
            vals['tag_ids'] = [(6, 0, tag_ids)]

        # Map milestone if present
        milestone_data = issue_data.get('milestone')
        if milestone_data and repo.project_id:
            m_ext_id = str(milestone_data.get('id'))
            milestone = env['project.milestone'].sudo().search([
                ('project_id', '=', repo.project_id.id),
                ('devops_external_id', '=', m_ext_id),
            ], limit=1)
            if milestone:
                vals['milestone_id'] = milestone.id

        if not task:
            vals['project_id'] = repo.project_id.id
            task = env['project.task'].sudo().create(vals)
            _logger.info("Created Odoo task '%s' (ID %s) from GitHub issue #%s", task.name, task.id,
                         issue_number)
        else:
            task.write(vals)
            _logger.info("Updated Odoo task '%s' (ID %s) from GitHub issue #%s", task.name, task.id,
                         issue_number)

        # Parse issue relationships and dependencies
        cls._parse_and_link_dependencies(env, task, repo, body)

        # Handle closed state
        if state == 'closed' and repo.closed_stage_id:
            task.write({'stage_id': repo.closed_stage_id.id})
        elif state == 'open' and repo.open_stage_id and task.stage_id == repo.closed_stage_id:
            task.write({'stage_id': repo.open_stage_id.id})

        return {'status': 'success', 'task_id': task.id, 'action': action}

    @classmethod
    def _process_github_comment(cls, env, server, repo, payload):
        issue_data = payload.get('issue', {})
        comment_data = payload.get('comment', {})
        issue_id = str(issue_data.get('id'))
        comment_id = str(comment_data.get('id'))
        comment_body = comment_data.get('body') or ''
        author_login = comment_data.get('user', {}).get('login', 'GitHub')

        task = env['project.task'].sudo().search([
            ('devops_repo_id', '=', repo.id),
            ('devops_external_id', '=', issue_id),
        ], limit=1)
        if not task:
            return {'status': 'skipped', 'reason': 'Task not found for comment'}

        # Check if already synced
        existing = env['mail.message'].sudo().search([
            ('model', '=', 'project.task'),
            ('res_id', '=', task.id),
            ('devops_external_id', '=', comment_id),
        ], limit=1)
        if existing:
            return {'status': 'already_synced', 'message_id': existing.id}

        # Anti-echo safeguard: check if this matches an outbound message that was just posted
        recent_msg = env['mail.message'].sudo().search([
            ('model', '=', 'project.task'),
            ('res_id', '=', task.id),
            ('devops_synced', '=', True),
            ('devops_external_id', '=', False),
        ], order='id desc', limit=1)
        if recent_msg and html2plaintext(recent_msg.body or '').strip() == comment_body.strip():
            recent_msg.sudo().write({'devops_external_id': comment_id})
            return {'status': 'already_synced', 'message_id': recent_msg.id}

        author_user = cls.resolve_odoo_user(env, server, author_login)
        author_partner_id = author_user.partner_id.id if author_user else env.ref(
            'base.partner_admin').id

        body_html = cls._format_comment_html('github', author_login, comment_body)
        msg = task.with_context(syncing_from_devops=True).message_post(
            body=body_html,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
            author_id=author_partner_id,
        )
        msg.sudo().write({'devops_external_id': comment_id, 'devops_synced': True})

        # Also parse dependencies mentioned in comments (e.g., 'Depends on #12')
        cls._parse_and_link_dependencies(env, task, repo, comment_body)

        return {'status': 'success', 'message_id': msg.id}

    @classmethod
    def _process_github_pr_comment(cls, env, server, repo, payload):
        issue_data = payload.get('issue') or payload.get('pull_request') or {}
        comment_data = payload.get('comment') or {}
        pr_number = str(
            issue_data.get('number') or payload.get('pull_request', {}).get('number') or '')
        comment_id = str(comment_data.get('id') or '')
        comment_body = comment_data.get('body') or ''
        author_login = comment_data.get('user', {}).get('login', 'GitHub')

        pr_record = env['odoo_devops_bridge.pull.request'].sudo().search([
            ('server_id', '=', server.id),
            ('repository_id', '=', repo.id),
            ('number', '=', pr_number),
        ], limit=1)
        if not pr_record:
            return {'status': 'skipped', 'reason': 'PR record not found for comment'}

        # Check if already synced
        existing = env['mail.message'].sudo().search([
            ('model', '=', 'odoo_devops_bridge.pull.request'),
            ('res_id', '=', pr_record.id),
            ('devops_external_id', '=', comment_id),
        ], limit=1)
        if existing:
            return {'status': 'already_synced', 'message_id': existing.id}

        # Anti-echo safeguard
        recent_msg = env['mail.message'].sudo().search([
            ('model', '=', 'odoo_devops_bridge.pull.request'),
            ('res_id', '=', pr_record.id),
            ('devops_synced', '=', True),
            ('devops_external_id', '=', False),
        ], order='id desc', limit=1)
        if recent_msg and html2plaintext(recent_msg.body or '').strip() == comment_body.strip():
            recent_msg.sudo().write({'devops_external_id': comment_id})
            return {'status': 'already_synced', 'message_id': recent_msg.id}

        author_user = cls.resolve_odoo_user(env, server, author_login)
        author_partner_id = author_user.partner_id.id if author_user else env.ref(
            'base.partner_admin').id

        body_html = cls._format_comment_html('github', author_login, comment_body)
        msg = pr_record.with_context(syncing_from_devops=True).message_post(
            body=body_html,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
            author_id=author_partner_id,
        )
        msg.sudo().write({'devops_external_id': comment_id, 'devops_synced': True})

        return {'status': 'success', 'message_id': msg.id}

    @classmethod
    def _process_github_pr_review(cls, env, server, repo, payload):
        pr_data = payload.get('pull_request', {})
        review_data = payload.get('review', {})
        pr_number = str(pr_data.get('number') or '')
        review_id = str(review_data.get('id') or '')
        review_state = (review_data.get('state') or 'COMMENTED').upper()
        review_body = review_data.get('body') or ''
        author_login = review_data.get('user', {}).get('login', 'GitHub')

        pr_record = env['odoo_devops_bridge.pull.request'].sudo().search([
            ('server_id', '=', server.id),
            ('repository_id', '=', repo.id),
            ('number', '=', pr_number),
        ], limit=1)
        if not pr_record:
            return {'status': 'skipped', 'reason': 'PR record not found for review'}

        status_map = {
            'APPROVED': 'approved',
            'CHANGES_REQUESTED': 'changes_requested',
            'COMMENTED': 'commented',
            'DISMISSED': 'pending',
        }
        new_status = status_map.get(review_state, 'pending')
        pr_record.sudo().write({'review_status': new_status})

        author_user = cls.resolve_odoo_user(env, server, author_login)
        if author_user and author_user.id not in pr_record.reviewer_ids.ids:
            pr_record.sudo().write({'reviewer_ids': [(4, author_user.id)]})

        # Post to chatter if there's review body or state notification
        existing = env['mail.message'].sudo().search([
            ('model', '=', 'odoo_devops_bridge.pull.request'),
            ('res_id', '=', pr_record.id),
            ('devops_external_id', '=', review_id),
        ], limit=1)
        if not existing:
            state_label = new_status.replace('_', ' ').capitalize()
            content = f"<strong>Review submitted ({state_label})</strong>"
            if review_body:
                content += f":<br/>{cls._markdown_to_html(review_body)}"
            body_html = Markup(
                f"<div class='o_devops_comment'>"
                f"<div class='d-flex align-items-center text-muted small mb-1'>"
                f"<i class='fa fa-github me-1'></i>"
                f"<span><strong>@{author_login}</strong> via GitHub:</span>"
                f"</div>"
                f"<div class='o_devops_comment_body ps-1'>{content}</div>"
                f"</div>"
            )
            author_partner_id = author_user.partner_id.id if author_user else env.ref(
                'base.partner_admin').id
            msg = pr_record.with_context(syncing_from_devops=True).message_post(
                body=body_html,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
                author_id=author_partner_id,
            )
            msg.sudo().write({'devops_external_id': review_id, 'devops_synced': True})

        return {'status': 'success', 'pr_id': pr_record.id, 'review_status': new_status}

    @classmethod
    def _process_github_pull_request(cls, env, server, repo, payload):
        action = payload.get('action')
        pr_data = payload.get('pull_request') or payload.get('issue') or {}
        pr_id = str(pr_data.get('id'))
        pr_number = pr_data.get('number')
        title = pr_data.get('title')
        body = pr_data.get('body') or ''
        state = pr_data.get('state')  # 'open' or 'closed'
        is_merged = pr_data.get('merged', False)
        merged_at = pr_data.get('merged_at')
        source_branch = pr_data.get('head', {}).get('ref', '') if isinstance(pr_data.get('head'),
                                                                             dict) else ''
        target_branch = pr_data.get('base', {}).get('ref', '') if isinstance(pr_data.get('base'),
                                                                             dict) else ''
        html_url = pr_data.get('html_url')
        author_login = pr_data.get('user', {}).get('login', '') if isinstance(pr_data.get('user'),
                                                                              dict) else ''
        merge_commit_sha = pr_data.get('merge_commit_sha')
        commits = pr_data.get('commits', 0)
        additions = pr_data.get('additions', 0)
        deletions = pr_data.get('deletions', 0)
        changed_files = pr_data.get('changed_files', 0)

        pr_record = env['odoo_devops_bridge.pull.request'].sudo().search([
            ('server_id', '=', server.id),
            ('repository_id', '=', repo.id),
            ('external_id', '=', pr_id),
        ], limit=1)
        if not pr_record and pr_number:
            pr_record = env['odoo_devops_bridge.pull.request'].sudo().search([
                ('server_id', '=', server.id),
                ('repository_id', '=', repo.id),
                ('number', '=', str(pr_number)),
            ], limit=1)

        # Detect linked task from branch or title/body
        task = False
        import re
        task_match = re.search(r'#(\d+)', f"{title} {source_branch}")
        if task_match:
            issue_num = task_match.group(1)
            task = env['project.task'].sudo().search([
                ('devops_repo_id', '=', repo.id),
                ('devops_issue_number', '=', issue_num),
            ], limit=1)

        pr_state = 'merged' if is_merged else ('closed' if state == 'closed' else 'open')

        # Map assignees
        assignees_data = pr_data.get('assignees') or []
        assignee_ids = []
        for a in assignees_data:
            login = a.get('login') if isinstance(a, dict) else str(a)
            u = cls.resolve_odoo_user(env, server, login)
            if u:
                assignee_ids.append(u.id)

        # Map requested reviewers
        reviewers_data = pr_data.get('requested_reviewers') or []
        reviewer_ids = []
        for r in reviewers_data:
            login = r.get('login') if isinstance(r, dict) else str(r)
            u = cls.resolve_odoo_user(env, server, login)
            if u:
                reviewer_ids.append(u.id)

        # Map labels / tags
        raw_labels = pr_data.get('labels') or []
        _, tag_ids = cls._infer_issue_type_and_sync_tags(env, raw_labels=raw_labels)

        vals = {
            'name': title,
            'server_id': server.id,
            'repository_id': repo.id,
            'project_id': repo.project_id.id if repo.project_id else False,
            'task_id': task.id if task else False,
            'external_id': pr_id,
            'number': str(pr_number),
            'source_branch': source_branch,
            'target_branch': target_branch,
            'state': pr_state,
            'is_merged': is_merged,
            'merged_at': merged_at,
            'merge_commit_sha': merge_commit_sha,
            'author_username': author_login,
            'web_url': html_url,
            'commits_count': commits,
            'additions': additions,
            'deletions': deletions,
            'changed_files': changed_files,
            'description': body,
        }
        if assignee_ids:
            vals['user_ids'] = [(6, 0, assignee_ids)]
        if reviewer_ids:
            vals['reviewer_ids'] = [(6, 0, reviewer_ids)]
        if tag_ids:
            vals['tag_ids'] = [(6, 0, tag_ids)]

        # Map milestone if present
        milestone_data = pr_data.get('milestone')
        if milestone_data and repo.project_id:
            m_ext_id = str(milestone_data.get('id'))
            milestone = env['project.milestone'].sudo().search([
                ('project_id', '=', repo.project_id.id),
                ('devops_external_id', '=', m_ext_id),
            ], limit=1)
            if milestone:
                vals['milestone_id'] = milestone.id

        if not pr_record:
            pr_record = env['odoo_devops_bridge.pull.request'].sudo().create(vals)
        else:
            pr_record.write(vals)

        return {'status': 'success', 'pr_id': pr_record.id, 'action': action}

    @classmethod
    def _process_github_milestone(cls, env, server, repo, payload):
        action = payload.get('action')
        m_data = payload.get('milestone', {})
        m_id = str(m_data.get('id'))
        title = m_data.get('title')
        due_on = m_data.get('due_on')
        state = m_data.get('state')  # 'open' or 'closed'

        if not repo.project_id:
            return {'status': 'skipped', 'reason': 'No project linked to repo'}

        milestone = env['project.milestone'].sudo().search([
            ('project_id', '=', repo.project_id.id),
            ('devops_external_id', '=', m_id),
        ], limit=1)

        vals = {
            'name': title,
            'project_id': repo.project_id.id,
            'devops_server_id': server.id,
            'devops_repo_id': repo.id,
            'devops_external_id': m_id,
            'devops_state': state,
        }
        if due_on:
            vals['deadline'] = due_on[:10]

        if not milestone:
            milestone = env['project.milestone'].sudo().create(vals)
        else:
            milestone.write(vals)

        return {'status': 'success', 'milestone_id': milestone.id, 'action': action}

    @classmethod
    def process_gitlab_event(cls, env, server, event_type, payload):
        """Handle incoming GitLab webhook events."""
        ctx = dict(env.context, syncing_from_devops=True)
        env = env(context=ctx)

        project_info = payload.get('project', {})
        project_path = project_info.get('path_with_namespace') or str(project_info.get('id', ''))

        repo = env['odoo_devops_bridge.repository'].sudo().search([
            ('server_id', '=', server.id),
            '|',
            ('external_slug', '=ilike', project_path),
            ('external_id', '=', str(project_info.get('id', ''))),
        ], limit=1)

        if not repo:
            _logger.info("GitLab event '%s' ignored: project '%s' not mapped.", event_type,
                         project_path)
            return {'status': 'skipped', 'reason': f'Project {project_path} not mapped'}

        object_kind = payload.get('object_kind')
        if object_kind == 'issue':
            return cls._process_gitlab_issue(env, server, repo, payload)
        elif object_kind == 'note':
            return cls._process_gitlab_note(env, server, repo, payload)
        elif object_kind == 'merge_request':
            return cls._process_gitlab_merge_request(env, server, repo, payload)

        return {'status': 'ignored', 'kind': object_kind}

    @classmethod
    def _process_gitlab_issue(cls, env, server, repo, payload):
        attrs = payload.get('object_attributes', {})
        issue_id = str(attrs.get('id'))
        issue_iid = attrs.get('iid')
        title = attrs.get('title')
        description = attrs.get('description') or ''
        state = attrs.get('state')  # 'opened', 'closed'
        url = attrs.get('url')

        task = env['project.task'].sudo().search([
            ('devops_repo_id', '=', repo.id),
            ('devops_external_id', '=', issue_id),
        ], limit=1)

        raw_labels = attrs.get('labels') or payload.get('labels') or []
        issue_type, tag_ids = cls._infer_issue_type_and_sync_tags(env, raw_labels=raw_labels,
                                                                  type_str=attrs.get('issue_type'))

        vals = {
            'name': title,
            'description': description,
            'devops_server_id': server.id,
            'devops_repo_id': repo.id,
            'devops_external_id': issue_id,
            'devops_issue_number': str(issue_iid),
            'devops_provider': 'gitlab',
            'devops_web_url': url,
            'devops_sync_status': 'synced',
            'devops_issue_type': issue_type,
        }
        if tag_ids:
            vals['tag_ids'] = [(6, 0, tag_ids)]

        # Resolve assignee
        assignees = payload.get('assignees') or []
        if assignees:
            first_user = cls.resolve_odoo_user(env, server, assignees[0].get('username'))
            if first_user:
                vals['user_ids'] = [(6, 0, [first_user.id])]

        if not task:
            vals['project_id'] = repo.project_id.id
            task = env['project.task'].sudo().create(vals)
        else:
            task.write(vals)

        # Parse issue relationships and dependencies
        cls._parse_and_link_dependencies(env, task, repo, description)

        if state == 'closed' and repo.closed_stage_id:
            task.write({'stage_id': repo.closed_stage_id.id})
        elif state == 'opened' and repo.open_stage_id and task.stage_id == repo.closed_stage_id:
            task.write({'stage_id': repo.open_stage_id.id})

        return {'status': 'success', 'task_id': task.id}

    @classmethod
    def _process_gitlab_note(cls, env, server, repo, payload):
        attrs = payload.get('object_attributes', {})
        noteable_type = attrs.get('noteable_type')
        note_id = str(attrs.get('id'))
        note_text = attrs.get('note') or ''
        author_username = payload.get('user', {}).get('username', 'GitLab')

        if noteable_type == 'Issue':
            issue_id = str(payload.get('issue', {}).get('id', ''))
            task = env['project.task'].sudo().search([
                ('devops_repo_id', '=', repo.id),
                ('devops_external_id', '=', issue_id),
            ], limit=1)
            if not task:
                return {'status': 'skipped', 'reason': 'Task not found'}

            existing = env['mail.message'].sudo().search([
                ('model', '=', 'project.task'),
                ('res_id', '=', task.id),
                ('devops_external_id', '=', note_id),
            ], limit=1)
            if existing:
                return {'status': 'already_synced'}

            # Anti-echo safeguard
            recent_msg = env['mail.message'].sudo().search([
                ('model', '=', 'project.task'),
                ('res_id', '=', task.id),
                ('devops_synced', '=', True),
                ('devops_external_id', '=', False),
            ], order='id desc', limit=1)
            if recent_msg and html2plaintext(recent_msg.body or '').strip() == note_text.strip():
                recent_msg.sudo().write({'devops_external_id': note_id})
                return {'status': 'already_synced', 'message_id': recent_msg.id}

            author_user = cls.resolve_odoo_user(env, server, author_username)
            author_partner = author_user.partner_id.id if author_user else env.ref(
                'base.partner_admin').id

            body_html = cls._format_comment_html('gitlab', author_username, note_text)
            msg = task.with_context(syncing_from_devops=True).message_post(
                body=body_html,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
                author_id=author_partner,
            )
            msg.sudo().write({'devops_external_id': note_id, 'devops_synced': True})

            cls._parse_and_link_dependencies(env, task, repo, note_text)
            return {'status': 'success', 'message_id': msg.id}

        elif noteable_type == 'MergeRequest':
            return cls._process_gitlab_pr_comment(env, server, repo, payload)

        return {'status': 'ignored', 'noteable_type': noteable_type}

    @classmethod
    def _process_gitlab_pr_comment(cls, env, server, repo, payload):
        attrs = payload.get('object_attributes', {})
        mr_data = payload.get('merge_request', {})
        mr_iid = str(mr_data.get('iid') or attrs.get('noteable_iid') or '')
        note_id = str(attrs.get('id') or '')
        note_text = attrs.get('note') or ''
        author_username = payload.get('user', {}).get('username', 'GitLab')

        mr_record = env['odoo_devops_bridge.pull.request'].sudo().search([
            ('server_id', '=', server.id),
            ('repository_id', '=', repo.id),
            ('number', '=', mr_iid),
        ], limit=1)
        if not mr_record:
            return {'status': 'skipped', 'reason': 'MR record not found for note'}

        existing = env['mail.message'].sudo().search([
            ('model', '=', 'odoo_devops_bridge.pull.request'),
            ('res_id', '=', mr_record.id),
            ('devops_external_id', '=', note_id),
        ], limit=1)
        if existing:
            return {'status': 'already_synced'}

        # Anti-echo safeguard
        recent_msg = env['mail.message'].sudo().search([
            ('model', '=', 'odoo_devops_bridge.pull.request'),
            ('res_id', '=', mr_record.id),
            ('devops_synced', '=', True),
            ('devops_external_id', '=', False),
        ], order='id desc', limit=1)
        if recent_msg and html2plaintext(recent_msg.body or '').strip() == note_text.strip():
            recent_msg.sudo().write({'devops_external_id': note_id})
            return {'status': 'already_synced', 'message_id': recent_msg.id}

        author_user = cls.resolve_odoo_user(env, server, author_username)
        author_partner = author_user.partner_id.id if author_user else env.ref(
            'base.partner_admin').id

        body_html = cls._format_comment_html('gitlab', author_username, note_text)
        msg = mr_record.with_context(syncing_from_devops=True).message_post(
            body=body_html,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
            author_id=author_partner,
        )
        msg.sudo().write({'devops_external_id': note_id, 'devops_synced': True})
        return {'status': 'success', 'message_id': msg.id}

    @classmethod
    def _process_gitlab_merge_request(cls, env, server, repo, payload):
        attrs = payload.get('object_attributes', {})
        mr_id = str(attrs.get('id'))
        mr_iid = attrs.get('iid')
        title = attrs.get('title')
        description = attrs.get('description') or ''
        state = attrs.get('state')  # 'opened', 'closed', 'merged'
        source_branch = attrs.get('source_branch', '')
        target_branch = attrs.get('target_branch', '')
        url = attrs.get('url')
        is_merged = state == 'merged'
        author_username = payload.get('user', {}).get('username', '')

        mr_record = env['odoo_devops_bridge.pull.request'].sudo().search([
            ('server_id', '=', server.id),
            ('repository_id', '=', repo.id),
            ('external_id', '=', mr_id),
        ], limit=1)
        if not mr_record and mr_iid:
            mr_record = env['odoo_devops_bridge.pull.request'].sudo().search([
                ('server_id', '=', server.id),
                ('repository_id', '=', repo.id),
                ('number', '=', str(mr_iid)),
            ], limit=1)

        # Detect linked task
        import re
        task = False
        task_match = re.search(r'#(\d+)', f"{title} {source_branch}")
        if task_match:
            issue_num = task_match.group(1)
            task = env['project.task'].sudo().search([
                ('devops_repo_id', '=', repo.id),
                ('devops_issue_number', '=', issue_num),
            ], limit=1)

        # Map assignees
        assignees_data = payload.get('assignees') or attrs.get('assignees') or []
        assignee_ids = []
        for a in assignees_data:
            uname = a.get('username') if isinstance(a, dict) else str(a)
            u = cls.resolve_odoo_user(env, server, uname)
            if u:
                assignee_ids.append(u.id)

        # Map reviewers
        reviewers_data = payload.get('reviewers') or attrs.get('reviewers') or []
        reviewer_ids = []
        for r in reviewers_data:
            uname = r.get('username') if isinstance(r, dict) else str(r)
            u = cls.resolve_odoo_user(env, server, uname)
            if u:
                reviewer_ids.append(u.id)

        # Map labels
        raw_labels = payload.get('labels') or attrs.get('labels') or []
        _, tag_ids = cls._infer_issue_type_and_sync_tags(env, raw_labels=raw_labels)

        vals = {
            'name': title,
            'server_id': server.id,
            'repository_id': repo.id,
            'project_id': repo.project_id.id if repo.project_id else False,
            'task_id': task.id if task else False,
            'external_id': mr_id,
            'number': str(mr_iid),
            'source_branch': source_branch,
            'target_branch': target_branch,
            'state': 'merged' if is_merged else ('closed' if state == 'closed' else 'open'),
            'is_merged': is_merged,
            'author_username': author_username,
            'web_url': url,
            'description': description,
        }
        if assignee_ids:
            vals['user_ids'] = [(6, 0, assignee_ids)]
        if reviewer_ids:
            vals['reviewer_ids'] = [(6, 0, reviewer_ids)]
        if tag_ids:
            vals['tag_ids'] = [(6, 0, tag_ids)]

        milestone_data = payload.get('milestone') or attrs.get('milestone')
        if milestone_data and repo.project_id:
            m_ext_id = str(milestone_data.get('id'))
            milestone = env['project.milestone'].sudo().search([
                ('project_id', '=', repo.project_id.id),
                ('devops_external_id', '=', m_ext_id),
            ], limit=1)
            if milestone:
                vals['milestone_id'] = milestone.id

        if not mr_record:
            mr_record = env['odoo_devops_bridge.pull.request'].sudo().create(vals)
        else:
            mr_record.write(vals)

        return {'status': 'success', 'mr_id': mr_record.id}

    @classmethod
    def _process_gitlab_milestone(cls, env, server, repo, milestone_data):
        """Create/update an Odoo project.milestone from a GitLab milestone payload."""
        if not repo.project_id:
            return {'status': 'skipped', 'reason': 'No project linked to repo'}

        m_id = str(milestone_data.get('id'))
        title = milestone_data.get('title')
        due_date = milestone_data.get('due_date')
        # GitLab milestone state values: 'active' or 'closed'
        state = milestone_data.get('state')
        mapped_state = 'closed' if state == 'closed' else 'open'

        milestone = env['project.milestone'].sudo().search([
            ('project_id', '=', repo.project_id.id),
            ('devops_external_id', '=', m_id),
        ], limit=1)

        vals = {
            'name': title,
            'project_id': repo.project_id.id,
            'devops_server_id': server.id,
            'devops_repo_id': repo.id,
            'devops_external_id': m_id,
            'devops_state': mapped_state,
        }
        if due_date:
            vals['deadline'] = due_date[:10]

        if not milestone:
            milestone = env['project.milestone'].sudo().create(vals)
        else:
            milestone.write(vals)

        return {'status': 'success', 'milestone_id': milestone.id}

    @classmethod
    def process_youtrack_event(cls, env, server, payload):
        """Handle incoming YouTrack webhook / workflow event."""
        ctx = dict(env.context, syncing_from_devops=True)
        env = env(context=ctx)

        project_info = payload.get('project', {})
        project_short_name = project_info.get('shortName') or project_info.get('name')

        repo = env['odoo_devops_bridge.repository'].sudo().search([
            ('server_id', '=', server.id),
            '|',
            ('external_slug', '=ilike', project_short_name),
            ('external_id', '=', str(project_info.get('id', ''))),
        ], limit=1)

        if not repo:
            return {'status': 'skipped',
                    'reason': f'YouTrack Project {project_short_name} not mapped'}

        issue_data = payload.get('issue') or payload
        issue_id = str(issue_data.get('id'))
        readable_id = issue_data.get('idReadable') or issue_data.get('summary')
        summary = issue_data.get('summary') or 'YouTrack Issue'
        description = issue_data.get('description') or ''

        task = env['project.task'].sudo().search([
            ('devops_repo_id', '=', repo.id),
            ('devops_external_id', '=', issue_id),
        ], limit=1)

        raw_tags = [t.get('name') for t in issue_data.get('tags', []) if isinstance(t, dict)]
        type_name = None
        for cf in issue_data.get('customFields', []):
            if cf.get('name') == 'Type' and isinstance(cf.get('value'), dict):
                type_name = cf['value'].get('name')

        issue_type, tag_ids = cls._infer_issue_type_and_sync_tags(env, raw_labels=raw_tags,
                                                                  type_str=type_name)

        vals = {
            'name': f"[{readable_id}] {summary}" if readable_id and readable_id not in summary else summary,
            'description': description,
            'devops_server_id': server.id,
            'devops_repo_id': repo.id,
            'devops_external_id': issue_id,
            'devops_issue_number': str(readable_id),
            'devops_provider': 'youtrack',
            'devops_sync_status': 'synced',
            'devops_issue_type': issue_type,
        }
        if tag_ids:
            vals['tag_ids'] = [(6, 0, tag_ids)]

        if not task:
            vals['project_id'] = repo.project_id.id
            task = env['project.task'].sudo().create(vals)
        else:
            task.write(vals)

        # Parse issue relationships and dependencies
        cls._parse_and_link_dependencies(env, task, repo, description)

        return {'status': 'success', 'task_id': task.id}

    @classmethod
    def sync_task_outbound(cls, task):
        """Push an Odoo task update to the connected external platform."""
        if task.env.context.get('syncing_from_devops'):
            return

        repo = task.devops_repo_id
        server = task.devops_server_id or (repo.server_id if repo else False)
        if not server or not repo or not server.sync_direction in ('bidirectional', 'export_only'):
            return

        user = task.env.user
        try:
            client = cls.get_client(server, user=user)
        except OdooDevOpsBridgeAuthError as e:
            _logger.warning("Cannot sync task #%s to DevOps: %s", task.id, str(e))
            return

        provider = server.provider
        slug = repo.external_slug

        # Prepare labels from tag_ids + devops_issue_type
        labels = list(set(task.tag_ids.mapped('name')))
        if task.devops_issue_type and task.devops_issue_type != 'task':
            if task.devops_issue_type not in labels:
                labels.append(task.devops_issue_type)

        try:
            if provider == 'github':
                parts = slug.split('/')
                if len(parts) == 2:
                    owner, repo_name = parts
                    if not task.devops_external_id:
                        res = client.create_issue(
                            owner, repo_name,
                            title=task.name,
                            body=task.description or '',
                            labels=labels or None
                        )
                        task.sudo().write({
                            'devops_external_id': str(res.get('id')),
                            'devops_issue_number': str(res.get('number')),
                            'devops_web_url': res.get('html_url'),
                            'devops_sync_status': 'synced',
                        })
                    else:
                        is_closed = repo.closed_stage_id and task.stage_id == repo.closed_stage_id
                        state = 'closed' if is_closed else 'open'
                        client.update_issue(
                            owner, repo_name,
                            issue_number=int(task.devops_issue_number or 0),
                            title=task.name,
                            body=task.description or '',
                            state=state,
                            labels=labels or None
                        )
                        task.sudo().write({'devops_sync_status': 'synced'})

            elif provider == 'gitlab':
                project_id = repo.external_id or slug
                if not task.devops_external_id:
                    res = client.create_issue(
                        project_id,
                        title=task.name,
                        description=task.description or '',
                        labels=labels or None
                    )
                    task.sudo().write({
                        'devops_external_id': str(res.get('id')),
                        'devops_issue_number': str(res.get('iid')),
                        'devops_web_url': res.get('web_url'),
                        'devops_sync_status': 'synced',
                    })
                else:
                    is_closed = repo.closed_stage_id and task.stage_id == repo.closed_stage_id
                    state_event = 'close' if is_closed else 'reopen'
                    client.update_issue(
                        project_id,
                        issue_iid=int(task.devops_issue_number or 0),
                        title=task.name,
                        description=task.description or '',
                        state_event=state_event,
                        labels=labels or None
                    )
                    task.sudo().write({'devops_sync_status': 'synced'})

            elif provider == 'youtrack':
                project_id = repo.external_id or slug
                if not task.devops_external_id:
                    res = client.create_issue(project_id, summary=task.name,
                                              description=task.description or '')
                    task.sudo().write({
                        'devops_external_id': str(res.get('id')),
                        'devops_issue_number': str(res.get('idReadable', '')),
                        'devops_sync_status': 'synced',
                    })
                else:
                    client.update_issue(task.devops_external_id, summary=task.name,
                                        description=task.description or '')
                    task.sudo().write({'devops_sync_status': 'synced'})

        except OdooDevOpsBridgeAPIError as e:
            _logger.error("Error syncing task #%s to DevOps provider %s: %s", task.id, provider,
                          str(e))
            task.sudo().write({'devops_sync_status': 'error'})

    @classmethod
    def sync_comment_outbound(cls, message):
        """Push an Odoo chatter note/comment to external issue/PR comment thread."""
        if message.env.context.get('syncing_from_devops') or message.devops_synced:
            return
        if message.model not in ('project.task',
                                 'odoo_devops_bridge.pull.request') or not message.res_id:
            return

        user = message.author_id.user_ids[
            0] if message.author_id and message.author_id.user_ids else message.env.user
        clean_text = html2plaintext(message.body or '').strip()
        if not clean_text:
            return

        if message.model == 'project.task':
            task = message.env['project.task'].sudo().browse(message.res_id)
            if not task.devops_repo_id or not task.devops_external_id:
                return

            repo = task.devops_repo_id
            server = repo.server_id
            if not server or server.sync_direction not in ('bidirectional', 'export_only'):
                return

            try:
                client = cls.get_client(server, user=user)
            except OdooDevOpsBridgeAuthError:
                return

            try:
                ext_id = False
                if server.provider == 'github':
                    parts = repo.external_slug.split('/')
                    if len(parts) == 2:
                        res = client.create_issue_comment(parts[0], parts[1],
                                                          int(task.devops_issue_number or 0),
                                                          clean_text)
                        if isinstance(res, dict) and res.get('id'):
                            ext_id = str(res['id'])
                        message.sudo().write({'devops_synced': True, 'devops_external_id': ext_id})
                elif server.provider == 'gitlab':
                    res = client.create_issue_note(repo.external_id or repo.external_slug,
                                                   int(task.devops_issue_number or 0), clean_text)
                    if isinstance(res, dict) and res.get('id'):
                        ext_id = str(res['id'])
                    message.sudo().write({'devops_synced': True, 'devops_external_id': ext_id})
                elif server.provider == 'youtrack':
                    res = client.create_issue_comment(task.devops_external_id, clean_text)
                    if isinstance(res, dict) and res.get('id'):
                        ext_id = str(res['id'])
                    message.sudo().write({'devops_synced': True, 'devops_external_id': ext_id})
            except Exception as e:
                _logger.warning("Failed to sync task comment outbound: %s", str(e))

        elif message.model == 'odoo_devops_bridge.pull.request':
            pr = message.env['odoo_devops_bridge.pull.request'].sudo().browse(message.res_id)
            if not pr.repository_id or not pr.number:
                return

            repo = pr.repository_id
            server = repo.server_id
            if not server or server.sync_direction not in ('bidirectional', 'export_only'):
                return

            try:
                client = cls.get_client(server, user=user)
            except OdooDevOpsBridgeAuthError:
                return

            try:
                ext_id = False
                if server.provider == 'github':
                    parts = repo.external_slug.split('/')
                    if len(parts) == 2:
                        res = client.create_issue_comment(parts[0], parts[1], int(pr.number or 0),
                                                          clean_text)
                        if isinstance(res, dict) and res.get('id'):
                            ext_id = str(res['id'])
                        message.sudo().write({'devops_synced': True, 'devops_external_id': ext_id})
                elif server.provider == 'gitlab':
                    res = client.create_merge_request_note(repo.external_id or repo.external_slug,
                                                           int(pr.number or 0), clean_text)
                    if isinstance(res, dict) and res.get('id'):
                        ext_id = str(res['id'])
                    message.sudo().write({'devops_synced': True, 'devops_external_id': ext_id})
            except Exception as e:
                _logger.warning("Failed to sync PR comment outbound: %s", str(e))

    @classmethod
    def sync_pull_request_outbound(cls, pr):
        """Push pull request edits made in Odoo to the remote DevOps provider."""
        if pr.env.context.get('syncing_from_devops'):
            return
        if not pr.repository_id or not pr.number:
            return

        repo = pr.repository_id
        server = repo.server_id
        if not server or server.sync_direction not in ('bidirectional', 'export_only'):
            return

        user = pr.env.user
        try:
            client = cls.get_client(server, user=user)
        except (OdooDevOpsBridgeAuthError, Exception) as e:
            _logger.warning("Auth error getting client for PR push: %s", str(e))
            return

        provider = server.provider
        slug = repo.external_slug
        labels = list(set(pr.tag_ids.mapped('name')))

        try:
            if provider == 'github':
                parts = slug.split('/')
                if len(parts) == 2:
                    owner, repo_name = parts
                    pr_num = int(pr.number)
                    state = 'closed' if pr.state == 'closed' else (
                        'open' if pr.state in ('open', 'draft') else None)
                    client.update_pull_request(
                        owner, repo_name, pr_num,
                        title=pr.name,
                        body=pr.description or '',
                        state=state
                    )
                    # Sync assignees, labels, milestone via issues API
                    assignees = [cls.resolve_remote_username(pr.env, server, u) for u in pr.user_ids
                                 if cls.resolve_remote_username(pr.env, server, u)]
                    milestone_num = None
                    if pr.milestone_id and pr.milestone_id.devops_external_id:
                        try:
                            milestone_num = int(pr.milestone_id.devops_external_id)
                        except (ValueError, TypeError):
                            milestone_num = None
                    client.update_issue(
                        owner, repo_name, pr_num,
                        assignees=assignees or None,
                        labels=labels or None,
                        milestone=milestone_num
                    )
                    pr.sudo().write({'devops_sync_status': 'synced'})

            elif provider == 'gitlab':
                project_id = repo.external_id or slug
                mr_iid = int(pr.number)
                state_event = 'close' if pr.state == 'closed' else (
                    'reopen' if pr.state == 'open' else None)
                assignee_ids = []
                for u in pr.user_ids:
                    acc = pr.env['odoo_devops_bridge.account'].sudo().search([
                        ('server_id', '=', server.id),
                        ('user_id', '=', u.id),
                        ('account_type', '=', 'personal'),
                    ], limit=1)
                    if acc and acc.external_id:
                        try:
                            assignee_ids.append(int(acc.external_id))
                        except ValueError:
                            pass
                reviewer_ids = []
                for u in pr.reviewer_ids:
                    acc = pr.env['odoo_devops_bridge.account'].sudo().search([
                        ('server_id', '=', server.id),
                        ('user_id', '=', u.id),
                        ('account_type', '=', 'personal'),
                    ], limit=1)
                    if acc and acc.external_id:
                        try:
                            reviewer_ids.append(int(acc.external_id))
                        except ValueError:
                            pass
                milestone_id = None
                if pr.milestone_id and pr.milestone_id.devops_external_id:
                    try:
                        milestone_id = int(pr.milestone_id.devops_external_id)
                    except (ValueError, TypeError):
                        pass

                client.update_merge_request(
                    project_id, mr_iid,
                    title=pr.name,
                    description=pr.description or '',
                    state_event=state_event,
                    labels=labels or None,
                    assignee_ids=assignee_ids or None,
                    reviewer_ids=reviewer_ids or None,
                    milestone_id=milestone_id
                )
                pr.sudo().write({'devops_sync_status': 'synced'})

        except Exception as e:
            _logger.error("Error syncing pull request #%s to DevOps: %s", pr.number, str(e))
            pr.sudo().write({'devops_sync_status': 'error'})

    @classmethod
    def merge_pull_request(cls, pr):
        """Merge a PR/MR on remote provider and update local record."""
        repo = pr.repository_id
        server = repo.server_id
        client = cls.get_client(server, user=pr.env.user)
        provider = server.provider
        slug = repo.external_slug

        try:
            res = {}
            if provider == 'github':
                parts = slug.split('/')
                if len(parts) == 2:
                    owner, repo_name = parts
                    res = client.merge_pull_request(owner, repo_name, int(pr.number))
            elif provider == 'gitlab':
                project_id = repo.external_id or slug
                res = client.merge_merge_request(project_id, int(pr.number))
            else:
                raise UserError(_("Merging is not supported for provider %s.") % provider)

            commit_sha = res.get('sha') or res.get('merge_commit_sha') or ''
            pr.with_context(syncing_from_devops=True).write({
                'state': 'merged',
                'is_merged': True,
                'merged_at': fields.Datetime.now(),
                'merge_commit_sha': commit_sha,
                'devops_sync_status': 'synced',
            })
            pr.message_post(body=Markup(
                f"<p><i class='fa fa-check text-success me-1'></i><strong>Pull Request #{pr.number} merged</strong> successfully on {server.name}.</p>"))

            # If linked to a task and repo has closed stage, close task
            if pr.task_id and repo.closed_stage_id and pr.task_id.stage_id != repo.closed_stage_id:
                pr.task_id.write({'stage_id': repo.closed_stage_id.id})

        except Exception as e:
            _logger.error("Failed to merge PR #%s on %s: %s", pr.number, server.name, str(e))
            raise UserError(_("Could not merge PR on %s: %s") % (server.name, str(e)))

    @classmethod
    def close_pull_request(cls, pr):
        """Close a PR/MR on remote provider."""
        repo = pr.repository_id
        server = repo.server_id
        client = cls.get_client(server, user=pr.env.user)
        provider = server.provider
        slug = repo.external_slug

        try:
            if provider == 'github':
                parts = slug.split('/')
                if len(parts) == 2:
                    client.update_pull_request(parts[0], parts[1], int(pr.number), state='closed')
            elif provider == 'gitlab':
                client.update_merge_request(repo.external_id or slug, int(pr.number),
                                            state_event='close')
            pr.with_context(syncing_from_devops=True).write(
                {'state': 'closed', 'devops_sync_status': 'synced'})
            pr.message_post(body=Markup(
                f"<p><i class='fa fa-times text-secondary me-1'></i><strong>Pull Request #{pr.number} closed</strong> on {server.name}.</p>"))
        except Exception as e:
            _logger.error("Failed to close PR #%s on %s: %s", pr.number, server.name, str(e))
            raise UserError(_("Could not close PR on %s: %s") % (server.name, str(e)))

    @classmethod
    def reopen_pull_request(cls, pr):
        """Reopen a closed PR/MR on remote provider."""
        repo = pr.repository_id
        server = repo.server_id
        client = cls.get_client(server, user=pr.env.user)
        provider = server.provider
        slug = repo.external_slug

        try:
            if provider == 'github':
                parts = slug.split('/')
                if len(parts) == 2:
                    client.update_pull_request(parts[0], parts[1], int(pr.number), state='open')
            elif provider == 'gitlab':
                client.update_merge_request(repo.external_id or slug, int(pr.number),
                                            state_event='reopen')
            pr.with_context(syncing_from_devops=True).write(
                {'state': 'open', 'devops_sync_status': 'synced'})
            pr.message_post(body=Markup(
                f"<p><i class='fa fa-refresh text-primary me-1'></i><strong>Pull Request #{pr.number} reopened</strong> on {server.name}.</p>"))
        except Exception as e:
            _logger.error("Failed to reopen PR #%s on %s: %s", pr.number, server.name, str(e))
            raise UserError(_("Could not reopen PR on %s: %s") % (server.name, str(e)))

    @classmethod
    def close_task(cls, task):
        """Close an issue/task on remote tracker and update Odoo stage."""
        if not task.devops_repo_id:
            raise UserError(_("No DevOps repository configured on this task."))
        repo = task.devops_repo_id
        server = repo.server_id
        client = cls.get_client(server, user=task.env.user)
        provider = server.provider
        slug = repo.external_slug

        try:
            if provider == 'github':
                parts = slug.split('/')
                if len(parts) == 2:
                    client.update_issue(parts[0], parts[1], int(task.devops_issue_number or 0),
                                        state='closed')
            elif provider == 'gitlab':
                client.update_issue(repo.external_id or slug, int(task.devops_issue_number or 0),
                                    state_event='close')
            elif provider == 'youtrack':
                client.update_issue(task.devops_external_id, state='Closed')

            vals = {'devops_sync_status': 'synced'}
            if repo.closed_stage_id:
                vals['stage_id'] = repo.closed_stage_id.id
            task.with_context(syncing_from_devops=True).write(vals)
            task.message_post(body=Markup(
                f"<p><i class='fa fa-check-circle text-success me-1'></i><strong>Issue closed</strong> remotely on {server.name}.</p>"))
        except Exception as e:
            _logger.error("Failed to close task #%s on %s: %s", task.id, server.name, str(e))
            raise UserError(_("Could not close issue on %s: %s") % (server.name, str(e)))

    @classmethod
    def reopen_task(cls, task):
        """Reopen an issue/task on remote tracker and update Odoo stage."""
        if not task.devops_repo_id:
            raise UserError(_("No DevOps repository configured on this task."))
        repo = task.devops_repo_id
        server = repo.server_id
        client = cls.get_client(server, user=task.env.user)
        provider = server.provider
        slug = repo.external_slug

        try:
            if provider == 'github':
                parts = slug.split('/')
                if len(parts) == 2:
                    client.update_issue(parts[0], parts[1], int(task.devops_issue_number or 0),
                                        state='open')
            elif provider == 'gitlab':
                client.update_issue(repo.external_id or slug, int(task.devops_issue_number or 0),
                                    state_event='reopen')
            elif provider == 'youtrack':
                client.update_issue(task.devops_external_id, state='Open')

            vals = {'devops_sync_status': 'synced'}
            if repo.open_stage_id:
                vals['stage_id'] = repo.open_stage_id.id
            task.with_context(syncing_from_devops=True).write(vals)
            task.message_post(body=Markup(
                f"<p><i class='fa fa-circle-o text-primary me-1'></i><strong>Issue reopened</strong> remotely on {server.name}.</p>"))
        except Exception as e:
            _logger.error("Failed to reopen task #%s on %s: %s", task.id, server.name, str(e))
            raise UserError(_("Could not reopen issue on %s: %s") % (server.name, str(e)))
