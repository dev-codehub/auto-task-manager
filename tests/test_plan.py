from __future__ import annotations

import unittest

from redmine_sync.client import Client
from redmine_sync.config import Config
from redmine_sync.plan import build_plan, has_marker, marker_line, subject_key, with_marker
from redmine_sync.render import format_plan
from redmine_sync.updatefile import Update, UpdateFile
from tests.fake_redmine import demo_fake


class SubjectKeyTests(unittest.TestCase):
    def test_space_after_id(self):
        self.assertEqual(subject_key("US-1 Fix login bug"), "US-1")

    def test_colon_then_space(self):
        self.assertEqual(subject_key("US-1: Fix login bug"), "US-1")

    def test_colon_with_no_space(self):
        self.assertEqual(subject_key("US-1:Fix login bug"), "US-1")

    def test_no_separator_at_all(self):
        self.assertEqual(subject_key("US-1"), "US-1")

    def test_blank_subject(self):
        self.assertEqual(subject_key("   "), "")


class MarkerTests(unittest.TestCase):
    def test_with_marker_appends_the_line(self):
        self.assertEqual(with_marker("did it\n", "s1"), "did it\n\n_redmine-sync: s1_")

    def test_has_marker_matches_whole_line(self):
        journals = [{"notes": "x\n\n" + marker_line("s1"), "user": {"id": 1}}]
        self.assertTrue(has_marker(journals, "s1", 1))
        self.assertFalse(has_marker(journals, "s", 1))

    def test_marker_by_another_user_does_not_count(self):
        journals = [{"notes": marker_line("s1"), "user": {"id": 2}}]
        self.assertFalse(has_marker(journals, "s1", 1))

    def test_has_marker_tolerates_missing_notes(self):
        self.assertFalse(has_marker([{"notes": None}, {}], "s1", 1))
        self.assertFalse(has_marker(None, "s1", 1))


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.fake = demo_fake().start()
        self.client = Client(self.fake.url, self.fake.key)
        self.config = Config(url=self.fake.url, project="demo")

    def tearDown(self):
        self.fake.stop()

    def plan(self, *updates, session="s1", config=None):
        return build_plan(self.client, config or self.config, UpdateFile(session, list(updates)))

    def test_resolves_prefix_and_number(self):
        p = self.plan(Update("EX-01.1", "a"), Update("#102", "b"))
        self.assertTrue(p.ok, p.errors)
        self.assertEqual([r.issue_id for r in p.rows], [101, 102])
        self.assertEqual(p.rows[0].subject, "EX-01.1 Build the thing")

    def test_ambiguous_prefix_is_error(self):
        self.fake.add_issue(105, "EX-01.1 Again")
        p = self.plan(Update("EX-01.1", "a"))
        self.assertFalse(p.ok)
        self.assertIn("ambiguous", p.errors[0])
        self.assertIn("#101", p.errors[0])
        self.assertIn("#105", p.errors[0])

    def test_prefix_is_matched_case_insensitively(self):
        p = self.plan(Update("ex-01.1", "a"))
        self.assertTrue(p.ok, p.errors)
        self.assertEqual(p.rows[0].issue_id, 101)

    def test_unknown_prefix_is_error(self):
        p = self.plan(Update("EX-77", "a"))
        self.assertIn("no issue", p.errors[0])

    def test_number_from_other_project_is_error(self):
        p = self.plan(Update("#201", "a"))
        self.assertFalse(p.ok)
        self.assertIn("belongs to project", p.errors[0])

    def test_missing_number_is_error(self):
        p = self.plan(Update("#999", "a"))
        self.assertIn("does not exist or is not visible", p.errors[0])

    def test_same_issue_twice_is_error(self):
        p = self.plan(Update("EX-01.1", "a"), Update("#101", "b"))
        self.assertFalse(p.ok)
        self.assertIn("already updated by update 1", p.errors[0])

    def test_unknown_status_lists_the_known_ones(self):
        p = self.plan(Update("EX-01.1", "a", status="Doing"))
        self.assertIn("unknown status 'Doing'", p.errors[0])
        self.assertIn("In Progress", p.errors[0])

    def test_status_is_matched_case_insensitively(self):
        p = self.plan(Update("EX-01.1", "a", status="in progress"))
        self.assertTrue(p.ok, p.errors)
        self.assertEqual((p.rows[0].target_status, p.rows[0].target_status_id), ("In Progress", 2))

    def test_disallowed_transition_is_error_when_exposed(self):
        self.fake.expose_allowed_statuses = True
        self.fake.workflow = {1: {2}}
        p = self.plan(Update("EX-01.1", "a", status="Closed"))
        self.assertFalse(p.ok)
        self.assertIn("not allowed", p.errors[0])
        self.assertIn("In Progress", p.errors[0])

    def test_transition_is_unchecked_when_not_exposed(self):
        self.fake.workflow = {1: {2}}
        p = self.plan(Update("EX-01.1", "a", status="Closed"))
        self.assertTrue(p.ok, p.errors)
        self.assertFalse(p.rows[0].transition_checked)

    def test_closing_below_100_warns(self):
        p = self.plan(Update("EX-01.1", "a", status="Closed", done_ratio=80))
        self.assertTrue(p.ok, p.errors)
        self.assertTrue(any("below 100" in w for w in p.rows[0].warnings))

    def test_closing_with_done_disabled_does_not_warn_about_done(self):
        self.fake.issues[101]["done_ratio"] = None
        p = self.plan(Update("EX-01.1", "a", status="Closed"))
        self.assertTrue(p.ok, p.errors)
        self.assertEqual(p.rows[0].warnings, [])

    def test_done_going_down_warns(self):
        self.fake.issues[101]["done_ratio"] = 50
        p = self.plan(Update("EX-01.1", "a", done_ratio=30))
        self.assertTrue(any("goes down" in w for w in p.rows[0].warnings))

    def test_done_not_multiple_of_ten_warns(self):
        p = self.plan(Update("EX-01.1", "a", done_ratio=45))
        self.assertTrue(any("multiple of 10" in w for w in p.rows[0].warnings))

    def test_already_applied_is_marked(self):
        self.fake.issues[101]["journals"].append({"id": 1, "notes": "x\n\n" + marker_line("s1"), "user": {"id": 1}})
        p = self.plan(Update("EX-01.1", "a", status="Closed"))
        self.assertTrue(p.ok, p.errors)
        self.assertTrue(p.rows[0].already_applied)

    def test_marker_of_longer_session_does_not_count(self):
        self.fake.issues[101]["journals"].append({"id": 1, "notes": marker_line("2026-01-15-2"), "user": {"id": 1}})
        p = self.plan(Update("EX-01.1", "a"), session="2026-01-15")
        self.assertFalse(p.rows[0].already_applied)
        self.fake.issues[102]["journals"].append({"id": 1, "notes": marker_line("2026-01-15"), "user": {"id": 1}})
        p = self.plan(Update("EX-01.2", "a"), session="2026-01-15-2")
        self.assertFalse(p.rows[0].already_applied)

    def test_id_only_config_rejects_prefixes(self):
        config = Config(url=self.fake.url, project="demo", issue_key="id_only")
        p = self.plan(Update("EX-01.1", "a"), Update("#102", "b"), config=config)
        self.assertEqual(len(p.errors), 1)
        self.assertIn("#number", p.errors[0])

    def test_building_and_rendering_a_plan_writes_nothing(self):
        p = self.plan(Update("EX-01.1", "a", status="In Progress", done_ratio=50))
        format_plan(p)
        self.assertEqual(self.fake.puts, [])

    def test_dry_run_says_when_a_transition_is_only_verified_on_write(self):
        text = format_plan(self.plan(Update("EX-01.1", "a", status="In Progress")))
        self.assertIn("verified on write", text)

    def test_dry_run_is_silent_when_the_transition_was_checked(self):
        self.fake.expose_allowed_statuses = True
        text = format_plan(self.plan(Update("EX-01.1", "a", status="In Progress")))
        self.assertNotIn("verified on write", text)

    def test_header_counts_what_will_be_written(self):
        self.fake.issues[101]["journals"].append({"id": 1, "notes": marker_line("s1"), "user": {"id": 1}})
        text = format_plan(self.plan(Update("EX-01.1", "a"), Update("EX-01.2", "b")))
        self.assertIn("1 to write, 1 already applied", text.splitlines()[0])

    def test_header_shows_the_configured_text_format(self):
        config = Config(url=self.fake.url, project="demo", text_format="markdown")
        text = format_plan(self.plan(Update("EX-01.1", "a"), config=config))
        self.assertIn("notes in markdown", text.splitlines()[0])

    def test_format_plan_shows_changes_and_errors(self):
        p = self.plan(Update("EX-01.1", "line one\nline two", status="In Progress", done_ratio=50),
                      Update("EX-77", "x"))
        text = format_plan(p)
        self.assertIn("New -> In Progress", text)
        self.assertIn("0% -> 50%", text)
        self.assertIn("| line one", text)
        self.assertIn("nothing will be written", text)


if __name__ == "__main__":
    unittest.main()
