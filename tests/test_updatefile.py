from __future__ import annotations

import json
import os
import tempfile
import unittest

from redmine_sync.updatefile import (Update, UpdateFileError, load_update_file,
                                     parse_update_file)


def doc(*updates, session="2026-01-15"):
    return json.dumps({"session": session, "updates": list(updates)})


class UpdateFileTests(unittest.TestCase):
    def test_parses_a_valid_file(self):
        uf = parse_update_file(doc(
            {"issue": "EX-01.1", "note": "did it", "done_ratio": 50, "status": "In Progress"},
            {"issue": "#102", "note": "noted"}))
        self.assertEqual(uf.session, "2026-01-15")
        self.assertEqual(uf.updates[0], Update("EX-01.1", "did it", 50, "In Progress"))
        self.assertEqual(uf.updates[1], Update("#102", "noted", None, None))

    def test_reads_a_file_with_bom_and_keeps_accents(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "u.json")
            with open(path, "w", encoding="utf-8-sig") as f:
                f.write(doc({"issue": "EX-01.1", "note": "Sessão concluída — ação"}))
            uf = load_update_file(path)
        self.assertEqual(uf.updates[0].note, "Sessão concluída — ação")

    def test_note_is_required_and_non_empty(self):
        for row in ({"issue": "EX-01.1"}, {"issue": "EX-01.1", "note": "   "}):
            with self.assertRaises(UpdateFileError) as cm:
                parse_update_file(doc(row))
            self.assertIn("note", str(cm.exception))

    def test_done_ratio_types_are_rejected(self):
        for value in (True, "90", 90.0, 101, -1, None):
            with self.assertRaises(UpdateFileError, msg=repr(value)) as cm:
                parse_update_file(doc({"issue": "EX-01.1", "note": "n", "done_ratio": value}))
            self.assertIn("done_ratio", str(cm.exception))

    def test_status_must_be_a_non_empty_string(self):
        for value in ("", 3, None):
            with self.assertRaises(UpdateFileError, msg=repr(value)):
                parse_update_file(doc({"issue": "EX-01.1", "note": "n", "status": value}))

    def test_unknown_key_is_rejected(self):
        with self.assertRaises(UpdateFileError) as cm:
            parse_update_file(doc({"issue": "EX-01.1", "note": "n", "done": 50}))
        self.assertIn("done", str(cm.exception))

    def test_issue_must_be_one_token(self):
        for value in ("", "EX 01", 101):
            with self.assertRaises(UpdateFileError, msg=repr(value)):
                parse_update_file(doc({"issue": value, "note": "n"}))

    def test_session_must_be_a_simple_token(self):
        for value in ("", "2026 01 15", "../x", 20260115):
            with self.assertRaises(UpdateFileError, msg=repr(value)):
                parse_update_file(doc({"issue": "EX-01.1", "note": "n"}, session=value))

    def test_updates_must_be_a_non_empty_list(self):
        with self.assertRaises(UpdateFileError):
            parse_update_file(json.dumps({"session": "s1", "updates": []}))
        with self.assertRaises(UpdateFileError):
            parse_update_file(json.dumps({"session": "s1"}))

    def test_every_problem_is_reported_at_once(self):
        with self.assertRaises(UpdateFileError) as cm:
            parse_update_file(doc({"issue": "EX-01.1"}, {"issue": "EX-01.2", "note": "n", "done_ratio": "x"}))
        message = str(cm.exception)
        self.assertIn("update 1", message)
        self.assertIn("update 2", message)

    def test_file_that_is_not_utf8(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "u.json")
            with open(path, "wb") as f:
                f.write('{"session": "s1", "updates": [{"issue": "EX-01.1", "note": "ação"}]}'.encode("latin-1"))
            with self.assertRaises(UpdateFileError) as cm:
                load_update_file(path)
        self.assertIn("UTF-8", str(cm.exception))

    def test_invalid_json(self):
        with self.assertRaises(UpdateFileError) as cm:
            parse_update_file("{nope", source="u.json")
        self.assertIn("u.json", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
