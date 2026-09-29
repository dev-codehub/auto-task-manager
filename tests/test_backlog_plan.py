from __future__ import annotations

import json
import unittest

from redmine_sync.backlog_file import parse_backlog_file
from redmine_sync.backlog_plan import build_backlog_plan
from redmine_sync.client import Client
from tests.fake_redmine import demo_fake


def doc(**overrides):
    d = {
        "project": "demo",
        "nodes": [
            {"id": "US-90", "subject": "US-90 A brand new story", "description": "d",
             "tracker": "User Story", "priority": "Normal", "parent": None},
            {"id": "US-90.1", "subject": "US-90.1 A task under it", "description": "d",
             "tracker": "Task", "priority": "Normal", "parent": "US-90"},
        ],
        "relations": [],
    }
    d.update(overrides)
    return d


class BacklogPlanTests(unittest.TestCase):
    def setUp(self):
        self.fake = demo_fake().start()
        self.client = Client(self.fake.url, self.fake.key)

    def tearDown(self):
        self.fake.stop()

    def test_new_nodes_ordered_parent_before_child(self):
        f = parse_backlog_file(json.dumps(doc()))
        plan = build_backlog_plan(self.client, f)
        self.assertTrue(plan.ok, plan.errors)
        ids = [p.node.id for p in plan.order]
        self.assertEqual(ids.index("US-90"), 0)
        self.assertEqual(ids.index("US-90.1"), 1)
        self.assertFalse(plan.order[0].exists)
        self.assertIsNone(plan.order[0].parent_ref)
        self.assertEqual(plan.order[1].parent_ref, "US-90")

    def test_already_existing_node_matched_by_subject(self):
        d = doc()
        d["nodes"][0]["id"] = "EX-01.1"
        d["nodes"][0]["subject"] = "EX-01.1 Build the thing"
        d["nodes"] = [d["nodes"][0]]
        f = parse_backlog_file(json.dumps(d))
        plan = build_backlog_plan(self.client, f)
        self.assertTrue(plan.ok, plan.errors)
        self.assertTrue(plan.order[0].exists)
        self.assertEqual(plan.order[0].issue_id, 101)

    def test_unknown_tracker_is_an_error_not_an_exception(self):
        d = doc()
        d["nodes"][0]["tracker"] = "Epic"
        f = parse_backlog_file(json.dumps(d))
        plan = build_backlog_plan(self.client, f)
        self.assertFalse(plan.ok)
        self.assertTrue(any("Epic" in e for e in plan.errors))

    def test_ambiguous_existing_match_is_a_plan_error_naming_both_issues(self):
        self.fake.add_issue(105, "US-90 A duplicate import")
        self.fake.add_issue(106, "US-90 Another duplicate")
        d = doc()
        d["nodes"] = [d["nodes"][0]]
        d["relations"] = []
        f = parse_backlog_file(json.dumps(d))
        plan = build_backlog_plan(self.client, f)
        self.assertFalse(plan.ok)
        msg = " ".join(plan.errors)
        self.assertIn("ambiguous", msg.lower())
        self.assertIn("105", msg)
        self.assertIn("106", msg)

    def test_tracker_not_enabled_for_the_project_is_rejected_even_if_it_exists_globally(self):
        # "Task" exists on the instance (demo_fake's global /trackers.json)
        # but is not one of the trackers enabled for the "demo" project.
        self.fake.project_trackers["demo"] = [{"id": 1, "name": "User Story"}]
        d = doc()
        d["nodes"][1]["tracker"] = "Task"
        f = parse_backlog_file(json.dumps(d))
        plan = build_backlog_plan(self.client, f)
        self.assertFalse(plan.ok)
        self.assertTrue(any("Task" in e for e in plan.errors), plan.errors)

    def test_hash_number_parent_must_exist(self):
        d = doc()
        d["nodes"][0]["parent"] = "#999999"
        f = parse_backlog_file(json.dumps(d))
        plan = build_backlog_plan(self.client, f)
        self.assertFalse(plan.ok)
        self.assertTrue(any("999999" in e for e in plan.errors))

    def test_categories_forbidden_still_resolved_via_project_include(self):
        # The dedicated /issue_categories.json endpoint is forbidden, but the
        # project's own `issue_categories` include (used first) needs no
        # extra permission, so the real category (id 1) is still found.
        self.fake.categories_forbidden = True
        d = doc()
        d["nodes"][0]["category"] = "SUPPORT"
        f = parse_backlog_file(json.dumps(d))
        plan = build_backlog_plan(self.client, f)
        self.assertTrue(plan.ok, plan.errors)
        self.assertEqual(plan.order[0].category_id, 1)

    def test_categories_forbidden_and_unused_by_any_issue_still_resolves(self):
        # Regression test: a category that exists but isn't attached to any
        # existing issue used to be reported as "does not exist" once the
        # dedicated endpoint was forbidden, because the last-resort fallback
        # can only see categories already in use. The project include fixes
        # this for any category, used or not.
        self.fake.categories_forbidden = True
        self.fake.add_category("demo", 2, "SECURITY")
        d = doc()
        d["nodes"][0]["category"] = "SECURITY"
        f = parse_backlog_file(json.dumps(d))
        plan = build_backlog_plan(self.client, f)
        self.assertTrue(plan.ok, plan.errors)
        self.assertEqual(plan.order[0].category_id, 2)

    def test_cycle_among_new_nodes_is_an_error(self):
        d = doc()
        d["nodes"][0]["parent"] = "US-90.1"  # US-90 -> US-90.1 -> US-90
        f = parse_backlog_file(json.dumps(d))
        plan = build_backlog_plan(self.client, f)
        self.assertFalse(plan.ok)
        self.assertTrue(any("cycle" in e.lower() for e in plan.errors))

    def test_relations_resolved_against_order(self):
        d = doc(relations=[{"type": "blocks", "from": "US-90.1", "to": "US-90"}])
        f = parse_backlog_file(json.dumps(d))
        plan = build_backlog_plan(self.client, f)
        self.assertTrue(plan.ok, plan.errors)
        self.assertEqual(len(plan.relations), 1)
        self.assertFalse(plan.relations[0].exists)

    def test_existing_relation_marked_exists(self):
        self.client.create_relation(101, 102, "blocks")
        d = doc()
        d["nodes"][0]["id"] = "EX-01.1"
        d["nodes"][0]["subject"] = "EX-01.1 Build the thing"
        d["nodes"].append({"id": "EX-01.2", "subject": "EX-01.2 Test the thing",
                           "description": "d", "tracker": "Task", "priority": "Normal",
                           "parent": None})
        d["nodes"] = [d["nodes"][0], d["nodes"][-1]]
        d["relations"] = [{"type": "blocks", "from": "EX-01.1", "to": "EX-01.2"}]
        f = parse_backlog_file(json.dumps(d))
        plan = build_backlog_plan(self.client, f)
        self.assertTrue(plan.ok, plan.errors)
        self.assertTrue(plan.relations[0].exists)


if __name__ == "__main__":
    unittest.main()
