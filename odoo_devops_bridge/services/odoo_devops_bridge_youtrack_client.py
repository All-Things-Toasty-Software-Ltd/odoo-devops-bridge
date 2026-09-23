# Part of Odoo. See LICENSE file for full copyright and licensing details.

import hmac
import logging

from .odoo_devops_bridge_base_client import OdooDevOpsBridgeBaseClient

_logger = logging.getLogger(__name__)


class OdooDevOpsBridgeYouTrackClient(OdooDevOpsBridgeBaseClient):
    """
    REST API Client for JetBrains YouTrack Cloud and YouTrack Standalone Server.
    Default endpoint: /api
    Authentication: Bearer <Permanent_Token>
    """

    def __init__(self, base_url, token=None, timeout=30):
        clean_url = (base_url or "").rstrip('/')
        if not clean_url.endswith('/api'):
            clean_url = f"{clean_url}/api"
        super().__init__(base_url=clean_url, token=token, timeout=timeout)

    def _get_headers(self):
        headers = super()._get_headers()
        if self.token:
            headers['Authorization'] = f"Bearer {self.token}"
        return headers

    @staticmethod
    def verify_webhook_token(token_header_or_param, secret):
        """
        Verify secret token sent by YouTrack webhook / workflow HTTP request.
        """
        if not token_header_or_param or not secret:
            return False
        # Remove 'Bearer ' prefix if present
        token = token_header_or_param.replace('Bearer ', '').strip()
        return hmac.compare_digest(token, secret.strip())

    def test_connection(self):
        """Validate token by retrieving current authenticated user."""
        params = {'fields': 'id,login,name,email'}
        return self._request('GET', 'users/me', params=params)

    def get_projects(self, top=100):
        """Fetch YouTrack projects."""
        params = {
            'fields': 'id,name,shortName,description,leader(name,login)',
            '$top': top,
        }
        return self._request('GET', 'admin/projects', params=params)

    def get_project(self, project_id):
        """Get single project."""
        params = {'fields': 'id,name,shortName,description,leader(name,login)'}
        return self._request('GET', f"admin/projects/{project_id}", params=params)

    def get_issues(self, query=None, top=50):
        """
        Search YouTrack issues using query syntax (e.g. 'project: PRJ order by: updated desc').
        """
        params = {
            'fields': 'id,idReadable,summary,description,created,updated,resolved,project(id,shortName,name),customFields(name,value(name,id,login,text)),tags(name)',
            '$top': top,
        }
        if query:
            params['query'] = query
        return self._request('GET', 'issues', params=params)

    def get_issue(self, issue_id):
        """Fetch single YouTrack issue by ID or readable ID (e.g. 'PRJ-123')."""
        params = {
            'fields': 'id,idReadable,summary,description,created,updated,resolved,project(id,shortName,name),customFields(name,value(name,id,login,text)),tags(name)'}
        return self._request('GET', f"issues/{issue_id}", params=params)

    def create_issue(self, project_id_or_shortname, summary, description=None, custom_fields=None):
        """
        Create a new YouTrack issue.
        """
        data = {
            'project': {
                'id': project_id_or_shortname} if not project_id_or_shortname.isalnum() else {
                'shortName': project_id_or_shortname},
            'summary': summary,
        }
        if description:
            data['description'] = description
        if custom_fields:
            data['customFields'] = custom_fields

        params = {'fields': 'id,idReadable,summary,description'}
        return self._request('POST', 'issues', params=params, data=data)

    def update_issue(self, issue_id, summary=None, description=None, custom_fields=None):
        """
        Update an existing YouTrack issue.
        """
        data = {}
        if summary is not None:
            data['summary'] = summary
        if description is not None:
            data['description'] = description
        if custom_fields:
            data['customFields'] = custom_fields

        params = {'fields': 'id,idReadable,summary,description'}
        return self._request('POST', f"issues/{issue_id}", params=params, data=data)

    def get_issue_comments(self, issue_id):
        """Get comments for issue."""
        params = {'fields': 'id,text,created,author(name,login)'}
        return self._request('GET', f"issues/{issue_id}/comments", params=params)

    def create_issue_comment(self, issue_id, text):
        """Post a comment to a YouTrack issue."""
        data = {'text': text}
        params = {'fields': 'id,text,created,author(name,login)'}
        return self._request('POST', f"issues/{issue_id}/comments", params=params, data=data)

    def get_versions(self, project_id):
        """Fetch project versions (milestones) bundle."""
        params = {'fields': 'id,name,archived,released,releaseDate'}
        return self._request('GET', f"admin/projects/{project_id}/versionBundle/values",
                             params=params)
