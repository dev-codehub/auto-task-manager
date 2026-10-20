from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

import jira_sync
from jira_sync import cli
from tests.fake_jira import demo_fake

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin", "jira-sync")
SESSION = "2026-10-19-jira"


class JiraCliTests(unittest.TestCase):
    TOKEN = "SECRET-TOKEN-do-not-print-7c1e"

    def setUp(self):
        self.fake = demo_fake(token=self.TOKEN).start()
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.write_config({"url": self.fake.url, "project": "SCRUM"})

    def tearDown(self):
        self.fake.stop()
        self.tmp.cleanup()

    def write_config(self, data):
        with open(os.path.join(self.dir, ".jira.json"), "w", encoding="utf-8") as f:
            json.dump(data, f)

    def write_updates(self, *updates, session=SESSION):
        path = os.path.join(self.dir, f"{session}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"session": session, "updates": list(updates)}, f, ensure_ascii=False)
        return path

    def run_cli(self, *argv, environ=None, cwd=None):
        out, err = io.StringIO(), io.StringIO()
        env = environ if environ is not None else {"JIRA_EMAIL": self.fake.email,
                                                   "JIRA_API_TOKEN": self.TOKEN}
        code = cli.main(list(argv), environ=env, cwd=cwd or self.dir, stdout=out, stderr=err,
                        credentials_path=os.path.join(self.dir, "no-credentials"))
        return code, out.getvalue(), err.getvalue()

    def test_dry_run_writes_nothing(self):
        path = self.write_updates({"issue": "SCRUM-1", "note": "n", "status": "In Progress",
                                   "story_points": 3})
        code, out, _ = self.run_cli("apply", path)
        self.assertEqual(code, 0, out)
        self.assertIn("status  To Do -> In Progress  (transition 'Start')", out)
        self.assertIn("dry run - nothing written", out)
        self.assertEqual(self.fake.writes, [])

    def test_apply_write_exits_0(self):
        path = self.write_updates({"issue": "SCRUM-1", "note": "n", "status": "In Progress"})
        code, out, _ = self.run_cli("apply", path, "--write")
        self.assertEqual(code, 0, out)
        self.assertIn("done: 1 written", out)
        self.assertEqual(self.fake.issues["SCRUM-1"]["fields"]["status"]["name"], "In Progress")

    def test_relative_update_path_is_resolved_against_cwd(self):
        self.write_updates({"issue": "SCRUM-1", "note": "n"})
        code, _, err = self.run_cli("apply", f"{SESSION}.json")
        self.assertEqual(code, 0, err)

    def test_apply_with_plan_errors_exits_1_and_writes_nothing(self):
        path = self.write_updates({"issue": "SCRUM-1", "note": "n", "status": "Nowhere"})
        code, out, _ = self.run_cli("apply", path, "--write")
        self.assertEqual(code, 1)
        self.assertIn("nothing will be written", out)
        self.assertEqual(self.fake.writes, [])

    def test_stopped_write_exits_1(self):
        self.fake.forbidden.add("SCRUM-1")
        path = self.write_updates({"issue": "SCRUM-1", "note": "n"})
        code, out, _ = self.run_cli("apply", path, "--write")
        self.assertEqual(code, 1)
        self.assertIn("re-run", out)

    def test_status_prints_status_points_and_available_transitions(self):
        self.fake.issues["SCRUM-2"]["fields"]["customfield_10016"] = 5
        self.fake.issues["SCRUM-2"]["fields"]["status"] = {"name": "In Progress"}
        code, out, _ = self.run_cli("status", "SCRUM-1", "SCRUM-2")
        self.assertEqual(code, 0, out)
        first, second = out.split("SCRUM-2", 1)
        self.assertIn("SCRUM-1  Epic one", first)
        self.assertIn("status        To Do", first)
        self.assertIn("story points  -", first)
        self.assertIn("transitions   Start -> In Progress", first)
        self.assertIn("status        In Progress", second)
        self.assertIn("story points  5", second)
        self.assertIn("transitions   Finish -> Done, Back -> To Do", second)
        self.assertEqual(self.fake.writes, [])

    def test_status_of_unknown_issue_exits_1(self):
        code, out, _ = self.run_cli("status", "SCRUM-77")
        self.assertEqual(code, 1)
        self.assertIn("SCRUM-77: does not exist or is not visible to you", out)

    def test_unfilled_credentials_exit_1_with_not_filled_in(self):
        code, _, err = self.run_cli("status", "SCRUM-1", environ={
            "JIRA_EMAIL": "PREENCHE: your email", "JIRA_API_TOKEN": "PREENCHE: your token"})
        self.assertEqual(code, 1)
        self.assertIn("not filled in", err)
        self.assertEqual(self.fake.hits, 0)

    def test_wrong_token(self):
        code, _, err = self.run_cli("status", "SCRUM-1", environ={
            "JIRA_EMAIL": self.fake.email, "JIRA_API_TOKEN": "wrong"})
        self.assertEqual(code, 1)
        self.assertIn("API token was rejected", err)

    def test_unknown_project(self):
        self.write_config({"url": self.fake.url, "project": "NOPE"})
        code, _, err = self.run_cli("status", "SCRUM-1")
        self.assertEqual(code, 1)
        self.assertIn("'NOPE'", err)
        self.assertIn("not visible", err)

    def test_missing_config(self):
        with tempfile.TemporaryDirectory() as empty:
            code, _, err = self.run_cli("status", "SCRUM-1", cwd=empty)
        self.assertEqual(code, 1)
        self.assertIn(".jira.json", err)

    def test_explicit_config_path(self):
        with tempfile.TemporaryDirectory() as empty:
            code, out, err = self.run_cli("--config", os.path.join(self.dir, ".jira.json"),
                                          "status", "SCRUM-1", cwd=empty)
        self.assertEqual(code, 0, err)
        self.assertIn("SCRUM-1", out)

    def test_invalid_update_file(self):
        path = os.path.join(self.dir, "bad.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{nope")
        code, _, err = self.run_cli("apply", path)
        self.assertEqual(code, 1)
        self.assertIn("not valid JSON", err)

    def test_the_token_is_never_printed(self):
        good = self.write_updates({"issue": "SCRUM-1", "note": "n", "status": "In Progress"})
        bad = self.write_updates({"issue": "SCRUM-2", "note": "n", "status": "Nowhere"},
                                 session="2026-10-19-bad")
        for argv in (("status", "SCRUM-1"), ("apply", good), ("apply", bad, "--write"),
                     ("apply", good, "--write")):
            _, out, err = self.run_cli(*argv)
            self.assertNotIn(self.TOKEN, out + err, argv)

    def test_version_flag(self):
        result = subprocess.run([sys.executable, BIN, "--version"], capture_output=True,
                                text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), f"jira-sync {jira_sync.__version__}")

    def test_bin_entry_point_is_executable_and_runs(self):
        self.assertTrue(os.access(BIN, os.X_OK))
        result = subprocess.run([BIN, "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("jira-sync", result.stdout)


if __name__ == "__main__":
    unittest.main()
