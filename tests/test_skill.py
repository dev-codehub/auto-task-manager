"""The skill is instructions, so its safety rules are pinned by what it says."""
from __future__ import annotations

import os
import re
import unittest

SKILL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "skills", "redmine-session-close", "SKILL.md")


def step(n: int) -> str:
    with open(SKILL, encoding="utf-8") as f:
        text = f.read()
    match = re.search(rf"^{n}\. (.*?)(?=^\d+\. |\Z)", text, re.S | re.M)
    assert match, f"step {n} not found"
    return match.group(1)


class SkillTests(unittest.TestCase):
    def test_resuming_after_a_stop_never_writes_an_edited_file_unapproved(self):
        resume = step(6)
        self.assertIn("unchanged", resume)
        self.assertIn("dry-run again", resume)
        self.assertIn("ask again", resume)

    def test_the_update_file_is_committed_only_if_the_person_agrees(self):
        self.assertIn("only if the person agrees", step(7))

    def test_status_step_says_to_quote_number_keys(self):
        self.assertIn("'#", step(2))
        self.assertIn("comment", step(2))

    def test_approval_step_forbids_writing_without_a_yes(self):
        self.assertIn("Never run `--write` without this yes", step(5))


if __name__ == "__main__":
    unittest.main()
