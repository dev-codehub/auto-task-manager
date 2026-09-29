from __future__ import annotations

import io
import json
import os
import tempfile
import unittest

from redmine_sync import backlog_cli
from tests.fake_redmine import demo_fake


class BacklogCliTests(unittest.TestCase):
    def setUp(self):
        self.fake = demo_fake().start()
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        with open(os.path.join(self.dir, ".redmine.json"), "w", encoding="utf-8") as f:
            json.dump({"url": self.fake.url, "project": "demo"}, f)

    def tearDown(self):
        self.fake.stop()
        self.tmp.cleanup()

    def _write_plan(self, doc, name="plan.json"):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        return path

    def _run(self, args, key="test-key"):
        out, err = io.StringIO(), io.StringIO()
        code = backlog_cli.main(args, environ={"REDMINE_API_KEY": key},
                                cwd=self.dir, stdout=out, stderr=err)
        return code, out.getvalue(), err.getvalue()

    def _doc(self):
        return {
            "project": "demo",
            "nodes": [
                {"id": "US-90", "subject": "US-90 A new story", "description": "d",
                 "tracker": "User Story", "priority": "Normal", "parent": None},
            ],
            "relations": [],
        }

    def test_id_only_config_is_refused(self):
        with open(os.path.join(self.dir, ".redmine.json"), "w", encoding="utf-8") as f:
            json.dump({"url": self.fake.url, "project": "demo", "issue_key": "id_only"}, f)
        path = self._write_plan(self._doc())
        code, out, err = self._run(["plan", path])
        self.assertEqual(code, 1)
        self.assertIn("id_only", err)

    def test_plan_is_read_only(self):
        path = self._write_plan(self._doc())
        code, out, _ = self._run(["plan", path])
        self.assertEqual(code, 0)
        self.assertIn("US-90", out)
        self.assertEqual(len(self.fake.issues), 4)

    def test_apply_without_write_creates_nothing(self):
        path = self._write_plan(self._doc())
        code, out, _ = self._run(["apply", path])
        self.assertEqual(code, 0)
        self.assertIn("would create", out)
        self.assertEqual(len(self.fake.issues), 4)

    def test_apply_with_write_creates(self):
        path = self._write_plan(self._doc())
        code, out, _ = self._run(["apply", path, "--write"])
        self.assertEqual(code, 0)
        self.assertIn("created", out)
        self.assertEqual(len(self.fake.issues), 5)

    def test_apply_with_file_errors_exits_nonzero_and_writes_nothing(self):
        d = self._doc()
        d["nodes"][0]["tracker"] = "Epic"
        path = self._write_plan(d)
        code, out, _ = self._run(["apply", path, "--write"])
        self.assertEqual(code, 1)
        self.assertIn("Epic", out)
        self.assertEqual(len(self.fake.issues), 4)

    def test_fix_parents_report_only_by_default(self):
        d = self._doc()
        d["nodes"][0]["id"] = "EX-01.2"
        d["nodes"][0]["subject"] = "EX-01.2 Test the thing"
        d["nodes"][0]["parent"] = "#101"
        path = self._write_plan(d)
        code, out, _ = self._run(["fix-parents", path])
        self.assertEqual(code, 0)
        self.assertIn("wrong: 1", out)
        self.assertIsNone(self.fake.issues[102].get("parent_id"))

    def test_update_descriptions_requires_only(self):
        path = self._write_plan(self._doc())
        code, out, err = self._run(["update-descriptions", path, "--write"])
        self.assertEqual(code, 1)
        self.assertIn("--only", err)

    def test_update_descriptions_empty_only_is_refused_not_treated_as_all(self):
        d = self._doc()
        d["nodes"][0]["id"] = "EX-01.1"
        d["nodes"][0]["subject"] = "EX-01.1 Build the thing"
        d["nodes"][0]["description"] = "overwritten"
        path = self._write_plan(d)
        code, out, err = self._run(["update-descriptions", path, "--only=,", "--write"])
        self.assertEqual(code, 1)
        self.assertIn("--only", err)
        self.assertNotEqual(self.fake.issues[101].get("description"), "overwritten")

    def test_update_descriptions_unknown_only_id_is_an_error(self):
        d = self._doc()
        d["nodes"][0]["id"] = "EX-01.1"
        d["nodes"][0]["subject"] = "EX-01.1 Build the thing"
        path = self._write_plan(d)
        code, out, _ = self._run(["update-descriptions", path, "--only=NO-SUCH-ID", "--write"])
        self.assertEqual(code, 1)
        self.assertIn("NO-SUCH-ID", out)

    def test_update_descriptions_with_only_and_write(self):
        d = self._doc()
        d["nodes"][0]["id"] = "EX-01.1"
        d["nodes"][0]["subject"] = "EX-01.1 Build the thing"
        d["nodes"][0]["description"] = "brand new text"
        path = self._write_plan(d)
        code, out, _ = self._run(["update-descriptions", path, "--only=EX-01.1", "--write"])
        self.assertEqual(code, 0)
        self.assertIn("updated", out)


if __name__ == "__main__":
    unittest.main()
