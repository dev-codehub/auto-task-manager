from __future__ import annotations

import json
import unittest

from jira_sync.backlog_file import parse_backlog_file
from jira_sync.backlog_plan import build_backlog_plan, index_by_key, resolve_key
from jira_sync.client import Client
from tests.fake_jira import demo_fake

POINTS = "customfield_10016"


def doc(**overrides):
    d = {
        "project": "SCRUM",
        "nodes": [
            {"id": "EP-01", "subject": "EP-01 A brand new epic", "description": "d",
             "type": "Epic", "parent": None},
            {"id": "ST-01", "subject": "ST-01 A story under it", "description": "d",
             "type": "Story", "parent": "EP-01"},
        ],
        "relations": [],
    }
    d.update(overrides)
    return d


def screen_field(fid, name, **extra):
    return {"fieldId": fid, "key": fid, "name": name, "required": False,
            "operations": ["set"], "hasDefaultValue": False, **extra}


class BacklogPlanTests(unittest.TestCase):
    def setUp(self):
        # demo_fake: project SCRUM with SCRUM-1 "Epic one" (Epic), SCRUM-2
        # "Story one" (Story), SCRUM-3 "Task one" (Task); issue types Epic (10001,
        # level 1), Story (10002), Task (10003), Sub-task (10004, level -1).
        self.fake = demo_fake().start()
        self.client = Client(self.fake.url, self.fake.email, self.fake.token)

    def tearDown(self):
        self.fake.stop()

    def plan(self, d, **kwargs):
        return build_backlog_plan(self.client, parse_backlog_file(json.dumps(d)), **kwargs)

    def test_new_nodes_ordered_parent_before_child(self):
        d = doc()
        d["nodes"].reverse()
        plan = self.plan(d)
        self.assertTrue(plan.ok, plan.errors)
        self.assertEqual(plan.project_key, "SCRUM")
        self.assertEqual([p.node.id for p in plan.order], ["EP-01", "ST-01"])
        self.assertEqual([p.type_id for p in plan.order], ["10001", "10002"])
        self.assertFalse(any(p.exists for p in plan.order))
        self.assertIsNone(plan.order[0].parent_ref)
        self.assertEqual(plan.order[1].parent_ref, "EP-01")
        self.assertEqual(self.fake.writes, [])

    def test_unknown_type_lists_the_projects_types(self):
        d = doc()
        d["nodes"][1]["type"] = "Feature"
        plan = self.plan(d)
        self.assertFalse(plan.ok)
        msg = " ".join(plan.errors)
        self.assertIn("ST-01", msg)
        self.assertIn("'Feature'", msg)
        self.assertIn("Epic, Story, Sub-task, Task", msg)

    def test_priority_set_but_not_on_the_create_screen_is_an_error_naming_node_and_field(self):
        d = doc()
        d["nodes"][1]["priority"] = "High"
        plan = self.plan(d)
        self.assertFalse(plan.ok)
        self.assertEqual(len(plan.errors), 1, plan.errors)
        self.assertIn("ST-01", plan.errors[0])
        self.assertIn("priority", plan.errors[0].lower())

    def test_priority_on_the_create_screen_must_be_one_of_its_values(self):
        self.fake.create_fields["10002"].append(screen_field(
            "priority", "Priority", allowedValues=[{"id": "1", "name": "High"},
                                                   {"id": "2", "name": "Low"}]))
        d = doc()
        d["nodes"][1]["priority"] = "High"
        plan = self.plan(d)
        self.assertTrue(plan.ok, plan.errors)
        d["nodes"][1]["priority"] = "Urgent"
        plan = self.plan(d)
        self.assertFalse(plan.ok)
        self.assertIn("Urgent", plan.errors[0])
        self.assertIn("High, Low", plan.errors[0])

    def test_priority_left_out_sends_and_reports_nothing(self):
        plan = self.plan(doc())
        self.assertTrue(plan.ok, plan.errors)
        self.assertEqual(self.fake.writes, [])
        # Nothing to check, so the create screens are never asked for.
        self.assertFalse(any(r.startswith("GET /rest/api/3/issue/createmeta/SCRUM/issuetypes/")
                             for r in self.fake.requests), self.fake.requests)

    def test_story_points_set_but_field_not_on_the_create_screen_is_an_error(self):
        d = doc()
        d["nodes"][1]["story_points"] = 3
        plan = self.plan(d)
        self.assertFalse(plan.ok)
        self.assertEqual(len(plan.errors), 1, plan.errors)
        self.assertIn("ST-01", plan.errors[0])
        self.assertIn("Story point estimate", plan.errors[0])
        self.assertIn(POINTS, plan.errors[0])

    def test_story_points_on_the_create_screen_resolves_the_field_id(self):
        self.fake.create_fields["10002"].append(screen_field(POINTS, "Story point estimate"))
        d = doc()
        d["nodes"][1]["story_points"] = 3
        plan = self.plan(d)
        self.assertTrue(plan.ok, plan.errors)
        self.assertEqual(plan.story_points_field, POINTS)

    def test_story_points_field_given_is_used_without_a_lookup(self):
        self.fake.create_fields["10002"].append(screen_field("customfield_10099", "Points"))
        d = doc()
        d["nodes"][1]["story_points"] = 3
        plan = self.plan(d, story_points_field="customfield_10099")
        self.assertTrue(plan.ok, plan.errors)
        self.assertEqual(plan.story_points_field, "customfield_10099")
        self.assertNotIn("GET /rest/api/3/field", self.fake.requests)

    def test_no_story_points_field_on_the_site_is_an_error_only_when_a_node_sets_points(self):
        self.fake.fields = [f for f in self.fake.fields if f["id"] != POINTS]
        plan = self.plan(doc())
        self.assertTrue(plan.ok, plan.errors)
        self.assertIsNone(plan.story_points_field)
        d = doc()
        d["nodes"][1]["story_points"] = 3
        plan = self.plan(d)
        self.assertFalse(plan.ok)
        self.assertIn("story_points_field", " ".join(plan.errors))

    def test_story_under_a_sub_task_is_a_hierarchy_error(self):
        sub_key = self.fake.add_issue("An existing sub-task", type_name="Sub-task")
        new_parent = doc(nodes=[
            {"id": "SB-01", "subject": "SB-01 A sub-task", "description": "d",
             "type": "Sub-task", "parent": None},
            {"id": "ST-01", "subject": "ST-01 A story", "description": "d",
             "type": "Story", "parent": "SB-01"}])
        key_parent = doc(nodes=[
            {"id": "ST-01", "subject": "ST-01 A story", "description": "d",
             "type": "Story", "parent": f"#{sub_key}"}])
        for label, d in (("new node parent", new_parent), ("#KEY parent", key_parent)):
            with self.subTest(label):
                plan = self.plan(d)
                self.assertFalse(plan.ok)
                msg = " ".join(plan.errors)
                self.assertIn("ST-01", msg)
                self.assertIn("Sub-task", msg)
                self.assertIn("hierarchy", msg.lower())

    def test_story_under_a_story_is_a_hierarchy_error(self):
        d = doc(nodes=[
            {"id": "ST-01", "subject": "ST-01 A story", "description": "d",
             "type": "Story", "parent": "#SCRUM-2"}])  # SCRUM-2 is a Story
        plan = self.plan(d)
        self.assertFalse(plan.ok)
        self.assertIn("hierarchy", " ".join(plan.errors).lower())

    def test_sub_task_under_story_is_allowed(self):
        new_parent = doc(nodes=[
            {"id": "ST-01", "subject": "ST-01 A story", "description": "d",
             "type": "Story", "parent": None},
            {"id": "SB-01", "subject": "SB-01 A sub-task", "description": "d",
             "type": "Sub-task", "parent": "ST-01"}])
        key_parent = doc(nodes=[
            {"id": "SB-01", "subject": "SB-01 A sub-task", "description": "d",
             "type": "Sub-task", "parent": "#SCRUM-2"}])  # SCRUM-2 is a Story
        for label, d in (("new node parent", new_parent), ("#KEY parent", key_parent)):
            with self.subTest(label):
                plan = self.plan(d)
                self.assertTrue(plan.ok, plan.errors)

    def test_story_under_an_existing_node_is_checked_against_its_type(self):
        self.fake.add_issue("SB-09 Already there", type_name="Sub-task")
        d = doc(nodes=[
            {"id": "SB-09", "subject": "SB-09 Already there", "description": "d",
             "type": "Sub-task", "parent": None},
            {"id": "ST-01", "subject": "ST-01 A story", "description": "d",
             "type": "Story", "parent": "SB-09"}])
        plan = self.plan(d)
        self.assertFalse(plan.ok)
        self.assertIn("hierarchy", " ".join(plan.errors).lower())

    def test_hash_key_parent_must_exist(self):
        d = doc()
        d["nodes"][1]["parent"] = "#SCRUM-999"
        plan = self.plan(d)
        self.assertFalse(plan.ok)
        self.assertTrue(any("SCRUM-999" in e for e in plan.errors), plan.errors)

    def test_each_hash_key_is_fetched_once(self):
        d = doc(relations=[{"type": "relates", "from": "ST-01", "to": "#SCRUM-2"},
                           {"type": "blocks", "from": "#SCRUM-2", "to": "EP-01"}])
        d["nodes"][0]["parent"] = None
        d["nodes"][1]["parent"] = "#SCRUM-1"
        plan = self.plan(d)
        self.assertTrue(plan.ok, plan.errors)
        self.assertEqual(self.fake.requests.count("GET /rest/api/3/issue/SCRUM-2"), 1)
        self.assertEqual(self.fake.requests.count("GET /rest/api/3/issue/SCRUM-1"), 1)

    def test_existing_node_found_by_summary_prefix_and_skipped(self):
        key = self.fake.add_issue("st-01: Login page", type_name="Story")
        plan = self.plan(doc())
        self.assertTrue(plan.ok, plan.errors)
        by_id = {p.node.id: p for p in plan.order}
        self.assertTrue(by_id["ST-01"].exists)
        self.assertEqual(by_id["ST-01"].issue_key, key)
        self.assertFalse(by_id["EP-01"].exists)
        self.assertIsNone(by_id["EP-01"].issue_key)
        # Existing nodes come first: nothing to create for them.
        self.assertEqual([p.node.id for p in plan.order], ["ST-01", "EP-01"])

    def test_two_issues_with_the_same_prefix_are_ambiguous_not_picked(self):
        first = self.fake.add_issue("ST-01 An import", type_name="Story")
        second = self.fake.add_issue("ST-01: Another import", type_name="Story")
        plan = self.plan(doc())
        self.assertFalse(plan.ok)
        msg = " ".join(plan.errors)
        self.assertIn("ambiguous", msg.lower())
        self.assertIn(first, msg)
        self.assertIn(second, msg)
        self.assertFalse(any(p.issue_key for p in plan.order))

    def test_index_by_key_and_resolve_key(self):
        issues = [{"key": "A-1", "fields": {"summary": "X-1 one"}},
                  {"key": "A-2", "fields": {"summary": "x-1: two"}},
                  {"key": "A-3", "fields": {"summary": "Y-1 three"}}]
        index = index_by_key(issues)
        self.assertEqual(resolve_key(index, "Y-1"), ("A-3", None))
        self.assertEqual(resolve_key(index, "Z-1"), (None, None))
        key, problem = resolve_key(index, "X-1")
        self.assertIsNone(key)
        self.assertIn("A-1, A-2", problem)

    def test_link_type_missing_on_the_site_lists_what_the_site_has(self):
        d = doc(relations=[{"type": "duplicates", "from": "ST-01", "to": "EP-01"}])
        plan = self.plan(d)
        self.assertFalse(plan.ok)
        msg = " ".join(plan.errors)
        self.assertIn("Duplicate", msg)
        self.assertIn("Blocks, Relates", msg)

    def test_relation_types_map_to_the_sites_link_type_names(self):
        self.fake.link_types[0]["name"] = "BLOCKS"  # matched casefolded
        d = doc(relations=[{"type": "blocks", "from": "ST-01", "to": "EP-01"},
                           {"type": "relates", "from": "EP-01", "to": "#SCRUM-3"}])
        plan = self.plan(d)
        self.assertTrue(plan.ok, plan.errors)
        self.assertEqual([r.link_type for r in plan.relations], ["BLOCKS", "Relates"])
        self.assertFalse(any(r.exists for r in plan.relations))

    def test_relation_from_an_issue_to_itself_is_an_error(self):
        key = self.fake.add_issue("EX-01 Build the thing", type_name="Story")  # SCRUM-4
        nodes = [{"id": "EX-01", "subject": "EX-01 Build the thing", "description": "d",
                  "type": "Story", "parent": None}]
        for rel in ({"type": "blocks", "from": "EX-01", "to": "EX-01"},
                    {"type": "relates", "from": "EX-01", "to": f"#{key}"}):
            with self.subTest(rel):
                plan = self.plan(doc(nodes=nodes, relations=[rel]))
                self.assertFalse(plan.ok)
                msg = " ".join(plan.errors)
                self.assertIn("itself", msg)
                self.assertIn(key, msg)
        self.assertEqual(self.fake.writes, [])

    def test_relation_already_present_in_issuelinks_is_marked_existing(self):
        blocker = self.fake.add_issue("EX-01 Build the thing", type_name="Story")
        blocked = self.fake.add_issue("EX-02 Test the thing", type_name="Story")
        blocks = dict(self.fake.link_types[0])  # Blocks
        # As Jira reads a link back: on each issue, the other end, under the
        # role the *other* issue plays ("EX-01 blocks EX-02").
        self.fake.issues[blocker]["fields"]["issuelinks"].append(
            {"id": "1", "type": blocks, "outwardIssue": {"key": blocked}})
        self.fake.issues[blocked]["fields"]["issuelinks"].append(
            {"id": "1", "type": blocks, "inwardIssue": {"key": blocker}})
        d = doc(nodes=[
            {"id": "EX-01", "subject": "EX-01 Build the thing", "description": "d",
             "type": "Story", "parent": None},
            {"id": "EX-02", "subject": "EX-02 Test the thing", "description": "d",
             "type": "Story", "parent": None}],
            relations=[{"type": "blocks", "from": "EX-01", "to": "EX-02"},
                       {"type": "relates", "from": "EX-01", "to": "EX-02"}])
        plan = self.plan(d)
        self.assertTrue(plan.ok, plan.errors)
        self.assertEqual([r.exists for r in plan.relations], [True, False])


if __name__ == "__main__":
    unittest.main()
