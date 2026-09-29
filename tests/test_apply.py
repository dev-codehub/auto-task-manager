from __future__ import annotations

import unittest

from redmine_sync.apply import apply_plan
from redmine_sync.client import Client
from redmine_sync.config import Config
from redmine_sync.plan import build_plan, marker_line
from redmine_sync.render import format_report
from redmine_sync.updatefile import Update, UpdateFile
from tests.fake_redmine import demo_fake


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.fake = demo_fake().start()
        self.client = Client(self.fake.url, self.fake.key)
        self.config = Config(url=self.fake.url, project="demo")

    def tearDown(self):
        self.fake.stop()

    def plan(self, *updates, session="s1"):
        return build_plan(self.client, self.config, UpdateFile(session, list(updates)))

    def run_apply(self, *updates, session="s1"):
        plan = self.plan(*updates, session=session)
        self.assertTrue(plan.ok, plan.errors)
        return apply_plan(self.client, plan)

    def test_writes_status_then_comment_and_done(self):
        report = self.run_apply(Update("EX-01.1", "did it", done_ratio=50, status="In Progress"))
        self.assertIsNone(report.error)
        issue = self.fake.issues[101]
        self.assertEqual((issue["status_id"], issue["done_ratio"]), (2, 50))
        self.assertEqual(issue["journals"][-1]["notes"], "did it\n\n" + marker_line("s1"))
        self.assertEqual(self.fake.puts[0], (101, {"status_id": 2}))
        self.assertEqual(self.fake.puts[1][1]["done_ratio"], 50)
        self.assertEqual(report.outcomes[0].result, "written")
        self.assertIn("status New -> In Progress", report.outcomes[0].verified)

    def test_unchanged_status_is_not_sent(self):
        self.run_apply(Update("EX-01.1", "note", status="New"))
        self.assertEqual([f for _, f in self.fake.puts if "status_id" in f], [])

    def test_second_run_writes_nothing(self):
        self.run_apply(Update("EX-01.1", "did it", status="In Progress"))
        puts = len(self.fake.puts)
        report = self.run_apply(Update("EX-01.1", "did it", status="In Progress"))
        self.assertEqual(len(self.fake.puts), puts)
        self.assertEqual(report.outcomes[0].result, "skipped")
        self.assertEqual(len(self.fake.issues[101]["journals"]), 1)

    def test_disallowed_transition_is_caught_on_read_back_and_stops(self):
        self.fake.workflow = {1: {2}}
        report = self.run_apply(Update("EX-01.1", "close it", status="Closed"),
                                Update("EX-01.2", "other"))
        self.assertIn("not applied", report.error)
        self.assertIn("#101", report.error)
        self.assertEqual(self.fake.issues[101]["journals"], [])
        self.assertEqual(self.fake.issues[101]["status_id"], 1)
        self.assertNotIn(102, [iid for iid, _ in self.fake.puts])

    def test_derived_done_is_a_warning_and_the_comment_lands(self):
        self.fake.derived_done.add(101)
        report = self.run_apply(Update("EX-01.1", "progress", done_ratio=60))
        self.assertIsNone(report.error)
        self.assertTrue(any("derives" in w for w in report.outcomes[0].warnings))
        self.assertEqual(len(self.fake.issues[101]["journals"]), 1)

    def test_done_disabled_on_the_instance_is_said_plainly(self):
        self.fake.issues[101]["done_ratio"] = None
        self.fake.derived_done.add(101)
        report = self.run_apply(Update("EX-01.1", "progress", done_ratio=60))
        warning = " ".join(report.outcomes[0].warnings)
        self.assertIn("not available", warning)
        self.assertNotIn("None", warning)

    def test_interrupted_run_resumes(self):
        self.fake.fail_puts_after = 1
        first = self.run_apply(Update("EX-01.1", "one"), Update("EX-01.2", "two"))
        self.assertIsNotNone(first.error)
        self.assertIn("#102", first.error)
        self.fake.fail_puts_after = None
        second = self.run_apply(Update("EX-01.1", "one"), Update("EX-01.2", "two"))
        self.assertIsNone(second.error)
        self.assertEqual([o.result for o in second.outcomes], ["skipped", "written"])
        self.assertEqual(len(self.fake.issues[101]["journals"]), 1)
        self.assertEqual(len(self.fake.issues[102]["journals"]), 1)

    def test_forbidden_stops_with_a_role_message(self):
        self.fake.forbidden.add(102)
        report = self.run_apply(Update("EX-01.1", "one"), Update("EX-01.2", "two"))
        self.assertIn("#102", report.error)
        self.assertIn("role", report.error)
        self.assertEqual(report.outcomes[0].result, "written")

    def test_non_ascii_note_round_trips(self):
        note = "Sessão concluída — ação pendente: validação"
        self.run_apply(Update("EX-01.1", note))
        self.assertEqual(self.fake.issues[101]["journals"][0]["notes"],
                         note + "\n\n" + marker_line("s1"))

    def test_same_session_id_by_two_people_both_land(self):
        self.run_apply(Update("EX-01.1", "from the first person"))
        self.fake.add_user("key-b", 2, "second")
        other = Client(self.fake.url, "key-b")
        plan = build_plan(other, self.config, UpdateFile("s1", [Update("EX-01.1", "from the second")]))
        self.assertFalse(plan.rows[0].already_applied)
        report = apply_plan(other, plan)
        self.assertIsNone(report.error)
        self.assertEqual(report.outcomes[0].result, "written")
        self.assertEqual([j["user"]["id"] for j in self.fake.issues[101]["journals"]], [1, 2])

    def test_refuses_a_plan_with_errors(self):
        plan = self.plan(Update("EX-77", "x"))
        with self.assertRaises(ValueError):
            apply_plan(self.client, plan)

    def test_report_after_a_stop_says_how_to_resume(self):
        self.fake.fail_puts_after = 0
        text = format_report(self.run_apply(Update("EX-01.1", "one")))
        self.assertIn("stopped", text)
        self.assertIn("re-run", text)


if __name__ == "__main__":
    unittest.main()
