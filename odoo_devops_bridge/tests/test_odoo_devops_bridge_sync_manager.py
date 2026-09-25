# Part of Odoo DevOps Bridge. See LICENSE file for full copyright and licensing details.

from odoo.tests.common import TransactionCase, tagged
from unittest.mock import patch

from ..services.odoo_devops_bridge_sync_manager import OdooDevOpsBridgeSyncManager


@tagged('post_install', '-at_install', 'odoo_devops_bridge')
class TestOdooDevOpsBridgeSyncManager(TransactionCase):
    """Tests for inbound webhook processing, outbound push triggers, and the
    anti-recursion loop guard implemented in OdooDevOpsBridgeSyncManager."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({'name': 'DevOps Bridge Test Project'})
        cls.server = cls.env['odoo_devops_bridge.server'].create({
            'name': 'GitHub Sync Test Server',
            'provider': 'github',
            'base_url': 'https://api.github.com',
        })
        cls.bot_account = cls.env['odoo_devops_bridge.account'].create({
            'server_id': cls.server.id,
            'account_type': 'bot',
            'user_id': False,
            'token': 'bot-token',
            'state': 'valid',
        })
        cls.server.default_bot_account_id = cls.bot_account.id
        cls.repo = cls.env['odoo_devops_bridge.repository'].create({
            'name': 'octocat/hello-world',
            'server_id': cls.server.id,
            'project_id': cls.project.id,
            'external_id': '1001',
            'external_slug': 'octocat/hello-world',
        })

    def test_01_inbound_github_issue_creates_task(self):
        """A GitHub 'issues' webhook payload for an unmapped issue should
        create a new project.task bound to the mapped repository."""
        payload = {
            'action': 'opened',
            'repository': {'full_name': 'octocat/hello-world'},
            'issue': {
                'id': 555001,
                'number': 42,
                'title': 'Fix the login bug',
                'body': 'Steps to reproduce...',
                'state': 'open',
                'html_url': 'https://github.com/octocat/hello-world/issues/42',
            },
        }
        result = OdooDevOpsBridgeSyncManager.process_github_event(self.env, self.server, 'issues',
                                                                  payload)
        self.assertEqual(result['status'], 'success')

        task = self.env['project.task'].search([
            ('devops_repo_id', '=', self.repo.id),
            ('devops_external_id', '=', '555001'),
        ], limit=1)
        self.assertTrue(task, "Task should have been created from the inbound issue payload")
        self.assertEqual(task.name, 'Fix the login bug')
        self.assertEqual(task.devops_issue_number, '42')
        self.assertEqual(task.devops_sync_status, 'synced')

    def test_02_inbound_github_issue_update_reuses_existing_task(self):
        """A second webhook for the same external issue ID should update the
        existing task rather than creating a duplicate."""
        payload_create = {
            'action': 'opened',
            'repository': {'full_name': 'octocat/hello-world'},
            'issue': {'id': 555002, 'number': 43, 'title': 'Initial title', 'state': 'open'},
        }
        OdooDevOpsBridgeSyncManager.process_github_event(self.env, self.server, 'issues',
                                                         payload_create)

        payload_update = {
            'action': 'edited',
            'repository': {'full_name': 'octocat/hello-world'},
            'issue': {'id': 555002, 'number': 43, 'title': 'Updated title', 'state': 'open'},
        }
        OdooDevOpsBridgeSyncManager.process_github_event(self.env, self.server, 'issues',
                                                         payload_update)

        tasks = self.env['project.task'].search([
            ('devops_repo_id', '=', self.repo.id),
            ('devops_external_id', '=', '555002'),
        ])
        self.assertEqual(len(tasks), 1,
                         "Should not create a duplicate task for the same external issue")
        self.assertEqual(tasks.name, 'Updated title')

    def test_03_inbound_github_issue_closed_moves_stage(self):
        """Closing an issue externally should move the task to the
        repository's configured closed stage, if one is set."""
        stage_open = self.env['project.task.type'].create(
            {'name': 'To Do', 'project_ids': [(4, self.project.id)]})
        stage_closed = self.env['project.task.type'].create(
            {'name': 'Done', 'project_ids': [(4, self.project.id)]})
        self.repo.write({'open_stage_id': stage_open.id, 'closed_stage_id': stage_closed.id})

        payload = {
            'action': 'closed',
            'repository': {'full_name': 'octocat/hello-world'},
            'issue': {'id': 555003, 'number': 44, 'title': 'Closable issue', 'state': 'closed'},
        }
        OdooDevOpsBridgeSyncManager.process_github_event(self.env, self.server, 'issues', payload)

        task = self.env['project.task'].search([
            ('devops_repo_id', '=', self.repo.id),
            ('devops_external_id', '=', '555003'),
        ], limit=1)
        self.assertEqual(task.stage_id, stage_closed)

    def test_04_inbound_unmapped_repository_is_skipped(self):
        """Events for a repository that has no odoo_devops_bridge.repository binding
        must be safely skipped, never raise, and never create a task."""
        payload = {
            'action': 'opened',
            'repository': {'full_name': 'someone-else/unmapped-repo'},
            'issue': {'id': 999999, 'number': 1, 'title': 'Should be ignored', 'state': 'open'},
        }
        result = OdooDevOpsBridgeSyncManager.process_github_event(self.env, self.server, 'issues',
                                                                  payload)
        self.assertEqual(result['status'], 'skipped')

        task = self.env['project.task'].search([('devops_external_id', '=', '999999')])
        self.assertFalse(task)

    # -- User resolution ---------------------------------------------------

    def test_05_resolve_odoo_user_matches_case_insensitively(self):
        """resolve_odoo_user should match the external username regardless
        of case, and return False when there is no match."""
        self.env['odoo_devops_bridge.account'].create({
            'server_id': self.server.id,
            'account_type': 'personal',
            'user_id': self.env.user.id,
            'token': 'user-token',
            'external_username': 'OctoCat',
            'state': 'valid',
        })
        matched = OdooDevOpsBridgeSyncManager.resolve_odoo_user(self.env, self.server, 'octocat')
        self.assertEqual(matched, self.env.user)

        unmatched = OdooDevOpsBridgeSyncManager.resolve_odoo_user(self.env, self.server,
                                                                  'nonexistent-handle')
        self.assertFalse(unmatched)

    # -- Recursion / loop guard ---------------------------------------------

    def test_06_outbound_sync_skipped_when_syncing_from_devops(self):
        """sync_task_outbound must be a no-op when the context flag
        'syncing_from_devops' is set, preventing infinite webhook loops."""
        task = self.env['project.task'].with_context(syncing_from_devops=True).create({
            'name': 'Loop guard task',
            'project_id': self.project.id,
            'devops_repo_id': self.repo.id,
            'devops_server_id': self.server.id,
        })
        with patch(
                'odoo.addons.odoo_devops_bridge.services.odoo_devops_bridge_github_client.OdooDevOpsBridgeGitHubClient.create_issue'
        ) as mocked_create:
            OdooDevOpsBridgeSyncManager.sync_task_outbound(task)
            mocked_create.assert_not_called()

    def test_07_outbound_sync_creates_remote_issue_when_not_yet_synced(self):
        """A task with a bound repository and no external ID yet should
        trigger an outbound create_issue call exactly once."""
        task = self.env['project.task'].create({
            'name': 'Needs outbound push',
            'project_id': self.project.id,
            'devops_repo_id': self.repo.id,
            'devops_server_id': self.server.id,
        })
        with patch(
                'odoo.addons.odoo_devops_bridge.services.odoo_devops_bridge_github_client.OdooDevOpsBridgeGitHubClient.create_issue',
                return_value={'id': 777, 'number': 99,
                              'html_url': 'https://github.com/octocat/hello-world/issues/99'},
        ) as mocked_create:
            OdooDevOpsBridgeSyncManager.sync_task_outbound(task)
            mocked_create.assert_called_once()
        self.assertEqual(task.devops_external_id, '777')
        self.assertEqual(task.devops_sync_status, 'synced')

    def test_08_inbound_comment_not_duplicated_on_replay(self):
        """Replaying the same inbound comment webhook twice must not create
        two mail.message records for the same external comment ID."""
        OdooDevOpsBridgeSyncManager.process_github_event(self.env, self.server, 'issues', {
            'action': 'opened',
            'repository': {'full_name': 'octocat/hello-world'},
            'issue': {'id': 555010, 'number': 50, 'title': 'Commentable issue', 'state': 'open'},
        })
        comment_payload = {
            'repository': {'full_name': 'octocat/hello-world'},
            'issue': {'id': 555010},
            'comment': {'id': 88001, 'body': 'This is a synced comment',
                        'user': {'login': 'octocat'}},
        }
        result_1 = OdooDevOpsBridgeSyncManager.process_github_event(self.env, self.server,
                                                                    'issue_comment',
                                                                    comment_payload)
        result_2 = OdooDevOpsBridgeSyncManager.process_github_event(self.env, self.server,
                                                                    'issue_comment',
                                                                    comment_payload)

        self.assertEqual(result_1['status'], 'success')
        self.assertEqual(result_2['status'], 'already_synced')

        messages = self.env['mail.message'].search([('devops_external_id', '=', '88001')])
        self.assertEqual(len(messages), 1)

    def test_09_outbound_comment_stores_external_id_and_prevents_webhook_echo(self):
        """When an Odoo user posts a chatter message, outbound sync should store
        the returned external comment ID and prevent inbound webhook echoes."""
        task = self.env['project.task'].create({
            'name': 'Task for Comment Sync',
            'project_id': self.project.id,
            'devops_repo_id': self.repo.id,
            'devops_server_id': self.server.id,
            'devops_external_id': '555020',
            'devops_issue_number': '60',
        })
        with patch(
                'odoo.addons.odoo_devops_bridge.services.odoo_devops_bridge_github_client.OdooDevOpsBridgeGitHubClient.create_issue_comment',
                return_value={'id': 99001, 'body': 'Hello from Odoo chatter'},
        ) as mock_comment:
            msg = task.message_post(body='<p>Hello from Odoo chatter</p>', message_type='comment')
            mock_comment.assert_called_once()

        self.assertTrue(msg.devops_synced)
        self.assertEqual(msg.devops_external_id, '99001')

        # GitHub webhook sends the comment back
        comment_payload = {
            'repository': {'full_name': 'octocat/hello-world'},
            'issue': {'id': 555020},
            'comment': {'id': 99001, 'body': 'Hello from Odoo chatter',
                        'user': {'login': 'octocat'}},
        }
        result = OdooDevOpsBridgeSyncManager.process_github_event(self.env, self.server,
                                                                  'issue_comment', comment_payload)
        self.assertEqual(result['status'], 'already_synced')

        # Total messages on task should remain 1
        task_messages = self.env['mail.message'].search([
            ('model', '=', 'project.task'),
            ('res_id', '=', task.id),
            ('message_type', '=', 'comment'),
        ])
        self.assertEqual(len(task_messages), 1)

    def test_10_inbound_comment_formatting_with_markdown_and_quotes(self):
        """Markdown quotes (> text), bold, code, and links should be parsed
        into clean HTML elements in chatter."""
        task = self.env['project.task'].with_context(syncing_from_devops=True).create({
            'name': 'Task for Rich Comments',
            'project_id': self.project.id,
            'devops_repo_id': self.repo.id,
            'devops_server_id': self.server.id,
            'devops_external_id': '555030',
            'devops_issue_number': '70',
        })
        comment_payload = {
            'repository': {'full_name': 'octocat/hello-world'},
            'issue': {'id': 555030},
            'comment': {
                'id': 88002,
                'body': '> hello g\n\nHere is **important** info with `variable_name` and [Docs](https://example.com)',
                'user': {'login': 'AustinATTS'},
            },
        }
        result = OdooDevOpsBridgeSyncManager.process_github_event(self.env, self.server,
                                                                  'issue_comment', comment_payload)
        self.assertEqual(result['status'], 'success')

        msg = self.env['mail.message'].browse(result['message_id'])
        self.assertIn('<blockquote', msg.body)
        self.assertIn('hello g', msg.body)
        self.assertIn('<strong>important</strong>', msg.body)
        self.assertIn('<code', msg.body)
        self.assertIn('<a href="https://example.com"', msg.body)
        self.assertIn('@AustinATTS', msg.body)
        self.assertIn('GitHub', msg.body)

    def test_11_inbound_issue_labels_and_type_detection(self):
        """Inbound issues with labels should detect issue type (bug, feature, recommendation)
        and populate project tags."""
        payload_bug = {
            'action': 'opened',
            'repository': {'full_name': 'octocat/hello-world'},
            'issue': {
                'id': 555041,
                'number': 81,
                'title': 'Memory Leak Bug',
                'body': 'Details here',
                'labels': [{'name': 'bug'}, {'name': 'critical-fix'}],
            },
        }
        OdooDevOpsBridgeSyncManager.process_github_event(self.env, self.server, 'issues',
                                                         payload_bug)
        task_bug = self.env['project.task'].search([('devops_external_id', '=', '555041')])
        self.assertEqual(task_bug.devops_issue_type, 'bug')
        tag_names = task_bug.tag_ids.mapped('name')
        self.assertIn('bug', tag_names)
        self.assertIn('critical-fix', tag_names)

        payload_rec = {
            'action': 'opened',
            'repository': {'full_name': 'octocat/hello-world'},
            'issue': {
                'id': 555042,
                'number': 82,
                'title': 'Improve caching architecture',
                'body': 'Details here',
                'labels': [{'name': 'recommendation'}, {'name': 'performance'}],
            },
        }
        OdooDevOpsBridgeSyncManager.process_github_event(self.env, self.server, 'issues',
                                                         payload_rec)
        task_rec = self.env['project.task'].search([('devops_external_id', '=', '555042')])
        self.assertEqual(task_rec.devops_issue_type, 'recommendation')

    def test_12_outbound_task_sync_includes_tags_and_issue_type(self):
        """Outbound issue creation and updates should pass tags and issue type as remote labels."""
        tag = self.env['project.tags'].create({'name': 'frontend'})
        task = self.env['project.task'].create({
            'name': 'Feature Request with Tags',
            'project_id': self.project.id,
            'devops_repo_id': self.repo.id,
            'devops_server_id': self.server.id,
            'devops_issue_type': 'feature',
            'tag_ids': [(4, tag.id)],
        })
        with patch(
                'odoo.addons.odoo_devops_bridge.services.odoo_devops_bridge_github_client.OdooDevOpsBridgeGitHubClient.create_issue',
                return_value={'id': 555050, 'number': 95,
                              'html_url': 'https://github.com/octocat/hello-world/issues/95'},
        ) as mock_create:
            OdooDevOpsBridgeSyncManager.sync_task_outbound(task)
            mock_create.assert_called_once()
            _, kwargs = mock_create.call_args
            labels = kwargs.get('labels')
            self.assertIn('feature', labels)
            self.assertIn('frontend', labels)

    def test_13_issue_dependencies_and_relationship_linking(self):
        """Parsing directives like 'Depends on #10' and 'Blocks #20' should link
        depend_on_ids and dependent_ids on project.task."""
        task_a = self.env['project.task'].with_context(syncing_from_devops=True).create({
            'name': 'Prerequisite Task A',
            'project_id': self.project.id,
            'devops_repo_id': self.repo.id,
            'devops_server_id': self.server.id,
            'devops_external_id': '555061',
            'devops_issue_number': '10',
        })
        task_b = self.env['project.task'].with_context(syncing_from_devops=True).create({
            'name': 'Blocked Task B',
            'project_id': self.project.id,
            'devops_repo_id': self.repo.id,
            'devops_server_id': self.server.id,
            'devops_external_id': '555062',
            'devops_issue_number': '20',
        })

        payload_c = {
            'action': 'opened',
            'repository': {'full_name': 'octocat/hello-world'},
            'issue': {
                'id': 555063,
                'number': 30,
                'title': 'Intermediate Task C',
                'body': 'Implementation details.\n\nDepends on #10\nBlocks #20',
            },
        }
        OdooDevOpsBridgeSyncManager.process_github_event(self.env, self.server, 'issues', payload_c)
        task_c = self.env['project.task'].search([('devops_external_id', '=', '555063')])
        self.assertTrue(task_c)
        self.assertIn(task_a, task_c.depend_on_ids)
        self.assertIn(task_b, task_c.dependent_ids)
        self.assertIn(task_c, task_a.dependent_ids)
        self.assertIn(task_c, task_b.depend_on_ids)

    def test_14_inbound_github_pr_comment_routes_to_pull_request_record(self):
        """Comments on GitHub pull requests (via issue_comment with pull_request key or pull_request_review_comment)
        must be routed to odoo_devops_bridge.pull.request chatter, NOT project.task."""
        pr = self.env['odoo_devops_bridge.pull.request'].with_context(
            syncing_from_devops=True).create({
            'name': 'Refactor Authentication',
            'server_id': self.server.id,
            'repository_id': self.repo.id,
            'project_id': self.project.id,
            'number': '55',
            'external_id': '999055',
            'state': 'open',
        })

        payload = {
            'repository': {'full_name': 'octocat/hello-world'},
            'issue': {
                'id': 999055,
                'number': 55,
                'pull_request': {
                    'url': 'https://api.github.com/repos/octocat/hello-world/pulls/55'},
            },
            'comment': {
                'id': 77701,
                'body': 'Looks good to me, please check the unit tests.',
                'user': {'login': 'reviewer_user'},
            },
        }

        res = OdooDevOpsBridgeSyncManager.process_github_event(self.env, self.server,
                                                               'issue_comment', payload)
        self.assertEqual(res['status'], 'success')

        # Check comment is on PR chatter
        msg = self.env['mail.message'].search([
            ('model', '=', 'odoo_devops_bridge.pull.request'),
            ('res_id', '=', pr.id),
            ('devops_external_id', '=', '77701'),
        ])
        self.assertTrue(msg, "Comment should be posted on odoo_devops_bridge.pull.request chatter")
        self.assertIn('Looks good to me', msg.body)

        # Ensure no comment was placed on any project.task
        task_msg = self.env['mail.message'].search([
            ('model', '=', 'project.task'),
            ('devops_external_id', '=', '77701'),
        ])
        self.assertFalse(task_msg, "Comment must NOT be attached to project.task")

    def test_15_outbound_pr_comment_syncs_to_github(self):
        """Messages posted to odoo_devops_bridge.pull.request chatter should be pushed out to the remote provider."""
        pr = self.env['odoo_devops_bridge.pull.request'].with_context(
            syncing_from_devops=True).create({
            'name': 'Add Feature X',
            'server_id': self.server.id,
            'repository_id': self.repo.id,
            'project_id': self.project.id,
            'number': '56',
            'external_id': '999056',
            'state': 'open',
        })

        with patch(
                'odoo.addons.odoo_devops_bridge.services.odoo_devops_bridge_github_client.OdooDevOpsBridgeGitHubClient.create_issue_comment',
                return_value={'id': 77702},
        ) as mock_comment:
            msg = pr.with_context(syncing_from_devops=False).message_post(
                body='<p>Thanks for the feedback, updating now!</p>', message_type='comment')
            mock_comment.assert_called_once()
            args, _ = mock_comment.call_args
            self.assertEqual(args[0], 'octocat')
            self.assertEqual(args[1], 'hello-world')
            self.assertEqual(args[2], 56)
            self.assertIn('Thanks for the feedback', args[3])
            self.assertTrue(msg.devops_synced)
            self.assertEqual(msg.devops_external_id, '77702')

    def test_16_inbound_pr_reviews_assignees_labels_milestones(self):
        """Inbound pull request webhook and review webhooks should populate assignees,
        reviewers, labels, milestones, and review status."""
        milestone = self.env['project.milestone'].create({
            'name': 'v2.0 Release',
            'project_id': self.project.id,
            'devops_server_id': self.server.id,
            'devops_repo_id': self.repo.id,
            'devops_external_id': '101',
        })
        user = self.env['res.users'].create({
            'name': 'Dev Lead',
            'login': 'devlead',
            'email': 'devlead@example.com',
        })
        self.env['odoo_devops_bridge.account'].create({
            'server_id': self.server.id,
            'user_id': user.id,
            'external_username': 'devlead_gh',
            'account_type': 'personal',
            'token': 'lead-token',
            'state': 'valid',
        })

        pr_payload = {
            'action': 'opened',
            'repository': {'full_name': 'octocat/hello-world'},
            'pull_request': {
                'id': 999060,
                'number': 60,
                'title': 'Feature: Awesome Core',
                'body': 'Implements core feature',
                'state': 'open',
                'assignees': [{'login': 'devlead_gh'}],
                'requested_reviewers': [{'login': 'devlead_gh'}],
                'labels': [{'name': 'feature'}, {'name': 'backend'}],
                'milestone': {'id': 101},
                'html_url': 'https://github.com/octocat/hello-world/pull/60',
            },
        }
        res = OdooDevOpsBridgeSyncManager.process_github_event(self.env, self.server,
                                                               'pull_request', pr_payload)
        self.assertEqual(res['status'], 'success')

        pr = self.env['odoo_devops_bridge.pull.request'].search([('external_id', '=', '999060')])
        self.assertTrue(pr)
        self.assertIn(user, pr.user_ids)
        self.assertIn(user, pr.reviewer_ids)
        self.assertIn('feature', pr.tag_ids.mapped('name'))
        self.assertIn('backend', pr.tag_ids.mapped('name'))
        self.assertEqual(pr.milestone_id, milestone)

        # Now test review event
        review_payload = {
            'action': 'submitted',
            'repository': {'full_name': 'octocat/hello-world'},
            'pull_request': {'number': 60},
            'review': {
                'id': 88801,
                'state': 'APPROVED',
                'body': 'Looks stellar, approved!',
                'user': {'login': 'devlead_gh'},
            },
        }
        res_review = OdooDevOpsBridgeSyncManager.process_github_event(self.env, self.server,
                                                                      'pull_request_review',
                                                                      review_payload)
        self.assertEqual(res_review['status'], 'success')
        self.assertEqual(pr.review_status, 'approved')

    def test_17_pr_merge_action_and_task_closure(self):
        """Merging a PR from Odoo should call provider merge API, mark PR as merged,
        and close linked task if closed stage is configured."""
        stage_closed = self.env['project.task.type'].create(
            {'name': 'Done', 'project_ids': [(4, self.project.id)]})
        self.repo.write({'closed_stage_id': stage_closed.id})

        task = self.env['project.task'].create({
            'name': 'Linked Bug Task',
            'project_id': self.project.id,
            'devops_repo_id': self.repo.id,
            'devops_server_id': self.server.id,
            'devops_issue_number': '77',
            'devops_external_id': '555077',
        })
        pr = self.env['odoo_devops_bridge.pull.request'].with_context(
            syncing_from_devops=True).create({
            'name': 'Fix for bug #77',
            'server_id': self.server.id,
            'repository_id': self.repo.id,
            'project_id': self.project.id,
            'task_id': task.id,
            'number': '77',
            'external_id': '999077',
            'state': 'open',
        })

        with patch(
                'odoo.addons.odoo_devops_bridge.services.odoo_devops_bridge_github_client.OdooDevOpsBridgeGitHubClient.merge_pull_request',
                return_value={'sha': 'abcdef123456', 'merged': True},
        ) as mock_merge:
            pr.action_merge_pr()
            mock_merge.assert_called_once_with('octocat', 'hello-world', 77)
            self.assertEqual(pr.state, 'merged')
            self.assertTrue(pr.is_merged)
            self.assertEqual(pr.merge_commit_sha, 'abcdef123456')
            self.assertEqual(task.stage_id, stage_closed)

    def test_18_pr_close_and_reopen_actions(self):
        """Closing and reopening PRs from Odoo should invoke remote API and update state."""
        pr = self.env['odoo_devops_bridge.pull.request'].with_context(
            syncing_from_devops=True).create({
            'name': 'Test Close PR',
            'server_id': self.server.id,
            'repository_id': self.repo.id,
            'project_id': self.project.id,
            'number': '88',
            'external_id': '999088',
            'state': 'open',
        })

        with patch(
                'odoo.addons.odoo_devops_bridge.services.odoo_devops_bridge_github_client.OdooDevOpsBridgeGitHubClient.update_pull_request') as mock_update:
            pr.action_close_pr()
            mock_update.assert_called_once_with('octocat', 'hello-world', 88, state='closed')
            self.assertEqual(pr.state, 'closed')

        with patch(
                'odoo.addons.odoo_devops_bridge.services.odoo_devops_bridge_github_client.OdooDevOpsBridgeGitHubClient.update_pull_request') as mock_update:
            pr.action_reopen_pr()
            mock_update.assert_called_once_with('octocat', 'hello-world', 88, state='open')
            self.assertEqual(pr.state, 'open')

    def test_19_task_close_and_reopen_actions(self):
        """Closing and reopening task issues from Odoo should invoke remote API and update state/stage."""
        stage_open = self.env['project.task.type'].create(
            {'name': 'To Do', 'project_ids': [(4, self.project.id)]})
        stage_closed = self.env['project.task.type'].create(
            {'name': 'Done', 'project_ids': [(4, self.project.id)]})
        self.repo.write({'open_stage_id': stage_open.id, 'closed_stage_id': stage_closed.id})

        task = self.env['project.task'].create({
            'name': 'Closeable Issue Task',
            'project_id': self.project.id,
            'devops_repo_id': self.repo.id,
            'devops_server_id': self.server.id,
            'devops_issue_number': '99',
            'devops_external_id': '555099',
            'stage_id': stage_open.id,
        })

        with patch(
                'odoo.addons.odoo_devops_bridge.services.odoo_devops_bridge_github_client.OdooDevOpsBridgeGitHubClient.update_issue') as mock_update:
            task.action_close_devops_issue()
            mock_update.assert_called_once_with('octocat', 'hello-world', 99, state='closed')
            self.assertEqual(task.stage_id, stage_closed)

        with patch(
                'odoo.addons.odoo_devops_bridge.services.odoo_devops_bridge_github_client.OdooDevOpsBridgeGitHubClient.update_issue') as mock_update:
            task.action_reopen_devops_issue()
            mock_update.assert_called_once_with('octocat', 'hello-world', 99, state='open')
            self.assertEqual(task.stage_id, stage_open)
