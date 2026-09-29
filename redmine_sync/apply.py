from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .client import Client, RedmineError
from .plan import Plan, Row, has_marker, with_marker


class ApplyError(Exception):
    pass


@dataclass
class Outcome:
    issue_id: int
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
            report.outcomes.append(_apply_row(client, plan.session, plan.user_id, row))
        except (ApplyError, RedmineError) as e:
            report.error = f"#{row.issue_id} ({row.update.issue}): {e}"
            return report
    return report


def _apply_row(client: Client, session: str, user_id: int, row: Row) -> Outcome:
    assert row.issue_id is not None
    key = row.update.issue
    issue = client.get_issue(row.issue_id)
    if has_marker(issue.get("journals"), session, user_id):
        return Outcome(row.issue_id, key, "skipped", [], ["already applied in this session"])

    verified: List[str] = []
    warnings = list(row.warnings)

    if row.target_status_id is not None and issue["status"]["id"] != row.target_status_id:
        before = issue["status"]["name"]
        issue = client.write_and_reread(row.issue_id, {"status_id": row.target_status_id})
        if issue["status"]["id"] != row.target_status_id:
            raise ApplyError(
                f"status '{before}' -> '{row.target_status}' was not applied - the workflow "
                f"does not allow it for your role; nothing else was written to this issue")
        verified.append(f"status {before} -> {row.target_status}")

    fields = {"notes": with_marker(row.update.note, session)}
    if row.target_done is not None:
        fields["done_ratio"] = row.target_done
    issue = client.write_and_reread(row.issue_id, fields)
    if not has_marker(issue.get("journals"), session, user_id):
        raise ApplyError("the comment was sent but is not on the issue")
    verified.append("comment recorded")
    if row.target_done is not None:
        if issue.get("done_ratio") == row.target_done:
            verified.append(f"% Done {row.target_done}")
        elif issue.get("done_ratio") is None:
            warnings.append("% Done is not available on this issue (the field is disabled "
                            "for its tracker) - not set")
        else:
            warnings.append(f"% Done stayed at {issue.get('done_ratio')} - the instance derives "
                            f"it (from the status or from subtasks)")
    return Outcome(row.issue_id, key, "written", verified, warnings)
