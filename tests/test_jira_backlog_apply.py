from __future__ import annotations

import json
import unittest

from jira_sync.adf import markdown_to_adf
from jira_sync.backlog_apply import apply_backlog_plan, fix_parents, update_descriptions
from jira_sync.backlog_file import parse_backlog_file
from jira_sync.backlog_plan import build_backlog_plan
from jira_sync.client import Client
from jira_sync.render import (format_backlog_plan, format_backlog_report,
                              format_description_report, format_parent_report)
from tests.fake_jira import demo_fake

POINTS = "customfield_10016"
CREATE = ("POST", "/rest/api/3/issue")
NOTE = "description written, content not compared"


def node(nid, type_name, parent=None, description="d", **extra):
    return {"id": nid, "subject": f"{nid} The {type_name.lower()}", "description": description,
            "type": type_name, "parent": parent, **extra}


def doc(nodes, relations=()):
    return {"project": "SCRUM", "nodes": list(nodes), "relations": list(relations)}


def screen_field(fid, name, **extra):
    return {"fieldId": fid, "key": fid, "name": name, "required": False,
            "operations": ["set"], "hasDefaultValue": False, **extra}


class Base(unittest.TestCase):
    def setUp(self):
        # demo_fake: project SCRUM with SCRUM-1 "Epic one", SCRUM-2 "Story one",
        # SCRUM-3 "Task one"; types Epic (10001), Story (10002), Task (10003),
        # Sub-task (10004). Story's create screen also offers priority and points.
        self.fake = demo_fake().start()
        self.client = Client(self.fake.url, self.fake.email, self.fake.token)
        self.fake.create_fields["10002"] += [
            screen_field("priority", "Priority", allowedValues=[{"id": "1", "name": "High"},
                                                                {"id": "2", "name": "Low"}]),
            screen_field(POINTS, "Story point estimate")]

    def tearDown(self):
        self.fake.stop()

    def file(self, d):
        return parse_backlog_file(json.dumps(d))

    def plan(self, d):
        plan = build_backlog_plan(self.client, self.file(d))
        self.assertTrue(plan.ok, plan.errors)
        return plan

    def apply(self, d):
        return apply_backlog_plan(self.client, self.plan(d), write=True)

    def creates(self):
        return [body for method, path, body in self.fake.writes if (method, path) == CREATE]


class BacklogApplyTests(Base):
    def test_dry_run_creates_nothing(self):
        plan = self.plan(doc([node("EP-01", "Epic"), node("ST-01", "Story", "EP-01")],
                             [{"type": "relates", "from": "ST-01", "to": "#SCRUM-3"}]))
        report = apply_backlog_plan(self.client, plan, write=False)
        self.assertEqual([o.result for o in report.nodes], ["would create", "would create"])
        self.assertEqual([r.result for r in report.relations], ["would create"])
        self.assertEqual(self.fake.writes, [])

    def test_creates_parents_before_children_and_reads_back_type_parent_priority_points(self):
        d = doc([node("SB-01", "Sub-task", "ST-01", description=""),
                 node("ST-01", "Story", "EP-01", priority="High", story_points=3),
                 node("EP-01", "Epic", description="# Goal\n\nShip **it**")])
        report = self.apply(d)
        self.assertIsNone(report.error)
        self.assertEqual([(o.node_id, o.result, o.issue_key) for o in report.nodes],
                         [("EP-01", "created", "SCRUM-4"), ("ST-01", "created", "SCRUM-5"),
                          ("SB-01", "created", "SCRUM-6")])
        self.assertEqual(self.creates(), [
            {"fields": {"project": {"key": "SCRUM"}, "issuetype": {"id": "10001"},
                        "summary": "EP-01 The epic",
                        "description": markdown_to_adf("# Goal\n\nShip **it**")}},
            {"fields": {"project": {"key": "SCRUM"}, "issuetype": {"id": "10002"},
                        "summary": "ST-01 The story", "description": markdown_to_adf("d"),
                        "parent": {"key": "SCRUM-4"}, "priority": {"name": "High"},
                        POINTS: 3}},
            {"fields": {"project": {"key": "SCRUM"}, "issuetype": {"id": "10004"},
                        "summary": "SB-01 The sub-task", "parent": {"key": "SCRUM-5"}}},
        ])
        story = report.nodes[1]
        self.assertEqual(story.verified, ["type Story", "parent SCRUM-4", "priority High",
                                          "story points 3"])
        self.assertEqual(story.warnings, [])
        self.assertEqual(report.nodes[2].verified, ["type Sub-task", "parent SCRUM-5"])
        fields = self.fake.issues["SCRUM-6"]["fields"]
        self.assertEqual(fields["parent"]["key"], "SCRUM-5")
        self.assertEqual(self.fake.issues["SCRUM-5"]["fields"][POINTS], 3)
        text = format_backlog_report(report)
        self.assertIn("SCRUM-5", text)
        self.assertIn("ok: story points 3", text)
        self.assertIn("done: 3 created, 0 skipped", text)

    def test_structured_field_that_does_not_read_back_is_a_failure(self):
        self.fake.ignored_fields = {POINTS}
        d = doc([node("ST-01", "Story", story_points=3), node("ST-02", "Story")])
        report = self.apply(d)
        self.assertIsNotNone(report.error)
        self.assertIn("ST-01", report.error)
        self.assertIn("story points", report.error)
        # It was created, so the report names it; the run stops there.
        self.assertEqual([(o.node_id, o.result, o.issue_key) for o in report.nodes],
                         [("ST-01", "created", "SCRUM-4")])
        self.assertEqual(len(self.creates()), 1)

    def test_failure_on_the_second_node_then_rerun_creates_only_the_missing_one(self):
        d = doc([node("EP-01", "Epic"), node("ST-01", "Story", "EP-01")],
                [{"type": "relates", "from": "ST-01", "to": "#SCRUM-3"}])
        create, calls = self.fake._create, []

        def fails_second(fields):
            calls.append(fields)
            if len(calls) == 2:
                return None, {"errorMessages": ["Jira had a hiccup"], "errors": {}}
            return create(fields)

        self.fake._create = fails_second
        first = self.apply(d)
        self.assertIn("ST-01", first.error)
        self.assertIn("hiccup", first.error)
        self.assertEqual([(o.node_id, o.result) for o in first.nodes], [("EP-01", "created")])
        self.assertEqual(first.relations, [])
        self.assertIn("re-run", format_backlog_report(first))

        self.fake._create = create
        before = len(self.fake.issues)
        second = self.apply(d)
        self.assertIsNone(second.error)
        self.assertEqual([(o.node_id, o.result, o.issue_key) for o in second.nodes],
                         [("EP-01", "skipped", "SCRUM-4"), ("ST-01", "created", "SCRUM-5")])
        self.assertEqual(len(self.fake.issues), before + 1)
        self.assertEqual(self.fake.issues["SCRUM-5"]["fields"]["parent"]["key"], "SCRUM-4")
        self.assertEqual([r.result for r in second.relations], ["created"])

        writes = len(self.fake.writes)
        third = self.apply(d)
        self.assertEqual([o.result for o in third.nodes], ["skipped", "skipped"])
        self.assertEqual([r.result for r in third.relations], ["skipped"])
        self.assertEqual(len(self.fake.writes), writes)
        self.assertEqual(len(self.fake.issues["SCRUM-5"]["fields"]["issuelinks"]), 1)

    def test_parent_that_did_not_land_warns_to_run_fix_parents(self):
        self.fake.ignored_fields = {"parent"}
        report = self.apply(doc([node("EP-01", "Epic"), node("ST-01", "Story", "EP-01")]))
        self.assertIsNone(report.error)
        self.assertEqual([o.result for o in report.nodes], ["created", "created"])
        warning = " ".join(report.nodes[1].warnings)
        self.assertIn("parent", warning)
        self.assertIn("fix-parents", warning)
        self.assertNotIn("parent SCRUM-4", report.nodes[1].verified)
        self.assertIn("warning:", format_backlog_report(report))

    def test_relation_direction_blocks(self):
        d = doc([node("EX-01", "Story"), node("EX-02", "Story")],
                [{"type": "blocks", "from": "EX-01", "to": "EX-02"}])
        report = self.apply(d)
        self.assertIsNone(report.error)
        self.assertEqual([(r.label, r.result) for r in report.relations],
                         [("EX-01 blocks EX-02", "created")])
        a, b = report.nodes[0].issue_key, report.nodes[1].issue_key
        links = self.client.get_issue(a, ("issuelinks",))["fields"]["issuelinks"]
        self.assertEqual([(l["type"]["name"], l.get("outwardIssue", {}).get("key"))
                          for l in links], [("Blocks", b)])
        links = self.client.get_issue(b, ("issuelinks",))["fields"]["issuelinks"]
        self.assertEqual([(l["type"]["name"], l.get("inwardIssue", {}).get("key"))
                          for l in links], [("Blocks", a)])
        method, path, body = self.fake.writes[-1]
        self.assertEqual((method, path), ("POST", "/rest/api/3/issueLink"))
        self.assertEqual(body["type"], {"name": "Blocks"})
        self.assertEqual({body["inwardIssue"]["key"], body["outwardIssue"]["key"]}, {a, b})
        # The plan reads the same link back as already there.
        again = build_backlog_plan(self.client, self.file(d))
        self.assertEqual([r.exists for r in again.relations], [True])

    def test_a_link_that_reads_back_the_other_way_stops_the_run(self):
        # A site whose orientation disagrees with link_endpoints: apply must stop
        # at the first link, not report "created" and post it again next run.
        link = self.fake._link

        def flipped(body):
            return link(dict(body, inwardIssue=body.get("outwardIssue"),
                             outwardIssue=body.get("inwardIssue")))

        self.fake._link = flipped
        d = doc([node("EX-01", "Story"), node("EX-02", "Story"), node("EX-03", "Story")],
                [{"type": "blocks", "from": "EX-01", "to": "EX-02"},
                 {"type": "blocks", "from": "EX-02", "to": "EX-03"}])
        report = self.apply(d)
        self.assertIsNotNone(report.error)
        self.assertIn("EX-01 blocks EX-02", report.error)
        self.assertIn("does not show", report.error)
        self.assertEqual(report.relations, [])
        links = [w for w in self.fake.writes if w[1] == "/rest/api/3/issueLink"]
        self.assertEqual(len(links), 1)

    def test_identical_relations_listed_twice_create_one_link(self):
        rel = {"type": "blocks", "from": "EX-01", "to": "EX-02"}
        report = self.apply(doc([node("EX-01", "Story"), node("EX-02", "Story")],
                                [rel, dict(rel)]))
        self.assertIsNone(report.error)
        self.assertEqual([r.result for r in report.relations], ["created", "skipped"])
        self.assertIn("listed twice", " ".join(report.relations[1].warnings))
        links = [w for w in self.fake.writes if w[1] == "/rest/api/3/issueLink"]
        self.assertEqual(len(links), 1)

    def test_description_is_verified_only_as_present_and_the_report_says_content_not_compared(
            self):
        create = self.fake._create

        def normalises(fields):
            # Jira stores its own normal form of the document: different, not empty.
            fields = dict(fields, description={"type": "doc", "version": 1, "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "rewritten"}]}]})
            return create(fields)

        self.fake._create = normalises
        report = self.apply(doc([node("EP-01", "Epic", description="Ship **it**")]))
        self.assertIsNone(report.error)
        outcome = report.nodes[0]
        self.assertEqual(outcome.notes, [NOTE])
        self.assertFalse(any("description" in v for v in outcome.verified), outcome.verified)
        self.assertIn(f"note: {NOTE}", format_backlog_report(report))

    def test_description_that_does_not_read_back_at_all_is_a_failure(self):
        self.fake.ignored_fields = {"description"}
        report = self.apply(doc([node("EP-01", "Epic", description="Ship it")]))
        self.assertIsNotNone(report.error)
        self.assertIn("EP-01", report.error)
        self.assertIn("description", report.error)
        self.assertIn("update-descriptions", report.error)

    def test_empty_description_is_not_verified_and_not_an_error(self):
        report = self.apply(doc([node("EP-01", "Epic", description="  \n")]))
        self.assertIsNone(report.error)
        self.assertNotIn("description", self.creates()[0]["fields"])
        self.assertEqual(report.nodes[0].notes, [])
        self.assertEqual(report.nodes[0].warnings, [])

    def test_refuses_a_plan_with_errors(self):
        plan = build_backlog_plan(self.client, self.file(doc([node("XX-01", "Feature")])))
        self.assertFalse(plan.ok)
        with self.assertRaises(ValueError):
            apply_backlog_plan(self.client, plan, write=True)
        self.assertEqual(self.fake.writes, [])

    def test_format_backlog_plan_shows_keys_and_what_would_be_created(self):
        self.fake.add_issue("EP-01 Already there", type_name="Epic")
        text = format_backlog_plan(self.plan(doc(
            [node("EP-01", "Epic"), node("ST-01", "Story", "EP-01", story_points=2)],
            [{"type": "blocks", "from": "ST-01", "to": "#SCRUM-3"}])))
        self.assertIn("EP-01", text)
        self.assertIn("already exists as SCRUM-4", text)
        self.assertIn("would create Story (parent EP-01)", text)
        self.assertIn("ST-01 blocks #SCRUM-3", text)


class FixParentsTests(Base):
    def setUp(self):
        super().setUp()
        self.epic = self.fake.add_issue("EX-01 The epic", type_name="Epic")      # SCRUM-4
        self.story = self.fake.add_issue("EX-02 A story", type_name="Story")     # SCRUM-5
        self.other = self.fake.add_issue("EX-03 Another", type_name="Story")     # SCRUM-6
        self.d = doc([node("EX-01", "Epic"), node("EX-02", "Story", "EX-01"),
                      node("EX-03", "Story", "#SCRUM-1"), node("EX-04", "Story")])

    def test_fix_parents_reports_then_fixes_and_flags_unconfirmed(self):
        report = fix_parents(self.client, self.file(self.d), write=False)
        self.assertEqual(report.correct, 1)
        self.assertEqual(report.absent, ["EX-04"])
        self.assertEqual([(f.node_id, f.issue_key, f.current, f.wanted) for f in report.wrong],
                         [("EX-02", self.story, None, self.epic),
                          ("EX-03", self.other, None, "SCRUM-1")])
        self.assertEqual(self.fake.writes, [])
        self.assertIn("wrong: 2", format_parent_report(report))

        edit = self.fake._edit

        def drops_parent_on_other(issue, body):
            if issue["key"] == self.other:
                body = {"fields": {k: v for k, v in body["fields"].items() if k != "parent"}}
            return edit(issue, body)

        self.fake._edit = drops_parent_on_other
        report = fix_parents(self.client, self.file(self.d), write=True)
        self.assertIsNone(report.error)
        self.assertEqual(report.fixed, ["EX-02"])
        self.assertEqual(report.not_confirmed, ["EX-03"])
        self.assertEqual([(m, p, b) for m, p, b in self.fake.writes],
                         [("PUT", f"/rest/api/3/issue/{self.story}",
                           {"fields": {"parent": {"key": self.epic}}}),
                          ("PUT", f"/rest/api/3/issue/{self.other}",
                           {"fields": {"parent": {"key": "SCRUM-1"}}})])
        self.assertEqual(self.fake.issues[self.story]["fields"]["parent"]["key"], self.epic)
        text = format_parent_report(report)
        self.assertIn("(fixed)", text)
        self.assertIn("did not land", text)

        # Once right, a second report finds nothing wrong for EX-02.
        again = fix_parents(self.client, self.file(self.d), write=False)
        self.assertEqual([f.node_id for f in again.wrong], ["EX-03"])

    def test_ambiguous_match_is_reported_not_resolved(self):
        self.fake.add_issue("EX-02: An import", type_name="Story")
        report = fix_parents(self.client, self.file(self.d), write=True)
        self.assertEqual(report.ambiguous, ["EX-02"])
        self.assertNotIn("EX-02", [f.node_id for f in report.wrong])


class UpdateDescriptionsTests(Base):
    def setUp(self):
        super().setUp()
        self.key = self.fake.add_issue("EX-01 The epic", type_name="Epic")  # SCRUM-4
        self.d = doc([node("EX-01", "Epic", description="New **text**"),
                      node("EX-02", "Story")])

    def test_update_descriptions_write_requires_only(self):
        with self.assertRaises(ValueError):
            update_descriptions(self.client, self.file(self.d), only=[], write=True)
        self.assertEqual(self.fake.writes, [])

    def test_dry_run_reports_would_update_and_writes_nothing(self):
        report = update_descriptions(self.client, self.file(self.d), only=[], write=False)
        self.assertEqual([(o.node_id, o.issue_key, o.result) for o in report.outcomes],
                         [("EX-01", self.key, "would update"),
                          ("EX-02", None, "skipped-no-issue")])
        self.assertEqual(self.fake.writes, [])

    def test_write_sends_adf_and_notes_content_not_compared(self):
        report = update_descriptions(self.client, self.file(self.d), only=["EX-01"], write=True)
        self.assertIsNone(report.error)
        self.assertEqual([(o.node_id, o.result, o.notes) for o in report.outcomes],
                         [("EX-01", "updated", [NOTE])])
        self.assertEqual(self.fake.writes,
                         [("PUT", f"/rest/api/3/issue/{self.key}",
                           {"fields": {"description": markdown_to_adf("New **text**")}})])
        self.assertIn(NOTE, format_description_report(report))

    def test_description_that_does_not_read_back_is_an_error(self):
        self.fake.ignored_fields = {"description"}
        report = update_descriptions(self.client, self.file(self.d), only=["EX-01"], write=True)
        self.assertIn("EX-01", report.error)
        self.assertIn("description", report.error)

    def test_clearing_a_description_is_confirmed_by_the_read_back(self):
        self.fake.issues[self.key]["fields"]["description"] = markdown_to_adf("Old text")
        d = doc([node("EX-01", "Epic", description="")])
        report = update_descriptions(self.client, self.file(d), only=["EX-01"], write=True)
        self.assertIsNone(report.error)
        self.assertEqual([(o.node_id, o.result) for o in report.outcomes],
                         [("EX-01", "updated")])
        self.assertIn("cleared", " ".join(report.outcomes[0].notes))
        self.assertIsNone(self.fake.issues[self.key]["fields"]["description"])

    def test_clearing_a_description_that_still_reads_back_is_an_error(self):
        self.fake.issues[self.key]["fields"]["description"] = markdown_to_adf("Old text")
        self.fake.ignored_fields = {"description"}
        d = doc([node("EX-01", "Epic", description="")])
        report = update_descriptions(self.client, self.file(d), only=["EX-01"], write=True)
        self.assertIsNotNone(report.error)
        self.assertIn("EX-01", report.error)
        self.assertIn("sent empty but the issue still has a description", report.error)
        self.assertEqual(report.outcomes, [])

    def test_write_for_an_only_id_with_no_issue_or_an_ambiguous_one_fails_and_writes_nothing(
            self):
        report = update_descriptions(self.client, self.file(self.d), only=["EX-01", "EX-02"],
                                     write=True)
        self.assertIsNotNone(report.error)
        self.assertIn("EX-02", report.error)
        self.assertNotIn("EX-01", report.error)
        self.assertEqual(self.fake.writes, [])

        self.fake.add_issue("EX-01: A copy", type_name="Epic")
        report = update_descriptions(self.client, self.file(self.d), only=["EX-01"], write=True)
        self.assertIsNotNone(report.error)
        self.assertIn("EX-01", report.error)
        self.assertIn("ambiguous", report.error)
        self.assertEqual(self.fake.writes, [])
        self.assertIn("error:", format_description_report(report))

    def test_unknown_only_id_is_an_error(self):
        report = update_descriptions(self.client, self.file(self.d), only=["NO-SUCH"],
                                     write=True)
        self.assertIn("NO-SUCH", report.error)
        self.assertEqual(self.fake.writes, [])


if __name__ == "__main__":
    unittest.main()
