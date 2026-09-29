from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import List, Optional

from .keys import unknown_keys_problem

_SESSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_ROW_KEYS = {"issue", "note", "done_ratio", "status"}


class UpdateFileError(Exception):
    pass


@dataclass(frozen=True)
class Update:
    issue: str
    note: str
    done_ratio: Optional[int] = None
    status: Optional[str] = None


@dataclass(frozen=True)
class UpdateFile:
    session: str
    updates: List[Update]


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
        if not isinstance(issue, str) or not issue or len(issue.split()) != 1:
            problems.append(f"{where}: 'issue' must be one token, a subject prefix or #number")
        note = row.get("note")
        if not isinstance(note, str) or not note.strip():
            problems.append(f"{where}: 'note' is required and must not be empty")
        done = row.get("done_ratio", None) if "done_ratio" in row else None
        if "done_ratio" in row and not (type(done) is int and 0 <= done <= 100):
            problems.append(f"{where}: 'done_ratio' must be an integer from 0 to 100")
        status = row.get("status") if "status" in row else None
        if "status" in row and (not isinstance(status, str) or not status.strip()):
            problems.append(f"{where}: 'status' must be a non-empty status name")
        updates.append(Update(issue=issue if isinstance(issue, str) else "",
                              note=note if isinstance(note, str) else "",
                              done_ratio=done if type(done) is int else None,
                              status=status.strip() if isinstance(status, str) else None))

    if problems:
        raise UpdateFileError(f"{source}:\n" + "\n".join(f"  - {p}" for p in problems))
    return UpdateFile(session=session, updates=updates)
