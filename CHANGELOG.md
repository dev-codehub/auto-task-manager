# Changelog

## Unreleased

### Fixed
- A wrong email or token is now reported as such; before, `jira-sync` and
  `jira-backlog` said the project did not exist, because Jira answers 404 to
  unrecognised credentials on everything except `/myself`.

## 0.4.0

Jira Cloud support, next to Redmine, in the same plugin.

### Added
- Skills `jira-session-close` and `jira-backlog`, and the CLIs `jira-sync` and
  `jira-backlog` (`bin/`, package `jira_sync/`, standard library only).
  - Session close: a comment per issue, a move to a target status by name (the
    tool finds the transition and reports the fields it requires), and story
    points when given. Jira has no `% Done`; there is no substitute.
  - Backlog: create Epics, Tasks and Sub-tasks from a plan file with their
    parents and story points, `relates`/`duplicates`/`blocks` links, fix parents
    and update descriptions.
- Same safety contract as the Redmine skills: dry run first, `--write` only
  after approval, every write read back, and re-runs never duplicate (comments
  carry `_jira-sync: <session>_`; backlog nodes are found by their id as the
  summary prefix).
- Configuration: `.jira.json` (`url`, `project`, `updates_dir`,
  `story_points_field`), credentials `JIRA_EMAIL` / `JIRA_API_TOKEN` or
  `~/.config/jira-sync/credentials` (mode 600). Templates: `jira.example.json`,
  `jira.plan.example.json`, `jira.update.example.json`.
- `AGENTS.md`, `README.md` and `TESTING.md` cover the Jira skills.

### Notes
- Jira Cloud only; Data Center and Server are not supported.
- Transition fields support text, number and single-option; other types must be
  set in Jira. Descriptions are verified only as present.
- Verified against an in-memory fake and one Jira Cloud test site. The live run
  corrected the direction of `blocks` links. Not yet seen live: transitions with
  required fields, `fix-parents`, `update-descriptions`, `relates` and
  `duplicates` links, priorities.
- A repository with both `.redmine.json` and `.jira.json` makes the skills stop
  and ask which tracker is meant.

## 0.3.1

Re-labelled: these changes shipped on `main` with `plugin.json`, the
marketplace entry and the CLI version saying `0.3.0`, but `0.3.0` is the Codex
release below. Tag `0.3.1` marks the commit that contains them.

### Added
- `required_fields_on_close` in `.redmine.json` and per-row `custom_fields` in
  update files, for instances that require custom fields to close an issue at
  100% done (validated, sent with the closing request, verified on read-back).
- Session ids named `YYYY-MM-DD-<topic>`; the dry run notes a bare-date session.

### Changed
- The CLI version is aligned with `plugin.json`, pinned by a test.

## 0.3.0

Codex support, and a guide for testers. (Tag `0.3.0`; `plugin.json` still said
`0.2.0` at that commit.)

### Added
- Codex CLI support through the Agent Skills open standard: `.agents/skills/`
  links to the same `SKILL.md` files Claude Code reads, and `AGENTS.md`.
- `TESTING.md`, a manual-install guide (zip) for Claude Code and Codex testers,
  and the `redmine.example.json` template.

Earlier versions: see the git history.
