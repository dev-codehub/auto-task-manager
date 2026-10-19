from __future__ import annotations

import unittest

from jira_sync.apply import apply_plan
from jira_sync.client import Client, ForbiddenError, TransportError
from jira_sync.config import Config
from jira_sync.plan import build_plan, has_marker
from jira_sync.render import format_plan, format_report
from jira_sync.updatefile import Update, UpdateFile
from tests.fake_jira import demo_fake

SESSION = "2026-10-19-jira"
POINTS = "customfield_10016"
RESOLUTION = {"required": True, "name": "Resolution", "hasDefaultValue": False,
              "schema": {"type": "resolution", "system": "resolution"},
              "allowedValues": [{"id": "1", "name": "Done"}, {"id": "2", "name": "Won't Do"}]}


class JiraApplyTests(unittest.TestCase):
    def setUp(self):
        self.fake = demo_fake().start()
        self.client = Client(self.fake.url, self.fake.email, self.fake.token)
        self.config = Config(url=self.fake.url, project="SCRUM")
        self.fake.workflow["To Do"].append(
            {"id": "41", "name": "Close", "to": "Done", "fields": {"resolution": RESOLUTION}})

    def tearDown(self):
        self.fake.stop()

    def plan(self, *updates):
        return build_plan(self.client, self.config, UpdateFile(SESSION, list(updates)))

    def run_apply(self, *updates):
        plan = self.plan(*updates)
        self.assertTrue(plan.ok, plan.errors)
        return apply_plan(self.client, plan)

    def comments(self, key):
        return self.fake.issues[key]["comments"]

    def test_write_transitions_then_comments_and_verifies_each(self):
        report = self.run_apply(Update("SCRUM-1", "did **it**", status="Done",
                                       transition_fields={"Resolution": "Done"}))
        self.assertIsNone(report.error)
        outcome = report.outcomes[0]
        self.assertEqual((outcome.issue_key, outcome.key, outcome.result),
                         ("SCRUM-1", "SCRUM-1", "written"))
        self.assertEqual(outcome.verified,
                         ["status To Do -> Done", "Resolution = Done", "comment recorded"])
        fields = self.fake.issues["SCRUM-1"]["fields"]
        self.assertEqual(fields["status"], {"name": "Done"})
        self.assertEqual(fields["resolution"], {"name": "Done"})
        self.assertEqual(self.fake.writes[0],
                         ("POST", "/rest/api/3/issue/SCRUM-1/transitions",
                          {"transition": {"id": "41"}, "fields": {"resolution": {"name": "Done"}}}))
        method, path, body = self.fake.writes[-1]
        self.assertEqual((method, path), ("POST", "/rest/api/3/issue/SCRUM-1/comment"))
        self.assertEqual(body["body"]["type"], "doc")
        self.assertEqual(len(self.fake.writes), 2)
        self.assertTrue(has_marker(self.comments("SCRUM-1"), SESSION, "acc-1"))
        text = format_report(report)
        self.assertIn("ok: status To Do -> Done", text)
        self.assertIn("done: 1 written, 0 skipped", text)

    def test_a_transition_that_did_not_land_stops_before_writing_anything_else_to_that_issue(self):
        self.fake.stuck.add("SCRUM-1")
        report = self.run_apply(Update("SCRUM-1", "start it", status="In Progress",
                                       story_points=3),
                                Update("SCRUM-2", "other"))
        self.assertIn("SCRUM-1", report.error)
        self.assertIn("did not land", report.error)
        self.assertIn("nothing else was written", report.error)
        self.assertEqual(report.outcomes, [])
        self.assertEqual([(m, p) for m, p, _ in self.fake.writes],
                         [("POST", "/rest/api/3/issue/SCRUM-1/transitions")])
        self.assertEqual(self.comments("SCRUM-1"), [])
        self.assertNotIn(POINTS, self.fake.issues["SCRUM-1"]["fields"])
        self.assertEqual(self.comments("SCRUM-2"), [])

    def test_a_transition_field_that_does_not_read_back_is_a_failure(self):
        self.fake.ignored_fields = {"resolution"}
        report = self.run_apply(Update("SCRUM-1", "close", status="Done",
                                       transition_fields={"Resolution": "Done"}))
        self.assertIn("Resolution", report.error)
        self.assertEqual(report.outcomes, [])
        self.assertEqual(self.comments("SCRUM-1"), [])

    def test_story_points_that_do_not_read_back_are_a_failure(self):
        self.fake.ignored_fields = {POINTS}
        report = self.run_apply(Update("SCRUM-1", "estimated", story_points=5))
        self.assertIsNotNone(report.error)
        self.assertIn("SCRUM-1", report.error)
        self.assertIn("story points", report.error)
        self.assertIn("5", report.error)
        self.assertNotIn("written", [o.result for o in report.outcomes])
        # The marker is what makes a re-run skip the row, so it is not written
        # until everything else on the row is verified.
        self.assertEqual(self.comments("SCRUM-1"), [])
        self.assertIn("stopped", format_report(report))

    def test_story_points_are_sent_as_a_bare_number_and_verified(self):
        report = self.run_apply(Update("SCRUM-1", "estimated", status="In Progress",
                                       story_points=5))
        self.assertIsNone(report.error)
        self.assertIn(("PUT", "/rest/api/3/issue/SCRUM-1", {"fields": {POINTS: 5}}),
                      self.fake.writes)
        self.assertEqual(self.fake.issues["SCRUM-1"]["fields"][POINTS], 5)
        self.assertIn("story points 5", report.outcomes[0].verified)

    def test_story_points_untouched_when_the_row_does_not_set_them(self):
        report = self.run_apply(Update("SCRUM-1", "note only"))
        self.assertIsNone(report.error)
        self.assertEqual([m for m, _, _ in self.fake.writes], ["POST"])
        self.assertNotIn(POINTS, self.fake.issues["SCRUM-1"]["fields"])
        self.assertEqual(report.outcomes[0].verified, ["comment recorded"])

    def test_status_already_reached_sends_no_transition(self):
        report = self.run_apply(Update("SCRUM-1", "still to do", status="To Do"))
        self.assertIsNone(report.error)
        self.assertEqual([p for _, p, _ in self.fake.writes],
                         ["/rest/api/3/issue/SCRUM-1/comment"])

    def test_a_lost_answer_to_the_comment_says_it_may_not_have_been_written(self):
        def times_out(key, adf):
            raise TransportError(f"cannot reach {self.fake.url} (timed out)")

        self.client.add_comment = times_out
        report = self.run_apply(Update("SCRUM-1", "start it", status="In Progress"))
        self.assertIn("timed out", report.error)
        self.assertIn("status To Do -> In Progress", report.error)
        self.assertIn("the comment may not have been written", report.error)
        self.assertIn("a re-run checks for the marker", report.error)
        self.assertNotIn("the comment was not written", report.error)

    def test_a_comment_jira_refused_after_other_writes_says_it_was_not_written(self):
        def refuses(key, adf):
            raise ForbiddenError("your account is not allowed to do this")

        self.client.add_comment = refuses
        report = self.run_apply(Update("SCRUM-1", "start it", status="In Progress"))
        self.assertIn("the comment was not written", report.error)

    def test_rerun_after_story_points_failed_does_not_transition_again(self):
        row = Update("SCRUM-1", "start it", status="In Progress", story_points=3)
        self.fake.ignored_fields = {POINTS}
        first = self.run_apply(row)
        self.assertIn("story points", first.error)
        self.assertEqual(self.fake.issues["SCRUM-1"]["fields"]["status"], {"name": "In Progress"})
        self.assertEqual(self.comments("SCRUM-1"), [])

        self.fake.ignored_fields = set()
        writes = len(self.fake.writes)
        second = self.run_apply(row)
        self.assertIsNone(second.error)
        later = [(m, p) for m, p, _ in self.fake.writes[writes:]]
        self.assertNotIn(("POST", "/rest/api/3/issue/SCRUM-1/transitions"), later)
        self.assertEqual(self.fake.issues["SCRUM-1"]["fields"][POINTS], 3)
        self.assertEqual(len(self.comments("SCRUM-1")), 1)
        transitions = [w for w in self.fake.writes if w[1].endswith("/transitions")]
        self.assertEqual(len(transitions), 1)

    def test_rerun_skips_rows_already_applied(self):
        rows = (Update("SCRUM-1", "start it", status="In Progress", story_points=2),
                Update("SCRUM-2", "note"))
        self.run_apply(*rows)
        writes = len(self.fake.writes)
        report = self.run_apply(*rows)
        self.assertIsNone(report.error)
        self.assertEqual([o.result for o in report.outcomes], ["skipped", "skipped"])
        self.assertEqual(len(self.fake.writes), writes)
        self.assertEqual(len(self.comments("SCRUM-1")), 1)
        self.assertIn("done: 0 written, 2 skipped", format_report(report))

    def test_failure_midway_reports_how_many_were_written_and_says_to_rerun(self):
        self.fake.forbidden.add("SCRUM-2")
        rows = (Update("SCRUM-1", "one"), Update("SCRUM-2", "two"), Update("SCRUM-3", "three"))
        report = self.run_apply(*rows)
        self.assertIn("SCRUM-2", report.error)
        self.assertEqual([o.result for o in report.outcomes], ["written"])
        self.assertEqual(self.comments("SCRUM-3"), [])
        text = format_report(report)
        self.assertIn("stopped at SCRUM-2", text)
        self.assertIn("1 issue(s) written before the stop", text)
        self.assertIn("re-run", text)
        self.assertIn("run the dry run again first", text)
        self.assertNotIn("re-run the same command", text)

        self.fake.forbidden.clear()
        second = self.run_apply(*rows)
        self.assertIsNone(second.error)
        self.assertEqual([o.result for o in second.outcomes], ["skipped", "written", "written"])
        self.assertEqual(len(self.comments("SCRUM-1")), 1)

    def test_refuses_a_plan_with_errors(self):
        plan = self.plan(Update("SCRUM-1", "x", status="Nowhere"))
        with self.assertRaises(ValueError):
            apply_plan(self.client, plan)


class JiraRenderTests(unittest.TestCase):
    def setUp(self):
        self.fake = demo_fake().start()
        self.client = Client(self.fake.url, self.fake.email, self.fake.token)
        self.config = Config(url=self.fake.url, project="SCRUM")

    def tearDown(self):
        self.fake.stop()

    def format(self, *updates, session=SESSION):
        return format_plan(build_plan(self.client, self.config,
                                      UpdateFile(session, list(updates))))

    def test_plan_shows_status_transition_fields_points_and_note(self):
        self.fake.workflow["To Do"].append(
            {"id": "41", "name": "Close", "to": "Done", "fields": {"resolution": RESOLUTION}})
        text = self.format(Update("SCRUM-1", "line 1\nline 2\nline 3\nline 4", status="Done",
                                  story_points=8, transition_fields={"Resolution": "Done"}))
        self.assertIn(f"session {SESSION}: 1 to write", text)
        self.assertIn("SCRUM-1  Epic one", text)
        self.assertIn("status  To Do -> Done  (transition 'Close')", text)
        self.assertIn("Resolution = Done", text)
        self.assertIn("story points -> 8", text)
        self.assertIn("| line 3", text)
        self.assertNotIn("| line 4", text)
        self.assertIn("1 more line(s)", text)

    def test_missing_required_field_is_shown_under_its_row(self):
        self.fake.workflow["To Do"].append(
            {"id": "41", "name": "Close", "to": "Done", "fields": {"resolution": RESOLUTION}})
        text = self.format(Update("SCRUM-1", "n", status="Done"))
        row = text.split("SCRUM-1", 1)[1]
        self.assertIn("error: transition 'Close' requires 'Resolution' (resolution), one of: "
                      "Done, Won't Do",
                      row)
        self.assertIn("1 error(s) - nothing will be written", text)

    def test_bare_date_session_and_already_applied_are_noted(self):
        self.fake.issues["SCRUM-1"]["comments"].append(
            {"id": "1", "author": {"accountId": "acc-1"},
             "body": {"type": "doc", "version": 1, "content": [
                 {"type": "paragraph", "content": [
                     {"type": "text", "text": "_jira-sync: 2026-10-19_"}]}]}})
        text = self.format(Update("SCRUM-1", "n"), session="2026-10-19")
        self.assertIn("note: session '2026-10-19' is only a date", text)
        self.assertIn("0 to write, 1 already applied", text)
        self.assertIn("already applied in this session - will be skipped", text)


if __name__ == "__main__":
    unittest.main()
