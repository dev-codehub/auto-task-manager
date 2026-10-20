from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from redmine_sync.keys import missing_keys_problem, unknown_keys_problem

RELATION_TYPES = ("relates", "duplicates", "blocks")
_NODE_KEYS = {"id", "subject", "description", "type", "priority", "parent", "story_points"}
_REQUIRED_NODE_KEYS = {"id", "subject", "description", "type", "parent"}
_REL_KEYS = {"type", "from", "to"}
# An existing issue: '#' plus its Jira key, so a node id like 'EX-01' (which
# looks like a key) is never taken for one.
_ISSUE_REF = re.compile(r"#[A-Z][A-Z0-9_]*-\d+")


class BacklogFileError(Exception):
    pass


@dataclass(frozen=True)
class Node:
    id: str
    subject: str
    description: str
    type: str
    priority: Optional[str]
    parent: Optional[str]
    story_points: Optional[float] = None


@dataclass(frozen=True)
class Relation:
    type: str
    from_id: str
    to_id: str


@dataclass(frozen=True)
class BacklogFile:
    project: str
    nodes: List[Node]
    relations: List[Relation]


def subject_key(subject: str) -> str:
    """The summary's first token, up to any ':' - a node's id."""
    stripped = subject.strip()
    if not stripped:
        return ""
    token = stripped.split(None, 1)[0]
    return token.split(":", 1)[0]


def is_issue_ref(value: str) -> bool:
    return bool(_ISSUE_REF.fullmatch(value))


def load_backlog_file(path: str) -> BacklogFile:
    try:
        with open(path, encoding="utf-8-sig") as f:
            text = f.read()
    except UnicodeDecodeError:
        raise BacklogFileError(f"{path}: not UTF-8 text") from None
    return parse_backlog_file(text, source=path)


def _is_ref_ok(value: str, known_ids: set) -> bool:
    if value.startswith("#"):
        return is_issue_ref(value)
    return value in known_ids


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _parent_cycles(nodes: List[Node]) -> List[str]:
    """Node ids that sit on a cycle of in-file parent references."""
    parent_of: Dict[str, Optional[str]] = {n.id: n.parent for n in nodes}
    on_cycle: set = set()
    for start in parent_of:
        seen: List[str] = []
        here: Optional[str] = start
        while here in parent_of and here not in seen:
            seen.append(here)
            here = parent_of[here]
        if here in seen:
            on_cycle.update(seen[seen.index(here):])
    return sorted(on_cycle)


def parse_backlog_file(text: str, source: str = "<plan file>") -> BacklogFile:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        raise BacklogFileError(f"{source}: not valid JSON ({e})") from None
    if not isinstance(raw, dict):
        raise BacklogFileError(f"{source}: must be a JSON object")

    problems: List[str] = []
    project = raw.get("project")
    if not isinstance(project, str) or not project.strip():
        problems.append("'project' is required")

    raw_nodes = raw.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        problems.append("'nodes' must be a non-empty list")
        raw_nodes = []

    nodes: List[Node] = []
    seen_ids: set = set()
    for n, row in enumerate(raw_nodes, 1):
        where = f"node {n}"
        if not isinstance(row, dict):
            problems.append(f"{where}: must be an object")
            continue
        problem = unknown_keys_problem(row, _NODE_KEYS, where)
        if problem:
            problems.append(problem)
        problem = missing_keys_problem(row, _REQUIRED_NODE_KEYS, where)
        if problem:
            problems.append(problem)
            continue
        nid = row["id"]
        if not isinstance(nid, str) or not nid.strip():
            problems.append(f"{where}: 'id' must be a non-empty string")
            continue
        where = f"node {n} ({nid})"
        if nid in seen_ids:
            problems.append(f"{where}: duplicate id '{nid}'")
            continue
        seen_ids.add(nid)
        subject = row["subject"]
        if not isinstance(subject, str) or subject_key(subject) != nid:
            problems.append(f"{where}: 'subject' must start with the id '{nid}'")
        description = row["description"]
        if not isinstance(description, str):
            problems.append(f"{where}: 'description' must be a string")
        issue_type = row["type"]
        if not isinstance(issue_type, str) or not issue_type.strip():
            problems.append(f"{where}: 'type' must be a non-empty string")
        priority = row.get("priority")
        if priority is not None and (not isinstance(priority, str) or not priority.strip()):
            problems.append(f"{where}: 'priority' must be a non-empty string, or left out")
        parent = row["parent"]
        if parent is not None and not isinstance(parent, str):
            problems.append(f"{where}: 'parent' must be a string or null")
        points = row.get("story_points")
        if points is not None and not (_is_number(points) and points >= 0):
            problems.append(f"{where}: 'story_points' must be a number of 0 or more")
        nodes.append(Node(id=nid, subject=subject if isinstance(subject, str) else "",
                          description=description if isinstance(description, str) else "",
                          type=issue_type if isinstance(issue_type, str) else "",
                          priority=priority if isinstance(priority, str) else None,
                          parent=parent if isinstance(parent, str) else None,
                          story_points=float(points) if _is_number(points) else None))

    known_ids = seen_ids
    for node in nodes:
        if node.parent is not None and not _is_ref_ok(node.parent, known_ids):
            problems.append(f"node ({node.id}): parent '{node.parent}' is not another "
                            f"node's id in this file, nor an existing issue as '#PROJ-123'")
    cycle = _parent_cycles(nodes)
    if cycle:
        problems.append("cycle among parent references: " + ", ".join(cycle))

    raw_relations = raw.get("relations", [])
    if not isinstance(raw_relations, list):
        problems.append("'relations' must be a list")
        raw_relations = []

    relations: List[Relation] = []
    for n, row in enumerate(raw_relations, 1):
        where = f"relation {n}"
        if not isinstance(row, dict):
            problems.append(f"{where}: must be an object")
            continue
        problem = unknown_keys_problem(row, _REL_KEYS, where)
        if problem:
            problems.append(problem)
        problem = missing_keys_problem(row, _REL_KEYS, where)
        if problem:
            problems.append(problem)
            continue
        rtype = row["type"]
        if rtype == "precedes":
            problems.append(f"{where}: Jira has no 'precedes' link; use one of "
                            f"{', '.join(RELATION_TYPES)}")
        elif rtype not in RELATION_TYPES:
            problems.append(f"{where}: 'type' must be one of {', '.join(RELATION_TYPES)}")
        rfrom, rto = row["from"], row["to"]
        for label, value in (("from", rfrom), ("to", rto)):
            if not isinstance(value, str) or not _is_ref_ok(value, known_ids):
                problems.append(f"{where}: '{label}' ({value!r}) is not a node id in "
                                f"this file, nor an existing issue as '#PROJ-123'")
        relations.append(Relation(type=rtype if rtype in RELATION_TYPES else "",
                                  from_id=rfrom if isinstance(rfrom, str) else "",
                                  to_id=rto if isinstance(rto, str) else ""))

    if problems:
        raise BacklogFileError(f"{source}:\n" + "\n".join(f"  - {p}" for p in problems))
    return BacklogFile(project=project, nodes=nodes, relations=relations)
