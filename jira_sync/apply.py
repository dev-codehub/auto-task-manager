from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

from .client import Client, JiraError
from .plan import Plan, Row, has_marker, with_marker_adf


class ApplyError(Exception):
    pass


@dataclass
class Outcome:
    issue_key: str
    key: str
    result: str
    verified: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class Report:
    outcomes: List[Outcome]
    error: Optional[str] = None


def apply_plan(client: Client, plan: Plan) -> Report:
    if not plan.ok:
        raise ValueError("refusing to apply a plan that has errors")
    report = Report(outcomes=[])
    for row in plan.rows:
        try:
            report.outcomes.append(_apply_row(client, plan, row))
        except (ApplyError, JiraError) as e:
            report.error = f"{row.update.issue}: {e}"
            return report
    return report


def display(value: Any) -> str:
    """A field value as the person would write it: an option's name or value,
    a number without a trailing .0."""
    if isinstance(value, dict) and len(value) == 1:
        value = next(iter(value.values()))
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _is_number(value: Any) -> bool:
    return type(value) in (int, float)


def _reads_back_as(sent: Any, live: Any) -> bool:
    """Exact comparison. An option is sent as {"name": ...} or {"value": ...}
    and read back as a fuller object, so only the keys sent are compared."""
    if isinstance(sent, dict):
        return isinstance(live, dict) and all(live.get(k) == v for k, v in sent.items())
    if _is_number(sent):
        return _is_number(live) and live == sent
    return live == sent


def _apply_row(client: Client, plan: Plan, row: Row) -> Outcome:
    key = row.update.issue
    if row.already_applied or has_marker(client.list_comments(key), plan.session,
                                         plan.account_id):
        return Outcome(key, key, "skipped", [], ["already applied in this session"])
    verified: List[str] = []
    try:
        _write_row(client, plan, row, verified)
    except (ApplyError, JiraError) as e:
        if verified:
            raise ApplyError(f"{e} (already done on this issue: {', '.join(verified)}; "
                             f"the comment was not written)") from None
        raise
    return Outcome(key, key, "written", verified, list(row.warnings))


def _write_row(client: Client, plan: Plan, row: Row, verified: List[str]) -> None:
    """Transition, then story points, then the comment. The comment carries the
    marker that makes a re-run skip the row, so it goes last: a row that stops
    part-way is picked up again by the next run."""
    key = row.update.issue
    if row.transition_id is not None:
        _transition(client, row, verified)
    if row.story_points_target is not None:
        assert plan.story_points_field is not None
        target = row.story_points_target
        issue = client.write_and_reread(key, {plan.story_points_field: target})
        live = (issue.get("fields") or {}).get(plan.story_points_field)
        if not _reads_back_as(target, live):
            raise ApplyError(
                f"story points were sent as {display(target)} but read back as {live!r} - "
                f"Jira accepted the edit without storing it; the story points field "
                f"({plan.story_points_field}) is probably not on this issue's edit screen")
        verified.append(f"story points {display(target)}")
    client.add_comment(key, with_marker_adf(row.update.note, plan.session))
    if not has_marker(client.list_comments(key), plan.session, plan.account_id):
        raise ApplyError("the comment was sent but is not on the issue")
    verified.append("comment recorded")


def _transition(client: Client, row: Row, verified: List[str]) -> None:
    key = row.update.issue
    move = f"'{row.current_status}' -> '{row.target_status}'"
    try:
        client.do_transition(key, row.transition_id, row.fields)
    except JiraError as e:
        raise ApplyError(f"transition {move} failed: {e}; nothing else was written "
                         f"to this issue") from None
    live = client.get_issue(key, ("status", *row.fields)).get("fields") or {}
    status = (live.get("status") or {}).get("name")
    if status != row.target_status:
        raise ApplyError(
            f"transition {move} did not land - Jira accepted it but the issue reads back as "
            f"'{status}' (a workflow rule or automation may have moved it); nothing else "
            f"was written to this issue")
    verified.append(f"status {row.current_status} -> {row.target_status}")
    for (fid, sent), (name, _) in zip(row.fields.items(), row.field_labels):
        if not _reads_back_as(sent, live.get(fid)):
            raise ApplyError(f"{name} was sent as '{display(sent)}' with the transition but "
                             f"reads back as {live.get(fid)!r}")
        verified.append(f"{name} = {display(sent)}")
