# Changelog

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

## 0.3.0

### Added
- `required_fields_on_close` in `.redmine.json` and per-row `custom_fields` in
  update files, for instances that require custom fields to close an issue at
  100% done (validated, sent with the closing request, verified on read-back).
- Session ids named `YYYY-MM-DD-<topic>`; the dry run notes a bare-date session.

### Changed
- The CLI version is aligned with `plugin.json`, pinned by a test.

Earlier versions: see the git history.
