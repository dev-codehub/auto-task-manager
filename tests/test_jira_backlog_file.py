from __future__ import annotations

import json
import unittest

from jira_sync.backlog_file import BacklogFileError, parse_backlog_file


def minimal(**overrides):
    doc = {
        "project": "SCRUM",
        "nodes": [
            {"id": "EP-01", "subject": "EP-01 An epic", "description": "d",
             "type": "Epic", "parent": None},
            {"id": "ST-01", "subject": "ST-01 A story", "description": "d",
             "type": "Story", "parent": "EP-01"},
        ],
        "relations": [],
    }
    doc.update(overrides)
    return doc


def parse(doc):
    return parse_backlog_file(json.dumps(doc))


class ParseTests(unittest.TestCase):
    def problems(self, doc) -> str:
        with self.assertRaises(BacklogFileError) as ctx:
            parse(doc)
        return str(ctx.exception)

    def test_minimal_file_parses(self):
        f = parse(minimal())
        self.assertEqual(f.project, "SCRUM")
        self.assertEqual([n.id for n in f.nodes], ["EP-01", "ST-01"])
        self.assertEqual(f.nodes[0].type, "Epic")
        self.assertEqual(f.nodes[1].parent, "EP-01")
        self.assertEqual(f.relations, [])

    def test_not_json_raises(self):
        with self.assertRaises(BacklogFileError):
            parse_backlog_file("not json")

    def test_tracker_is_not_a_jira_key(self):
        doc = minimal()
        doc["nodes"][0]["tracker"] = "Epic"
        self.assertIn("tracker", self.problems(doc))

    def test_precedes_is_rejected_with_a_clear_message(self):
        doc = minimal(relations=[{"type": "precedes", "from": "EP-01", "to": "ST-01"}])
        self.assertIn("Jira has no 'precedes' link", self.problems(doc))

    def test_relation_types_relates_duplicates_blocks_accepted(self):
        rels = [{"type": t, "from": "EP-01", "to": "ST-01"}
                for t in ("relates", "duplicates", "blocks")]
        f = parse(minimal(relations=rels))
        self.assertEqual([(r.type, r.from_id, r.to_id) for r in f.relations],
                         [("relates", "EP-01", "ST-01"), ("duplicates", "EP-01", "ST-01"),
                          ("blocks", "EP-01", "ST-01")])

    def test_existing_issue_reference_is_hash_plus_key(self):
        doc = minimal(relations=[{"type": "blocks", "from": "ST-01", "to": "#OTHER_2-123"}])
        doc["nodes"][0]["parent"] = "#SCRUM-7"
        f = parse(doc)
        self.assertEqual(f.nodes[0].parent, "#SCRUM-7")
        self.assertEqual(f.relations[0].to_id, "#OTHER_2-123")
        # A bare key is not a reference (it could be a node id), nor is a
        # Redmine-style number or a lower-case key.
        for bad in ("SCRUM-7", "#123", "#scrum-7", "#SCRUM-", "#SCRUM-7x"):
            with self.subTest(parent=bad):
                doc = minimal()
                doc["nodes"][0]["parent"] = bad
                self.assertIn("#PROJ-123", self.problems(doc))

    def test_node_id_shaped_like_a_jira_key_is_a_node_id(self):
        doc = minimal()
        doc["nodes"][0]["id"] = "EX-01"
        doc["nodes"][0]["subject"] = "EX-01 An epic"
        doc["nodes"][1]["parent"] = "EX-01"
        f = parse(doc)
        self.assertEqual(f.nodes[1].parent, "EX-01")

    def test_priority_and_story_points_are_optional(self):
        f = parse(minimal())
        self.assertIsNone(f.nodes[1].priority)
        self.assertIsNone(f.nodes[1].story_points)
        doc = minimal()
        doc["nodes"][1]["priority"] = "High"
        doc["nodes"][1]["story_points"] = 3
        f = parse(doc)
        self.assertEqual(f.nodes[1].priority, "High")
        self.assertEqual(f.nodes[1].story_points, 3.0)
        for bad in ("3", True, -1):
            with self.subTest(story_points=bad):
                doc = minimal()
                doc["nodes"][1]["story_points"] = bad
                self.assertIn("story_points", self.problems(doc))
        doc = minimal()
        doc["nodes"][1]["priority"] = ""
        self.assertIn("priority", self.problems(doc))

    def test_subject_must_start_with_the_node_id(self):
        doc = minimal()
        doc["nodes"][1]["subject"] = "SOMETHING-ELSE A story"
        msg = self.problems(doc)
        self.assertIn("ST-01", msg)
        self.assertIn("subject", msg)
        doc["nodes"][1]["subject"] = "ST-01: A story"
        self.assertEqual(parse(doc).nodes[1].subject, "ST-01: A story")

    def test_duplicate_id_rejected(self):
        doc = minimal()
        doc["nodes"].append(dict(doc["nodes"][0]))
        msg = self.problems(doc)
        self.assertIn("EP-01", msg)
        self.assertIn("duplicate", msg.lower())

    def test_parent_referencing_unknown_id_rejected(self):
        doc = minimal()
        doc["nodes"][1]["parent"] = "NO-SUCH-NODE"
        self.assertIn("NO-SUCH-NODE", self.problems(doc))

    def test_cycle_in_parents_is_an_error(self):
        doc = minimal()
        doc["nodes"][0]["parent"] = "ST-01"  # EP-01 -> ST-01 -> EP-01
        msg = self.problems(doc)
        self.assertIn("cycle", msg.lower())
        self.assertIn("EP-01", msg)
        self.assertIn("ST-01", msg)
        doc = minimal()
        doc["nodes"][0]["parent"] = "EP-01"  # its own parent
        self.assertIn("cycle", self.problems(doc).lower())

    def test_relation_unknown_endpoint_rejected(self):
        doc = minimal(relations=[{"type": "blocks", "from": "ST-01", "to": "GHOST"}])
        self.assertIn("GHOST", self.problems(doc))

    def test_relation_delay_is_not_a_jira_key(self):
        doc = minimal(relations=[{"type": "blocks", "from": "ST-01", "to": "EP-01",
                                  "delay": 2}])
        self.assertIn("delay", self.problems(doc))

    def test_all_problems_reported_together(self):
        doc = minimal(relations=[{"type": "precedes", "from": "EP-01", "to": "ST-01"}])
        doc["nodes"][1]["subject"] = "WRONG-PREFIX text"
        doc["nodes"][1]["story_points"] = "lots"
        msg = self.problems(doc)
        self.assertIn("ST-01", msg)
        self.assertIn("story_points", msg)
        self.assertIn("precedes", msg)


if __name__ == "__main__":
    unittest.main()
