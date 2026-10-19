"""In-memory Jira Cloud (REST v3) serving only what jira-sync calls.

It reproduces, on purpose, the ways a real site disagrees with a naive client:

* ``ignored_fields``: a PUT or POST answers success but a listed field is not
  stored, the way Jira treats a field that is absent from the edit screen.
  Code that trusts the 2xx is wrong; it must read the issue back.
* search is paged 2 issues at a time with ``nextPageToken``, ``createmeta``
  and comments are paged by ``startAt``/``maxResults``.
* ``stuck``: issue keys whose transitions answer success but leave the status
  where it was (an automation rule or post-function moving it back).
* ``forbidden``: issue keys where every write (edit, comment, transition)
  answers 403.
* ``answer_html`` (a login page where JSON should be) and ``redirect_to``.
* ``omit_keys``: top-level keys left out of every JSON object answered (a
  paged answer without its items key, for example).

It answers 400 to payload shapes real Jira rejects: a comment that is not
``{"body": <ADF doc>}``, a transition without ``{"transition": {"id": ...}}``
or with a field that is not on the transition's screen, a create or an edit
without ``{"fields": {...}}``, a create with a field that is not on that
type's create screen, a description that is not an ADF doc, a parent or
priority that is not an object naming one (a parent must also exist), a
non-number for a field whose schema is number, and an issue link whose
``type``, ``inwardIssue`` or ``outwardIssue`` is not ``{"name"}`` /
``{"key"}``.

Every call is logged in ``requests``; every mutating call is also logged in
``writes`` as (method, path, body). ``POST /search/jql`` is a read, so it is
in ``requests`` only.
"""
from __future__ import annotations

import base64
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qs, unquote, urlparse

API = "/rest/api/3"
SEARCH_PAGE_SIZE = 2


class FakeJira:
    def __init__(self, email: str = "tester@example.com", token: str = "test-token"):
        self.email = email
        self.token = token
        self.account_id = "acc-1"
        self.projects: Dict[str, dict] = {}
        self.issue_types: List[dict] = []
        self.create_fields: Dict[str, List[dict]] = {}
        self.issues: Dict[str, dict] = {}
        self.initial_status = "To Do"
        self.workflow: Dict[str, List[dict]] = {}
        self.link_types: List[dict] = []
        self.fields: List[dict] = []
        self.ignored_fields: Set[str] = set()
        self.forbidden: Set[str] = set()
        self.stuck: Set[str] = set()
        self.answer_html = False
        self.redirect_to: Optional[str] = None
        self.omit_keys: Set[str] = set()
        self.hits = 0
        self.requests: List[str] = []
        self.writes: List[Tuple[str, str, dict]] = []
        self.queries: List[str] = []
        self.last_authorization: Optional[str] = None
        self._next_issue_id = 10000
        self._next_number: Dict[str, int] = {}
        self._next_comment_id = 1
        self._next_link_id = 1
        self._server: Optional[ThreadingHTTPServer] = None

    # -- seeding helpers ------------------------------------------------

    def add_project(self, key: str, pid: str, name: Optional[str] = None) -> None:
        self.projects[key] = {"id": pid, "key": key, "name": name or key.title()}

    def add_issue_type(self, tid: str, name: str, subtask: bool = False,
                       hierarchy_level: int = 0) -> None:
        self.issue_types.append({"id": tid, "name": name, "subtask": subtask,
                                 "hierarchyLevel": hierarchy_level})

    def add_issue(self, summary: str, project: str = "SCRUM", type_name: str = "Task",
                  status: Optional[str] = None, extra: Optional[dict] = None) -> str:
        number = self._next_number.get(project, 0) + 1
        self._next_number[project] = number
        key = f"{project}-{number}"
        issue_type = next(t for t in self.issue_types if t["name"] == type_name)
        fields = {"summary": summary,
                  "project": dict(self.projects[project]),
                  "issuetype": dict(issue_type),
                  "status": {"name": status or self.initial_status},
                  "issuelinks": []}
        fields.update(extra or {})
        self.issues[key] = {"id": str(self._next_issue_id), "key": key,
                            "fields": fields, "comments": []}
        self._next_issue_id += 1
        return key

    # -- server ---------------------------------------------------------

    @property
    def url(self) -> str:
        assert self._server is not None, "start() the fake first"
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def start(self) -> "FakeJira":
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(self))
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    # -- behaviour ------------------------------------------------------

    def _store(self, target: dict, fields: dict) -> None:
        for name, value in fields.items():
            if name in self.ignored_fields:
                continue
            if name == "parent" and isinstance(value, dict):
                # Read back the way Jira answers: the parent's id and key.
                parent = self._find_issue(value)
                value = {"id": parent["id"], "key": parent["key"]}
            target[name] = value

    def _find_issue(self, ref: dict) -> Optional[dict]:
        if ref.get("key"):
            return self.issues.get(ref["key"])
        return next((i for i in self.issues.values() if i["id"] == str(ref.get("id"))), None)

    def _issue_json(self, issue: dict, wanted: Optional[List[str]]) -> dict:
        fields = issue["fields"]
        if wanted and not ({"*all", "*navigable"} & set(wanted)):
            fields = {k: v for k, v in fields.items() if k in wanted}
        return {"id": issue["id"], "key": issue["key"],
                "self": f"{self.url}{API}/issue/{issue['key']}",
                "fields": json.loads(json.dumps(fields))}

    def _transitions_json(self, issue: dict, with_fields: bool) -> List[dict]:
        out = []
        for t in self.workflow.get(issue["fields"]["status"]["name"], []):
            item = {"id": t["id"], "name": t["name"],
                    "to": {"name": t["to"], "id": str(self._status_id(t["to"]))},
                    "hasScreen": bool(t.get("fields")), "isAvailable": True}
            if with_fields:
                item["fields"] = json.loads(json.dumps(t.get("fields", {})))
            out.append(item)
        return out

    def _status_id(self, name: str) -> int:
        names = list(self.workflow)
        return 1 + names.index(name) if name in names else 0

    def _search(self, jql: str) -> List[dict]:
        match = re.search(r"project\s*=\s*\"?([A-Za-z0-9_]+)\"?", jql)
        items = list(self.issues.values())
        if match:
            items = [i for i in items if i["fields"]["project"]["key"] == match.group(1)]
        return items

    def _create(self, fields: dict) -> Tuple[Optional[dict], Optional[dict]]:
        project = fields.get("project")
        project = project if isinstance(project, dict) else {}
        key = project.get("key") or next(
            (k for k, p in self.projects.items() if p["id"] == project.get("id")), None)
        if key not in self.projects:
            return None, {"errorMessages": [], "errors": {"project": "valid project is required"}}
        type_ref = fields.get("issuetype")
        type_ref = type_ref if isinstance(type_ref, dict) else {}
        issue_type = next((t for t in self.issue_types
                           if t["id"] == type_ref.get("id") or t["name"] == type_ref.get("name")), None)
        if issue_type is None:
            return None, {"errorMessages": [], "errors": {"issuetype": "valid issue type is required"}}
        if not fields.get("summary"):
            return None, {"errorMessages": [],
                          "errors": {"summary": "You must specify a summary of the issue."}}
        errors = self._shape_errors(fields)
        screen = self.create_fields.get(issue_type["id"])
        if screen is not None:
            # parent is treated as always settable on create; a site that drops
            # it is modelled with ignored_fields.
            allowed = {str(f.get("fieldId") or f.get("key")) for f in screen}
            allowed |= {"project", "issuetype", "summary", "parent"}
            errors.update({fid: f"Field '{fid}' cannot be set. It is not on the appropriate "
                                f"screen, or unknown." for fid in fields if fid not in allowed})
        if errors:
            return None, {"errorMessages": [], "errors": errors}
        stored = {k: v for k, v in fields.items() if k not in ("project", "issuetype", "summary")}
        issue_key = self.add_issue(fields["summary"], project=key, type_name=issue_type["name"])
        self._store(self.issues[issue_key]["fields"], stored)
        return self.issues[issue_key], None

    def _shape_errors(self, fields: dict) -> dict:
        """Jira's answers to a value of the wrong shape: a non-number for a number
        field, a description that is not an ADF doc, a parent or priority that
        is not an object naming one, a parent that does not exist."""
        numbers = {f["id"] for f in self.fields if (f.get("schema") or {}).get("type") == "number"}
        errors = {fid: "Operation value must be a number."
                  for fid, value in fields.items()
                  if fid in numbers and (type(value) not in (int, float))}
        description = fields.get("description")
        if description is not None and not _is_adf(description):
            errors["description"] = "Operation value must be an Atlassian Document."
        if fields.get("parent") is not None:
            parent = fields["parent"]
            if not isinstance(parent, dict) or not (parent.get("key") or parent.get("id")):
                errors["parent"] = "Specify the parent as an object with 'key' or 'id'."
            elif self._find_issue(parent) is None:
                errors["parent"] = "Could not find issue by id or key."
        if "priority" in fields:
            priority = fields["priority"]
            if not isinstance(priority, dict) or not (priority.get("name") or priority.get("id")):
                errors["priority"] = "Specify the priority as an object with 'name' or 'id'."
        return errors

    def _edit(self, issue: dict, body: dict) -> Optional[dict]:
        fields = body.get("fields")
        if not isinstance(fields, dict):
            return {"errorMessages": ['The request must be {"fields": {...}}.'], "errors": {}}
        errors = self._shape_errors(fields)
        if errors:
            return {"errorMessages": [], "errors": errors}
        self._store(issue["fields"], fields)
        return None

    def _transition(self, issue: dict, body: dict) -> Optional[dict]:
        ref = body.get("transition")
        tid = str(ref.get("id", "")) if isinstance(ref, dict) else ""
        if not tid:
            return {"errorMessages": ['The request must be {"transition": {"id": "<id>"}}.'],
                    "errors": {}}
        available = self.workflow.get(issue["fields"]["status"]["name"], [])
        chosen = next((t for t in available if t["id"] == tid), None)
        if chosen is None:
            return {"errorMessages": [f"Transition id '{tid}' is not valid for this issue."],
                    "errors": {}}
        sent = body.get("fields") or {}
        if not isinstance(sent, dict):
            return {"errorMessages": ["'fields' must be an object."], "errors": {}}
        screen = chosen.get("fields") or {}
        errors = {fid: f"Field '{fid}' cannot be set. It is not on the appropriate screen, "
                       f"or unknown."
                  for fid in sent if fid not in screen}
        errors.update({fid: f"{meta.get('name', fid)} is required."
                       for fid, meta in screen.items()
                       if meta.get("required") and fid not in sent})
        errors.update(self._shape_errors(sent))
        if errors:
            return {"errorMessages": [], "errors": errors}
        if issue["key"] not in self.stuck:
            issue["fields"]["status"] = {"name": chosen["to"]}
        self._store(issue["fields"], sent)
        return None

    def _link(self, body: dict) -> Optional[Tuple[int, dict]]:
        shape = [name for name, item, wanted in (("type", body.get("type"), "name"),
                                                  ("inwardIssue", body.get("inwardIssue"), "key"),
                                                  ("outwardIssue", body.get("outwardIssue"), "key"))
                 if not isinstance(item, dict) or not isinstance(item.get(wanted), str)]
        if shape:
            return 400, {"errorMessages": [
                'The request must be {"type": {"name": ...}, "inwardIssue": {"key": ...}, '
                '"outwardIssue": {"key": ...}}.'], "errors": {n: "invalid" for n in shape}}
        type_name = body["type"]["name"]
        link_type = next((t for t in self.link_types if t["name"] == type_name), None)
        if link_type is None:
            return 404, {"errorMessages": ["No issue link type with name "
                                           f"'{type_name}' found."], "errors": {}}
        inward = self.issues.get((body.get("inwardIssue") or {}).get("key"))
        outward = self.issues.get((body.get("outwardIssue") or {}).get("key"))
        if inward is None or outward is None:
            return 404, {"errorMessages": ["Issue does not exist or you do not have "
                                           "permission to see it."], "errors": {}}
        lid = str(self._next_link_id)
        self._next_link_id += 1
        # "A is blocked by B" is posted with inwardIssue=A, outwardIssue=B and is
        # read back on A as an inwardIssue entry and on B as an outwardIssue one.
        inward["fields"]["issuelinks"].append(
            {"id": lid, "type": dict(link_type),
             "inwardIssue": {"key": outward["key"], "id": outward["id"]}})
        outward["fields"]["issuelinks"].append(
            {"id": lid, "type": dict(link_type),
             "outwardIssue": {"key": inward["key"], "id": inward["id"]}})
        return None


def _is_adf(value) -> bool:
    return (isinstance(value, dict) and value.get("type") == "doc" and value.get("version") == 1
            and isinstance(value.get("content"), list))


def demo_fake(email: str = "tester@example.com", token: str = "test-token") -> FakeJira:
    fake = FakeJira(email=email, token=token)
    fake.add_project("SCRUM", "10000", "Scrum")
    fake.add_issue_type("10001", "Epic", hierarchy_level=1)
    fake.add_issue_type("10002", "Story")
    fake.add_issue_type("10003", "Task")
    fake.add_issue_type("10004", "Sub-task", subtask=True, hierarchy_level=-1)
    fake.workflow = {
        "To Do": [{"id": "11", "name": "Start", "to": "In Progress"}],
        "In Progress": [{"id": "21", "name": "Finish", "to": "Done"},
                        {"id": "31", "name": "Back", "to": "To Do"}],
        "Done": [],
    }
    fake.link_types = [
        {"id": "10000", "name": "Blocks", "inward": "is blocked by", "outward": "blocks"},
        {"id": "10001", "name": "Relates", "inward": "relates to", "outward": "relates to"},
    ]
    fake.fields = [
        {"id": "summary", "name": "Summary", "custom": False},
        {"id": "customfield_10016", "name": "Story point estimate", "custom": True,
         "schema": {"type": "number"}},
    ]
    for type_id in ("10001", "10002", "10003", "10004"):
        fake.create_fields[type_id] = [
            {"fieldId": "summary", "key": "summary", "name": "Summary", "required": True,
             "operations": ["set"], "hasDefaultValue": False},
            {"fieldId": "description", "key": "description", "name": "Description",
             "required": False, "operations": ["set"], "hasDefaultValue": False},
        ]
    fake.add_issue("Epic one", type_name="Epic")
    fake.add_issue("Story one", type_name="Story")
    fake.add_issue("Task one", type_name="Task")
    return fake


_ISSUE = re.compile(API + r"/issue/([^/]+)")
_ISSUE_PART = re.compile(API + r"/issue/([^/]+)/(comment|transitions)")
_CREATEMETA_TYPES = re.compile(API + r"/issue/createmeta/([^/]+)/issuetypes")
_CREATEMETA_FIELDS = re.compile(API + r"/issue/createmeta/([^/]+)/issuetypes/([^/]+)")


def _page(items: List[dict], query: dict) -> Tuple[int, int, List[dict]]:
    start = int(query.get("startAt", ["0"])[0])
    size = int(query.get("maxResults", ["50"])[0])
    return start, size, items[start:start + size]


def _handler_for(fake: FakeJira):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code: int, body: Optional[dict] = None) -> None:
            if isinstance(body, dict) and fake.omit_keys:
                body = {k: v for k, v in body.items() if k not in fake.omit_keys}
            data = b"" if body is None else json.dumps(body).encode("utf-8")
            self.send_response(code)
            if body is not None:
                self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length", "0"))
            if not length:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))

        def _gate(self, method: str, write: bool, body: Optional[dict] = None) -> bool:
            """Log the call, then answer redirect / HTML / 401 where they apply.
            True means the handler should go on."""
            fake.hits += 1
            path = urlparse(self.path).path
            fake.requests.append(f"{method} {path}")
            fake.queries.append(unquote(urlparse(self.path).query))
            if write:
                fake.writes.append((method, path, body if body is not None else {}))
            if fake.redirect_to:
                self.send_response(302)
                self.send_header("Location", fake.redirect_to)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return False
            fake.last_authorization = self.headers.get("Authorization")
            expected = "Basic " + base64.b64encode(
                f"{fake.email}:{fake.token}".encode("utf-8")).decode("ascii")
            if fake.last_authorization != expected:
                self._send(401)
                return False
            if fake.answer_html:
                data = b"<html><body>Sign in</body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return False
            return True

        def _issue(self, path: str, pattern=_ISSUE) -> Optional[dict]:
            match = pattern.fullmatch(path)
            return fake.issues.get(unquote(match.group(1))) if match else None

        def do_GET(self):
            if not self._gate("GET", False):
                return
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            path = parsed.path
            if path == f"{API}/myself":
                return self._send(200, {"accountId": fake.account_id,
                                        "emailAddress": fake.email, "displayName": "Tester"})
            if path == f"{API}/field":
                return self._send(200, fake.fields)  # a bare list, like the real one
            if path == f"{API}/issueLinkType":
                return self._send(200, {"issueLinkTypes": fake.link_types})
            match = _CREATEMETA_FIELDS.fullmatch(path)
            if match:
                if unquote(match.group(1)) not in fake.projects:
                    return self._send(404, {"errorMessages": ["No project could be found."],
                                            "errors": {}})
                items = fake.create_fields.get(match.group(2))
                if items is None:
                    return self._send(404, {"errorMessages": ["Issue type not found."],
                                            "errors": {}})
                start, size, chunk = _page(items, query)
                return self._send(200, {"startAt": start, "maxResults": size,
                                        "total": len(items), "fields": chunk})
            match = _CREATEMETA_TYPES.fullmatch(path)
            if match:
                if unquote(match.group(1)) not in fake.projects:
                    return self._send(404, {"errorMessages": ["No project could be found."],
                                            "errors": {}})
                start, size, chunk = _page(fake.issue_types, query)
                return self._send(200, {"startAt": start, "maxResults": size,
                                        "total": len(fake.issue_types), "issueTypes": chunk})
            match = re.fullmatch(API + r"/project/([^/]+)", path)
            if match:
                project = fake.projects.get(unquote(match.group(1)))
                if project is None:
                    return self._send(404, {"errorMessages": ["No project could be found."],
                                            "errors": {}})
                return self._send(200, dict(project))
            match = _ISSUE_PART.fullmatch(path)
            if match:
                issue = self._issue(path, _ISSUE_PART)
                if issue is None:
                    return self._send(404, {"errorMessages": ["Issue does not exist or you "
                                                              "do not have permission to see it."],
                                            "errors": {}})
                if match.group(2) == "comment":
                    start, size, chunk = _page(issue["comments"], query)
                    return self._send(200, {"startAt": start, "maxResults": size,
                                            "total": len(issue["comments"]), "comments": chunk})
                expand = ",".join(query.get("expand", []))
                return self._send(200, {"transitions": fake._transitions_json(
                    issue, "transitions.fields" in expand)})
            issue = self._issue(path)
            if issue is not None:
                wanted = ",".join(query.get("fields", [])).split(",")
                return self._send(200, fake._issue_json(issue, [w for w in wanted if w]))
            self._send(404, {"errorMessages": ["not found"], "errors": {}})

        def do_PUT(self):
            body = self._body()
            if not self._gate("PUT", True, body):
                return
            issue = self._issue(urlparse(self.path).path)
            if issue is None:
                return self._send(404, {"errorMessages": ["Issue does not exist or you do "
                                                          "not have permission to see it."],
                                        "errors": {}})
            if issue["key"] in fake.forbidden:
                return self._send(403, {"errorMessages": ["no permission"], "errors": {}})
            problem = fake._edit(issue, body)
            if problem:
                return self._send(400, problem)
            self._send(204)

        def do_POST(self):
            path = urlparse(self.path).path
            body = self._body()
            if not self._gate("POST", path != f"{API}/search/jql", body):
                return
            if path == f"{API}/search/jql":
                items = fake._search(body.get("jql", ""))
                start = int(body.get("nextPageToken") or 0)
                chunk = items[start:start + SEARCH_PAGE_SIZE]
                out = {"issues": [fake._issue_json(i, body.get("fields")) for i in chunk]}
                if start + SEARCH_PAGE_SIZE < len(items):
                    out["nextPageToken"] = str(start + SEARCH_PAGE_SIZE)
                else:
                    out["isLast"] = True
                return self._send(200, out)
            if path == f"{API}/issue":
                if not isinstance(body.get("fields"), dict):
                    return self._send(400, {"errorMessages": [
                        'The request must be {"fields": {...}}.'], "errors": {}})
                issue, error = fake._create(body["fields"])
                if error:
                    return self._send(400, error)
                return self._send(201, {"id": issue["id"], "key": issue["key"],
                                        "self": f"{fake.url}{API}/issue/{issue['key']}"})
            if path == f"{API}/issueLink":
                problem = fake._link(body)
                if problem:
                    return self._send(*problem)
                return self._send(201)
            match = _ISSUE_PART.fullmatch(path)
            if match:
                issue = self._issue(path, _ISSUE_PART)
                if issue is None:
                    return self._send(404, {"errorMessages": ["Issue does not exist or you "
                                                              "do not have permission to see it."],
                                            "errors": {}})
                if issue["key"] in fake.forbidden:
                    return self._send(403, {"errorMessages": ["no permission"], "errors": {}})
                if match.group(2) == "comment":
                    doc = body.get("body")
                    if not isinstance(doc, dict) or doc.get("type") != "doc":
                        return self._send(400, {
                            "errorMessages": ["Comment body is not valid! The request must be "
                                              '{"body": <ADF document>}.'],
                            "errors": {}})
                    comment = {"id": str(fake._next_comment_id),
                               "author": {"accountId": fake.account_id},
                               "body": doc, "created": "2026-10-19T10:00:00.000+0000"}
                    fake._next_comment_id += 1
                    issue["comments"].append(comment)
                    return self._send(201, comment)
                problem = fake._transition(issue, body)
                if problem:
                    return self._send(400, problem)
                return self._send(204)
            self._send(404, {"errorMessages": ["not found"], "errors": {}})

    return Handler
