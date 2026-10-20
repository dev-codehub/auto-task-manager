from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from redmine_sync.keys import unknown_keys_problem

_SESSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_ISSUE = re.compile(r"[A-Z][A-Z0-9_]*-\d+")
_ROW_KEYS = {"issue", "note", "status", "story_points", "transition_fields"}


class UpdateFileError(Exception):
    pass


@dataclass(frozen=True)
class Update:
    issue: str
    note: str
    status: Optional[str] = None
    story_points: Optional[float] = None
    # Keyed by the field's name as Jira reports it on the transition (plan.py
    # also accepts the field id); values are text or numbers as the person
    # wrote them. plan.py checks them against the transition and shapes them.
    transition_fields: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class UpdateFile:
    session: str
    updates: List[Update]


def _is_number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _is_field_value(value: Any) -> bool:
    return (isinstance(value, str) and bool(value.strip())) or _is_number(value)


def load_update_file(path: str) -> UpdateFile:
    try:
        with open(path, encoding="utf-8-sig") as f:
            text = f.read()
    except UnicodeDecodeError:
        raise UpdateFileError(f"{path}: not UTF-8 text") from None
    return parse_update_file(text, source=path)


def parse_update_file(text: str, source: str = "<update file>") -> UpdateFile:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        raise UpdateFileError(f"{source}: not valid JSON ({e})") from None
    if not isinstance(raw, dict):
        raise UpdateFileError(f"{source}: must be a JSON object")

    problems: List[str] = []
    session = raw.get("session")
    if not isinstance(session, str) or not _SESSION.fullmatch(session):
        problems.append("'session' must be a token of letters, digits, '.', '_' or '-'")
    rows = raw.get("updates")
    if not isinstance(rows, list) or not rows:
        problems.append("'updates' must be a non-empty list")
        rows = []

    updates: List[Update] = []
    for n, row in enumerate(rows, 1):
        where = f"update {n}"
        if not isinstance(row, dict):
            problems.append(f"{where}: must be an object")
            continue
        problem = unknown_keys_problem(row, _ROW_KEYS, where)
        if problem:
            problems.append(problem)
        issue = row.get("issue")
        if not isinstance(issue, str) or not _ISSUE.fullmatch(issue):
            problems.append(f"{where}: 'issue' must be a Jira issue key such as SCRUM-12")
        note = row.get("note")
        if not isinstance(note, str) or not note.strip():
            problems.append(f"{where}: 'note' is required and must not be empty")
        status = row.get("status") if "status" in row else None
        if "status" in row and (not isinstance(status, str) or not status.strip()):
            problems.append(f"{where}: 'status' must be a non-empty status name")
        points = row.get("story_points") if "story_points" in row else None
        if "story_points" in row and not (_is_number(points) and points >= 0):
            problems.append(f"{where}: 'story_points' must be a number of 0 or more")
            points = None
        fields = row.get("transition_fields", {}) if "transition_fields" in row else {}
        if "transition_fields" in row:
            if not isinstance(fields, dict) or not all(
                    isinstance(k, str) and k.strip() and _is_field_value(v)
                    for k, v in fields.items()):
                problems.append(f"{where}: 'transition_fields' must be an object of non-empty "
                                f"text or number values, keyed by field name")
                fields = {}
        updates.append(Update(issue=issue if isinstance(issue, str) else "",
                              note=note if isinstance(note, str) else "",
                              status=status.strip() if isinstance(status, str) else None,
                              story_points=points,
                              transition_fields=dict(fields)))

    if problems:
        raise UpdateFileError(f"{source}:\n" + "\n".join(f"  - {p}" for p in problems))
    return UpdateFile(session=session, updates=updates)
