# Jira Cloud support for auto-task-manager

Status: draft for approval. Written 2026-10-19.

## Intent

The plugin manages Redmine issues from Claude Code with two skills, both
dry-run first and written only after the person says yes:

- `redmine-session-close` writes one update per issue a working session
  touched (comment, `% Done`, status).
- `redmine-backlog` creates features, stories and tasks from a JSON plan,
  relates issues, repairs parents and updates descriptions.

The team works on client projects, and which tracker is used is the client's
choice. Some clients use Jira. This design adds the same two capabilities for
**Jira Cloud** (sites at `https://<site>.atlassian.net`) in the same plugin, so
one install covers both trackers.

## Goals

- Two new skills, `jira-session-close` and `jira-backlog`, with their own
  commands, `jira-sync` and `jira-backlog`, and their own per-repository config
  file, `.jira.json`.
- The same safety contract as the Redmine skills, without exception:
  - Every write is shown as a dry-run first and happens only after explicit
    approval.
  - Every write is read back and verified, because Jira can accept a request and
    still not apply a field.
  - Re-running a command never duplicates anything.
  - The skill never reads, prints or asks for the credentials.
- Works for any team's workflow without per-team code changes. Each team has
  different transitions and mandatory fields, so the tool discovers them from
  Jira instead of having them hard-coded.
- Python 3 standard library only, like the Redmine CLI. No third-party packages.
- Works in Claude Code and Codex, as the Redmine skills do (the Codex
  `.agents/skills/` symlinks and `AGENTS.md` are extended to the new skills).

## Non-goals

- Jira Data Center or Server. Only Jira Cloud is in scope. The two differ in
  authentication, API version and how epics are linked.
- Sprints, boards, ranking, versions/releases, components, assignees, worklogs
  and time tracking.
- Reading Jira descriptions back into Markdown. Descriptions are write-only.
- A replacement for `% Done`. Jira has no equivalent and none is invented.
- Changing the Redmine code, its behaviour or its tests. The three open PRs
  (`codex-support`, `task/descriptive-session-id`,
  `feat/required-fields-on-close`) must not be disturbed.
- Supporting a repository that is configured for both trackers at once. See
  "Which skill fires".

## Anti-goals

Any of these makes the feature a failure even if it otherwise works:

- A write the person did not approve.
- A duplicate issue after a re-run, or an ambiguous match resolved by picking
  one silently.
- Treating an accepted request as a successful write without reading it back.
- Guessing the value of a mandatory field instead of asking the person.
- Sending the credentials to a host other than the configured Jira site
  (including through a redirect).

## What was decided

These were decided with the requester; the builder should not reopen them.

**Same plugin, parallel implementation.** The new skills live in the existing
plugin, next to the Redmine ones. The Jira code is a new package, `jira_sync/`,
beside `redmine_sync/`, with new executables in `bin/`.

**Jira Cloud only.** Sites are `*.atlassian.net`. The REST API is v3.
Authentication is the account email plus an API token.

**Workflow is generic.** Each team has its own transitions and mandatory
fields. The tool does not hard-code any. It asks Jira what the transition
needs and tells the person what is missing.

**Story points replace `% Done`.**

- In the backlog plan, a story or task node may carry `story_points`.
- In a session-close update, `story_points` changes only when the row sets it
  explicitly. The skill never infers a value from the work done, because story
  points are an estimate and not progress.
- Progress is the issue's status plus the comment. No `% Done` substitute.

## Behaviour

### Session close (`jira-sync`)

For each issue the session touched, one update. A row has:

- `issue`: a Jira key such as `PROJ-123`. Jira keys are native, so there is no
  subject-prefix scheme.
- `note`: the comment, required.
- `status` (optional): the *name of the target status*. The tool finds the
  transition that leads there from the issue's current status. If none does,
  that is a dry-run error that lists the statuses reachable now.
- `story_points` (optional): a number, set only when given.
- `transition_fields` (optional): values for fields the chosen transition
  requires, keyed by the field's name as Jira reports it.

Dry-run (`jira-sync apply <file>`, read-only) reports for every row: the
current status, the transition it would use, the required fields that are
already satisfied and the ones that are **missing**, and the comment. A missing
required field is an error that blocks the whole write, naming the field and,
for fields with a fixed list of options, the options Jira accepts. The skill
asks the person for those values and never guesses them.

`apply --write` posts the comment, performs the transition with its fields, sets
story points, then reads the issue back and verifies each change.

Idempotency: each comment ends with a marker line, `_jira-sync: <session>_`,
as the Redmine comments do. A row is skipped when the current user's own
comment on that issue already carries the marker for that session. "Current
user" is the authenticated account, not an email string.

The session id follows the Redmine convention, `YYYY-MM-DD-<topic>`, and the
dry-run notes a bare-date session the same way.

`jira-sync status <key>...` is read-only and prints each issue's status,
story points and the transitions available now.

### Backlog (`jira-backlog`)

The plan file has the same shape as the Redmine one: `project`, `nodes`
(`id`, `subject` starting with that `id`, `description`, `type`, `priority`,
`parent`, optional `story_points`) and `relations` (`type`, `from`, `to`).
`type` is the Jira issue type name (Epic, Story, Task, Sub-task, Bug, or
whatever the project calls them; names differ per project and language), looked
up in the project. An unknown type is a plan error that lists the project's
types.

`parent` is `null`, another node's `id`, or an existing issue key. A parent that
Jira's hierarchy does not allow (for example a Story under a Sub-task) is a
plan error, reported before anything is created.

Relations map to the link types the Jira site has configured, looked up by
name. The plan's `relates`, `duplicates` and `blocks` map to the site's
Relates, Duplicate and Blocks link types. The direction must come out right
(`A blocks B` is not `B blocks A`). Redmine's `precedes` has no Jira
equivalent: a plan that uses it fails validation with a clear message. If the
site has renamed or removed a link type, that is a plan error that lists what
the site has.

The three-step flow is unchanged: validate (`plan`), dry-run (`apply`), then
write only after approval. Re-running skips nodes that already exist, and
creates only what is missing, relations included. The commands to update an
existing issue's description and to repair parents have Jira counterparts with
the same dry-run-first behaviour.

Descriptions are written in plain text or light Markdown in the plan file. The
CLI converts them to what Jira Cloud requires (the Atlassian Document Format).
The supported subset is headings, paragraphs, bullet and numbered lists, code
blocks, inline code, bold and links. Anything else is passed through as plain
paragraph text, never dropped.

### Configuration and credentials

`.jira.json` at the repository root (found by walking up, like
`.redmine.json`):

- `url`: the site root, for example `https://projeto-wit.atlassian.net`.
- `project`: the Jira project key.
- `updates_dir`: where session-update files live (default
  `jira/session-updates`).
- `story_points_field` (optional): the id of the story points field, for
  example `customfield_10016`. When absent the tool looks the field up by name
  and, if it cannot find exactly one, says so and asks for the id in config.

Credentials, once per person: `JIRA_EMAIL` and `JIRA_API_TOKEN` in the
environment, or both in `~/.config/jira-sync/credentials` (mode 600, refused
otherwise, as for Redmine). The token is created at id.atlassian.com under
Security. The skills never read that file.

The HTTP client refuses redirects, so the token is never re-sent to another
host, and reports Jira's error messages in plain words.

### Which skill fires

Each skill's description and "before you start" check name its own config
file. `jira-*` skills act only when `.jira.json` exists, `redmine-*` skills only
when `.redmine.json` exists. If a repository has both, the skill stops and asks
which tracker the person means. It never picks one.

## Constraints

- Python 3 standard library only.
- Tests need no network. Following `tests/fake_redmine.py`, a fake Jira server
  covers the client and apply paths.
- Version: this is a new feature, so a minor bump (to 0.4.0), applied to
  `plugin.json`, `marketplace.json` and the CLI's `__version__`, which a
  test already pins to agree.
- Docs: README gains a Jira section, `AGENTS.md` mentions the new skills,
  `.agents/skills/` gets symlinks for them, and the plugin description mentions
  both trackers.

## What is left to the builder

These are the builder's calls; record each in the plan.

- Whether to extract code shared with `redmine_sync/` (the file parsers, the
  plan/report rendering shape, the key checks). The Redmine modules are tied to
  Redmine's shapes (integer ids, `#number`, `done_ratio`), so most of the Jira
  logic will be a parallel implementation. Extraction is allowed only if the
  Redmine behaviour and tests are untouched.
- The exact Jira Cloud endpoints and payloads. The REST API changes; check
  current Atlassian documentation rather than relying on this document. In
  particular, issue search by JQL (the older search endpoint has been
  deprecated in favour of a newer one with token-based paging), the shape of
  transition fields, and how the `parent` field works for Epics and Sub-tasks.
- How to detect that a backlog node already exists, so a re-run never
  duplicates: matching on the summary prefix as the Redmine tool does, a label
  per node, or something else. Whatever is chosen must treat more than one match
  as ambiguous and never pick one silently.
- The command-line surface of `jira-sync` and `jira-backlog`, kept close to the
  Redmine commands so a person who knows one knows the other.
- The Markdown to ADF converter's details within the subset above.
- Output wording of dry-runs and reports, in the style of the Redmine ones.
- Any further scope questions that come up go back to the requester, not into
  the design by assumption.
