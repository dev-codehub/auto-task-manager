from __future__ import annotations

import json
import os
import tempfile
import unittest

from jira_sync.updatefile import (Update, UpdateFileError, load_update_file,
                                  parse_update_file)


def doc(*updates, session="2026-10-19-jira"):
    return json.dumps({"session": session, "updates": list(updates)})


class JiraUpdateFileTests(unittest.TestCase):
    def test_parses_a_valid_file(self):
        uf = parse_update_file(doc(
            {"issue": "SCRUM-3", "note": "did it", "status": "Done", "story_points": 3,
             "transition_fields": {"Resolution": "Done", "Hours": 2.5}},
            {"issue": "SCRUM-1", "note": "noted"}))
        self.assertEqual(uf.session, "2026-10-19-jira")
        self.assertEqual(uf.updates[0], Update("SCRUM-3", "did it", "Done", 3,
                                               {"Resolution": "Done", "Hours": 2.5}))
        self.assertEqual(uf.updates[1], Update("SCRUM-1", "noted"))
        self.assertEqual(uf.updates[1].transition_fields, {})

    def test_reads_a_file_with_bom_and_keeps_accents(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "u.json")
            with open(path, "w", encoding="utf-8-sig") as f:
                f.write(doc({"issue": "SCRUM-1", "note": "Sessão concluída — ação"}))
            uf = load_update_file(path)
        self.assertEqual(uf.updates[0].note, "Sessão concluída — ação")

    def test_rejects_unknown_keys(self):
        with self.assertRaises(UpdateFileError) as cm:
            parse_update_file(doc({"issue": "SCRUM-1", "note": "n", "done_ratio": 50}))
        self.assertIn("unknown key", str(cm.exception))
        self.assertIn("done_ratio", str(cm.exception))

    def test_issue_must_be_a_jira_key(self):
        for value in ("#12", "scrum 1", "EX-01.2", "scrum-1", "SCRUM", "", 12):
            with self.assertRaises(UpdateFileError, msg=repr(value)) as cm:
                parse_update_file(doc({"issue": value, "note": "n"}))
            self.assertIn("'issue'", str(cm.exception))
        self.assertEqual(parse_update_file(doc({"issue": "MY_P2-17", "note": "n"}))
                         .updates[0].issue, "MY_P2-17")

    def test_note_is_required_and_non_empty(self):
        for row in ({"issue": "SCRUM-1"}, {"issue": "SCRUM-1", "note": "  "}):
            with self.assertRaises(UpdateFileError) as cm:
                parse_update_file(doc(row))
            self.assertIn("note", str(cm.exception))

    def test_story_points_must_be_a_non_bool_number(self):
        for value in (True, False, "3", -1, None, [3], float("inf")):
            with self.assertRaises(UpdateFileError, msg=repr(value)) as cm:
                parse_update_file(doc({"issue": "SCRUM-1", "note": "n", "story_points": value}))
            self.assertIn("story_points", str(cm.exception))
        for value in (0, 5, 0.5):
            uf = parse_update_file(doc({"issue": "SCRUM-1", "note": "n", "story_points": value}))
            self.assertEqual(uf.updates[0].story_points, value)

    def test_status_must_be_a_non_empty_string(self):
        for value in ("", "  ", 3, None):
            with self.assertRaises(UpdateFileError, msg=repr(value)):
                parse_update_file(doc({"issue": "SCRUM-1", "note": "n", "status": value}))

    def test_transition_fields_values_must_be_text_or_number(self):
        for bad in ("Done", ["Done"], {"Resolution": ""}, {"Resolution": "  "},
                    {"Resolution": True}, {"Resolution": None}, {"Resolution": {"name": "Done"}},
                    {"Resolution": ["Done"]}, {"": "Done"}):
            with self.assertRaises(UpdateFileError, msg=repr(bad)) as cm:
                parse_update_file(doc({"issue": "SCRUM-1", "note": "n", "status": "Done",
                                       "transition_fields": bad}))
            self.assertIn("transition_fields", str(cm.exception))
        uf = parse_update_file(doc({"issue": "SCRUM-1", "note": "n", "status": "Done",
                                    "transition_fields": {"Resolution": "Done", "Hours": 2}}))
        self.assertEqual(uf.updates[0].transition_fields, {"Resolution": "Done", "Hours": 2})

    def test_session_must_be_a_simple_token(self):
        for value in ("", "2026 10 19", "../x", 20261019):
            with self.assertRaises(UpdateFileError, msg=repr(value)):
                parse_update_file(doc({"issue": "SCRUM-1", "note": "n"}, session=value))

    def test_updates_must_be_a_non_empty_list(self):
        for raw in ({"session": "s1", "updates": []}, {"session": "s1"}):
            with self.assertRaises(UpdateFileError):
                parse_update_file(json.dumps(raw))

    def test_every_problem_is_reported_at_once(self):
        with self.assertRaises(UpdateFileError) as cm:
            parse_update_file(doc({"issue": "SCRUM-1"},
                                  {"issue": "SCRUM-2", "note": "n", "story_points": "x"}))
        self.assertIn("update 1", str(cm.exception))
        self.assertIn("update 2", str(cm.exception))

    def test_invalid_json_and_non_utf8(self):
        with self.assertRaises(UpdateFileError) as cm:
            parse_update_file("{nope", source="u.json")
        self.assertIn("u.json", str(cm.exception))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "u.json")
            with open(path, "wb") as f:
                f.write('{"session": "s1", "updates": [{"issue": "SCRUM-1", "note": "ação"}]}'
                        .encode("latin-1"))
            with self.assertRaises(UpdateFileError) as cm:
                load_update_file(path)
        self.assertIn("UTF-8", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
