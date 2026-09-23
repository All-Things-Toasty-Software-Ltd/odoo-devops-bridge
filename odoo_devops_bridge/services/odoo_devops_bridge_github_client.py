# Part of Odoo DevOps Bridge. See LICENSE file for full copyright and licensing details.

import hmac
import hashlib
import logging
from .odoo_devops_bridge_base_client import OdooDevOpsBridgeBaseClient, OdooDevOpsBridgeAPIError

_logger = logging.getLogger(__name__)


class OdooDevOpsBridgeGitHubClient(OdooDevOpsBridgeBaseClient):
    """
    REST API Client for GitHub SaaS (api.github.com) and GitHub Enterprise Server.
    """

    def __init__(self, base_url="https://api.github.com", token=None, timeout=30):
        # Normalize base_url for GitHub Enterprise Server vs GitHub.com
        clean_url = (base_url or "https://api.github.com").rstrip('/')
        if clean_url in ("https://github.com", "http://github.com"):
            clean_url = "https://api.github.com"
        elif not clean_url.endswith('/api/v3') and clean_url != "https://api.github.com":
            clean_url = f"{clean_url}/api/v3"
        super().__init__(base_url=clean_url, token=token, timeout=timeout)

    def _get_headers(self):
        headers = super()._get_headers()
        headers['Accept'] = 'application/vnd.github+json'
        headers['X-GitHub-Api-Version'] = '2022-11-28'
        if self.token:
            headers['Authorization'] = f"Bearer {self.token}"
        return headers

    @staticmethod
    def verify_webhook_signature(payload_bytes, signature_header, secret):
        """
        Verify GitHub HMAC SHA-256 webhook signature.
        Header format: sha256=<hex_digest>
        """
        if not signature_header or not secret:
            return False
        if not signature_header.startswith('sha256='):
            return False
        expected_sig = signature_header[7:]
        mac = hmac.new(secret.encode('utf-8'), msg=payload_bytes, digestmod=hashlib.sha256)
        computed_sig = mac.hexdigest()
        return hmac.compare_digest(computed_sig, expected_sig)

    def test_connection(self):
        """Validate token by retrieving current authenticated user."""
        return self._request('GET', 'user')

    def get_organizations(self):
        """List organizations for the authenticated user."""
        return self._request('GET', 'user/orgs')

    def get_repositories(self, org=None, per_page=100):
        """Fetch repositories for user or organization."""
        endpoint = f"orgs/{org}/repos" if org else "user/repos"
        params = {'per_page': per_page, 'sort': 'updated'}
        return self._request('GET', endpoint, params=params)

    def get_repository(self, owner, repo):
        """Get repository metadata."""
        return self._request('GET', f"repos/{owner}/{repo}")

    def get_issues(self, owner, repo, state='all', since=None, per_page=50):
        """Get repository issues (excludes PRs by default in caller logic)."""
        params = {'state': state, 'per_page': per_page}
        if since:
            params['since'] = since
        return self._request('GET', f"repos/{owner}/{repo}/issues", params=params)

    def get_issue(self, owner, repo, issue_number):
        """Fetch single issue."""
        return self._request('GET', f"repos/{owner}/{repo}/issues/{issue_number}")

    def create_issue(self, owner, repo, title, body=None, assignees=None, labels=None, milestone=None):
        """Create new issue in GitHub repository."""
        data = {'title': title}
        if body:
            data['body'] = body
        if assignees:
            data['assignees'] = assignees if isinstance(assignees, list) else [assignees]
        if labels:
            data['labels'] = labels if isinstance(labels, list) else [labels]
        if milestone:
            data['milestone'] = int(milestone)
        return self._request('POST', f"repos/{owner}/{repo}/issues", data=data)

    def update_issue(self, owner, repo, issue_number, title=None, body=None, state=None, assignees=None, labels=None, milestone=None):
        """Update existing issue in GitHub repository."""
        data = {}
        if title is not None:
            data['title'] = title
        if body is not None:
            data['body'] = body
        if state is not None:
            data['state'] = state
        if assignees is not None:
            data['assignees'] = assignees if isinstance(assignees, list) else [assignees]
        if labels is not None:
            data['labels'] = labels if isinstance(labels, list) else [labels]
        if milestone is not None:
            data['milestone'] = int(milestone) if milestone else None
        return self._request('PATCH', f"repos/{owner}/{repo}/issues/{issue_number}", data=data)

    def get_issue_comments(self, owner, repo, issue_number, per_page=100):
        """Fetch comments for issue or PR."""
        params = {'per_page': per_page}
        return self._request('GET', f"repos/{owner}/{repo}/issues/{issue_number}/comments", params=params)

    def create_issue_comment(self, owner, repo, issue_number, body):
        """Post a comment to an issue or PR."""
        data = {'body': body}
        return self._request('POST', f"repos/{owner}/{repo}/issues/{issue_number}/comments", data=data)

    def get_pull_requests(self, owner, repo, state='all', per_page=50):
        """List pull requests in repository."""
        params = {'state': state, 'per_page': per_page}
        return self._request('GET', f"repos/{owner}/{repo}/pulls", params=params)

    def get_pull_request(self, owner, repo, pull_number):
        """Get single pull request details."""
        return self._request('GET', f"repos/{owner}/{repo}/pulls/{pull_number}")

    def update_pull_request(self, owner, repo, pull_number, title=None, body=None, state=None, base=None):
        """Update pull request attributes (title, body, state: 'open' or 'closed', base branch)."""
        data = {}
        if title is not None:
            data['title'] = title
        if body is not None:
            data['body'] = body
        if state is not None:
            data['state'] = state
        if base is not None:
            data['base'] = base
        return self._request('PATCH', f"repos/{owner}/{repo}/pulls/{pull_number}", data=data)

    def merge_pull_request(self, owner, repo, pull_number, commit_title=None, commit_message=None, merge_method='merge'):
        """Merge a pull request. merge_method can be 'merge', 'squash', or 'rebase'."""
        data = {'merge_method': merge_method}
        if commit_title:
            data['commit_title'] = commit_title
        if commit_message:
            data['commit_message'] = commit_message
        return self._request('PUT', f"repos/{owner}/{repo}/pulls/{pull_number}/merge", data=data)

    def get_pull_request_reviews(self, owner, repo, pull_number):
        """Fetch reviews for a pull request."""
        return self._request('GET', f"repos/{owner}/{repo}/pulls/{pull_number}/reviews")

    def get_pull_request_comments(self, owner, repo, pull_number, per_page=100):
        """Fetch review comments on the pull request diff."""
        params = {'per_page': per_page}
        return self._request('GET', f"repos/{owner}/{repo}/pulls/{pull_number}/comments", params=params)

    def get_milestones(self, owner, repo, state='all', per_page=100):
        """List milestones in repository."""
        params = {'state': state, 'per_page': per_page}
        return self._request('GET', f"repos/{owner}/{repo}/milestones", params=params)

    def create_milestone(self, owner, repo, title, description=None, due_on=None):
        """Create a new milestone."""
        data = {'title': title}
        if description:
            data['description'] = description
        if due_on:
            data['due_on'] = due_on
        return self._request('POST', f"repos/{owner}/{repo}/milestones", data=data)

    def update_milestone(self, owner, repo, milestone_number, title=None, description=None, due_on=None, state=None):
        """Update a milestone."""
        data = {}
        if title is not None:
            data['title'] = title
        if description is not None:
            data['description'] = description
        if due_on is not None:
            data['due_on'] = due_on
        if state is not None:
            data['state'] = state
        return self._request('PATCH', f"repos/{owner}/{repo}/milestones/{milestone_number}", data=data)
