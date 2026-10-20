from __future__ import annotations

import unittest

from jira_sync.adf import adf_lines
from jira_sync.client import Client
from jira_sync.config import Config
from jira_sync.plan import (build_plan, has_marker, marker_line, session_warnings,
                            with_marker_adf)
from jira_sync.updatefile import Update, UpdateFile
from tests.fake_jira import demo_fake

RESOLUTION = {"required": True, "name": "Resolution", "hasDefaultValue": False,
              "schema": {"type": "resolution", "system": "resolution"},
              "allowedValues": [{"id": "1", "name": "Done"}, {"id": "2", "name": "Won't Do"}]}
REVIEWER = {"required": True, "name": "Reviewer", "hasDefaultValue": False,
            "schema": {"type": "user", "custom":
                       "com.atlassian.jira.plugin.system.customfieldtypes:userpicker",
                       "customId": 10050}}


def comment(text, account_id="acc-1"):
    return {"id": "9", "author": {"accountId": account_id},
            "body": {"type": "doc", "version": 1, "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": text}]}]}}


class MarkerTests(unittest.TestCase):
    def test_marker_line(self):
        self.assertEqual(marker_line("s1"), "_jira-sync: s1_")

    def test_with_marker_adf_appends_the_marker_as_its_own_last_paragraph(self):
        doc = with_marker_adf("did **it**", "s1")
        self.assertEqual(doc["type"], "doc")
        self.assertEqual(doc["content"][-1], {"type": "paragraph", "content": [
            {"type": "text", "text": "_jira-sync: s1_"}]})
        self.assertEqual(adf_lines(doc), ["did it", "_jira-sync: s1_"])

    def test_marker_survives_an_unclosed_code_fence_in_the_note(self):
        doc = with_marker_adf("look:\n```\ncode never closed", "s1")
        self.assertEqual(doc["content"][-2]["type"], "codeBlock")
        self.assertEqual(adf_lines(doc)[-1], "_jira-sync: s1_")
        self.assertTrue(has_marker([{"author": {"accountId": "a"}, "body": doc}], "s1", "a"))

    def test_has_marker_matches_the_whole_line_and_tolerates_odd_comments(self):
        comments = [{}, {"author": None, "body": None}, comment("x " + marker_line("s1")),
                    comment(marker_line("s1"))]
        self.assertTrue(has_marker(comments, "s1", "acc-1"))
        self.assertFalse(has_marker(comments, "s", "acc-1"))
        self.assertFalse(has_marker(comments[:3], "s1", "acc-1"))
        self.assertFalse(has_marker([], "s1", "acc-1"))


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.fake = demo_fake().start()
        self.client = Client(self.fake.url, self.fake.email, self.fake.token)
        self.config = Config(url=self.fake.url, project="SCRUM")
        self.fake.issues["SCRUM-3"]["fields"]["status"] = {"name": "In Progress"}

    def tearDown(self):
        self.fake.stop()

    def plan(self, *updates, session="2026-10-19-jira", config=None):
        return build_plan(self.client, config or self.config, UpdateFile(session, list(updates)))

    def finish_fields(self, fields):
        self.fake.workflow["In Progress"][0]["fields"] = fields

    def test_plain_row_is_read_without_writing(self):
        p = self.plan(Update("SCRUM-3", "a"))
        self.assertTrue(p.ok, p.errors)
        row = p.rows[0]
        self.assertEqual((row.subject, row.current_status), ("Task one", "In Progress"))
        self.assertIsNone(row.transition_id)
        self.assertFalse(row.already_applied)
        self.assertEqual(p.account_id, "acc-1")
        self.assertEqual(self.fake.writes, [])

    def test_a_comment_with_the_marker_from_another_account_does_not_skip_the_row(self):
        self.fake.issues["SCRUM-3"]["comments"].append(
            comment(marker_line("2026-10-19-jira"), account_id="someone-else"))
        p = self.plan(Update("SCRUM-3", "a", status="Done"))
        self.assertTrue(p.ok, p.errors)
        self.assertFalse(p.rows[0].already_applied)
        self.assertEqual(p.rows[0].transition_id, "21")

    def test_own_marker_marks_the_row_already_applied(self):
        self.fake.issues["SCRUM-3"]["comments"].append(
            {"id": "1", "author": {"accountId": "acc-1"},
             "body": with_marker_adf("earlier", "2026-10-19-jira")})
        p = self.plan(Update("SCRUM-3", "a", status="Done"))
        self.assertTrue(p.ok, p.errors)
        self.assertTrue(p.rows[0].already_applied)
        self.assertFalse(self.plan(Update("SCRUM-3", "a"), session="2026-10-20-other")
                         .rows[0].already_applied)

    def test_status_is_reached_through_the_transition_that_leads_there(self):
        p = self.plan(Update("SCRUM-3", "a", status="done"))
        self.assertTrue(p.ok, p.errors)
        row = p.rows[0]
        self.assertEqual((row.transition_id, row.transition_name, row.target_status),
                         ("21", "Finish", "Done"))
        self.assertEqual(row.fields, {})

    def test_status_already_current_needs_no_transition(self):
        p = self.plan(Update("SCRUM-3", "a", status="In Progress"))
        self.assertTrue(p.ok, p.errors)
        self.assertIsNone(p.rows[0].transition_id)
        self.assertEqual(p.rows[0].target_status, "In Progress")

    def test_unreachable_status_lists_the_statuses_reachable_now(self):
        p = self.plan(Update("SCRUM-1", "a", status="Done"))
        self.assertFalse(p.ok)
        self.assertIn("'Done'", p.errors[0])
        self.assertIn("reachable now: In Progress", p.errors[0])

    def test_two_transitions_to_the_same_status_are_an_error_listing_both_names(self):
        self.fake.workflow["In Progress"].append({"id": "41", "name": "Close quickly", "to": "Done"})
        p = self.plan(Update("SCRUM-3", "a", status="Done"))
        self.assertFalse(p.ok)
        self.assertIn("Finish", p.errors[0])
        self.assertIn("Close quickly", p.errors[0])
        self.assertIsNone(p.rows[0].transition_id)

    def test_missing_required_transition_field_blocks_and_lists_the_options(self):
        self.finish_fields({"resolution": RESOLUTION})
        p = self.plan(Update("SCRUM-3", "a", status="Done"))
        self.assertFalse(p.ok)
        self.assertEqual(len(p.errors), 1)
        self.assertIn("Resolution", p.errors[0])
        self.assertIn("Done, Won't Do", p.errors[0])
        self.assertEqual(p.rows[0].fields, {})

    def test_required_field_supplied_is_shaped_for_the_api(self):
        self.finish_fields({"resolution": RESOLUTION})
        p = self.plan(Update("SCRUM-3", "a", status="Done",
                             transition_fields={"resolution": "won't do"}))
        self.assertTrue(p.ok, p.errors)
        self.assertEqual(p.rows[0].fields, {"resolution": {"name": "Won't Do"}})
        self.assertEqual(p.rows[0].field_labels, [("Resolution", "won't do")])

    def test_required_field_with_a_default_is_not_asked_for(self):
        self.finish_fields({"resolution": dict(RESOLUTION, hasDefaultValue=True)})
        p = self.plan(Update("SCRUM-3", "a", status="Done"))
        self.assertTrue(p.ok, p.errors)
        self.assertEqual(p.rows[0].fields, {})

    def test_text_number_and_option_fields(self):
        self.finish_fields({
            "customfield_1": {"required": False, "name": "Notes", "schema": {"type": "string"}},
            "customfield_2": {"required": False, "name": "Hours", "schema": {"type": "number"}},
            "customfield_3": {"required": False, "name": "Risk",
                              "schema": {"type": "option"},
                              "allowedValues": [{"id": "7", "value": "Low"}]}})
        p = self.plan(Update("SCRUM-3", "a", status="Done", transition_fields={
            "Notes": "fine", "Hours": 2.5, "risk": "LOW"}))
        self.assertTrue(p.ok, p.errors)
        self.assertEqual(p.rows[0].fields, {"customfield_1": "fine", "customfield_2": 2.5,
                                            "customfield_3": {"value": "Low"}})
        for bad in ({"Notes": 3}, {"Hours": "two"}):
            p = self.plan(Update("SCRUM-3", "a", status="Done", transition_fields=bad))
            self.assertFalse(p.ok, bad)
            self.assertIn(next(iter(bad)), p.errors[0])

    def test_a_name_two_fields_share_is_an_error_naming_both_ids(self):
        self.finish_fields({
            "customfield_1": {"required": True, "name": "Notes", "schema": {"type": "string"}},
            "customfield_2": {"required": False, "name": "Notes", "schema": {"type": "string"}}})
        p = self.plan(Update("SCRUM-3", "a", status="Done", transition_fields={"Notes": "x"}))
        self.assertFalse(p.ok)
        self.assertEqual(len(p.errors), 1, p.errors)
        self.assertIn("Notes (customfield_1)", p.errors[0])
        self.assertIn("Notes (customfield_2)", p.errors[0])
        self.assertIn("field id", p.errors[0])
        self.assertEqual(p.rows[0].fields, {})
        # Both optional: still an error, never a silent pick.
        self.finish_fields({
            "customfield_1": {"required": False, "name": "Notes", "schema": {"type": "string"}},
            "customfield_2": {"required": False, "name": "notes", "schema": {"type": "string"}}})
        p = self.plan(Update("SCRUM-3", "a", status="Done", transition_fields={"NOTES": "x"}))
        self.assertFalse(p.ok)
        self.assertIn("customfield_1", p.errors[0])
        self.assertIn("customfield_2", p.errors[0])
        # The field id picks one.
        p = self.plan(Update("SCRUM-3", "a", status="Done",
                             transition_fields={"customfield_2": "x"}))
        self.assertTrue(p.ok, p.errors)
        self.assertEqual(p.rows[0].fields, {"customfield_2": "x"})

    def test_one_field_given_twice_is_an_error(self):
        self.finish_fields({"resolution": RESOLUTION})
        for given in ({"Resolution": "Done", "resolution": "Won't Do"},
                      {"Resolution": "Done", "RESOLUTION": "Done"}):
            p = self.plan(Update("SCRUM-3", "a", status="Done", transition_fields=given))
            self.assertFalse(p.ok, given)
            self.assertEqual(len(p.errors), 1, p.errors)
            self.assertIn("more than once", p.errors[0])
            self.assertIn("(resolution)", p.errors[0])

    def test_missing_required_field_error_names_the_field_id(self):
        self.finish_fields({
            "customfield_1": {"required": True, "name": "Notes", "schema": {"type": "string"}}})
        p = self.plan(Update("SCRUM-3", "a", status="Done"))
        self.assertFalse(p.ok)
        self.assertIn("requires 'Notes' (customfield_1)", p.errors[0])
        self.finish_fields({"resolution": RESOLUTION})
        p = self.plan(Update("SCRUM-3", "a", status="Done"))
        self.assertIn("requires 'Resolution' (resolution)", p.errors[0])
        self.finish_fields({"customfield_10050": REVIEWER})
        p = self.plan(Update("SCRUM-3", "a", status="Done"))
        self.assertIn("requires 'Reviewer' (customfield_10050)", p.errors[0])

    def test_option_value_not_in_allowed_values_is_an_error(self):
        self.finish_fields({"resolution": RESOLUTION})
        p = self.plan(Update("SCRUM-3", "a", status="Done",
                             transition_fields={"Resolution": "Fixed"}))
        self.assertFalse(p.ok)
        self.assertIn("'Fixed'", p.errors[0])
        self.assertIn("Done, Won't Do", p.errors[0])

    def test_field_the_transition_does_not_have_is_an_error(self):
        self.finish_fields({"resolution": RESOLUTION})
        p = self.plan(Update("SCRUM-3", "a", status="Done",
                             transition_fields={"Resolution": "Done", "Colour": "red"}))
        self.assertFalse(p.ok)
        self.assertIn("'Colour'", p.errors[0])
        self.assertIn("Resolution", p.errors[0])

    def test_unsupported_field_type_blocks_with_set_it_in_jira(self):
        self.finish_fields({"customfield_10050": REVIEWER})
        p = self.plan(Update("SCRUM-3", "a", status="Done"))
        self.assertFalse(p.ok)
        self.assertIn("Reviewer", p.errors[0])
        self.assertIn("field not supported, set it in Jira", p.errors[0])
        p = self.plan(Update("SCRUM-3", "a", status="Done",
                             transition_fields={"Reviewer": "Ana"}))
        self.assertFalse(p.ok)
        self.assertIn("field not supported, set it in Jira", p.errors[0])
        self.assertEqual(len(p.errors), 1)

    def test_multi_select_and_rich_text_are_unsupported(self):
        self.finish_fields({
            "customfield_4": {"required": False, "name": "Tags",
                              "schema": {"type": "array", "items": "option"},
                              "allowedValues": [{"value": "a"}]},
            "customfield_5": {"required": False, "name": "Summary note", "schema": {
                "type": "string",
                "custom": "com.atlassian.jira.plugin.system.customfieldtypes:textarea"}}})
        for name in ("Tags", "Summary note"):
            p = self.plan(Update("SCRUM-3", "a", status="Done", transition_fields={name: "a"}))
            self.assertFalse(p.ok, name)
            self.assertIn(f"'{name}': field not supported, set it in Jira", p.errors[0])

    def test_story_points_field_taken_from_config_else_found_by_exact_name_else_error(self):
        row = Update("SCRUM-3", "a", story_points=3)
        p = self.plan(row, config=Config(url=self.fake.url, project="SCRUM",
                                         story_points_field="customfield_10099"))
        self.assertTrue(p.ok, p.errors)
        self.assertEqual(p.story_points_field, "customfield_10099")
        self.assertEqual(p.rows[0].story_points_target, 3)

        p = self.plan(row)
        self.assertTrue(p.ok, p.errors)
        self.assertEqual(p.story_points_field, "customfield_10016")

        self.fake.fields.append({"id": "customfield_10020", "name": "Story Points", "custom": True})
        p = self.plan(row)
        self.assertFalse(p.ok)
        self.assertIsNone(p.story_points_field)
        self.assertIn("customfield_10016", p.errors[0])
        self.assertIn("customfield_10020", p.errors[0])
        self.assertIn("story_points_field", p.errors[0])
        self.assertTrue(self.plan(Update("SCRUM-3", "a")).ok)

        self.fake.fields = [{"id": "summary", "name": "Summary", "custom": False},
                            {"id": "customfield_10030", "name": "story points", "custom": True}]
        p = self.plan(row)
        self.assertFalse(p.ok)
        self.assertIn("no field named", p.errors[0])
        self.assertIn("story_points_field", p.errors[0])
        self.assertTrue(self.plan(Update("SCRUM-3", "a")).ok)

    def test_issue_of_another_project_is_an_error(self):
        self.fake.add_project("OTHER", "10001")
        self.fake.add_issue("Elsewhere", project="OTHER")
        p = self.plan(Update("OTHER-1", "a"), Update("SCRUM-9", "b"))
        self.assertEqual(len(p.errors), 2)
        self.assertIn("project 'OTHER', not 'SCRUM'", p.errors[0])
        self.assertIn("SCRUM-9", p.errors[1])
        self.assertIn("does not exist", p.errors[1])

    def test_two_rows_for_one_issue_are_an_error(self):
        p = self.plan(Update("SCRUM-3", "a"), Update("SCRUM-3", "b"))
        self.assertFalse(p.ok)
        self.assertIn("update 2", p.errors[0])
        self.assertIn("already updated by update 1", p.errors[0])

    def test_bare_date_session_is_noted(self):
        self.assertTrue(self.plan(Update("SCRUM-3", "a"), session="2026-10-19").warnings)
        self.assertIn("2026-10-19-", session_warnings("2026-10-19-2")[0])
        self.assertEqual(session_warnings("2026-10-19-jira"), [])
        self.assertTrue(self.plan(Update("SCRUM-3", "a"), session="2026-10-19").ok)

    def test_no_status_row_never_asks_for_transition_fields(self):
        self.finish_fields({"resolution": RESOLUTION, "customfield_10050": REVIEWER})
        p = self.plan(Update("SCRUM-3", "a"))
        self.assertTrue(p.ok, p.errors)
        self.assertEqual(p.rows[0].fields, {})
        self.assertFalse(any("/transitions" in r for r in self.fake.requests))

    def test_transition_fields_without_a_status_is_an_error(self):
        p = self.plan(Update("SCRUM-3", "a", transition_fields={"Resolution": "Done"}))
        self.assertFalse(p.ok)
        self.assertIn("'status'", p.errors[0])


if __name__ == "__main__":
    unittest.main()
