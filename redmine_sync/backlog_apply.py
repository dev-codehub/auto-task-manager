from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .backlog_file import BacklogFile
from .backlog_plan import BacklogPlan, index_by_key, resolve_key
from .client import Client, RedmineError


@dataclass
class NodeOutcome:
    node_id: str
    result: str
    issue_id: Optional[int] = None
    warnings: List[str] = field(default_factory=list)


@dataclass
class RelationOutcome:
    label: str
    result: str


@dataclass
class BacklogReport:
    nodes: List[NodeOutcome] = field(default_factory=list)
    relations: List[RelationOutcome] = field(default_factory=list)
    error: Optional[str] = None


def apply_backlog_plan(client: Client, plan: BacklogPlan, write: bool) -> BacklogReport:
    if not plan.ok:
        raise ValueError("refusing to apply a plan that has errors")
    report = BacklogReport()
    created_ids: Dict[str, int] = {}

    for pn in plan.order:
        if pn.exists:
            report.nodes.append(NodeOutcome(pn.node.id, "skipped", pn.issue_id))
            created_ids[pn.node.id] = pn.issue_id
            continue
        if not write:
            report.nodes.append(NodeOutcome(pn.node.id, "would create"))
            continue
        fields = {
            "subject": pn.node.subject, "description": pn.node.description,
            "tracker_id": pn.tracker_id, "priority_id": pn.priority_id,
        }
        if pn.version_id is not None:
            fields["fixed_version_id"] = pn.version_id
        if pn.category_id is not None:
            fields["category_id"] = pn.category_id
        if pn.node.estimated_hours is not None:
            fields["estimated_hours"] = pn.node.estimated_hours
        parent_id = _resolve_parent_id(pn.parent_ref, created_ids)
        if parent_id is not None:
            fields["parent_issue_id"] = parent_id
        try:
            issue = client.create_issue(plan.project_id, fields)
        except RedmineError as e:
            report.error = f"{pn.node.id}: {e}"
            return report
        created_ids[pn.node.id] = issue["id"]
        warnings: List[str] = []
        if parent_id is not None and (issue.get("parent") or {}).get("id") != parent_id:
            warnings.append(f"parent was not set on creation - run "
                            f"'redmine-backlog fix-parents' to correct it")
        report.nodes.append(NodeOutcome(pn.node.id, "created", issue["id"], warnings))

    for pr in plan.relations:
        label = f"{pr.relation.from_id} {pr.relation.type} {pr.relation.to_id}"
        if pr.exists:
            report.relations.append(RelationOutcome(label, "skipped"))
            continue
        if not write:
            report.relations.append(RelationOutcome(label, "would create"))
            continue
        from_id = _resolve_ref(pr.relation.from_id, created_ids)
        to_id = _resolve_ref(pr.relation.to_id, created_ids)
        try:
            created = client.create_relation(from_id, to_id, pr.relation.type, pr.relation.delay)
        except RedmineError as e:
            report.error = f"relation {label}: {e}"
            return report
        if created.get("relation_type") != pr.relation.type:
            report.error = (f"relation {label}: Redmine created "
                            f"'{created.get('relation_type')}' instead of '{pr.relation.type}'")
            return report
        report.relations.append(RelationOutcome(label, "created"))

    return report


def _resolve_parent_id(ref: Optional[str], created_ids: Dict[str, int]) -> Optional[int]:
    if ref is None:
        return None
    return _resolve_ref(ref, created_ids)


def _resolve_ref(ref: str, created_ids: Dict[str, int]) -> int:
    if ref.startswith("#"):
        return int(ref[1:])
    return created_ids[ref]


@dataclass
class ParentFix:
    node_id: str
    issue_id: int
    current: Optional[int]
    wanted: Optional[int]


@dataclass
class ParentReport:
    correct: int = 0
    absent: List[str] = field(default_factory=list)
    unresolved: List[str] = field(default_factory=list)
    ambiguous: List[str] = field(default_factory=list)
    wrong: List[ParentFix] = field(default_factory=list)
    fixed: List[str] = field(default_factory=list)
    not_confirmed: List[str] = field(default_factory=list)
    error: Optional[str] = None


def fix_parents(client: Client, file: BacklogFile, write: bool) -> ParentReport:
    project_issues = client.list_issues(file.project)
    key_index = index_by_key(project_issues)
    parent_of: Dict[int, Optional[int]] = {
        issue["id"]: (issue.get("parent") or {}).get("id") for issue in project_issues}

    report = ParentReport()
    to_fix: List[ParentFix] = []
    for node in file.nodes:
        issue_id, ambiguity = resolve_key(key_index, node.id)
        if ambiguity:
            report.ambiguous.append(node.id)
            continue
        if issue_id is None:
            report.absent.append(node.id)
            continue
        if node.parent is None:
            wanted: Optional[int] = None
        elif node.parent.startswith("#"):
            wanted = int(node.parent[1:])
        else:
            parent_id, parent_ambiguity = resolve_key(key_index, node.parent)
            if parent_ambiguity or parent_id is None:
                report.unresolved.append(node.id)
                continue
            wanted = parent_id
        have = parent_of[issue_id]
        if have == wanted:
            report.correct += 1
        else:
            fix = ParentFix(node.id, issue_id, have, wanted)
            report.wrong.append(fix)
            to_fix.append(fix)

    if not write:
        return report

    for fix in to_fix:
        try:
            reread = client.write_and_reread(fix.issue_id, {"parent_issue_id": fix.wanted})
        except RedmineError as e:
            report.error = f"{fix.node_id}: {e}"
            return report
        if (reread.get("parent") or {}).get("id") != fix.wanted:
            report.not_confirmed.append(fix.node_id)
        else:
            report.fixed.append(fix.node_id)
    return report


@dataclass
class DescriptionOutcome:
    node_id: str
    issue_id: Optional[int]
    result: str


@dataclass
class DescriptionReport:
    outcomes: List[DescriptionOutcome] = field(default_factory=list)
    error: Optional[str] = None


def update_descriptions(client: Client, file: BacklogFile, only: List[str],
                        write: bool) -> DescriptionReport:
    if write and not only:
        raise ValueError("update_descriptions: write=True requires a non-empty 'only' list - "
                         "there is no 'every node' default for a write")
    wanted = set(only) if only else {n.id for n in file.nodes}
    key_index = index_by_key(client.list_issues(file.project))

    report = DescriptionReport()
    unknown = wanted - {n.id for n in file.nodes}
    if unknown:
        report.error = f"--only names id(s) not in the plan file: {', '.join(sorted(unknown))}"
        return report
    for node in file.nodes:
        if node.id not in wanted:
            continue
        issue_id, ambiguity = resolve_key(key_index, node.id)
        if ambiguity:
            report.outcomes.append(DescriptionOutcome(node.id, None, "ambiguous"))
            continue
        if issue_id is None:
            report.outcomes.append(DescriptionOutcome(node.id, None, "skipped-no-issue"))
            continue
        if not write:
            report.outcomes.append(DescriptionOutcome(node.id, issue_id, "would update"))
            continue
        try:
            reread = client.write_and_reread(issue_id, {"description": node.description})
        except RedmineError as e:
            report.error = f"{node.id}: {e}"
            return report
        if reread.get("description") != node.description:
            report.error = f"{node.id}: description was sent but does not read back as sent"
            return report
        report.outcomes.append(DescriptionOutcome(node.id, issue_id, "updated"))
    return report
