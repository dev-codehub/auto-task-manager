from __future__ import annotations

from typing import List

from .apply import Report, display
from .plan import Plan


def format_plan(plan: Plan) -> str:
    applied = sum(1 for row in plan.rows if row.already_applied)
    header = f"session {plan.session}: {len(plan.rows) - applied} to write"
    if applied:
        header += f", {applied} already applied"
    out: List[str] = [header]
    out += [f"note: {w}" for w in plan.warnings]
    shown = set()
    for n, row in enumerate(plan.rows, 1):
        prefix = f"update {n} ({row.update.issue}): "
        row_errors = [e for e in plan.errors if e.startswith(prefix)]
        shown.update(row_errors)
        out.append("")
        out.append(f"{row.update.issue}  {row.subject}".rstrip())
        if row.already_applied:
            out.append("  already applied in this session - will be skipped")
            continue
        if row.current_status:
            if row.transition_id is None:
                out.append(f"  status  {row.current_status}")
            else:
                out.append(f"  status  {row.current_status} -> {row.target_status}  "
                           f"(transition '{row.transition_name}')")
            for (_, sent), (name, _) in zip(row.fields.items(), row.field_labels):
                out.append(f"  {name} = {display(sent)}")
            if row.story_points_target is not None:
                out.append(f"  story points -> {display(row.story_points_target)}")
            lines = row.update.note.strip().splitlines()
            for line in lines[:3]:
                out.append(f"  | {line}")
            if len(lines) > 3:
                out.append(f"  | ... ({len(lines) - 3} more line(s))")
        for warning in row.warnings:
            out.append(f"  warning: {warning}")
        out += [f"  error: {e[len(prefix):]}" for e in row_errors]
    if plan.errors:
        others = [e for e in plan.errors if e not in shown]
        out.append("")
        out.append(f"{len(plan.errors)} error(s) - nothing will be written"
                   + (":" if others else " (see the rows above)"))
        out += [f"  - {e}" for e in others]
    return "\n".join(out)


def format_report(report: Report) -> str:
    out: List[str] = []
    for outcome in report.outcomes:
        out.append(f"{outcome.key}  {outcome.result}")
        out += [f"  ok: {v}" for v in outcome.verified]
        out += [f"  warning: {w}" for w in outcome.warnings]
    written = sum(1 for o in report.outcomes if o.result == "written")
    skipped = sum(1 for o in report.outcomes if o.result == "skipped")
    out.append("")
    if report.error:
        out.append(f"stopped at {report.error}")
        out.append(f"{written} issue(s) written before the stop; "
                   f"re-run the same command to resume")
    else:
        out.append(f"done: {written} written, {skipped} skipped")
    return "\n".join(out)
