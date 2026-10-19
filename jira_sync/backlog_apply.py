from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from .adf import markdown_to_adf
from .apply import _reads_back_as, display
from .backlog_file import BacklogFile
from .backlog_plan import BacklogPlan, PlannedNode, _link_exists, index_by_key, resolve_key
from .client import Client, JiraError

# A description is only checked as present and non-empty: Jira stores its own
# normal form of the document, so comparing content would fail a correct write.
DESCRIPTION_NOTE = "description written, content not compared"


@dataclass
class NodeOutcome:
    node_id: str
    result: str
    issue_key: Optional[str] = None
    verified: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass
class RelationOutcome:
    label: str
    result: str
    warnings: List[str] = field(default_factory=list)


@dataclass
class BacklogReport:
    nodes: List[NodeOutcome] = field(default_factory=list)
    relations: List[RelationOutcome] = field(default_factory=list)
    error: Optional[str] = None


def link_endpoints(from_key: str, to_key: str, link_type: dict) -> Tuple[str, str]:
    """(inward_key, outward_key) for POST /issueLink, so that the plan's
    "from <type> to" (A blocks B, A duplicates B) reads back on `from` with
    `to` as its outwardIssue - the reading `_link_exists` in backlog_plan.py
    uses to find an existing relation. `link_type` is the site's link type, in
    case one type ever needs its own orientation; none does today.

    The orientation is the fake's model (tests/fake_jira.py: a POST with
    inwardIssue=X, outwardIssue=Y reads back on Y with X as outwardIssue).
    Task 10 must confirm it on a real site; if Jira turns out the other way,
    the fix is this one line."""
    return to_key, from_key


def _endpoint(ref: str, keys: Dict[str, str]) -> str:
    """A reference's issue key: '#KEY' itself, or the key a node was found or
    created as (its own id when it is still only planned, in a dry run)."""
    return ref[1:] if ref.startswith("#") else keys.get(ref, ref)


def apply_backlog_plan(client: Client, plan: BacklogPlan, write: bool) -> BacklogReport:
    if not plan.ok:
        raise ValueError("refusing to apply a plan that has errors")
    report = BacklogReport()
    keys: Dict[str, str] = {}

    for pn in plan.order:
        if pn.exists:
            report.nodes.append(NodeOutcome(pn.node.id, "skipped", pn.issue_key))
            keys[pn.node.id] = pn.issue_key
            continue
        if not write:
            report.nodes.append(NodeOutcome(pn.node.id, "would create"))
            continue
        fields = _create_fields(plan, pn, keys)
        try:
            made = client.create_issue(fields)
        except JiraError as e:
            report.error = f"{pn.node.id}: {e}"
            return report
        outcome = NodeOutcome(pn.node.id, "created", made["key"])
        keys[pn.node.id] = made["key"]
        report.nodes.append(outcome)
        try:
            problem = _verify_created(client, plan, pn, fields, outcome)
        except JiraError as e:
            problem = f"it could not be read back ({e})"
        if problem:
            report.error = (f"{pn.node.id} ({made['key']}): {problem}; the issue was created, "
                            f"so a re-run skips it")
            return report

    done: Set[Tuple[str, ...]] = set()
    for pr in plan.relations:
        rel = pr.relation
        label = f"{rel.from_id} {rel.type} {rel.to_id}"
        if pr.exists:
            report.relations.append(RelationOutcome(label, "skipped"))
            continue
        from_key, to_key = _endpoint(rel.from_id, keys), _endpoint(rel.to_id, keys)
        ends = tuple(sorted((from_key, to_key))) if rel.type == "relates" else (from_key, to_key)
        ident = (rel.type,) + ends
        if ident in done:
            report.relations.append(RelationOutcome(
                label, "skipped", ["listed twice in the plan file; the link is made once"]))
            continue
        done.add(ident)
        if not write:
            report.relations.append(RelationOutcome(label, "would create"))
            continue
        assert pr.link_type is not None
        inward, outward = link_endpoints(from_key, to_key, {"name": pr.link_type})
        try:
            client.create_link(pr.link_type, inward, outward)
            links = (client.get_issue(from_key, ("issuelinks",)).get("fields") or {}).get(
                "issuelinks") or []
        except JiraError as e:
            report.error = f"relation {label}: {e}"
            return report
        # Presence only; which end is which is link_endpoints' call.
        if not _link_exists(links, {"name": pr.link_type}, to_key):
            report.error = (f"relation {label}: Jira accepted the link but {from_key} does not "
                            f"show a '{pr.link_type}' link to {to_key}")
            return report
        report.relations.append(RelationOutcome(label, "created"))

    return report


def _create_fields(plan: BacklogPlan, pn: PlannedNode, keys: Dict[str, str]) -> Dict[str, Any]:
    node = pn.node
    fields: Dict[str, Any] = {"project": {"key": plan.project_key},
                              "issuetype": {"id": pn.type_id}, "summary": node.subject}
    description = markdown_to_adf(node.description)
    if description["content"]:
        fields["description"] = description
    if pn.parent_ref is not None:
        fields["parent"] = {"key": _endpoint(pn.parent_ref, keys)}
    if node.priority is not None:
        fields["priority"] = {"name": node.priority}
    if node.story_points is not None:
        assert plan.story_points_field is not None
        fields[plan.story_points_field] = node.story_points
    return fields


def _verify_created(client: Client, plan: BacklogPlan, pn: PlannedNode,
                    sent: Dict[str, Any], outcome: NodeOutcome) -> Optional[str]:
    """Read the new issue back. Structured fields compare exactly (a mismatch
    is the returned problem), except the parent, which warns towards
    fix-parents; the description only has to be there and not empty."""
    node = pn.node
    points = plan.story_points_field if node.story_points is not None else None
    wanted = ("issuetype", "parent", "priority", "description") + ((points,) if points else ())
    live = client.get_issue(outcome.issue_key, wanted).get("fields") or {}

    issue_type = live.get("issuetype") or {}
    if str(issue_type.get("id")) != pn.type_id:
        return (f"type was sent as '{node.type}' but reads back as "
                f"'{issue_type.get('name')}'")
    outcome.verified.append(f"type {node.type}")
    if "parent" in sent:
        want = sent["parent"]["key"]
        have = (live.get("parent") or {}).get("key")
        if have == want:
            outcome.verified.append(f"parent {want}")
        else:
            outcome.warnings.append(
                f"parent {want} was sent but reads back as {have or 'none'} - run "
                f"'jira-backlog fix-parents' to correct it")
    if "priority" in sent:
        have = (live.get("priority") or {}).get("name")
        if have != node.priority:
            return f"priority was sent as '{node.priority}' but reads back as {have!r}"
        outcome.verified.append(f"priority {node.priority}")
    if points:
        have = live.get(points)
        if not _reads_back_as(node.story_points, have):
            return (f"story points were sent as {display(node.story_points)} but read back as "
                    f"{have!r} - Jira accepted them without storing them ({points})")
        outcome.verified.append(f"story points {display(node.story_points)}")
    if "description" in sent:
        if not _has_content(live.get("description")):
            return (f"the description was sent but reads back empty; write it with "
                    f"'jira-backlog update-descriptions --only {node.id} --write'")
        outcome.notes.append(DESCRIPTION_NOTE)
    return None


def _has_content(description: Any) -> bool:
    return isinstance(description, dict) and bool(description.get("content"))


@dataclass
class ParentFix:
    node_id: str
    issue_key: str
    current: Optional[str]
    wanted: Optional[str]


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


def _project_issues(client: Client, file: BacklogFile, fields: Tuple[str, ...]) -> List[dict]:
    project_key = client.get_project(file.project)["key"]
    return client.search(f"project = {project_key}", fields)


def fix_parents(client: Client, file: BacklogFile, write: bool) -> ParentReport:
    issues = _project_issues(client, file, ("summary", "parent"))
    key_index = index_by_key(issues)
    parent_of: Dict[str, Optional[str]] = {
        i["key"]: (((i.get("fields") or {}).get("parent")) or {}).get("key") for i in issues}

    report = ParentReport()
    for node in file.nodes:
        key, ambiguity = resolve_key(key_index, node.id)
        if ambiguity:
            report.ambiguous.append(node.id)
            continue
        if key is None:
            report.absent.append(node.id)
            continue
        if node.parent is None:
            wanted: Optional[str] = None
        elif node.parent.startswith("#"):
            wanted = node.parent[1:]
        else:
            wanted, parent_ambiguity = resolve_key(key_index, node.parent)
            if parent_ambiguity or wanted is None:
                report.unresolved.append(node.id)
                continue
        have = parent_of[key]
        if have == wanted:
            report.correct += 1
        else:
            report.wrong.append(ParentFix(node.id, key, have, wanted))

    if not write:
        return report

    for fix in report.wrong:
        try:
            reread = client.write_and_reread(
                fix.issue_key, {"parent": {"key": fix.wanted} if fix.wanted else None})
        except JiraError as e:
            report.error = f"{fix.node_id} ({fix.issue_key}): {e}"
            return report
        have = (((reread.get("fields") or {}).get("parent")) or {}).get("key")
        (report.fixed if have == fix.wanted else report.not_confirmed).append(fix.node_id)
    return report


@dataclass
class DescriptionOutcome:
    node_id: str
    issue_key: Optional[str]
    result: str
    notes: List[str] = field(default_factory=list)


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
    report = DescriptionReport()
    unknown = wanted - {n.id for n in file.nodes}
    if unknown:
        report.error = f"--only names id(s) not in the plan file: {', '.join(sorted(unknown))}"
        return report
    key_index = index_by_key(_project_issues(client, file, ("summary",)))

    for node in file.nodes:
        if node.id not in wanted:
            continue
        key, ambiguity = resolve_key(key_index, node.id)
        if ambiguity:
            report.outcomes.append(DescriptionOutcome(node.id, None, "ambiguous"))
            continue
        if key is None:
            report.outcomes.append(DescriptionOutcome(node.id, None, "skipped-no-issue"))
            continue
        if not write:
            report.outcomes.append(DescriptionOutcome(node.id, key, "would update"))
            continue
        description = markdown_to_adf(node.description)
        empty = not description["content"]
        try:
            reread = client.write_and_reread(key, {"description": None if empty else description})
        except JiraError as e:
            report.error = f"{node.id} ({key}): {e}"
            return report
        if empty:
            report.outcomes.append(DescriptionOutcome(
                node.id, key, "updated", ["description empty in the plan file - cleared"]))
            continue
        if not _has_content((reread.get("fields") or {}).get("description")):
            report.error = (f"{node.id} ({key}): the description was sent but reads back "
                            f"empty - Jira accepted the edit without storing it")
            return report
        report.outcomes.append(DescriptionOutcome(node.id, key, "updated", [DESCRIPTION_NOTE]))
    return report
