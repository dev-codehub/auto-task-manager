from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

from redmine_sync import cli
from tests.fake_redmine import demo_fake

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin", "redmine-sync")


class CliTests(unittest.TestCase):
    KEY = "SECRET-KEY-do-not-print-4f2a"

    def setUp(self):
        self.fake = demo_fake(key=self.KEY).start()
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.write_config({"url": self.fake.url, "project": "demo"})

    def tearDown(self):
        self.fake.stop()
        self.tmp.cleanup()

    def write_config(self, data):
        with open(os.path.join(self.dir, ".redmine.json"), "w", encoding="utf-8") as f:
            json.dump(data, f)

    def write_updates(self, *updates, session="s1"):
        path = os.path.join(self.dir, f"{session}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"session": session, "updates": list(updates)}, f, ensure_ascii=False)
        return path

    def run_cli(self, *argv, key=None, cwd=None):
        out, err = io.StringIO(), io.StringIO()
        code = cli.main(list(argv), environ={"REDMINE_API_KEY": key or self.KEY},
                        cwd=cwd or self.dir, stdout=out, stderr=err,
                        credentials_path=os.path.join(self.dir, "no-credentials"))
        return code, out.getvalue(), err.getvalue()

    def test_status_prints_current_state(self):
        self.fake.issues[101]["journals"].append({"id": 1, "notes": "earlier work\nmore"})
        code, out, _ = self.run_cli("status", "EX-01.1", "#102")
        self.assertEqual(code, 0)
        self.assertIn("#101", out)
        self.assertIn("New", out)
        self.assertIn("earlier work", out)
        self.assertIn("#102", out)

    def test_status_of_unknown_issue_exits_1(self):
        code, out, _ = self.run_cli("status", "EX-77")
        self.assertEqual(code, 1)
        self.assertIn("EX-77", out)

    def test_apply_is_a_dry_run_by_default(self):
        path = self.write_updates({"issue": "EX-01.1", "note": "n", "status": "In Progress"})
        code, out, _ = self.run_cli("apply", path)
        self.assertEqual(code, 0)
        self.assertIn("dry run", out)
        self.assertEqual(self.fake.puts, [])

    def test_apply_write(self):
        path = self.write_updates({"issue": "EX-01.1", "note": "n", "status": "In Progress"})
        code, out, _ = self.run_cli("apply", path, "--write")
        self.assertEqual(code, 0, out)
        self.assertIn("done: 1 written", out)
        self.assertEqual(self.fake.issues[101]["status_id"], 2)

    def test_relative_update_path_is_resolved_against_cwd(self):
        self.write_updates({"issue": "EX-01.1", "note": "n"})
        code, _, _ = self.run_cli("apply", "s1.json")
        self.assertEqual(code, 0)

    def test_apply_with_errors_exits_1_and_writes_nothing(self):
        path = self.write_updates({"issue": "EX-01.1", "note": "n", "status": "Doing"})
        code, out, _ = self.run_cli("apply", path, "--write")
        self.assertEqual(code, 1)
        self.assertIn("nothing will be written", out)
        self.assertEqual(self.fake.puts, [])

    def test_stopped_write_exits_1(self):
        self.fake.fail_puts_after = 0
        path = self.write_updates({"issue": "EX-01.1", "note": "n"})
        code, out, _ = self.run_cli("apply", path, "--write")
        self.assertEqual(code, 1)
        self.assertIn("re-run", out)

    def test_wrong_key(self):
        code, _, err = self.run_cli("status", "EX-01.1", key="wrong")
        self.assertEqual(code, 1)
        self.assertIn("API key was rejected", err)

    def test_unknown_project(self):
        self.write_config({"url": self.fake.url, "project": "nope"})
        code, _, err = self.run_cli("status", "EX-01.1")
        self.assertEqual(code, 1)
        self.assertIn("'nope'", err)
        self.assertIn("not visible", err)

    def test_plain_http_url_warns_on_stderr(self):
        self.write_config({"url": "http://redmine.invalid", "project": "demo"})
        _, _, err = self.run_cli("status", "EX-01.1")
        self.assertIn("cleartext", err)

    def test_loopback_http_does_not_warn(self):
        _, _, err = self.run_cli("status", "EX-01.1")
        self.assertNotIn("cleartext", err)

    def test_project_is_read_once_per_run(self):
        path = self.write_updates({"issue": "EX-01.1", "note": "n"}, {"issue": "EX-01.2", "note": "m"})
        self.run_cli("apply", path)
        self.assertEqual(self.fake.requests.count("GET /projects/demo.json"), 1)

    def test_missing_config(self):
        with tempfile.TemporaryDirectory() as empty:
            code, _, err = self.run_cli("status", "EX-01.1", cwd=empty)
        self.assertEqual(code, 1)
        self.assertIn(".redmine.json", err)

    def test_invalid_update_file(self):
        path = os.path.join(self.dir, "bad.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{nope")
        code, _, err = self.run_cli("apply", path)
        self.assertEqual(code, 1)
        self.assertIn("not valid JSON", err)

    def test_the_key_is_never_printed(self):
        good = self.write_updates({"issue": "EX-01.1", "note": "n", "status": "In Progress"})
        bad = self.write_updates({"issue": "EX-01.1", "note": "n", "status": "Doing"}, session="s2")
        runs = [("status", "EX-01.1"), ("apply", good), ("apply", bad, "--write"),
                ("apply", good, "--write")]
        for argv in runs:
            _, out, err = self.run_cli(*argv)
            self.assertNotIn(self.KEY, out + err, argv)
        self.fake.fail_puts_after = 0
        other = self.write_updates({"issue": "EX-01.2", "note": "n"}, session="s3")
        _, out, err = self.run_cli("apply", other, "--write")
        self.assertNotIn(self.KEY, out + err)

    def test_bin_entry_point_runs(self):
        result = subprocess.run([sys.executable, BIN, "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("redmine-sync", result.stdout)


if __name__ == "__main__":
    unittest.main()
