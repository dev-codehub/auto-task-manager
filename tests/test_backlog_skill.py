"""The skill is instructions, so its safety rules are pinned by what it says."""
from __future__ import annotations

import os
import re
import unittest

SKILL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "skills", "redmine-backlog", "SKILL.md")


def step(n: int) -> str:
    with open(SKILL, encoding="utf-8") as f:
        text = f.read()
    match = re.search(rf"^{n}\. (.*?)(?=^\d+\. |\Z)", text, re.S | re.M)
    assert match, f"step {n} not found"
    return match.group(1)


class BacklogSkillTests(unittest.TestCase):
    def test_never_reads_or_prints_the_credentials_file(self):
        with open(SKILL, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("Never read, print", text)

    def test_plan_step_is_read_only_and_comes_first(self):
        self.assertIn("redmine-backlog plan", step(1))

    def test_write_requires_explicit_yes(self):
        found = False
        for n in range(1, 10):
            try:
                s = step(n)
            except AssertionError:
                break
            if "--write" in s and "yes" in s.lower():
                found = True
        self.assertTrue(found, "no step ties --write to an explicit yes")

    def test_update_descriptions_only_flag_is_required(self):
        with open(SKILL, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("--only", text)


if __name__ == "__main__":
    unittest.main()
