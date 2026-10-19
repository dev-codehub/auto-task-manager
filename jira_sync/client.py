from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Sequence

TIMEOUT = 30
API = "/rest/api/3"
PAGE = 50
SEARCH_PAGE = 100


class JiraError(Exception):
    pass


class AuthError(JiraError):
    pass


class ForbiddenError(JiraError):
    pass


class NotFoundError(JiraError):
    pass


class RejectedError(JiraError):
    pass


class TransportError(JiraError):
    pass


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """urllib would re-send the Authorization header to whatever host a redirect names."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


def _quote(value: str) -> str:
    return urllib.parse.quote(str(value), safe="")


class Client:
    def __init__(self, base_url: str, email: str, token: str, timeout: float = TIMEOUT):
        self._base = base_url.rstrip("/")
        self._auth = "Basic " + base64.b64encode(f"{email}:{token}".encode("utf-8")).decode("ascii")
        self._timeout = timeout
        self._opener = urllib.request.build_opener(_RefuseRedirects())

    def myself(self) -> dict:
        return self._request("GET", f"{API}/myself")

    def get_project(self, key: str) -> dict:
        return self._request("GET", f"{API}/project/{_quote(key)}")

    def issue_types(self, project: str) -> List[dict]:
        return self._paged(f"{API}/issue/createmeta/{_quote(project)}/issuetypes", "issueTypes")

    def create_screen_fields(self, project: str, type_id: str) -> List[dict]:
        return self._paged(
            f"{API}/issue/createmeta/{_quote(project)}/issuetypes/{_quote(type_id)}", "fields")

    def search(self, jql: str, fields: Sequence[str]) -> List[dict]:
        issues: List[dict] = []
        token: Optional[str] = None
        while True:
            body: Dict[str, Any] = {"jql": jql, "fields": list(fields),
                                    "maxResults": SEARCH_PAGE}
            if token:
                body["nextPageToken"] = token
            page = self._request("POST", f"{API}/search/jql", body)
            issues += page.get("issues", [])
            token = page.get("nextPageToken")
            if not token or page.get("isLast"):
                return issues

    def get_issue(self, key: str, fields: Sequence[str] = ("*all",)) -> dict:
        query = urllib.parse.urlencode({"fields": ",".join(fields)})
        return self._request("GET", f"{API}/issue/{_quote(key)}?{query}")

    def create_issue(self, fields: Dict[str, Any]) -> dict:
        return self._request("POST", f"{API}/issue", {"fields": fields})

    def update_issue(self, key: str, fields: Dict[str, Any]) -> None:
        self._request("PUT", f"{API}/issue/{_quote(key)}", {"fields": fields})

    def list_comments(self, key: str) -> List[dict]:
        return self._paged(f"{API}/issue/{_quote(key)}/comment", "comments")

    def add_comment(self, key: str, adf: dict) -> dict:
        return self._request("POST", f"{API}/issue/{_quote(key)}/comment", adf)

    def transitions(self, key: str) -> List[dict]:
        query = urllib.parse.urlencode({"expand": "transitions.fields"})
        return self._request(
            "GET", f"{API}/issue/{_quote(key)}/transitions?{query}").get("transitions", [])

    def do_transition(self, key: str, transition_id: str, fields: Dict[str, Any]) -> None:
        body: Dict[str, Any] = {"transition": {"id": str(transition_id)}}
        if fields:
            body["fields"] = fields
        self._request("POST", f"{API}/issue/{_quote(key)}/transitions", body)

    def list_fields(self) -> List[dict]:
        return self._request("GET", f"{API}/field")

    def link_types(self) -> List[dict]:
        return self._request("GET", f"{API}/issueLinkType").get("issueLinkTypes", [])

    def create_link(self, type_name: str, inward_key: str, outward_key: str) -> None:
        self._request("POST", f"{API}/issueLink", {
            "type": {"name": type_name},
            "inwardIssue": {"key": inward_key},
            "outwardIssue": {"key": outward_key}})

    def write_and_reread(self, key: str, fields: Dict[str, Any]) -> dict:
        """update_issue then get_issue: a write is only ever trusted once read
        back - Jira answers success to a PUT and silently drops a field that is
        not on the issue's edit screen."""
        self.update_issue(key, fields)
        return self.get_issue(key)

    def _paged(self, path: str, items_key: str) -> List[dict]:
        """Follow startAt/maxResults pages (createmeta, comments) until total."""
        out: List[dict] = []
        while True:
            query = urllib.parse.urlencode({"startAt": len(out), "maxResults": PAGE})
            page = self._request("GET", f"{path}?{query}")
            got = page.get(items_key, [])
            out += got
            if not got or len(out) >= page.get("total", 0):
                return out

    def _request(self, method: str, path: str, payload: Optional[dict] = None) -> Any:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self._base + path, data=data, method=method)
        req.add_header("Authorization", self._auth)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        failure: Optional[JiraError] = None
        try:
            with self._opener.open(req, timeout=self._timeout) as resp:
                body = resp.read()
        except urllib.error.HTTPError as e:
            failure = self._http_error(e, method, path)
            e.close()
        except urllib.error.URLError as e:
            failure = TransportError(f"cannot reach {self._base} ({e.reason})")
        except OSError as e:
            failure = TransportError(f"cannot reach {self._base} ({e})")
        # Raised outside the except block so the error carries no __context__:
        # an HTTPError there would keep its connection open until collected.
        if failure is not None:
            raise failure
        if not body:
            return {}
        try:
            return json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise TransportError(
                f"{self._base} did not answer with JSON ({method} {path.split('?', 1)[0]}) - "
                f"check that 'url' is the Jira site root and that no login page is in the way"
            ) from None

    def _http_error(self, e: urllib.error.HTTPError, method: str, path: str) -> JiraError:
        where = f"{method} {path.split('?', 1)[0]}"
        if 300 <= e.code < 400:
            return TransportError(
                f"{where} was redirected to {e.headers.get('Location', '?')}; the API token is "
                f"not sent on to another address - set 'url' in .jira.json to the final one")
        if e.code == 401:
            return AuthError("the API token was rejected (missing, wrong or revoked, or the "
                             "email does not match the token)")
        if e.code == 403:
            return ForbiddenError(f"your account is not allowed to do this ({where})")
        if e.code == 404:
            return NotFoundError(f"not found ({where})")
        if e.code in (400, 422):
            return RejectedError(f"Jira rejected {where}: {self._reason(e)}")
        return TransportError(f"Jira answered HTTP {e.code} to {where}")

    @staticmethod
    def _reason(e: urllib.error.HTTPError) -> str:
        try:
            body = json.loads(e.read().decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return "no reason given"
        if not isinstance(body, dict):
            return "no reason given"
        parts = [str(m) for m in body.get("errorMessages") or []]
        errors = body.get("errors")
        if isinstance(errors, dict):
            parts += [f"{name}: {text}" for name, text in errors.items()]
        return "; ".join(parts) or "no reason given"
