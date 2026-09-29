from __future__ import annotations

import json
import unittest

from redmine_sync.backlog_apply import apply_backlog_plan, fix_parents, update_descriptions
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
        "relations": [{"type": "blocks", "from": "US-90.1", "to": "US-90"}],
    }
    d.update(overrides)
    return d


class BacklogApplyTests(unittest.TestCase):
    def setUp(self):
        self.fake = demo_fake().start()
        self.client = Client(self.fake.url, self.fake.key)

    def tearDown(self):
        self.fake.stop()

    def _plan(self, d):
        f = parse_backlog_file(json.dumps(d))
        plan = build_backlog_plan(self.client, f)
        self.assertTrue(plan.ok, plan.errors)
        return plan

    def test_dry_run_creates_nothing(self):
        plan = self._plan(doc())
        report = apply_backlog_plan(self.client, plan, write=False)
        self.assertEqual([o.result for o in report.nodes], ["would create", "would create"])
        self.assertEqual(len(self.fake.issues), 4)  # the demo_fake fixtures, unchanged

    def test_write_creates_parent_then_child_and_reads_parent_back(self):
        plan = self._plan(doc())
        report = apply_backlog_plan(self.client, plan, write=True)
        self.assertEqual([o.result for o in report.nodes], ["created", "created"])
        parent_id = report.nodes[0].issue_id
        child_id = report.nodes[1].issue_id
        self.assertEqual(self.fake.issues[child_id]["parent_id"], parent_id)
        self.assertEqual(report.relations[0].result, "created")
        self.assertEqual(len(self.fake.relations), 1)

    def test_already_existing_node_is_skipped(self):
        d = doc()
        d["nodes"][0]["id"] = "EX-01.1"
        d["nodes"][0]["subject"] = "EX-01.1 Build the thing"
        d["nodes"] = [d["nodes"][0]]
        d["relations"] = []
        plan = self._plan(d)
        report = apply_backlog_plan(self.client, plan, write=True)
        self.assertEqual(report.nodes[0].result, "skipped")
        self.assertEqual(report.nodes[0].issue_id, 101)

    def test_re_run_is_idempotent(self):
        plan = self._plan(doc())
        apply_backlog_plan(self.client, plan, write=True)
        # Re-resolve against the now-updated live state and apply again.
        f = parse_backlog_file(json.dumps(doc()))
        plan2 = build_backlog_plan(self.client, f)
        report2 = apply_backlog_plan(self.client, plan2, write=True)
        self.assertEqual([o.result for o in report2.nodes], ["skipped", "skipped"])
        self.assertEqual(report2.relations[0].result, "skipped")
        self.assertEqual(len(self.fake.relations), 1)  # not duplicated

    def test_parent_not_landing_is_a_warning_not_a_crash(self):
        # Simulate a Redmine that silently drops parent_issue_id on create.
        orig = self.fake._create_issue

        def flaky(fields):
            fields = dict(fields)
            fields.pop("parent_issue_id", None)
            return orig(fields)

        self.fake._create_issue = flaky
        plan = self._plan(doc())
        report = apply_backlog_plan(self.client, plan, write=True)
        self.assertIn("parent", " ".join(report.nodes[1].warnings).lower())
        self.assertIn("fix-parents", " ".join(report.nodes[1].warnings).lower())

    def test_relation_response_not_matching_the_request_is_an_error(self):
        # A stand-in for Redmine accepting the POST but creating a different
        # relation type than asked (or silently coercing it) - the response
        # body is already in hand, so this costs no extra request.
        orig = self.client.create_relation

        def wrong_type(issue_id, to_id, relation_type, delay=None):
            rel = orig(issue_id, to_id, relation_type, delay)
            rel["relation_type"] = "relates"  # not what was requested
            return rel

        self.client.create_relation = wrong_type
        plan = self._plan(doc())
        report = apply_backlog_plan(self.client, plan, write=True)
        self.assertIsNotNone(report.error)
        self.assertIn("blocks", report.error)


class FixParentsTests(unittest.TestCase):
    def setUp(self):
        self.fake = demo_fake().start()
        self.client = Client(self.fake.url, self.fake.key)

    def tearDown(self):
        self.fake.stop()

    def _file(self, d):
        return parse_backlog_file(json.dumps(d))

    def test_reports_absent_issue(self):
        d = doc()
        d["nodes"] = [d["nodes"][0]]
        d["relations"] = []
        report = fix_parents(self.client, self._file(d), write=False)
        self.assertIn("US-90", report.absent)

    def test_reports_correct_and_wrong(self):
        d = doc()
        d["nodes"][0]["id"] = "EX-01.1"
        d["nodes"][0]["subject"] = "EX-01.1 Build the thing"
        d["nodes"][1]["id"] = "EX-01.2"
        d["nodes"][1]["subject"] = "EX-01.2 Test the thing"
        d["nodes"][1]["parent"] = "EX-01.1"
        d["relations"] = []
        # EX-01.2 (#102) currently has no parent set in the fixture.
        report = fix_parents(self.client, self._file(d), write=False)
        self.assertEqual(report.correct, 1)  # EX-01.1 wants no parent, has none
        self.assertEqual(len(report.wrong), 1)
        self.assertEqual(report.wrong[0].node_id, "EX-01.2")
        self.assertEqual(self.fake.issues[102].get("parent_id"), None)  # unchanged, no --write

    def test_write_fixes_the_wrong_ones(self):
        d = doc()
        d["nodes"][0]["id"] = "EX-01.1"
        d["nodes"][0]["subject"] = "EX-01.1 Build the thing"
        d["nodes"][1]["id"] = "EX-01.2"
        d["nodes"][1]["subject"] = "EX-01.2 Test the thing"
        d["nodes"][1]["parent"] = "EX-01.1"
        d["relations"] = []
        report = fix_parents(self.client, self._file(d), write=True)
        self.assertEqual(report.fixed, ["EX-01.2"])
        self.assertEqual(self.fake.issues[102]["parent_id"], 101)

    def test_write_that_does_not_land_is_reported_not_marked_fixed(self):
        # Simulate a role that cannot set parent_issue_id: Redmine accepts
        # the PUT (204) but silently drops the field, as it already does
        # for other fields today (see _apply_put's own docstring).
        orig = self.fake._apply_put

        def flaky(issue, fields, user):
            fields = dict(fields)
            fields.pop("parent_issue_id", None)
            return orig(issue, fields, user)

        self.fake._apply_put = flaky
        d = doc()
        d["nodes"][0]["id"] = "EX-01.1"
        d["nodes"][0]["subject"] = "EX-01.1 Build the thing"
        d["nodes"][1]["id"] = "EX-01.2"
        d["nodes"][1]["subject"] = "EX-01.2 Test the thing"
        d["nodes"][1]["parent"] = "EX-01.1"
        d["relations"] = []
        report = fix_parents(self.client, self._file(d), write=True)
        self.assertEqual(report.fixed, [])
        self.assertEqual(report.not_confirmed, ["EX-01.2"])

    def test_ambiguous_match_is_reported_not_resolved_silently(self):
        self.fake.add_issue(105, "EX-01.1 A duplicate import")
        d = doc()
        d["nodes"] = [d["nodes"][0]]
        d["nodes"][0]["id"] = "EX-01.1"
        d["nodes"][0]["subject"] = "EX-01.1 Build the thing"
        d["relations"] = []
        report = fix_parents(self.client, self._file(d), write=False)
        self.assertEqual(report.ambiguous, ["EX-01.1"])
        self.assertEqual(report.correct, 0)
        self.assertEqual(report.wrong, [])


class UpdateDescriptionsTests(unittest.TestCase):
    def setUp(self):
        self.fake = demo_fake().start()
        self.client = Client(self.fake.url, self.fake.key)

    def tearDown(self):
        self.fake.stop()

    def _file(self, description="new text"):
        d = doc()
        d["nodes"][0]["id"] = "EX-01.1"
        d["nodes"][0]["subject"] = "EX-01.1 Build the thing"
        d["nodes"][0]["description"] = description
        d["nodes"] = [d["nodes"][0]]
        d["relations"] = []
        return parse_backlog_file(json.dumps(d))

    def test_dry_run_reports_would_update(self):
        report = update_descriptions(self.client, self._file(), only=["EX-01.1"], write=False)
        self.assertEqual(report.outcomes[0].result, "would update")

    def test_write_updates_and_reads_back(self):
        report = update_descriptions(self.client, self._file("the real new text"),
                                     only=["EX-01.1"], write=True)
        self.assertEqual(report.outcomes[0].result, "updated")
        self.assertEqual(self.client.get_issue(101).get("description"), "the real new text")

    def test_only_filters_to_named_nodes(self):
        report = update_descriptions(self.client, self._file(), only=["NO-SUCH-ID"], write=False)
        self.assertEqual(report.outcomes, [])

    def test_node_without_existing_issue_is_skipped(self):
        d = doc()
        d["relations"] = []
        f = parse_backlog_file(json.dumps(d))  # US-90 / US-90.1, neither created
        report = update_descriptions(self.client, f, only=["US-90"], write=False)
        self.assertEqual(report.outcomes[0].result, "skipped-no-issue")

    def test_ambiguous_match_is_reported_not_resolved_silently(self):
        self.fake.add_issue(105, "EX-01.1 A duplicate import")
        report = update_descriptions(self.client, self._file(), only=["EX-01.1"], write=False)
        self.assertEqual(report.outcomes[0].result, "ambiguous")

    def test_write_with_empty_only_raises_rather_than_updating_everything(self):
        with self.assertRaises(ValueError):
            update_descriptions(self.client, self._file(), only=[], write=True)
        self.assertNotEqual(self.fake.issues[101].get("description"), "new text")

    def test_write_with_unknown_only_id_is_reported_as_an_error(self):
        report = update_descriptions(self.client, self._file(), only=["NO-SUCH-ID"], write=True)
        self.assertIsNotNone(report.error)
        self.assertIn("NO-SUCH-ID", report.error)


if __name__ == "__main__":
    unittest.main()
