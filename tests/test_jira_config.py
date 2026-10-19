from __future__ import annotations

import json
import os
import tempfile
import unittest

from jira_sync.config import ConfigError, find_config, load_config, load_credentials


class JiraConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, content, mode=None):
        path = os.path.join(self.dir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        if mode is not None:
            os.chmod(path, mode)
        return path

    def config(self, **raw):
        return self.write(".jira.json", json.dumps(raw))

    def test_find_config_walks_up(self):
        path = self.write(".jira.json", "{}")
        nested = os.path.join(self.dir, "a", "b")
        os.makedirs(nested)
        self.assertEqual(find_config(nested), path)

    def test_find_config_missing_names_the_file(self):
        nested = os.path.join(self.dir, "x")
        os.makedirs(nested)
        with self.assertRaises(ConfigError) as cm:
            find_config(nested)
        self.assertIn(".jira.json", str(cm.exception))

    def test_loads_url_project_and_defaults(self):
        path = self.config(url="https://projeto-wit.atlassian.net/", project="WIT")
        c = load_config(path)
        self.assertEqual(c.url, "https://projeto-wit.atlassian.net")
        self.assertEqual(c.project, "WIT")
        self.assertEqual(c.updates_dir, "jira/session-updates")
        self.assertIsNone(c.story_points_field)
        self.assertEqual(c.path, path)

    def test_unknown_key_is_rejected(self):
        path = self.config(url="https://x.atlassian.net", project="WIT", projcet="x")
        with self.assertRaises(ConfigError) as cm:
            load_config(path)
        self.assertIn("projcet", str(cm.exception))

    def test_url_and_project_are_required(self):
        for raw, missing in (({"project": "WIT"}, "url"),
                             ({"url": "https://x.atlassian.net"}, "project")):
            path = self.config(**raw)
            with self.assertRaises(ConfigError) as cm:
                load_config(path)
            self.assertIn(f"'{missing}' is required", str(cm.exception))

    def test_invalid_json_is_reported(self):
        path = self.write(".jira.json", "{not json")
        with self.assertRaises(ConfigError) as cm:
            load_config(path)
        self.assertIn("not valid JSON", str(cm.exception))

    def test_http_url_is_rejected_unless_loopback(self):
        path = self.config(url="http://jira.example.com", project="WIT")
        with self.assertRaises(ConfigError) as cm:
            load_config(path)
        self.assertIn("https", str(cm.exception))
        path = self.config(url="http://127.0.0.1:8080", project="WIT")
        self.assertEqual(load_config(path).url, "http://127.0.0.1:8080")

    def test_unfilled_url_or_project_is_reported_not_filled_in(self):
        for key in ("url", "project"):
            raw = {"url": "https://x.atlassian.net", "project": "WIT"}
            raw[key] = "PREENCHE: o valor"
            path = self.config(**raw)
            with self.assertRaises(ConfigError) as cm:
                load_config(path)
            self.assertIn("not filled in", str(cm.exception), key)
            self.assertIn(f"'{key}'", str(cm.exception), key)

    def test_the_shipped_template_is_reported_not_filled_in(self):
        template = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "jira.example.json")
        with self.assertRaises(ConfigError) as cm:
            load_config(template)
        self.assertIn("'url' is not filled in", str(cm.exception))

    def test_url_without_a_scheme_or_host_says_what_a_jira_url_looks_like(self):
        for bad in ("lj-test-jira.atlassian.net", "ftp://x.atlassian.net", "https://",
                    "https:///rest", "x.atlassian.net/jira"):
            path = self.config(url=bad, project="WIT")
            with self.assertRaises(ConfigError, msg=bad) as cm:
                load_config(path)
            self.assertIn("https://<site>.atlassian.net", str(cm.exception), bad)
            self.assertIn("'url'", str(cm.exception), bad)

    def test_url_on_any_https_host_is_accepted(self):
        path = self.config(url="https://jira.example.com", project="WIT")
        self.assertEqual(load_config(path).url, "https://jira.example.com")

    def test_story_points_field_must_look_like_customfield_digits(self):
        path = self.config(url="https://x.atlassian.net", project="WIT",
                           story_points_field="customfield_10016")
        self.assertEqual(load_config(path).story_points_field, "customfield_10016")
        for bad in ("Story Points", "customfield_", "customfield_abc", 10016, ""):
            path = self.config(url="https://x.atlassian.net", project="WIT",
                               story_points_field=bad)
            with self.assertRaises(ConfigError) as cm:
                load_config(path)
            self.assertIn("story_points_field", str(cm.exception))

    def test_unfilled_story_points_field_is_reported(self):
        path = self.config(url="https://x.atlassian.net", project="WIT",
                           story_points_field="PREENCHE: id do campo, ex. customfield_10016")
        with self.assertRaises(ConfigError) as cm:
            load_config(path)
        self.assertIn("not filled in", str(cm.exception))
        self.assertIn("story_points_field", str(cm.exception))

    def test_credentials_from_environment_win(self):
        creds = load_credentials(
            {"JIRA_EMAIL": " a@b.c ", "JIRA_API_TOKEN": " tok "},
            credentials_path=os.path.join(self.dir, "absent"))
        self.assertEqual(creds, ("a@b.c", "tok"))

    def test_credentials_file_with_two_lines(self):
        path = self.write("cred", "JIRA_EMAIL=a@b.c\nJIRA_API_TOKEN=tok=en\n", 0o600)
        self.assertEqual(load_credentials({}, credentials_path=path), ("a@b.c", "tok=en"))

    def test_credentials_file_with_bom(self):
        path = self.write("cred", "﻿JIRA_EMAIL=a@b.c\nJIRA_API_TOKEN=tok\n", 0o600)
        self.assertEqual(load_credentials({}, credentials_path=path), ("a@b.c", "tok"))

    def test_credentials_file_readable_by_others_is_refused(self):
        path = self.write("cred", "JIRA_EMAIL=a@b.c\nJIRA_API_TOKEN=secret-tok\n", 0o644)
        with self.assertRaises(ConfigError) as cm:
            load_credentials({}, credentials_path=path)
        self.assertIn("chmod 600", str(cm.exception))
        self.assertNotIn("secret-tok", str(cm.exception))

    def test_credentials_file_missing_a_line(self):
        path = self.write("cred", "JIRA_EMAIL=a@b.c\n", 0o600)
        with self.assertRaises(ConfigError) as cm:
            load_credentials({}, credentials_path=path)
        self.assertIn("JIRA_API_TOKEN", str(cm.exception))

    def test_placeholder_credentials_are_reported_not_filled_in(self):
        path = self.write(
            "cred", "JIRA_EMAIL=PREENCHE: zq-mail\nJIRA_API_TOKEN=PREENCHE: zq-token\n", 0o600)
        with self.assertRaises(ConfigError) as cm:
            load_credentials({}, credentials_path=path)
        self.assertIn("not filled in", str(cm.exception))
        self.assertNotIn("zq-", str(cm.exception))

    def test_placeholder_in_environment_is_reported_too(self):
        with self.assertRaises(ConfigError) as cm:
            load_credentials({"JIRA_EMAIL": "a@b.c", "JIRA_API_TOKEN": "PREENCHE: x"},
                             credentials_path=os.path.join(self.dir, "absent"))
        self.assertIn("not filled in", str(cm.exception))

    def test_missing_credentials_message_names_both_ways(self):
        with self.assertRaises(ConfigError) as cm:
            load_credentials({}, credentials_path=os.path.join(self.dir, "absent"))
        message = str(cm.exception)
        self.assertIn("JIRA_EMAIL", message)
        self.assertIn("JIRA_API_TOKEN", message)
        self.assertIn("jira-sync/credentials", message)


if __name__ == "__main__":
    unittest.main()
