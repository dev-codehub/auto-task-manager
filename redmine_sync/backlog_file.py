from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List, Optional

from .client import RELATION_TYPES
from .keys import missing_keys_problem, unknown_keys_problem
from .plan import subject_key

_NODE_KEYS = {"id", "subject", "description", "tracker", "priority", "parent",
             "target_version", "category", "estimated_hours"}
_REQUIRED_NODE_KEYS = {"id", "subject", "description", "tracker", "priority", "parent"}
_REL_KEYS = {"type", "from", "to", "delay"}


class BacklogFileError(Exception):
    pass


@dataclass(frozen=True)
class Node:
    id: str
    subject: str
    description: str
    tracker: str
    priority: str
    parent: Optional[str]
    target_version: Optional[str] = None
    category: Optional[str] = None
    estimated_hours: Optional[float] = None


@dataclass(frozen=True)
class Relation:
    type: str
    from_id: str
    to_id: str
    delay: Optional[int] = None


@dataclass(frozen=True)
class BacklogFile:
    project: str
    nodes: List[Node]
    relations: List[Relation]


def load_backlog_file(path: str) -> BacklogFile:
    try:
        with open(path, encoding="utf-8-sig") as f:
            text = f.read()
    except UnicodeDecodeError:
        raise BacklogFileError(f"{path}: not UTF-8 text") from None
    return parse_backlog_file(text, source=path)


def _is_ref_ok(value: str, known_ids: set) -> bool:
    if value.startswith("#"):
        return value[1:].isdigit()
    return value in known_ids


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
        tracker = row["tracker"]
        if not isinstance(tracker, str) or not tracker.strip():
            problems.append(f"{where}: 'tracker' must be a non-empty string")
        priority = row["priority"]
        if not isinstance(priority, str) or not priority.strip():
            problems.append(f"{where}: 'priority' must be a non-empty string")
        parent = row["parent"]
        if parent is not None and not isinstance(parent, str):
            problems.append(f"{where}: 'parent' must be a string or null")
        target_version = row.get("target_version")
        if target_version is not None and not isinstance(target_version, str):
            problems.append(f"{where}: 'target_version' must be a string")
        category = row.get("category")
        if category is not None and not isinstance(category, str):
            problems.append(f"{where}: 'category' must be a string")
        hours = row.get("estimated_hours")
        if hours is not None and (isinstance(hours, bool) or not isinstance(hours, (int, float))):
            problems.append(f"{where}: 'estimated_hours' must be a number")
        nodes.append(Node(id=nid, subject=subject if isinstance(subject, str) else "",
                          description=description if isinstance(description, str) else "",
                          tracker=tracker if isinstance(tracker, str) else "",
                          priority=priority if isinstance(priority, str) else "",
                          parent=parent if isinstance(parent, str) else None,
                          target_version=target_version, category=category,
                          estimated_hours=float(hours) if isinstance(hours, (int, float))
                          and not isinstance(hours, bool) else None))

    known_ids = seen_ids
    for node in nodes:
        if node.parent is not None and not _is_ref_ok(node.parent, known_ids):
            problems.append(f"node ({node.id}): parent '{node.parent}' is not another "
                            f"node's id in this file, nor '#number'")

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
        problem = missing_keys_problem(row, {"type", "from", "to"}, where)
        if problem:
            problems.append(problem)
            continue
        rtype = row["type"]
        if rtype not in RELATION_TYPES:
            problems.append(f"{where}: 'type' must be one of {', '.join(RELATION_TYPES)}")
        rfrom, rto = row["from"], row["to"]
        for label, value in (("from", rfrom), ("to", rto)):
            if not isinstance(value, str) or not _is_ref_ok(value, known_ids):
                problems.append(f"{where}: '{label}' ({value!r}) is not a node id in "
                                f"this file, nor '#number'")
        delay = row.get("delay")
        if delay is not None and (isinstance(delay, bool) or not isinstance(delay, int)):
            problems.append(f"{where}: 'delay' must be an integer")
        relations.append(Relation(type=rtype if rtype in RELATION_TYPES else "",
                                  from_id=rfrom if isinstance(rfrom, str) else "",
                                  to_id=rto if isinstance(rto, str) else "", delay=delay))

    if problems:
        raise BacklogFileError(f"{source}:\n" + "\n".join(f"  - {p}" for p in problems))
    return BacklogFile(project=project, nodes=nodes, relations=relations)
