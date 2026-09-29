from __future__ import annotations

from typing import List, Optional

from .apply import Report
from .plan import Plan


def _pct(value: Optional[int]) -> str:
    return "-" if value is None else f"{value}%"


def format_plan(plan: Plan) -> str:
    applied = sum(1 for row in plan.rows if row.already_applied)
    header = f"session {plan.session}: {len(plan.rows) - applied} to write"
    if applied:
        header += f", {applied} already applied"
    header += f" (notes in {plan.text_format})"
    out: List[str] = [header]
    for row in plan.rows:
        head = f"#{row.issue_id}" if row.issue_id is not None else "(unresolved)"
        out.append("")
        out.append(f"{head}  {row.update.issue}  {row.subject}".rstrip())
        if row.already_applied:
            out.append("  already applied in this session - will be skipped")
            continue
        if row.current_status_id is None:
            continue
        if row.target_status_id is None or row.target_status_id == row.current_status_id:
            out.append(f"  status  {row.current_status}")
        else:
            checked = "" if row.transition_checked else "  (not checkable in advance - verified on write)"
            out.append(f"  status  {row.current_status} -> {row.target_status}{checked}")
        if row.target_done is None or row.target_done == row.current_done:
            out.append(f"  done    {_pct(row.current_done)}")
        else:
            out.append(f"  done    {_pct(row.current_done)} -> {_pct(row.target_done)}")
        lines = row.update.note.strip().splitlines()
        for line in lines[:3]:
            out.append(f"  | {line}")
        if len(lines) > 3:
            out.append(f"  | ... ({len(lines) - 3} more line(s))")
        for warning in row.warnings:
            out.append(f"  warning: {warning}")
    if plan.errors:
        out.append("")
        out.append(f"{len(plan.errors)} error(s) - nothing will be written:")
        out += [f"  - {e}" for e in plan.errors]
    return "\n".join(out)


def format_report(report: Report) -> str:
    out: List[str] = []
    for outcome in report.outcomes:
        out.append(f"#{outcome.issue_id}  {outcome.key}  {outcome.result}")
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


def format_backlog_plan(plan) -> str:
    lines = [f"{len(plan.order)} node(s), {len(plan.relations)} relation(s)"]
    for pn in plan.order:
        if pn.exists:
            lines.append(f"  {pn.node.id:14} already exists as #{pn.issue_id}")
        else:
            parent = f" (parent {pn.parent_ref})" if pn.parent_ref else ""
            lines.append(f"  {pn.node.id:14} would create{parent}")
    for pr in plan.relations:
        r = pr.relation
        lines.append(f"  {r.from_id} {r.type} {r.to_id}"
                     f"{'  (already exists)' if pr.exists else ''}")
    if plan.errors:
        lines.append("")
        lines.append(f"{len(plan.errors)} problem(s):")
        lines.extend(f"  - {e}" for e in plan.errors)
    return "\n".join(lines)


def format_backlog_report(report) -> str:
    lines = []
    for o in report.nodes:
        tag = f"#{o.issue_id}" if o.issue_id is not None else ""
        lines.append(f"  {o.result:12} {o.node_id:14} {tag}")
        lines.extend(f"    warning: {w}" for w in o.warnings)
    for r in report.relations:
        lines.append(f"  {r.result:12} {r.label}")
    if report.error:
        lines.append(f"\nerror: {report.error}")
    return "\n".join(lines)


def format_parent_report(report) -> str:
    lines = [f"correct: {report.correct}   wrong: {len(report.wrong)}   "
            f"absent: {len(report.absent)}   unresolved: {len(report.unresolved)}   "
            f"ambiguous: {len(report.ambiguous)}"]
    for fix in report.wrong:
        have = fix.current if fix.current is not None else "NONE"
        want = fix.wanted if fix.wanted is not None else "NONE"
        if fix.node_id in report.fixed:
            status = "  (fixed)"
        elif fix.node_id in report.not_confirmed:
            status = "  (write sent but did not land - check permissions)"
        else:
            status = ""
        lines.append(f"  {fix.node_id:14} #{fix.issue_id}  parent {have} -> {want}{status}")
    for nid in report.absent:
        lines.append(f"  {nid:14} not in the project - nothing to fix")
    for nid in report.unresolved:
        lines.append(f"  {nid:14} parent not resolvable")
    for nid in report.ambiguous:
        lines.append(f"  {nid:14} matches more than one issue - not touched")
    if report.error:
        lines.append(f"\nerror: {report.error}")
    return "\n".join(lines)


def format_description_report(report) -> str:
    lines = []
    for o in report.outcomes:
        tag = f"#{o.issue_id}" if o.issue_id is not None else "(no issue)"
        lines.append(f"  {o.result:18} {o.node_id:14} {tag}")
    if report.error:
        lines.append(f"\nerror: {report.error}")
    return "\n".join(lines)
