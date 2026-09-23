# Part of Odoo DevOps Bridge. See LICENSE file for full copyright and licensing details.

import hmac
import logging
import urllib.parse

from .odoo_devops_bridge_base_client import OdooDevOpsBridgeBaseClient

_logger = logging.getLogger(__name__)


class OdooDevOpsBridgeGitLabClient(OdooDevOpsBridgeBaseClient):
    """
    REST API Client for GitLab SaaS (gitlab.com) and GitLab CE/EE Self-Hosted.
    Default API endpoint: /api/v4
    """

    def __init__(self, base_url="https://gitlab.com", token=None, timeout=30):
        clean_url = (base_url or "https://gitlab.com").rstrip('/')
        if not clean_url.endswith('/api/v4'):
            clean_url = f"{clean_url}/api/v4"
        super().__init__(base_url=clean_url, token=token, timeout=timeout)

    def _get_headers(self):
        headers = super()._get_headers()
        if self.token:
            headers['PRIVATE-TOKEN'] = self.token
        return headers

    @staticmethod
    def verify_webhook_token(token_header, secret):
        """
        Verify GitLab secret token passed via 'X-Gitlab-Token' header.
        """
        if not token_header or not secret:
            return False
        return hmac.compare_digest(token_header.strip(), secret.strip())

    def _encode_id(self, project_id_or_path):
        """URL-encode project path (e.g. 'group/subgroup/project' -> 'group%2Fsubgroup%2Fproject')."""
        if isinstance(project_id_or_path, str) and '/' in project_id_or_path:
            return urllib.parse.quote(project_id_or_path, safe='')
        return str(project_id_or_path)

    def test_connection(self):
        """Validate token by fetching current user profile."""
        return self._request('GET', 'user')

    def get_groups(self, per_page=100):
        """List groups (teams/organizations) accessible to user."""
        params = {'per_page': per_page}
        return self._request('GET', 'groups', params=params)

    def get_projects(self, membership=True, per_page=100):
        """Fetch accessible GitLab projects."""
        params = {'membership': 'true' if membership else 'false', 'per_page': per_page,
                  'order_by': 'last_activity_at'}
        return self._request('GET', 'projects', params=params)

    def get_project(self, project_id_or_path):
        """Get project details."""
        encoded = self._encode_id(project_id_or_path)
        return self._request('GET', f"projects/{encoded}")

    def get_issues(self, project_id_or_path, state='all', updated_after=None, per_page=50):
        """Fetch issues in project."""
        encoded = self._encode_id(project_id_or_path)
        params = {'state': state, 'per_page': per_page}
        if updated_after:
            params['updated_after'] = updated_after
        return self._request('GET', f"projects/{encoded}/issues", params=params)

    def get_issue(self, project_id_or_path, issue_iid):
        """Fetch single issue by internal IID."""
        encoded = self._encode_id(project_id_or_path)
        return self._request('GET', f"projects/{encoded}/issues/{issue_iid}")

    def create_issue(self, project_id_or_path, title, description=None, labels=None,
                     assignee_ids=None, milestone_id=None):
        """Create new issue in GitLab project."""
        encoded = self._encode_id(project_id_or_path)
        data = {'title': title}
        if description:
            data['description'] = description
        if labels:
            data['labels'] = ','.join(labels) if isinstance(labels, list) else labels
        if assignee_ids:
            data['assignee_ids'] = assignee_ids if isinstance(assignee_ids, list) else [
                assignee_ids]
        if milestone_id:
            data['milestone_id'] = int(milestone_id)
        return self._request('POST', f"projects/{encoded}/issues", data=data)

    def update_issue(self, project_id_or_path, issue_iid, title=None, description=None,
                     state_event=None, labels=None, assignee_ids=None, milestone_id=None):
        """Update existing issue in GitLab."""
        encoded = self._encode_id(project_id_or_path)
        data = {}
        if title is not None:
            data['title'] = title
        if description is not None:
            data['description'] = description
        if state_event in ('close', 'reopen'):
            data['state_event'] = state_event
        if labels is not None:
            data['labels'] = ','.join(labels) if isinstance(labels, list) else labels
        if assignee_ids is not None:
            data['assignee_ids'] = assignee_ids if isinstance(assignee_ids, list) else [
                assignee_ids]
        if milestone_id is not None:
            data['milestone_id'] = int(milestone_id) if milestone_id else None
        return self._request('PUT', f"projects/{encoded}/issues/{issue_iid}", data=data)

    def get_issue_notes(self, project_id_or_path, issue_iid, per_page=100):
        """Fetch comments (notes) on issue."""
        encoded = self._encode_id(project_id_or_path)
        params = {'per_page': per_page, 'sort': 'asc'}
        return self._request('GET', f"projects/{encoded}/issues/{issue_iid}/notes", params=params)

    def create_issue_note(self, project_id_or_path, issue_iid, body):
        """Post a comment (note) to an issue."""
        encoded = self._encode_id(project_id_or_path)
        data = {'body': body}
        return self._request('POST', f"projects/{encoded}/issues/{issue_iid}/notes", data=data)

    def get_merge_requests(self, project_id_or_path, state='all', per_page=50):
        """List merge requests for project."""
        encoded = self._encode_id(project_id_or_path)
        params = {'state': state, 'per_page': per_page}
        return self._request('GET', f"projects/{encoded}/merge_requests", params=params)

    def get_merge_request(self, project_id_or_path, mr_iid):
        """Fetch single merge request."""
        encoded = self._encode_id(project_id_or_path)
        return self._request('GET', f"projects/{encoded}/merge_requests/{mr_iid}")

    def update_merge_request(self, project_id_or_path, mr_iid, title=None, description=None,
                             state_event=None, target_branch=None, labels=None, assignee_ids=None,
                             reviewer_ids=None, milestone_id=None):
        """Update merge request attributes in GitLab."""
        encoded = self._encode_id(project_id_or_path)
        data = {}
        if title is not None:
            data['title'] = title
        if description is not None:
            data['description'] = description
        if state_event in ('close', 'reopen'):
            data['state_event'] = state_event
        if target_branch is not None:
            data['target_branch'] = target_branch
        if labels is not None:
            data['labels'] = ','.join(labels) if isinstance(labels, list) else labels
        if assignee_ids is not None:
            data['assignee_ids'] = assignee_ids if isinstance(assignee_ids, list) else [
                assignee_ids]
        if reviewer_ids is not None:
            data['reviewer_ids'] = reviewer_ids if isinstance(reviewer_ids, list) else [
                reviewer_ids]
        if milestone_id is not None:
            data['milestone_id'] = int(milestone_id) if milestone_id else None
        return self._request('PUT', f"projects/{encoded}/merge_requests/{mr_iid}", data=data)

    def merge_merge_request(self, project_id_or_path, mr_iid, commit_message=None, squash=False):
        """Accept and merge a merge request in GitLab."""
        encoded = self._encode_id(project_id_or_path)
        data = {}
        if commit_message:
            data['merge_commit_message'] = commit_message
        if squash:
            data['squash'] = True
        return self._request('PUT', f"projects/{encoded}/merge_requests/{mr_iid}/merge", data=data)

    def get_merge_request_notes(self, project_id_or_path, mr_iid, per_page=100):
        """Fetch comments (notes) on a merge request."""
        encoded = self._encode_id(project_id_or_path)
        params = {'per_page': per_page, 'sort': 'asc'}
        return self._request('GET', f"projects/{encoded}/merge_requests/{mr_iid}/notes",
                             params=params)

    def create_merge_request_note(self, project_id_or_path, mr_iid, body):
        """Post a comment (note) to a merge request."""
        encoded = self._encode_id(project_id_or_path)
        data = {'body': body}
        return self._request('POST', f"projects/{encoded}/merge_requests/{mr_iid}/notes", data=data)

    def get_milestones(self, project_id_or_path, state='all', per_page=100):
        """List milestones in GitLab project."""
        encoded = self._encode_id(project_id_or_path)
        params = {'state': state, 'per_page': per_page}
        return self._request('GET', f"projects/{encoded}/milestones", params=params)

    def create_milestone(self, project_id_or_path, title, description=None, due_date=None):
        """Create milestone in GitLab project."""
        encoded = self._encode_id(project_id_or_path)
        data = {'title': title}
        if description:
            data['description'] = description
        if due_date:
            data['due_date'] = due_date
        return self._request('POST', f"projects/{encoded}/milestones", data=data)

    def update_milestone(self, project_id_or_path, milestone_id, title=None, description=None,
                         due_date=None, state_event=None):
        """Update milestone in GitLab project."""
        encoded = self._encode_id(project_id_or_path)
        data = {}
        if title is not None:
            data['title'] = title
        if description is not None:
            data['description'] = description
        if due_date is not None:
            data['due_date'] = due_date
        if state_event in ('close', 'activate'):
            data['state_event'] = state_event
        return self._request('PUT', f"projects/{encoded}/milestones/{milestone_id}", data=data)
