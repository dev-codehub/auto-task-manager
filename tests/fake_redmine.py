"""In-memory Redmine serving only what redmine-sync calls.

It reproduces one behaviour on purpose: Redmine answers success to a PUT and
silently ignores a field the user may not change - a status transition the
workflow forbids, a % Done the instance derives. Code that trusts the 2xx is
wrong against a real instance; tests here must catch that.
"""
from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qs, urlparse


class FakeRedmine:
    def __init__(self, key: str = "test-key"):
        self.key = key
        self.projects: Dict[str, dict] = {}
        self.statuses: List[dict] = []
        self.issues: Dict[int, dict] = {}
        self.workflow: Optional[Dict[int, Set[int]]] = None
        self.expose_allowed_statuses = False
        self.derived_done: Set[int] = set()
        self.forbidden: Set[int] = set()
        self.fail_puts_after: Optional[int] = None
        self.puts: List[Tuple[int, dict]] = []
        self.users: Dict[str, dict] = {key: {"id": 1, "login": "tester"}}
        self.answer_html = False
        self.redirect_to: Optional[str] = None
        self.trackers: List[dict] = []
        self.project_trackers: Dict[str, List[dict]] = {}
        self.priorities: List[dict] = []
        self.versions: Dict[str, List[dict]] = {}
        self.categories: Dict[str, List[dict]] = {}
        self.categories_forbidden = False
        self.hits = 0
        self.requests: List[str] = []
        self._next_issue_id = 1000
        self.relations: List[dict] = []
        self._next_relation_id = 1
        self._put_attempts = 0
        self._server: Optional[ThreadingHTTPServer] = None

    def add_user(self, key: str, uid: int, login: str) -> None:
        self.users[key] = {"id": uid, "login": login}

    def add_project(self, identifier: str, pid: int, name: Optional[str] = None) -> None:
        self.projects[identifier] = {"id": pid, "name": name or identifier.title()}

    def add_status(self, sid: int, name: str, is_closed: bool = False) -> None:
        self.statuses.append({"id": sid, "name": name, "is_closed": is_closed})

    def add_tracker(self, tid: int, name: str) -> None:
        self.trackers.append({"id": tid, "name": name})

    def add_priority(self, pid: int, name: str) -> None:
        self.priorities.append({"id": pid, "name": name})

    def add_version(self, project: str, vid: int, name: str) -> None:
        self.versions.setdefault(project, []).append({"id": vid, "name": name})

    def add_category(self, project: str, cid: int, name: str) -> None:
        self.categories.setdefault(project, []).append({"id": cid, "name": name})

    def add_issue(self, iid: int, subject: str, project: str = "demo",
                  status: str = "New", done_ratio: Optional[int] = 0,
                  parent_id: Optional[int] = None) -> None:
        status_id = next(s["id"] for s in self.statuses if s["name"] == status)
        self.issues[iid] = {"id": iid, "subject": subject,
                            "project_id": self.projects[project]["id"],
                            "status_id": status_id, "done_ratio": done_ratio,
                            "journals": [], "parent_id": parent_id}

    def _create_issue(self, fields: dict) -> dict:
        pid = fields.get("project_id")
        project = next((p for p in self.projects.values() if p["id"] == pid), None)
        if project is None:
            raise KeyError("project")
        tracker_ok = any(t["id"] == fields.get("tracker_id") for t in self.trackers)
        priority_ok = any(p["id"] == fields.get("priority_id") for p in self.priorities)
        if not tracker_ok or not priority_ok:
            raise ValueError("tracker or priority")
        iid = self._next_issue_id
        self._next_issue_id += 1
        self.issues[iid] = {
            "id": iid, "subject": fields.get("subject", ""),
            "description": fields.get("description", ""),
            "project_id": pid, "status_id": self.statuses[0]["id"],
            "done_ratio": 0, "journals": [],
            "parent_id": fields.get("parent_issue_id"),
        }
        return self.issues[iid]

    @property
    def url(self) -> str:
        assert self._server is not None, "start() the fake first"
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def start(self) -> "FakeRedmine":
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(self))
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def _status(self, sid: int) -> dict:
        return next(s for s in self.statuses if s["id"] == sid)

    def _issue_json(self, issue: dict, include: Set[str]) -> dict:
        project = next((ident, p) for ident, p in self.projects.items()
                       if p["id"] == issue["project_id"])[1]
        status = self._status(issue["status_id"])
        out = {"id": issue["id"], "subject": issue["subject"],
               "project": {"id": project["id"], "name": project["name"]},
               "status": {"id": status["id"], "name": status["name"]},
               }
        if issue["done_ratio"] is not None:
            out["done_ratio"] = issue["done_ratio"]
        if issue.get("parent_id") is not None:
            out["parent"] = {"id": issue["parent_id"]}
        if issue.get("category") is not None:
            out["category"] = dict(issue["category"])
        if "description" in issue:
            out["description"] = issue["description"]
        if "journals" in include:
            out["journals"] = [dict(j) for j in issue["journals"]]
        if "allowed_statuses" in include and self.expose_allowed_statuses:
            if self.workflow is None:
                ids = [s["id"] for s in self.statuses]
            else:
                ids = sorted(self.workflow.get(issue["status_id"], set()) | {issue["status_id"]})
            out["allowed_statuses"] = [{"id": i, "name": self._status(i)["name"]} for i in ids]
        return out

    def _apply_put(self, issue: dict, fields: dict, user: dict) -> None:
        if "status_id" in fields:
            target = int(fields["status_id"])
            if self.workflow is None or target in self.workflow.get(issue["status_id"], set()):
                issue["status_id"] = target
        if "done_ratio" in fields and issue["id"] not in self.derived_done:
            issue["done_ratio"] = int(fields["done_ratio"])
        if fields.get("notes"):
            issue["journals"].append({"id": len(issue["journals"]) + 1, "notes": fields["notes"],
                                      "user": {"id": user["id"], "name": user["login"]}})
        if "parent_issue_id" in fields:
            issue["parent_id"] = fields["parent_issue_id"]
        if "description" in fields:
            issue["description"] = fields["description"]


def demo_fake(key: str = "test-key") -> FakeRedmine:
    fake = FakeRedmine(key=key)
    fake.add_project("demo", 1, "Demo")
    fake.add_project("other", 2, "Other")
    fake.add_status(1, "New")
    fake.add_status(2, "In Progress")
    fake.add_status(3, "Resolved")
    fake.add_status(4, "Closed", is_closed=True)
    fake.add_issue(101, "EX-01.1 Build the thing")
    fake.add_issue(102, "EX-01.2 Test the thing")
    fake.add_issue(103, "EX-02 A story")
    fake.add_issue(201, "EX-09 Somewhere else", project="other")
    fake.add_tracker(1, "User Story")
    fake.add_tracker(2, "Task")
    fake.add_priority(1, "Normal")
    fake.add_priority(2, "High")
    fake.add_version("demo", 1, "P1")
    fake.add_category("demo", 1, "SUPPORT")
    return fake


_ISSUE_PATH = re.compile(r"/issues/(\d+)\.json")


def _handler_for(fake: FakeRedmine):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code: int, body: Optional[dict] = None) -> None:
            data = b"" if body is None else json.dumps(body).encode("utf-8")
            self.send_response(code)
            if body is not None:
                self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authed(self) -> bool:
            self.user = fake.users.get(self.headers.get("X-Redmine-API-Key", ""))
            if self.user is None:
                self._send(401)
                return False
            return True

        def do_GET(self):
            fake.hits += 1
            fake.requests.append("GET " + urlparse(self.path).path)
            if fake.redirect_to:
                self.send_response(302)
                self.send_header("Location", fake.redirect_to)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if not self._authed():
                return
            if fake.answer_html:
                data = b"<html><body>Sign in</body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            path = parsed.path
            if path == "/users/current.json":
                return self._send(200, {"user": dict(self.user)})
            if path == "/issue_statuses.json":
                return self._send(200, {"issue_statuses": fake.statuses})
            if path == "/trackers.json":
                return self._send(200, {"trackers": fake.trackers})
            if path == "/enumerations/issue_priorities.json":
                return self._send(200, {"issue_priorities": fake.priorities})
            match = re.fullmatch(r"/projects/([^/]+)/versions\.json", path)
            if match:
                if match.group(1) not in fake.projects:
                    return self._send(404)
                return self._send(200, {"versions": fake.versions.get(match.group(1), [])})
            match = re.fullmatch(r"/projects/([^/]+)/issue_categories\.json", path)
            if match:
                if match.group(1) not in fake.projects:
                    return self._send(404)
                if fake.categories_forbidden:
                    return self._send(403)
                return self._send(200, {"issue_categories": fake.categories.get(match.group(1), [])})
            match = re.fullmatch(r"/issues/(\d+)/relations\.json", path)
            if match:
                iid = int(match.group(1))
                if iid not in fake.issues:
                    return self._send(404)
                mine = [r for r in fake.relations if r["issue_id"] == iid or r["issue_to_id"] == iid]
                return self._send(200, {"relations": mine})
            if path.startswith("/projects/") and path.endswith(".json"):
                ident = path[len("/projects/"):-len(".json")]
                project = fake.projects.get(ident)
                if project is None:
                    return self._send(404)
                body = {"id": project["id"], "identifier": ident, "name": project["name"]}
                include = set(",".join(query.get("include", [])).split(",")) - {""}
                if "trackers" in include:
                    body["trackers"] = fake.project_trackers.get(ident, fake.trackers)
                if "issue_categories" in include:
                    body["issue_categories"] = fake.categories.get(ident, [])
                return self._send(200, {"project": body})
            if path == "/issues.json":
                project = fake.projects.get(query.get("project_id", [""])[0])
                if project is None:
                    return self._send(404)
                items = [fake._issue_json(i, set()) for i in fake.issues.values()
                         if i["project_id"] == project["id"]]
                offset = int(query.get("offset", ["0"])[0])
                limit = int(query.get("limit", ["25"])[0])
                return self._send(200, {"issues": items[offset:offset + limit],
                                        "total_count": len(items),
                                        "offset": offset, "limit": limit})
            match = _ISSUE_PATH.fullmatch(path)
            if match:
                issue = fake.issues.get(int(match.group(1)))
                if issue is None:
                    return self._send(404)
                include = set(",".join(query.get("include", [])).split(",")) - {""}
                return self._send(200, {"issue": fake._issue_json(issue, include)})
            self._send(404)

        def do_PUT(self):
            fake.hits += 1
            fake.requests.append("PUT " + urlparse(self.path).path)
            if not self._authed():
                return
            match = _ISSUE_PATH.fullmatch(urlparse(self.path).path)
            issue = fake.issues.get(int(match.group(1))) if match else None
            if issue is None:
                return self._send(404)
            fake._put_attempts += 1
            if fake.fail_puts_after is not None and fake._put_attempts > fake.fail_puts_after:
                return self._send(500)
            if issue["id"] in fake.forbidden:
                return self._send(403)
            length = int(self.headers.get("Content-Length", "0"))
            fields = json.loads(self.rfile.read(length).decode("utf-8"))["issue"]
            fake._apply_put(issue, fields, self.user)
            fake.puts.append((issue["id"], fields))
            self._send(204)

        def do_POST(self):
            fake.hits += 1
            fake.requests.append("POST " + urlparse(self.path).path)
            if not self._authed():
                return
            path = urlparse(self.path).path
            if path == "/issues.json":
                length = int(self.headers.get("Content-Length", "0"))
                fields = json.loads(self.rfile.read(length).decode("utf-8"))["issue"]
                try:
                    issue = fake._create_issue(fields)
                except (KeyError, ValueError):
                    return self._send(422, {"errors": ["invalid project, tracker or priority"]})
                return self._send(201, {"issue": fake._issue_json(issue, set())})
            match = re.fullmatch(r"/issues/(\d+)/relations\.json", path)
            if match:
                iid = int(match.group(1))
                length = int(self.headers.get("Content-Length", "0"))
                fields = json.loads(self.rfile.read(length).decode("utf-8"))["relation"]
                to_id = fields.get("issue_to_id")
                if iid not in fake.issues or to_id not in fake.issues or to_id == iid:
                    return self._send(422, {"errors": ["invalid relation"]})
                rel = {"id": fake._next_relation_id, "issue_id": iid,
                       "issue_to_id": to_id, "relation_type": fields.get("relation_type")}
                if "delay" in fields:
                    rel["delay"] = fields["delay"]
                fake._next_relation_id += 1
                fake.relations.append(rel)
                return self._send(201, {"relation": rel})
            self._send(404)

    return Handler
