from __future__ import annotations

import json
import unittest

from redmine_sync.backlog_file import BacklogFileError, parse_backlog_file


def minimal(**overrides):
    doc = {
        "project": "demo",
        "nodes": [
            {"id": "US-01", "subject": "US-01 A story", "description": "d",
             "tracker": "User Story", "priority": "Normal", "parent": None},
        ],
        "relations": [],
    }
    doc.update(overrides)
    return doc


class ParseTests(unittest.TestCase):
    def test_minimal_file_parses(self):
        f = parse_backlog_file(json.dumps(minimal()))
        self.assertEqual(f.project, "demo")
        self.assertEqual(f.nodes[0].id, "US-01")
        self.assertEqual(f.relations, [])

    def test_not_json_raises(self):
        with self.assertRaises(BacklogFileError):
            parse_backlog_file("not json")

    def test_duplicate_id_rejected(self):
        doc = minimal()
        doc["nodes"].append(dict(doc["nodes"][0]))
        with self.assertRaises(BacklogFileError) as ctx:
            parse_backlog_file(json.dumps(doc))
        self.assertIn("US-01", str(ctx.exception))
        self.assertIn("duplicate", str(ctx.exception).lower())

    def test_subject_must_start_with_id(self):
        doc = minimal()
        doc["nodes"][0]["subject"] = "SOMETHING-ELSE A story"
        with self.assertRaises(BacklogFileError) as ctx:
            parse_backlog_file(json.dumps(doc))
        self.assertIn("US-01", str(ctx.exception))

    def test_parent_referencing_unknown_id_rejected(self):
        doc = minimal()
        doc["nodes"][0]["parent"] = "NO-SUCH-NODE"
        with self.assertRaises(BacklogFileError):
            parse_backlog_file(json.dumps(doc))

    def test_parent_hash_number_accepted(self):
        doc = minimal()
        doc["nodes"][0]["parent"] = "#1234"
        f = parse_backlog_file(json.dumps(doc))
        self.assertEqual(f.nodes[0].parent, "#1234")

    def test_relation_unknown_endpoint_rejected(self):
        doc = minimal(relations=[{"type": "blocks", "from": "US-01", "to": "GHOST"}])
        with self.assertRaises(BacklogFileError):
            parse_backlog_file(json.dumps(doc))

    def test_relation_unknown_type_rejected(self):
        doc = minimal(nodes=minimal()["nodes"] + [
            {"id": "US-02", "subject": "US-02 Another", "description": "d",
             "tracker": "User Story", "priority": "Normal", "parent": None}])
        doc["relations"] = [{"type": "flies-over", "from": "US-01", "to": "US-02"}]
        with self.assertRaises(BacklogFileError):
            parse_backlog_file(json.dumps(doc))

    def test_estimated_hours_string_rejected(self):
        doc = minimal()
        doc["nodes"][0]["estimated_hours"] = "3"
        with self.assertRaises(BacklogFileError):
            parse_backlog_file(json.dumps(doc))

    def test_estimated_hours_number_accepted(self):
        doc = minimal()
        doc["nodes"][0]["estimated_hours"] = 3.5
        f = parse_backlog_file(json.dumps(doc))
        self.assertEqual(f.nodes[0].estimated_hours, 3.5)

    def test_all_problems_reported_together(self):
        doc = minimal()
        doc["nodes"][0]["subject"] = "WRONG-PREFIX text"
        doc["nodes"][0]["estimated_hours"] = "not a number"
        with self.assertRaises(BacklogFileError) as ctx:
            parse_backlog_file(json.dumps(doc))
        msg = str(ctx.exception)
        self.assertIn("US-01", msg)
        self.assertIn("estimated_hours", msg)


if __name__ == "__main__":
    unittest.main()
