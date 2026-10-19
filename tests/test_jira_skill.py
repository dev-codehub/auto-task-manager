"""The Jira skills are instructions, so their safety rules are pinned by what they say."""
from __future__ import annotations

import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAMES = ("jira-session-close", "jira-backlog")


def path_of(name: str) -> str:
    return os.path.join(ROOT, "skills", name, "SKILL.md")


def text_of(name: str) -> str:
    with open(path_of(name), encoding="utf-8") as f:
        return f.read()


def squash(text: str) -> str:
    """Hard-wrapped lines read as one, so a phrase is pinned however it is wrapped."""
    return re.sub(r"\s+", " ", text)


def step(name: str, n: int) -> str:
    match = re.search(rf"^{n}\. (.*?)(?=^\d+\. |^## |\Z)", text_of(name), re.S | re.M)
    assert match, f"{name}: step {n} not found"
    return squash(match.group(1))


def section(name: str, title: str) -> str:
    match = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", text_of(name), re.S | re.M)
    assert match, f"{name}: section '{title}' not found"
    return squash(match.group(1))


def front_matter_description(name: str) -> str:
    match = re.search(r"^description: (.*)$", text_of(name), re.M)
    assert match, f"{name}: no description"
    return match.group(1)


class BothSkillsTests(unittest.TestCase):
    def test_description_names_jira_and_its_config_file(self):
        for name in NAMES:
            with self.subTest(skill=name):
                description = front_matter_description(name)
                self.assertIn("Jira", description)
                self.assertIn(".jira.json", description)

    def test_front_matter_name_matches_the_directory(self):
        for name in NAMES:
            with self.subTest(skill=name):
                self.assertRegex(text_of(name), rf"(?m)^name: {name}$")

    def test_acts_only_when_jira_json_exists(self):
        for name in NAMES:
            with self.subTest(skill=name):
                before = section(name, "Before you start")
                self.assertIn("`.jira.json` must exist", before)
                self.assertIn("root or a parent directory", before)

    def test_stops_and_asks_which_tracker_when_redmine_json_is_also_present(self):
        for name in NAMES:
            with self.subTest(skill=name):
                before = section(name, "Before you start")
                self.assertIn(".redmine.json", before)
                self.assertIn("stop and ask which tracker", before.lower())
                self.assertIn("never pick one", before.lower())

    def test_never_reads_prints_or_asks_for_the_credentials(self):
        for name in NAMES:
            with self.subTest(skill=name):
                before = section(name, "Before you start")
                self.assertIn("Never read, print, echo or ask for", before)
                self.assertIn("never open", before)
                self.assertIn("~/.config/jira-sync/credentials", before)
                self.assertIn("not filled in", before)
                self.assertIn("plugin README, Jira credentials", before)

    def test_does_not_tell_the_agent_to_open_the_credentials_file(self):
        for name in NAMES:
            with self.subTest(skill=name):
                for line in text_of(name).splitlines():
                    if "credentials" in line and re.search(r"\b(cat|open|read)\b", line):
                        self.assertRegex(line, r"(?i)never|do not|don't",
                                         f"{name}: {line!r} could read as an instruction")

    def test_names_no_cli_other_than_its_own(self):
        self.assertNotIn("redmine-sync", text_of("jira-session-close"))
        self.assertNotIn("redmine-backlog", text_of("jira-backlog"))

    def test_symlinks_point_at_the_skill_directories(self):
        for name in NAMES:
            with self.subTest(skill=name):
                link = os.path.join(ROOT, ".agents", "skills", name)
                self.assertTrue(os.path.islink(link))
                self.assertEqual(os.readlink(link), f"../../skills/{name}")
                self.assertTrue(os.path.isfile(os.path.join(link, "SKILL.md")))


class SessionCloseSkillTests(unittest.TestCase):
    NAME = "jira-session-close"

    def test_status_step_reads_state_and_quotes_keys_as_needed(self):
        status = step(self.NAME, 2)
        self.assertIn("jira-sync status", status)
        self.assertIn("quote", status.lower())

    def test_update_file_format_names_every_row_key(self):
        fields = step(self.NAME, 3)
        for key in ("issue", "note", "status", "story_points", "transition_fields"):
            self.assertIn(key, fields)
        self.assertIn("YYYY-MM-DD-<topic>", fields)

    def test_status_is_the_target_status_name(self):
        fields = step(self.NAME, 3)
        self.assertIn("target status", fields.lower())
        self.assertIn("finds the transition", fields)

    def test_there_is_no_percent_done(self):
        text = squash(text_of(self.NAME))
        self.assertIn("no `% Done`", text)
        self.assertNotIn("done_ratio", text)
        self.assertIn("status plus the comment", text)

    def test_story_points_change_only_when_the_person_gives_a_value(self):
        fields = step(self.NAME, 3)
        self.assertIn("story_points", fields)
        self.assertIn("only when the person gives a value", fields)
        self.assertIn("never inferred", fields)
        self.assertIn("estimate", fields)

    def test_transition_fields_are_asked_for_never_guessed(self):
        fields = step(self.NAME, 3)
        self.assertIn("transition_fields", fields)
        self.assertIn("Ask the person", fields)
        self.assertIn("rather than guessing", fields)
        self.assertIn("missing", fields)
        self.assertIn("options", fields)

    def test_unsupported_field_types_are_left_to_the_person_in_jira(self):
        fields = step(self.NAME, 3)
        self.assertIn("set it in Jira", fields)
        for kind in ("user", "multi-select", "version"):
            self.assertIn(kind, fields)

    def test_dry_run_is_shown_unedited(self):
        dry = step(self.NAME, 4)
        self.assertIn("jira-sync apply <file>", dry)
        self.assertIn("unedited", dry)

    def test_approval_step_forbids_writing_without_a_yes(self):
        self.assertIn("Never run `--write` without this yes", step(self.NAME, 5))

    def test_resuming_after_a_stop_never_writes_an_edited_file_unapproved(self):
        resume = step(self.NAME, 6)
        self.assertIn("jira-sync apply <file> --write", resume)
        self.assertIn("unchanged", resume)
        self.assertIn("dry-run again", resume)
        self.assertIn("ask again", resume)

    def test_resume_after_a_stop_re_runs_the_dry_run_first(self):
        resume = step(self.NAME, 6)
        self.assertIn("only by re-running the dry-run", resume)

    def test_the_update_file_is_committed_only_if_the_person_agrees(self):
        self.assertIn("only if the person agrees", step(self.NAME, 7))


class BacklogSkillTests(unittest.TestCase):
    NAME = "jira-backlog"

    def test_plan_step_is_read_only_and_comes_first(self):
        first = step(self.NAME, 1)
        self.assertIn("jira-backlog plan", first)
        self.assertIn("nothing is created yet", first)

    def test_plan_file_format_is_described(self):
        first = step(self.NAME, 1)
        for key in ("project", "nodes", "relations", "story_points", "priority"):
            self.assertIn(key, first)

    def test_hash_references_name_existing_issues(self):
        first = step(self.NAME, 1)
        self.assertIn("#PROJ-123", first)
        self.assertIn("already exists", first)

    def test_relation_types_exclude_precedes(self):
        first = step(self.NAME, 1)
        self.assertIn("`relates`/`duplicates`/`blocks`", first)
        self.assertIn("no `precedes`", first)

    def test_order_is_validate_then_dry_run_then_ask_then_write(self):
        text = squash(text_of(self.NAME))
        self.assertIn("validate (`plan`)", text)
        self.assertIn("dry-run (`apply`)", text)
        self.assertIn("jira-backlog apply <file>", step(self.NAME, 2))
        self.assertIn("Stop and ask", step(self.NAME, 3))
        self.assertIn("jira-backlog apply <file> --write", step(self.NAME, 4))

    def test_write_requires_explicit_yes(self):
        asking = step(self.NAME, 3)
        self.assertIn("Never run `--write` without this yes", asking)

    def test_descriptions_are_verified_only_as_present(self):
        text = squash(text_of(self.NAME))
        self.assertIn("content not compared", text)

    def test_fix_parents_write_exits_nonzero_when_a_fix_does_not_land(self):
        fixing = section(self.NAME, "Fixing parents")
        self.assertIn("jira-backlog fix-parents <file> --write", fixing)
        self.assertIn("exits 1", fixing)
        self.assertIn("did not land", fixing)
        self.assertIn("permission", fixing)

    def test_update_descriptions_requires_only_and_a_yes(self):
        updating = section(self.NAME, "Updating a description")
        self.assertIn("--only", updating)
        self.assertIn("requires `--only`", updating)
        self.assertIn("explicit yes", updating)
        self.assertIn("jira-sync", updating)

    def test_plan_file_is_committed_only_if_the_person_agrees(self):
        self.assertIn("only if the person agrees", step(self.NAME, 5))


if __name__ == "__main__":
    unittest.main()
