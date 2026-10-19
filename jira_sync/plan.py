from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .adf import adf_lines, markdown_to_adf
from .client import Client, NotFoundError
from .config import Config
from .updatefile import Update, UpdateFile

STORY_POINTS_NAMES = ("Story Points", "Story point estimate")
_UNSUPPORTED = "field not supported, set it in Jira"
# Rich-text fields are schema "string" too, but v3 wants ADF for them.
_RICH_TEXT_SYSTEM = {"description", "environment"}
_RICH_TEXT_CUSTOM = ":textarea"


def marker_line(session: str) -> str:
    return f"_jira-sync: {session}_"


def with_marker_adf(note: str, session: str) -> dict:
    """The note as ADF with the marker appended as its own last paragraph: never
    joined to the Markdown, where an unclosed code fence would swallow it."""
    doc = markdown_to_adf(note)
    marker = {"type": "paragraph", "content": [{"type": "text", "text": marker_line(session)}]}
    return {**doc, "content": list(doc["content"]) + [marker]}


def has_marker(comments: Optional[List[dict]], session: str, account_id: str) -> bool:
    """Only the current account's own comments count: session ids are dates, so
    two people can close sessions with the same id on the same issue."""
    target = marker_line(session)
    for comment in comments or []:
        if (comment.get("author") or {}).get("accountId") != account_id:
            continue
        body = comment.get("body")
        if isinstance(body, dict) and any(line.strip() == target for line in adf_lines(body)):
            return True
    return False


_DATE_ONLY = re.compile(r"\d{4}-\d{2}-\d{2}(-\d+)?")


def session_warnings(session: str) -> List[str]:
    """The session id ends up in every comment as `_jira-sync: <session>_`, next
    to a comment that already carries its date. A bare date (or date-N) tells
    the reader of the issue nothing; a short topic does."""
    if _DATE_ONLY.fullmatch(session):
        return [f"session '{session}' is only a date; name it YYYY-MM-DD-<topic> "
                f"(e.g. {session[:10]}-onboarding-flow) so the marker in Jira says "
                f"what this update was"]
    return []


@dataclass
class Row:
    update: Update
    subject: str = ""
    current_status: str = ""
    transition_id: Optional[str] = None
    transition_name: Optional[str] = None
    target_status: Optional[str] = None
    # Keyed by field id, values shaped for POST .../transitions.
    fields: Dict[str, Any] = field(default_factory=dict)
    # (field name, value as the person wrote it) - for the dry-run display only.
    field_labels: List[Tuple[str, Any]] = field(default_factory=list)
    story_points_target: Optional[float] = None
    already_applied: bool = False
    warnings: List[str] = field(default_factory=list)


@dataclass
class Plan:
    session: str
    rows: List[Row]
    errors: List[str]
    account_id: str
    # Plan-level notes for the dry-run (never block a write).
    warnings: List[str] = field(default_factory=list)
    story_points_field: Optional[str] = None

    @property
    def ok(self) -> bool:
        return not self.errors


def _field_kind(meta: dict) -> Optional[str]:
    """'text', 'number' or 'option'; None when the field is not supported."""
    schema = meta.get("schema") or {}
    kind = schema.get("type")
    if kind == "array":
        return None
    if meta.get("allowedValues"):
        return "option"
    if kind == "number":
        return "number"
    if kind == "string":
        if (schema.get("system") in _RICH_TEXT_SYSTEM
                or str(schema.get("custom", "")).endswith(_RICH_TEXT_CUSTOM)):
            return None
        return "text"
    return None


def _option_label(option: dict) -> str:
    return str(option.get("name") or option.get("value") or option.get("id", "?"))


def _options(meta: dict) -> str:
    return ", ".join(_option_label(o) for o in meta.get("allowedValues") or [])


def _shape(meta: dict, value: Any) -> Tuple[Any, Optional[str]]:
    """(API value, None) or (None, problem) for a supported field."""
    name = meta.get("name", "?")
    kind = _field_kind(meta)
    if kind == "text":
        if not isinstance(value, str):
            return None, f"'{name}' is a text field; give it text, not {value!r}"
        return value, None
    if kind == "number":
        if isinstance(value, str):
            return None, f"'{name}' is a number field; give it a number, not '{value}'"
        return value, None
    wanted = str(value).strip().casefold()
    for option in meta.get("allowedValues") or []:
        for key in ("name", "value"):
            if isinstance(option.get(key), str) and option[key].casefold() == wanted:
                return {key: option[key]}, None
    return None, f"'{name}' value '{value}' is not one of: {_options(meta)}"


def resolve_transition_fields(transition: dict,
                              supplied: Dict[str, Any]) -> Tuple[Dict[str, Any],
                                                                 List[Tuple[str, Any]], List[str]]:
    """Matches an update's transition_fields (by field name, casefolded, or id)
    to the transition's fields and checks every required one is covered.
    Returns (fields keyed by id for the API, labels, errors)."""
    metas: Dict[str, dict] = transition.get("fields") or {}
    by_name = {str(m.get("name", fid)).casefold(): fid for fid, m in metas.items()}
    fields: Dict[str, Any] = {}
    labels: List[Tuple[str, Any]] = []
    errors: List[str] = []
    given = set()
    for name, value in supplied.items():
        fid = name if name in metas else by_name.get(name.strip().casefold())
        if fid is None:
            names = ", ".join(str(m.get("name", f)) for f, m in metas.items()) or "none"
            errors.append(f"transition '{transition.get('name')}' has no field '{name}'; "
                          f"its fields: {names}")
            continue
        given.add(fid)
        meta = metas[fid]
        if _field_kind(meta) is None:
            errors.append(f"'{meta.get('name', fid)}': {_UNSUPPORTED}")
            continue
        shaped, problem = _shape(meta, value)
        if problem:
            errors.append(problem)
            continue
        fields[fid] = shaped
        labels.append((meta.get("name", fid), value))
    for fid, meta in metas.items():
        if fid in given or not meta.get("required") or meta.get("hasDefaultValue"):
            continue
        name = meta.get("name", fid)
        if _field_kind(meta) is None:
            errors.append(f"transition '{transition.get('name')}' requires '{name}': "
                          f"{_UNSUPPORTED}")
        elif meta.get("allowedValues"):
            errors.append(f"transition '{transition.get('name')}' requires '{name}', one of: "
                          f"{_options(meta)}; add it under 'transition_fields'")
        else:
            errors.append(f"transition '{transition.get('name')}' requires '{name}'; "
                          f"add it under 'transition_fields'")
    return fields, labels, errors


def _story_points_field(client: Client, config: Config) -> Tuple[Optional[str], Optional[str]]:
    """(field id, None) or (None, problem). The problem only matters when some
    row sets story points."""
    if config.story_points_field:
        return config.story_points_field, None
    matches = [f for f in client.list_fields() if f.get("name") in STORY_POINTS_NAMES]
    if len(matches) == 1:
        return matches[0]["id"], None
    names = " or ".join(f"'{n}'" for n in STORY_POINTS_NAMES)
    if not matches:
        return None, (f"no field named {names} on this site; set 'story_points_field' "
                      f"in .jira.json to the story points field id")
    found = ", ".join(f"{f.get('id')} ({f.get('name')})" for f in matches)
    return None, (f"several story points fields on this site: {found}; set "
                  f"'story_points_field' in .jira.json to the one this project uses")


def build_plan(client: Client, config: Config, update_file: UpdateFile) -> Plan:
    account_id = client.myself()["accountId"]
    project_key = client.get_project(config.project)["key"]
    points_field, points_problem = _story_points_field(client, config)
    rows: List[Row] = []
    errors: List[str] = []
    seen: Dict[str, int] = {}

    if points_problem and any(u.story_points is not None for u in update_file.updates):
        errors.append(points_problem)

    for n, update in enumerate(update_file.updates, 1):
        where = f"update {n} ({update.issue})"
        row = Row(update=update, story_points_target=update.story_points)
        rows.append(row)
        if update.issue in seen:
            errors.append(f"{where}: {update.issue} is already updated by update "
                          f"{seen[update.issue]}")
            continue
        seen[update.issue] = n
        try:
            issue = client.get_issue(update.issue, ("summary", "status", "project"))
        except NotFoundError:
            errors.append(f"{where}: {update.issue} does not exist or is not visible to you")
            continue
        fields = issue.get("fields") or {}
        its_project = (fields.get("project") or {}).get("key", "?")
        if its_project != project_key:
            errors.append(f"{where}: {update.issue} belongs to project '{its_project}', "
                          f"not '{project_key}'")
            continue

        row.subject = fields.get("summary", "")
        row.current_status = (fields.get("status") or {}).get("name", "")
        row.already_applied = has_marker(client.list_comments(update.issue),
                                         update_file.session, account_id)
        if row.already_applied:
            continue

        if update.status is None:
            if update.transition_fields:
                errors.append(f"{where}: 'transition_fields' needs a 'status' to transition to")
            continue
        if update.status.casefold() == row.current_status.casefold():
            row.target_status = row.current_status
            if update.transition_fields:
                row.warnings.append(f"already in '{row.current_status}'; "
                                    f"'transition_fields' are not used")
            continue

        transitions = client.transitions(update.issue)
        leading = [t for t in transitions
                   if str((t.get("to") or {}).get("name", "")).casefold()
                   == update.status.casefold()]
        if not leading:
            reachable: List[str] = []
            for t in transitions:
                name = (t.get("to") or {}).get("name")
                if name and name not in reachable:
                    reachable.append(name)
            errors.append(f"{where}: status '{update.status}' cannot be reached from "
                          f"'{row.current_status}'; reachable now: "
                          f"{', '.join(reachable) or 'none'}")
            continue
        if len(leading) > 1:
            errors.append(f"{where}: several transitions lead to '{update.status}': "
                          f"{', '.join(repr(t.get('name')) for t in leading)}; this tool will "
                          f"not pick one - do this transition in Jira")
            continue
        chosen = leading[0]
        row.transition_id = str(chosen["id"])
        row.transition_name = chosen.get("name")
        row.target_status = chosen["to"]["name"]
        row.fields, row.field_labels, field_errors = resolve_transition_fields(
            chosen, update.transition_fields)
        errors += [f"{where}: {e}" for e in field_errors]

    return Plan(session=update_file.session, rows=rows, errors=errors, account_id=account_id,
                warnings=session_warnings(update_file.session),
                story_points_field=points_field)
