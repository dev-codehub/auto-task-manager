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


def format_backlog_plan(plan) -> str:
    new = sum(1 for pn in plan.order if not pn.exists)
    lines = [f"project {plan.project_key}: {new} to create, {len(plan.order) - new} already "
             f"there, {len(plan.relations)} relation(s)"]
    for pn in plan.order:
        if pn.exists:
            lines.append(f"  {pn.node.id:14} already exists as {pn.issue_key}")
            continue
        what = f"would create {pn.node.type}"
        if pn.parent_ref:
            what += f" (parent {pn.parent_ref})"
        if pn.node.priority is not None:
            what += f", priority {pn.node.priority}"
        if pn.node.story_points is not None:
            what += f", story points {display(pn.node.story_points)}"
        lines.append(f"  {pn.node.id:14} {what}")
    for pr in plan.relations:
        r = pr.relation
        lines.append(f"  {r.from_id} {r.type} {r.to_id}"
                     f"{'  (already exists)' if pr.exists else ''}")
    if plan.errors:
        lines.append("")
        lines.append(f"{len(plan.errors)} problem(s) - nothing will be written:")
        lines.extend(f"  - {e}" for e in plan.errors)
    return "\n".join(lines)


def format_backlog_report(report) -> str:
    lines: List[str] = []
    for o in report.nodes:
        lines.append(f"  {o.result:12} {o.node_id:14} {o.issue_key or ''}".rstrip())
        lines.extend(f"    ok: {v}" for v in o.verified)
        lines.extend(f"    note: {n}" for n in o.notes)
        lines.extend(f"    warning: {w}" for w in o.warnings)
    for r in report.relations:
        lines.append(f"  {r.result:12} {r.label}")
        lines.extend(f"    warning: {w}" for w in r.warnings)
    created = sum(1 for o in report.nodes if o.result == "created")
    skipped = sum(1 for o in report.nodes if o.result == "skipped")
    lines.append("")
    if report.error:
        lines.append(f"stopped at {report.error}")
        lines.append(f"{created} issue(s) created before the stop; re-run the same command to "
                     f"resume - what already exists is skipped")
    else:
        links = sum(1 for r in report.relations if r.result == "created")
        lines.append(f"done: {created} created, {skipped} skipped; {links} link(s) created, "
                     f"{len(report.relations) - links} skipped")
    return "\n".join(lines)


def format_parent_report(report) -> str:
    lines = [f"correct: {report.correct}   wrong: {len(report.wrong)}   "
             f"absent: {len(report.absent)}   unresolved: {len(report.unresolved)}   "
             f"ambiguous: {len(report.ambiguous)}"]
    for fix in report.wrong:
        if fix.node_id in report.fixed:
            status = "  (fixed)"
        elif fix.node_id in report.not_confirmed:
            status = "  (write sent but did not land - check permissions and the edit screen)"
        else:
            status = ""
        lines.append(f"  {fix.node_id:14} {fix.issue_key}  parent {fix.current or 'NONE'} -> "
                     f"{fix.wanted or 'NONE'}{status}")
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
    lines: List[str] = []
    for o in report.outcomes:
        lines.append(f"  {o.result:18} {o.node_id:14} {o.issue_key or '(no issue)'}")
        lines.extend(f"    note: {n}" for n in o.notes)
    if report.error:
        lines.append(f"\nerror: {report.error}")
    return "\n".join(lines)
