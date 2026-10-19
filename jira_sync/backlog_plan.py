from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .backlog_file import BacklogFile, Node, Relation, subject_key
from .client import Client, NotFoundError
from .plan import find_story_points_field

# The plan's relation types and the site's link-type names they map to
# (matched casefolded).
LINK_TYPE_NAMES = {"relates": "Relates", "duplicates": "Duplicate", "blocks": "Blocks"}
_ISSUE_FIELDS = ("summary", "issuetype", "issuelinks")


@dataclass
class PlannedNode:
    node: Node
    exists: bool
    issue_key: Optional[str] = None
    type_id: Optional[str] = None
    parent_ref: Optional[str] = None


@dataclass
class PlannedRelation:
    relation: Relation
    exists: bool
    # The site's own name for the link type, as POST /issueLink wants it.
    link_type: Optional[str] = None


@dataclass
class BacklogPlan:
    project_key: str
    order: List[PlannedNode]
    relations: List[PlannedRelation]
    errors: List[str] = field(default_factory=list)
    story_points_field: Optional[str] = None

    @property
    def ok(self) -> bool:
        return not self.errors


def _key_order(key: str) -> Tuple[str, int]:
    project, _, number = key.rpartition("-")
    return project, int(number) if number.isdigit() else 0


def index_by_key(issues: List[dict]) -> Dict[str, List[str]]:
    """Every issue's key, grouped by its casefolded summary prefix - a prefix
    with more than one key is ambiguous and must never be resolved by picking
    one silently."""
    idx: Dict[str, List[str]] = {}
    for issue in issues:
        summary = (issue.get("fields") or {}).get("summary") or ""
        idx.setdefault(subject_key(summary).casefold(), []).append(issue["key"])
    return idx


def resolve_key(index: Dict[str, List[str]], key: str) -> Tuple[Optional[str], Optional[str]]:
    """(issue key, None) on a clean match, (None, None) on no match,
    (None, error) when more than one issue shares this prefix."""
    keys = index.get(key.casefold())
    if not keys:
        return None, None
    if len(keys) > 1:
        return None, f"'{key}' is ambiguous, it matches {', '.join(sorted(keys, key=_key_order))}"
    return keys[0], None


def _order_new_nodes(nodes: List[Node], existing_ids: set) -> Tuple[List[Node], List[str]]:
    """Topological order: a node is ready once its parent is None, '#KEY',
    already-existing, or already placed in the returned order."""
    placed: List[Node] = []
    placed_ids = set(existing_ids)
    remaining = [n for n in nodes if n.id not in existing_ids]
    errors: List[str] = []
    while remaining:
        ready = [n for n in remaining
                 if n.parent is None or n.parent.startswith("#") or n.parent in placed_ids]
        if not ready:
            errors.append("cycle among parent references: " +
                          ", ".join(sorted(n.id for n in remaining)))
            break
        placed.extend(ready)
        placed_ids.update(n.id for n in ready)
        remaining = [n for n in remaining if n not in ready]
    return placed, errors


def _level(issue_type: Optional[dict], types_by_id: Dict[str, dict]) -> Optional[int]:
    if not issue_type:
        return None
    level = issue_type.get("hierarchyLevel")
    if level is None:
        level = types_by_id.get(str(issue_type.get("id")), {}).get("hierarchyLevel")
    return level if isinstance(level, int) and not isinstance(level, bool) else None


def _link_exists(links: List[dict], link_type: dict, other_key: str) -> bool:
    """Whether an issue's `issuelinks` already hold this link to `other_key`.
    Read back on an issue, each entry names the other end; under
    `outwardIssue` when this issue plays the outward role ("this blocks
    other"), as the fake models it. For a symmetric type (same inward and
    outward wording, e.g. Relates) either side counts.
    Unconfirmed against a real site until Task 10."""
    name = str(link_type.get("name", "")).casefold()
    symmetric = link_type.get("inward") == link_type.get("outward")
    for link in links or []:
        if str((link.get("type") or {}).get("name", "")).casefold() != name:
            continue
        outward = (link.get("outwardIssue") or {}).get("key")
        inward = (link.get("inwardIssue") or {}).get("key")
        if outward == other_key or (symmetric and inward == other_key):
            return True
    return False


def build_backlog_plan(client: Client, file: BacklogFile,
                       story_points_field: Optional[str] = None) -> BacklogPlan:
    project_key = client.get_project(file.project)["key"]
    errors: List[str] = []

    types = client.issue_types(project_key)
    types_by_name = {t["name"]: t for t in types}
    types_by_id = {str(t["id"]): t for t in types}

    points_field, points_problem = find_story_points_field(client, story_points_field)
    if points_problem and any(n.story_points is not None for n in file.nodes):
        errors.append(points_problem)

    # A reference that isn't '#KEY' is always another node's own id
    # (backlog_file.py guarantees it), so only this file's node ids are ever
    # resolved against the project - and more than one match is an error.
    project_issues = client.search(f"project = {project_key}", _ISSUE_FIELDS)
    issue_by_key = {i["key"]: i for i in project_issues}
    key_index = index_by_key(project_issues)
    existing: Dict[str, str] = {}
    for node in file.nodes:
        key, ambiguity = resolve_key(key_index, node.id)
        if ambiguity:
            errors.append(f"node ({node.id}): {ambiguity}")
            continue
        if key is not None:
            existing[node.id] = key

    # '#KEY' references (parents and relation endpoints), one GET each. The
    # issue may be in another project; it only has to exist and be visible.
    refs = {n.parent for n in file.nodes if n.parent and n.parent.startswith("#")}
    refs |= {r.from_id for r in file.relations if r.from_id.startswith("#")}
    refs |= {r.to_id for r in file.relations if r.to_id.startswith("#")}
    fetched: Dict[str, dict] = {}
    for ref in sorted(refs):
        try:
            fetched[ref] = client.get_issue(ref[1:], _ISSUE_FIELDS)
        except NotFoundError:
            errors.append(f"'{ref}': issue {ref[1:]} does not exist or is not visible to you")

    def issue_of(ref: str) -> Optional[dict]:
        """The Jira issue behind a reference, or None for a node still to create."""
        if ref.startswith("#"):
            return fetched.get(ref)
        if ref in existing:
            return issue_by_key.get(existing[ref])
        return None

    order_nodes, cycle_errors = _order_new_nodes(file.nodes, set(existing))
    errors.extend(cycle_errors)
    # Existing nodes first (nothing to create for them), then the new ones,
    # parents before children, so a caller creates in a single pass.
    ordered_ids = [n.id for n in file.nodes if n.id in existing] + [n.id for n in order_nodes]
    by_id = {n.id: n for n in file.nodes}

    screens: Dict[str, Dict[str, dict]] = {}

    def screen(type_id: str) -> Dict[str, dict]:
        if type_id not in screens:
            screens[type_id] = {str(f.get("fieldId") or f.get("key")): f
                                for f in client.create_screen_fields(project_key, type_id)}
        return screens[type_id]

    field_names: Dict[str, str] = {}

    def field_label(fid: str) -> str:
        if not field_names:
            field_names.update({str(f.get("id")): str(f.get("name", ""))
                                for f in client.list_fields()})
        name = field_names.get(fid)
        return f"'{name}' ({fid})" if name else fid

    planned: List[PlannedNode] = []
    for nid in ordered_ids:
        node = by_id[nid]
        pn = PlannedNode(node=node, exists=nid in existing, issue_key=existing.get(nid),
                         parent_ref=node.parent)
        planned.append(pn)
        if pn.exists:
            continue
        issue_type = types_by_name.get(node.type)
        if issue_type is None:
            errors.append(f"node ({nid}): type '{node.type}' does not exist in '{project_key}'; "
                          f"available: {', '.join(sorted(types_by_name)) or '(none)'}")
            continue
        pn.type_id = str(issue_type["id"])
        where = f"the '{node.type}' create screen in '{project_key}'"

        if node.priority is not None:
            meta = screen(pn.type_id).get("priority")
            if meta is None:
                errors.append(f"node ({nid}): 'priority' is set but {where} has no priority "
                              f"field; leave 'priority' out")
            elif meta.get("allowedValues"):
                names = [str(v.get("name")) for v in meta["allowedValues"]]
                if node.priority not in names:
                    errors.append(f"node ({nid}): priority '{node.priority}' is not one of: "
                                  f"{', '.join(names)}")

        if node.story_points is not None and points_field:
            if points_field not in screen(pn.type_id):
                errors.append(f"node ({nid}): 'story_points' is set but {where} has no "
                              f"story points field {field_label(points_field)}; leave "
                              f"'story_points' out")

        if node.parent is not None:
            parent = issue_of(node.parent)
            if parent is not None:
                parent_type = (parent.get("fields") or {}).get("issuetype")
            elif node.parent in by_id:
                parent_type = types_by_name.get(by_id[node.parent].type)
            else:
                parent_type = None  # a '#KEY' that failed to resolve, already reported
            child_level, parent_level = _level(issue_type, types_by_id), _level(parent_type,
                                                                               types_by_id)
            if child_level is not None and parent_level is not None \
                    and child_level >= parent_level:
                errors.append(f"node ({nid}): a '{node.type}' cannot be a child of "
                              f"'{node.parent}', a '{parent_type.get('name')}' - Jira's "
                              f"hierarchy puts a child below its parent")

    relations: List[PlannedRelation] = []
    if file.relations:
        site_types = client.link_types()
        by_name = {str(t.get("name", "")).casefold(): t for t in site_types}
        chosen: Dict[str, Optional[dict]] = {}
        for rel in file.relations:
            if rel.type in chosen:
                continue
            wanted = LINK_TYPE_NAMES[rel.type]
            chosen[rel.type] = by_name.get(wanted.casefold())
            if chosen[rel.type] is None:
                have = ", ".join(sorted(str(t.get("name")) for t in site_types)) or "(none)"
                errors.append(f"relation type '{rel.type}' needs a '{wanted}' link type, "
                              f"which this site does not have; it has: {have}")
        for rel in file.relations:
            link_type = chosen[rel.type]
            source, target = issue_of(rel.from_id), issue_of(rel.to_id)
            exists = (link_type is not None and source is not None and target is not None
                      and _link_exists((source.get("fields") or {}).get("issuelinks") or [],
                                       link_type, target["key"]))
            relations.append(PlannedRelation(
                relation=rel, exists=exists,
                link_type=link_type.get("name") if link_type is not None else None))

    return BacklogPlan(project_key=project_key, order=planned, relations=relations,
                       errors=errors, story_points_field=points_field)
