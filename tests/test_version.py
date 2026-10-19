from __future__ import annotations

import json
import os
import unittest

import redmine_sync

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _version_in(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return json.load(f)


class VersionTests(unittest.TestCase):
    def test_cli_version_matches_the_plugin_version(self):
        plugin = _version_in(".claude-plugin", "plugin.json")["version"]
        self.assertEqual(redmine_sync.__version__, plugin)

    def test_marketplace_version_matches_the_plugin_version(self):
        plugin = _version_in(".claude-plugin", "plugin.json")["version"]
        entries = _version_in(".claude-plugin", "marketplace.json")["plugins"]
        self.assertEqual([e["version"] for e in entries], [plugin])


if __name__ == "__main__":
    unittest.main()
