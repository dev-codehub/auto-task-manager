from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Sequence

TIMEOUT = 30
RELATION_TYPES = ("relates", "duplicates", "blocks", "precedes")


class RedmineError(Exception):
    pass


class AuthError(RedmineError):
    pass


class ForbiddenError(RedmineError):
    pass


class NotFoundError(RedmineError):
    pass


class RejectedError(RedmineError):
    pass


class TransportError(RedmineError):
    pass


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """urllib would re-send the API key header to whatever host a redirect names."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


class Client:
    def __init__(self, base_url: str, api_key: str, timeout: float = TIMEOUT):
        self._base = base_url.rstrip("/")
        self._key = api_key
        self._timeout = timeout
        self._opener = urllib.request.build_opener(_RefuseRedirects())

    def current_user(self) -> dict:
        return self._request("GET", "/users/current.json")["user"]

    def get_project(self, identifier: str, include: Sequence[str] = ()) -> dict:
        path = f"/projects/{urllib.parse.quote(identifier, safe='')}.json"
        if include:
            path += f"?include={','.join(include)}"
        return self._request("GET", path)["project"]

    def list_statuses(self) -> List[dict]:
        return self._request("GET", "/issue_statuses.json")["issue_statuses"]

    def list_trackers(self) -> List[dict]:
        return self._request("GET", "/trackers.json")["trackers"]

    def list_priorities(self) -> List[dict]:
        return self._request("GET", "/enumerations/issue_priorities.json")["issue_priorities"]

    def list_versions(self, project: str) -> List[dict]:
        path = f"/projects/{urllib.parse.quote(project, safe='')}/versions.json"
        return self._request("GET", path)["versions"]

    def list_categories(self, project: str) -> List[dict]:
        path = f"/projects/{urllib.parse.quote(project, safe='')}/issue_categories.json"
        return self._request("GET", path)["issue_categories"]

    def list_issues(self, project: str) -> List[dict]:
        items: List[dict] = []
        offset = 0
        while True:
            query = urllib.parse.urlencode({"project_id": project, "subproject_id": "!*",
                                            "status_id": "*", "limit": 100,
                                            "offset": offset})
            page = self._request("GET", f"/issues.json?{query}")
            got = page.get("issues", [])
            items += got
            offset += len(got)
            if not got or offset >= page.get("total_count", 0):
                return items

    def get_issue(self, issue_id: int,
                  include: Sequence[str] = ("journals", "allowed_statuses")) -> dict:
        suffix = f"?include={','.join(include)}" if include else ""
        return self._request("GET", f"/issues/{int(issue_id)}.json{suffix}")["issue"]

    def update_issue(self, issue_id: int, fields: Dict[str, Any]) -> None:
        self._request("PUT", f"/issues/{int(issue_id)}.json", {"issue": fields})

    def write_and_reread(self, issue_id: int, fields: Dict[str, Any]) -> dict:
        """update_issue then get_issue, since a write is only ever trusted once
        read back - Redmine can accept a PUT and silently ignore a field the
        caller's role may not set."""
        self.update_issue(issue_id, fields)
        return self.get_issue(issue_id)

    def create_issue(self, project_id: int, fields: Dict[str, Any]) -> dict:
        body = dict(fields, project_id=project_id)
        return self._request("POST", "/issues.json", {"issue": body})["issue"]

    def create_relation(self, issue_id: int, to_id: int, relation_type: str,
                        delay: Optional[int] = None) -> dict:
        payload: Dict[str, Any] = {"issue_to_id": to_id, "relation_type": relation_type}
        if delay is not None:
            payload["delay"] = delay
        return self._request("POST", f"/issues/{int(issue_id)}/relations.json",
                             {"relation": payload})["relation"]

    def list_relations(self, issue_id: int) -> List[dict]:
        return self._request("GET", f"/issues/{int(issue_id)}/relations.json")["relations"]

    def _request(self, method: str, path: str, payload: Optional[dict] = None) -> dict:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self._base + path, data=data, method=method)
        req.add_header("X-Redmine-API-Key", self._key)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        failure: Optional[RedmineError] = None
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
                f"check that 'url' is the Redmine root and that no login page is in the way"
            ) from None

    def _http_error(self, e: urllib.error.HTTPError, method: str, path: str) -> RedmineError:
        where = f"{method} {path.split('?', 1)[0]}"
        if 300 <= e.code < 400:
            return TransportError(
                f"{where} was redirected to {e.headers.get('Location', '?')}; the API key is "
                f"not sent on to another address - set 'url' in .redmine.json to the final one")
        if e.code == 401:
            return AuthError("the API key was rejected (missing, wrong or revoked)")
        if e.code == 403:
            return ForbiddenError(f"your role is not allowed to do this ({where})")
        if e.code == 404:
            return NotFoundError(f"not found ({where})")
        if e.code == 422:
            try:
                errors = json.loads(e.read().decode("utf-8")).get("errors", [])
            except (ValueError, UnicodeDecodeError):
                errors = []
            return RejectedError(f"Redmine rejected {where}: {'; '.join(errors) or 'no reason given'}")
        return TransportError(f"Redmine answered HTTP {e.code} to {where}")
