from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .client import Client, NotFoundError
from .config import Config
from .updatefile import Update, UpdateFile


def marker_line(session: str) -> str:
    return f"_redmine-sync: {session}_"


def with_marker(note: str, session: str) -> str:
    return note.rstrip() + "\n\n" + marker_line(session)


def has_marker(journals: Optional[List[dict]], session: str, user_id: int) -> bool:
    """Only the current user's own comments count: session ids are dates, so two
    people can close sessions with the same id on the same issue."""
    target = marker_line(session)
    for journal in journals or []:
        if (journal.get("user") or {}).get("id") != user_id:
            continue
        for line in (journal.get("notes") or "").splitlines():
            if line.strip() == target:
                return True
    return False


def subject_key(subject: str) -> str:
    stripped = subject.strip()
    if not stripped:
        return ""
    token = stripped.split(None, 1)[0]
    return token.split(":", 1)[0]


class ResolveError(Exception):
    pass


class IssueIndex:
    """Resolves update keys to issue ids, listing the project at most once."""

    def __init__(self, client: Client, config: Config, project_id: Optional[int] = None):
        self._client = client
        self._config = config
        self._by_key: Optional[Dict[str, List[int]]] = None
        self._project_id = project_id

    def project_id(self) -> int:
        if self._project_id is None:
            self._project_id = self._client.get_project(self._config.project)["id"]
        return self._project_id

    def resolve(self, key: str) -> int:
        if key.startswith("#"):
            if not key[1:].isdigit():
                raise ResolveError(f"'{key}' is not an issue number")
            return int(key[1:])
        if self._config.issue_key == "id_only":
            raise ResolveError(f"'{key}': this repository is configured for #number keys only")
        if self._by_key is None:
            index: Dict[str, List[int]] = {}
            for issue in self._client.list_issues(self._config.project):
                casefolded = subject_key(issue.get("subject", "")).casefold()
                index.setdefault(casefolded, []).append(issue["id"])
            self._by_key = index
        ids = self._by_key.get(key.casefold(), [])
        if not ids:
            raise ResolveError(
                f"no issue in project '{self._config.project}' has a subject starting with '{key}'")
        if len(ids) > 1:
            raise ResolveError(
                f"'{key}' is ambiguous, it matches {', '.join(f'#{i}' for i in sorted(ids))}")
        return ids[0]


@dataclass
class Row:
    update: Update
    issue_id: Optional[int] = None
    subject: str = ""
    current_status: str = ""
    current_status_id: Optional[int] = None
    target_status: Optional[str] = None
    target_status_id: Optional[int] = None
    current_done: Optional[int] = None
    target_done: Optional[int] = None
    already_applied: bool = False
    transition_checked: bool = False
    warnings: List[str] = field(default_factory=list)


@dataclass
class Plan:
    session: str
    rows: List[Row]
    errors: List[str]
    user_id: int
    text_format: str = "textile"

    @property
    def ok(self) -> bool:
        return not self.errors


def build_plan(client: Client, config: Config, update_file: UpdateFile,
               project_id: Optional[int] = None) -> Plan:
    user_id = client.current_user()["id"]
    statuses = client.list_statuses()
    by_name = {s["name"].casefold(): s for s in statuses}
    index = IssueIndex(client, config, project_id)
    rows: List[Row] = []
    errors: List[str] = []
    seen: Dict[int, int] = {}

    for n, update in enumerate(update_file.updates, 1):
        where = f"update {n} ({update.issue})"
        row = Row(update=update)
        rows.append(row)
        try:
            row.issue_id = index.resolve(update.issue)
        except ResolveError as e:
            errors.append(f"{where}: {e}")
            continue
        if row.issue_id in seen:
            errors.append(f"{where}: #{row.issue_id} is already updated by update {seen[row.issue_id]}")
            continue
        seen[row.issue_id] = n
        try:
            issue = client.get_issue(row.issue_id)
        except NotFoundError:
            errors.append(f"{where}: #{row.issue_id} does not exist or is not visible to you")
            continue
        if issue["project"]["id"] != index.project_id():
            errors.append(f"{where}: #{row.issue_id} belongs to project "
                          f"'{issue['project'].get('name', '?')}', not '{config.project}'")
            continue

        row.subject = issue.get("subject", "")
        row.current_status = issue["status"]["name"]
        row.current_status_id = issue["status"]["id"]
        row.current_done = issue.get("done_ratio")
        row.already_applied = has_marker(issue.get("journals"), update_file.session, user_id)
        if row.already_applied:
            continue

        if update.status is not None:
            status = by_name.get(update.status.casefold())
            if status is None:
                errors.append(f"{where}: unknown status '{update.status}'; this instance has: "
                              f"{', '.join(s['name'] for s in statuses)}")
                continue
            row.target_status, row.target_status_id = status["name"], status["id"]
            if status["id"] != row.current_status_id and "allowed_statuses" in issue:
                row.transition_checked = True
                allowed = {a["id"]: a["name"] for a in issue["allowed_statuses"]}
                if status["id"] not in allowed:
                    errors.append(f"{where}: '{row.current_status}' -> '{status['name']}' is not "
                                  f"allowed for you; allowed: {', '.join(allowed.values()) or 'none'}")
                    continue
            final_done = update.done_ratio if update.done_ratio is not None else row.current_done
            if status.get("is_closed") and final_done is not None and final_done < 100:
                row.warnings.append(f"closing with % Done below 100 ({final_done}%)")

        if update.done_ratio is not None:
            row.target_done = update.done_ratio
            if update.done_ratio % 10:
                row.warnings.append(f"% Done {update.done_ratio} is not a multiple of 10 "
                                    f"(the web form offers only those)")
            if row.current_done is not None and update.done_ratio < row.current_done:
                row.warnings.append(f"% Done goes down, {row.current_done} -> {update.done_ratio}")

    return Plan(session=update_file.session, rows=rows, errors=errors, user_id=user_id,
               text_format=config.text_format)
