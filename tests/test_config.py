from __future__ import annotations

import json
import os
import tempfile
import unittest

from redmine_sync.config import (Config, ConfigError, find_config, insecure_url_warning,
                                 load_api_key, load_config)


class ConfigTests(unittest.TestCase):
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

    def test_find_config_walks_up(self):
        path = self.write(".redmine.json", "{}")
        nested = os.path.join(self.dir, "a", "b")
        os.makedirs(nested)
        self.assertEqual(find_config(nested), path)

    def test_find_config_missing(self):
        nested = os.path.join(self.dir, "x")
        os.makedirs(nested)
        with self.assertRaises(ConfigError) as cm:
            find_config(nested)
        self.assertIn(".redmine.json", str(cm.exception))

    def test_load_config_defaults(self):
        path = self.write(".redmine.json", json.dumps(
            {"url": "https://redmine.example.org/", "project": "demo"}))
        c = load_config(path)
        self.assertEqual(c.url, "https://redmine.example.org")
        self.assertEqual(c.project, "demo")
        self.assertEqual(c.text_format, "textile")
        self.assertEqual(c.issue_key, "subject_prefix")
        self.assertEqual(c.updates_dir, "redmine/session-updates")
        self.assertEqual(c.path, path)

    def test_load_config_requires_url_and_project(self):
        path = self.write(".redmine.json", json.dumps({"url": "https://redmine.example.org"}))
        with self.assertRaises(ConfigError) as cm:
            load_config(path)
        self.assertIn("'project' is required", str(cm.exception))

    def test_load_config_rejects_unknown_key(self):
        path = self.write(".redmine.json", json.dumps(
            {"url": "https://redmine.example.org", "project": "demo", "projcet": "x"}))
        with self.assertRaises(ConfigError) as cm:
            load_config(path)
        self.assertIn("projcet", str(cm.exception))

    def test_load_config_rejects_bad_choices(self):
        for key, value in (("text_format", "html"), ("issue_key", "title")):
            path = self.write(".redmine.json", json.dumps(
                {"url": "https://redmine.example.org", "project": "demo", key: value}))
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_required_fields_on_close_defaults_to_empty(self):
        path = self.write(".redmine.json", json.dumps(
            {"url": "https://redmine.example.org", "project": "demo"}))
        self.assertEqual(load_config(path).required_fields_on_close, ())

    def test_required_fields_on_close_parses(self):
        path = self.write(".redmine.json", json.dumps({
            "url": "https://redmine.example.org", "project": "demo",
            "required_fields_on_close": [
                {"id": 1, "key": "reviewed", "name": "Reviewed", "values": ["Yes", "No"]},
            ],
        }))
        fields = load_config(path).required_fields_on_close
        self.assertEqual(len(fields), 1)
        self.assertEqual(fields[0].id, 1)
        self.assertEqual(fields[0].key, "reviewed")
        self.assertEqual(fields[0].name, "Reviewed")
        self.assertEqual(fields[0].values, ("Yes", "No"))

    def test_required_fields_on_close_rejects_duplicate_key(self):
        path = self.write(".redmine.json", json.dumps({
            "url": "https://redmine.example.org", "project": "demo",
            "required_fields_on_close": [
                {"id": 1, "key": "reviewed", "name": "Reviewed", "values": ["Yes"]},
                {"id": 2, "key": "reviewed", "name": "Reviewed Again", "values": ["Yes"]},
            ],
        }))
        with self.assertRaises(ConfigError) as cm:
            load_config(path)
        self.assertIn("duplicate key", str(cm.exception))

    def test_required_fields_on_close_rejects_bad_shape(self):
        for bad in (
            [{"key": "reviewed", "name": "Reviewed", "values": ["Yes"]}],  # missing id
            [{"id": 1, "name": "Reviewed", "values": ["Yes"]}],  # missing key
            [{"id": 1, "key": "reviewed", "values": ["Yes"]}],  # missing name
            [{"id": 1, "key": "reviewed", "name": "Reviewed", "values": []}],  # empty values
            [{"id": "1", "key": "reviewed", "name": "Reviewed", "values": ["Yes"]}],  # id not int
            "not a list",
        ):
            path = self.write(".redmine.json", json.dumps({
                "url": "https://redmine.example.org", "project": "demo",
                "required_fields_on_close": bad,
            }))
            with self.assertRaises(ConfigError) as cm:
                load_config(path)
            self.assertIn("required_fields_on_close", str(cm.exception))
            self.assertNotIn("unknown key", str(cm.exception))

    def test_load_config_rejects_invalid_json(self):
        path = self.write(".redmine.json", "{not json")
        with self.assertRaises(ConfigError) as cm:
            load_config(path)
        self.assertIn("not valid JSON", str(cm.exception))

    def test_plain_http_to_a_remote_host_is_flagged(self):
        warning = insecure_url_warning(Config(url="http://redmine.example.org", project="p"))
        self.assertIn("cleartext", warning)

    def test_https_and_loopback_are_not_flagged(self):
        for url in ("https://redmine.example.org", "http://127.0.0.1:8080", "http://localhost"):
            self.assertIsNone(insecure_url_warning(Config(url=url, project="p")), url)

    def test_key_from_environment_wins(self):
        key = load_api_key({"REDMINE_API_KEY": " k1 "},
                           credentials_path=os.path.join(self.dir, "absent"))
        self.assertEqual(key, "k1")

    def test_key_from_credentials_file(self):
        path = self.write("cred", "k2\n", 0o600)
        self.assertEqual(load_api_key({}, credentials_path=path), "k2")

    def test_key_from_credentials_file_with_bom(self):
        path = self.write("cred", "﻿k2\n", 0o600)
        self.assertEqual(load_api_key({}, credentials_path=path), "k2")

    def test_credentials_file_with_open_permissions_is_refused(self):
        path = self.write("cred", "k3-secret\n", 0o644)
        with self.assertRaises(ConfigError) as cm:
            load_api_key({}, credentials_path=path)
        self.assertIn("chmod 600", str(cm.exception))
        self.assertNotIn("k3-secret", str(cm.exception))

    def test_empty_credentials_file(self):
        path = self.write("cred", "\n", 0o600)
        with self.assertRaises(ConfigError):
            load_api_key({}, credentials_path=path)

    def test_no_key_anywhere(self):
        with self.assertRaises(ConfigError) as cm:
            load_api_key({}, credentials_path=os.path.join(self.dir, "absent"))
        self.assertIn("REDMINE_API_KEY", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
