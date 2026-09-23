# Part of Odoo DevOps Bridge. See LICENSE file for full copyright and licensing details.

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

_logger = logging.getLogger(__name__)


class OdooDevOpsBridgeAPIError(Exception):
    """Base exception for DevOps API client errors."""

    def __init__(self, message, status_code=None, response_body=None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class OdooDevOpsBridgeAuthError(OdooDevOpsBridgeAPIError):
    """Authentication or authorization failure."""
    pass


class OdooDevOpsBridgeNotFoundError(OdooDevOpsBridgeAPIError):
    """Resource not found (404)."""
    pass


class OdooDevOpsBridgeRateLimitError(OdooDevOpsBridgeAPIError):
    """API rate limit exceeded (429 or provider equivalent)."""
    pass


class OdooDevOpsBridgeBaseClient:
    """
    Abstract base HTTP client for communicating with DevOps providers
    (GitHub, GitLab, YouTrack). Uses standard Python urllib to remain zero-dependency
    and fully compatible across all Odoo environments.
    """

    def __init__(self, base_url, token, timeout=30, verify_ssl=True):
        self.base_url = (base_url or '').rstrip('/')
        self.token = token or ''
        self.timeout = timeout
        self.verify_ssl = verify_ssl

    def _get_headers(self):
        """Override in subclasses to provide provider-specific headers."""
        return {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'User-Agent': 'Odoo-DevOps-Bridge/19.2',
        }

    def _request(self, method, endpoint, params=None, data=None, extra_headers=None):
        """
        Execute an HTTP request and return parsed JSON data.
        """
        url = endpoint if endpoint.startswith(
            ('http://', 'https://')) else f"{self.base_url}/{endpoint.lstrip('/')}"
        if params:
            query_string = urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None})
            if query_string:
                url = f"{url}?{query_string}" if '?' not in url else f"{url}&{query_string}"

        headers = self._get_headers()
        if extra_headers:
            headers.update(extra_headers)

        payload_bytes = None
        if data is not None:
            if isinstance(data, (dict, list)):
                payload_bytes = json.dumps(data).encode('utf-8')
            elif isinstance(data, str):
                payload_bytes = data.encode('utf-8')
            elif isinstance(data, bytes):
                payload_bytes = data

        req = urllib.request.Request(url, data=payload_bytes, headers=headers,
                                     method=method.upper())

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                status_code = response.getcode()
                raw_response = response.read().decode('utf-8')
                if not raw_response or status_code == 204:
                    return {}
                try:
                    return json.loads(raw_response)
                except json.JSONDecodeError:
                    return {'raw_content': raw_response}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8', errors='replace')
            _logger.warning("DevOps API HTTP error [%s %s]: %s - %s", method, url, e.code, err_body)
            if e.code in (401, 403):
                raise OdooDevOpsBridgeAuthError(f"Authentication failed: {e.reason}",
                                                status_code=e.code,
                                                response_body=err_body)
            elif e.code == 404:
                raise OdooDevOpsBridgeNotFoundError(f"Resource not found: {url}",
                                                    status_code=e.code,
                                                    response_body=err_body)
            elif e.code in (429, 403) and 'rate limit' in err_body.lower():
                raise OdooDevOpsBridgeRateLimitError(f"Rate limit exceeded: {err_body}",
                                                     status_code=e.code,
                                                     response_body=err_body)
            raise OdooDevOpsBridgeAPIError(f"API HTTP Error {e.code}: {e.reason}",
                                           status_code=e.code,
                                           response_body=err_body)
        except urllib.error.URLError as e:
            _logger.error("DevOps API connection error [%s %s]: %s", method, url, e.reason)
            raise OdooDevOpsBridgeAPIError(f"Connection failed: {e.reason}")
        except Exception as e:
            _logger.exception("Unexpected error in DevOps client: %s", str(e))
            raise OdooDevOpsBridgeAPIError(f"Unexpected error: {str(e)}")
