from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

import jira_sync
from jira_sync import backlog_cli
from tests.fake_jira import demo_fake

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin", "jira-backlog")


class JiraBacklogCliTests(unittest.TestCase):
    TOKEN = "SECRET-TOKEN-do-not-print-41b9"

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

    def write_plan(self, d, name="plan.json"):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f)
        return path

    def doc(self, **overrides):
        d = {"project": "SCRUM",
             "nodes": [{"id": "EP-01", "subject": "EP-01 A new epic", "description": "d",
                        "type": "Epic", "parent": None},
                       {"id": "ST-01", "subject": "ST-01 A story", "description": "d",
                        "type": "Story", "parent": "EP-01"}],
             "relations": [{"type": "blocks", "from": "ST-01", "to": "#SCRUM-3"}]}
        d.update(overrides)
        return d

    def run_cli(self, *argv, environ=None):
        out, err = io.StringIO(), io.StringIO()
        env = environ if environ is not None else {"JIRA_EMAIL": self.fake.email,
                                                   "JIRA_API_TOKEN": self.TOKEN}
        code = backlog_cli.main(list(argv), environ=env, cwd=self.dir, stdout=out, stderr=err,
                                credentials_path=os.path.join(self.dir, "no-credentials"))
        return code, out.getvalue(), err.getvalue()

    def test_plan_is_read_only_and_exits_0(self):
        code, out, err = self.run_cli("plan", self.write_plan(self.doc()))
        self.assertEqual(code, 0, out + err)
        self.assertIn("EP-01", out)
        self.assertIn("ST-01 blocks #SCRUM-3", out)
        self.assertEqual(self.fake.writes, [])

    def test_plan_exit_code_is_1_when_it_has_problems(self):
        d = self.doc()
        d["nodes"][1]["type"] = "Feature"
        code, out, _ = self.run_cli("plan", self.write_plan(d))
        self.assertEqual(code, 1)
        self.assertIn("'Feature'", out)
        self.assertEqual(self.fake.writes, [])

    def test_dry_run_creates_nothing(self):
        code, out, err = self.run_cli("apply", self.write_plan(self.doc()))
        self.assertEqual(code, 0, out + err)
        self.assertIn("would create", out)
        self.assertIn("dry run - nothing written", out)
        self.assertEqual(self.fake.writes, [])

    def test_apply_write_creates_and_exits_0_with_a_path_relative_to_cwd(self):
        self.write_plan(self.doc())
        code, out, err = self.run_cli("apply", "plan.json", "--write")
        self.assertEqual(code, 0, out + err)
        self.assertIn("done: 2 created, 0 skipped", out)
        self.assertEqual(self.fake.issues["SCRUM-5"]["fields"]["parent"]["key"], "SCRUM-4")

    def test_apply_with_plan_problems_writes_nothing(self):
        d = self.doc()
        d["nodes"][0]["type"] = "Feature"
        code, _, _ = self.run_cli("apply", self.write_plan(d), "--write")
        self.assertEqual(code, 1)
        self.assertEqual(self.fake.writes, [])

    def test_stopped_write_exits_1(self):
        self.fake.ignored_fields = {"description"}
        code, out, _ = self.run_cli("apply", self.write_plan(self.doc()), "--write")
        self.assertEqual(code, 1)
        self.assertIn("re-run", out)

    def test_project_mismatch_between_plan_and_config_exits_1(self):
        code, _, err = self.run_cli("plan", self.write_plan(self.doc(project="OTHER")))
        self.assertEqual(code, 1)
        self.assertIn("'OTHER'", err)
        self.assertIn("'SCRUM'", err)
        self.assertEqual(self.fake.hits, 0)

    def test_config_story_points_field_is_used(self):
        self.write_config({"url": self.fake.url, "project": "SCRUM",
                           "story_points_field": "customfield_10099"})
        self.fake.create_fields["10002"].append(
            {"fieldId": "customfield_10099", "key": "customfield_10099", "name": "Points",
             "required": False, "operations": ["set"], "hasDefaultValue": False})
        d = self.doc()
        d["nodes"][1]["story_points"] = 2
        code, out, err = self.run_cli("plan", self.write_plan(d))
        self.assertEqual(code, 0, out + err)
        self.assertNotIn("GET /rest/api/3/field", self.fake.requests)

    def test_fix_parents_reports_only_by_default(self):
        self.fake.add_issue("EX-01 Epic", type_name="Epic")    # SCRUM-4
        self.fake.add_issue("EX-02 Story", type_name="Story")  # SCRUM-5
        d = self.doc(nodes=[
            {"id": "EX-01", "subject": "EX-01 Epic", "description": "", "type": "Epic",
             "parent": None},
            {"id": "EX-02", "subject": "EX-02 Story", "description": "", "type": "Story",
             "parent": "EX-01"}], relations=[])
        path = self.write_plan(d)
        code, out, _ = self.run_cli("fix-parents", path)
        self.assertEqual(code, 0)
        self.assertIn("wrong: 1", out)
        self.assertIn("--write", out)
        self.assertEqual(self.fake.writes, [])
        self.fake.ignored_fields = {"parent"}
        code, out, _ = self.run_cli("fix-parents", path, "--write")
        self.assertEqual(code, 1, out)
        self.assertIn("did not land", out)
        self.fake.ignored_fields = set()
        code, out, _ = self.run_cli("fix-parents", path, "--write")
        self.assertEqual(code, 0, out)
        self.assertIn("(fixed)", out)

    def test_update_descriptions_write_requires_only(self):
        for argv in (("--write",), ("--only=,", "--write")):
            code, _, err = self.run_cli("update-descriptions", self.write_plan(self.doc()),
                                        *argv)
            self.assertEqual(code, 1, argv)
            self.assertIn("--only", err)
        self.assertEqual(self.fake.writes, [])

    def test_update_descriptions_with_only_and_write(self):
        self.fake.add_issue("EP-01 Existing epic", type_name="Epic")  # SCRUM-4
        code, out, err = self.run_cli("update-descriptions", self.write_plan(self.doc()),
                                      "--only=EP-01", "--write")
        self.assertEqual(code, 0, out + err)
        self.assertIn("updated", out)
        self.assertIn("content not compared", out)

    def test_update_descriptions_write_for_an_only_id_with_no_issue_exits_1(self):
        code, out, err = self.run_cli("update-descriptions", self.write_plan(self.doc()),
                                      "--only=EP-01", "--write")
        self.assertEqual(code, 1, out + err)
        self.assertIn("EP-01", out)
        self.assertEqual(self.fake.writes, [])

    def test_unfilled_credentials_exit_1_with_not_filled_in(self):
        code, _, err = self.run_cli("plan", self.write_plan(self.doc()), environ={
            "JIRA_EMAIL": "PREENCHE: your email", "JIRA_API_TOKEN": "PREENCHE: your token"})
        self.assertEqual(code, 1)
        self.assertIn("not filled in", err)
        self.assertEqual(self.fake.hits, 0)

    def test_wrong_token_is_reported_before_anything_else_is_asked(self):
        # Jira answers 404 on the project to credentials it does not know, so
        # the identity check has to come first or the person is told the
        # project is missing.
        for command in ("plan", "apply", "fix-parents", "update-descriptions"):
            with self.subTest(command=command):
                del self.fake.requests[:]
                code, _, err = self.run_cli(command, self.write_plan(self.doc()), environ={
                    "JIRA_EMAIL": self.fake.email, "JIRA_API_TOKEN": "wrong"})
                self.assertEqual(code, 1)
                self.assertIn("API token was rejected", err)
                self.assertNotIn("does not exist or is not visible", err)
                self.assertEqual(self.fake.requests, ["GET /rest/api/3/myself"])

    def test_wrong_email_is_reported_the_same_way(self):
        code, _, err = self.run_cli("plan", self.write_plan(self.doc()), environ={
            "JIRA_EMAIL": "someone-else@example.com", "JIRA_API_TOKEN": self.TOKEN})
        self.assertEqual(code, 1)
        self.assertIn("API token was rejected", err)
        self.assertNotIn("does not exist or is not visible", err)
        self.assertEqual(self.fake.requests, ["GET /rest/api/3/myself"])

    def test_unknown_config_project_exits_1(self):
        self.write_config({"url": self.fake.url, "project": "NOPE"})
        code, _, err = self.run_cli("plan", self.write_plan(self.doc(project="NOPE")))
        self.assertEqual(code, 1)
        self.assertIn("'NOPE'", err)
        self.assertIn("does not exist or is not visible to you", err)

    def test_invalid_plan_file_exits_1(self):
        path = os.path.join(self.dir, "bad.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{nope")
        code, _, err = self.run_cli("plan", path)
        self.assertEqual(code, 1)
        self.assertIn("not valid JSON", err)

    def test_the_token_is_never_printed(self):
        good = self.write_plan(self.doc())
        for argv in (("plan", good), ("apply", good), ("apply", good, "--write"),
                     ("fix-parents", good), ("update-descriptions", good)):
            _, out, err = self.run_cli(*argv)
            self.assertNotIn(self.TOKEN, out + err, argv)

    def test_version_flag(self):
        result = subprocess.run([sys.executable, BIN, "--version"], capture_output=True,
                                text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), f"jira-backlog {jira_sync.__version__}")

    def test_bin_entry_point_is_executable_and_runs(self):
        self.assertTrue(os.access(BIN, os.X_OK))
        result = subprocess.run([BIN, "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("jira-backlog", result.stdout)


if __name__ == "__main__":
    unittest.main()
