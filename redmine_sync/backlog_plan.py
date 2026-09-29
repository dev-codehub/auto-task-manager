from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .backlog_file import BacklogFile, Node, Relation
from .client import Client, ForbiddenError, NotFoundError
from .plan import subject_key


class BacklogPlanError(Exception):
    pass


@dataclass
class PlannedNode:
    node: Node
    exists: bool
    issue_id: Optional[int] = None
    tracker_id: Optional[int] = None
    priority_id: Optional[int] = None
    version_id: Optional[int] = None
    category_id: Optional[int] = None
    parent_ref: Optional[str] = None


@dataclass
class PlannedRelation:
    relation: Relation
    exists: bool


@dataclass
class BacklogPlan:
    project_id: int
    order: List[PlannedNode]
    relations: List[PlannedRelation]
    errors: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _by_name(items: List[dict]) -> Dict[str, int]:
    return {i["name"]: i["id"] for i in items}


def index_by_key(project_issues: List[dict]) -> Dict[str, List[int]]:
    """Every issue's id, grouped by subject_key - a key with more than one
    id is ambiguous and must never be resolved by picking one silently."""
    idx: Dict[str, List[int]] = {}
    for issue in project_issues:
        idx.setdefault(subject_key(issue.get("subject", "")), []).append(issue["id"])
    return idx


def resolve_key(index: Dict[str, List[int]], key: str) -> Tuple[Optional[int], Optional[str]]:
    """(issue_id, None) on a clean match, (None, None) on no match,
    (None, error) when more than one issue shares this key."""
    ids = index.get(key)
    if not ids:
        return None, None
    if len(ids) > 1:
        return None, f"'{key}' is ambiguous, it matches {', '.join(f'#{i}' for i in sorted(ids))}"
    return ids[0], None


def _order_new_nodes(nodes: List[Node], existing_ids: set) -> Tuple[List[Node], List[str]]:
    """Topological order: a node is ready once its parent is None, '#number',
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


def build_backlog_plan(client: Client, file: BacklogFile) -> BacklogPlan:
    project = client.get_project(file.project, include=("trackers", "issue_categories"))
    project_id = project["id"]
    errors: List[str] = []

    # The trackers *enabled for this project*, not every tracker on the
    # instance - a tracker that exists globally but isn't enabled here
    # would otherwise pass validation and then fail with a 422 partway
    # through --write.
    trackers = _by_name(project.get("trackers", []))
    priorities = _by_name(client.list_priorities())
    versions = _by_name(client.list_versions(file.project))
    project_issues = client.list_issues(file.project)
    # The project's own `issue_categories` include needs no extra permission
    # beyond viewing the project, unlike the dedicated /issue_categories.json
    # endpoint below - prefer it so a role without that permission still sees
    # every category, not only the ones already attached to an existing issue.
    categories = _by_name(project.get("issue_categories") or [])
    if not categories:
        try:
            categories = _by_name(client.list_categories(file.project))
        except ForbiddenError:
            # Last resort, and necessarily incomplete: a real category that no
            # existing issue currently uses will still be reported as "does
            # not exist" here - there is no other way to see it without either
            # permission.
            seen = {i["category"]["id"]: i["category"]["name"] for i in project_issues
                    if i.get("category")}
            categories = {name: cid for cid, name in seen.items()}

    # A reference that isn't '#number' is always another node's own id
    # (backlog_file.py's structural validation guarantees it) - so `existing`
    # only ever needs to resolve *this file's* node ids, never an arbitrary
    # subject_key from the project. Ambiguous matches are a plan error, not
    # a silent "first one wins" - the same discipline session-close's
    # IssueIndex.resolve already applies.
    key_index = index_by_key(project_issues)
    existing: Dict[str, int] = {}
    for node in file.nodes:
        issue_id, ambiguity = resolve_key(key_index, node.id)
        if ambiguity:
            errors.append(f"node ({node.id}): {ambiguity}")
            continue
        if issue_id is not None:
            existing[node.id] = issue_id

    # Cache #number references (parents and relation endpoints) with one GET each.
    hash_refs = {n.parent for n in file.nodes if n.parent and n.parent.startswith("#")}
    hash_refs |= {r.from_id for r in file.relations if r.from_id.startswith("#")}
    hash_refs |= {r.to_id for r in file.relations if r.to_id.startswith("#")}
    hash_ids: Dict[str, int] = {}
    for ref in hash_refs:
        iid = int(ref[1:])
        try:
            client.get_issue(iid)
            hash_ids[ref] = iid
        except NotFoundError:
            errors.append(f"'{ref}': issue {iid} does not exist or is not visible to you")

    existing_ids = set(existing)  # `existing` is keyed by this file's node ids only, see above
    order_nodes, cycle_errors = _order_new_nodes(file.nodes, existing_ids)
    errors.extend(cycle_errors)
    # Existing nodes come first in `order` (nothing to create for them), then
    # the topologically-sorted new ones, so callers can walk `order` in a
    # single pass and only ever create what does not already exist.
    ordered_ids = [n.id for n in file.nodes if n.id in existing_ids] + [n.id for n in order_nodes]
    by_id = {n.id: n for n in file.nodes}

    planned: List[PlannedNode] = []
    for nid in ordered_ids:
        node = by_id[nid]
        exists = nid in existing
        pn = PlannedNode(node=node, exists=exists,
                         issue_id=existing.get(nid), parent_ref=node.parent)
        if not exists:
            if node.tracker not in trackers:
                errors.append(f"node ({nid}): tracker '{node.tracker}' does not exist in "
                              f"'{file.project}'; available: {', '.join(sorted(trackers)) or '(none)'}")
            else:
                pn.tracker_id = trackers[node.tracker]
            if node.priority not in priorities:
                errors.append(f"node ({nid}): priority '{node.priority}' does not exist; "
                              f"available: {', '.join(sorted(priorities)) or '(none)'}")
            else:
                pn.priority_id = priorities[node.priority]
            if node.target_version is not None:
                if node.target_version not in versions:
                    errors.append(f"node ({nid}): target version '{node.target_version}' "
                                  f"does not exist in '{file.project}'")
                else:
                    pn.version_id = versions[node.target_version]
            if node.category is not None:
                if node.category not in categories:
                    errors.append(f"node ({nid}): category '{node.category}' does not exist "
                                  f"in '{file.project}'")
                else:
                    pn.category_id = categories[node.category]
        planned.append(pn)

    relations: List[PlannedRelation] = []

    def resolve_ref(ref: str) -> Optional[int]:
        if ref.startswith("#"):
            return hash_ids.get(ref)
        if ref in existing:
            return existing[ref]
        return None  # a not-yet-created new node; relation applied after creation

    existing_relation_pairs = set()
    endpoints_to_check = {resolve_ref(r.from_id) for r in file.relations} | \
        {resolve_ref(r.to_id) for r in file.relations}
    for iid in {i for i in endpoints_to_check if i is not None}:
        for rel in client.list_relations(iid):
            existing_relation_pairs.add((rel["issue_id"], rel["relation_type"], rel["issue_to_id"]))

    for rel in file.relations:
        from_id, to_id = resolve_ref(rel.from_id), resolve_ref(rel.to_id)
        exists = (from_id is not None and to_id is not None and
                 (from_id, rel.type, to_id) in existing_relation_pairs)
        relations.append(PlannedRelation(relation=rel, exists=exists))

    return BacklogPlan(project_id=project_id, order=planned, relations=relations, errors=errors)
