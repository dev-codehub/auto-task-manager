# auto-task-manager (redmine-sync, jira-sync)

Redmine and Jira Cloud task management from Claude Code: two skills for each
tracker, all dry-run first, written only after you say yes.

**`redmine-session-close`** — at the end of a working session, writes one
update per issue the session touched: a comment, and optionally `% Done` and
status.

**`redmine-backlog`** — creates features, user stories and tasks from a JSON
plan file, relates issues to each other, repairs parents, and updates
descriptions on request.

**`jira-session-close`** and **`jira-backlog`** — the same two jobs for Jira
Cloud (see [Jira](#jira)): one comment per issue the session touched plus an
optional status move and story points, and epics, stories and sub-tasks
created from a plan file.

Every write, in any of the skills, is read back, because the tracker can
accept a change and silently ignore a field your role may not set.

Which tracker a skill uses is decided by the repository: `.redmine.json` for
the Redmine skills, `.jira.json` for the Jira skills. If a repository has both,
the skills stop and ask which tracker you mean.

## Setup

**The plugin.**

```
/plugin marketplace add dev-codehub/auto-task-manager
/plugin install auto-task-manager@auto-task-manager
```

Or load a local copy for testing with
`claude --plugin-dir path/to/auto-task-manager`. While it is enabled, its
`bin/` is on the Bash tool's PATH, so `redmine-sync` runs by name.

**Credentials**, once per person. Either export `REDMINE_API_KEY`, or store the
key (from *My account* → *API access key* in Redmine) alone in a file:

```bash
mkdir -p ~/.config/redmine-sync
printf '%s\n' 'YOUR-KEY' > ~/.config/redmine-sync/credentials
chmod 600 ~/.config/redmine-sync/credentials
```

The CLI refuses to read that file if others can read it.

**Per repository**, commit a `.redmine.json` at its root:

```json
{
  "url": "https://redmine.example.org",
  "project": "your-project-identifier",
  "text_format": "textile",
  "issue_key": "subject_prefix",
  "updates_dir": "redmine/session-updates",
  "required_fields_on_close": [
    {"id": 1, "key": "reviewed", "name": "Reviewed", "values": ["Yes", "No"]}
  ]
}
```

`project` is the identifier in the project's URL. `text_format` is `textile` or
`markdown`, matching your instance. `issue_key` is `subject_prefix` (issues are
named by the first word of their subject, e.g. `EX-01.2`) or `id_only`
(`#1042` only). `#number` always works.

`required_fields_on_close` is optional - leave it out unless your instance makes
a custom field mandatory when an issue closes at 100% done; without it nothing
changes. `id` is the field's numeric id (find it from a live issue that already
has the field set - there is usually no non-admin API for the definition list),
`name` is how Redmine labels it, `key` is what an update file's own
`custom_fields` object calls it, and `values` is every value the field accepts,
so a typo is caught before the write rather than as a live rejection.

`redmine-backlog` always matches a plan file's node ids against existing
issues by subject prefix (see below), so it refuses to run at all in a
repository configured with `issue_key: "id_only"`.

## Commands: redmine-sync (session close)

```bash
redmine-sync status EX-01.2 '#1042'            # read-only
redmine-sync apply redmine/session-updates/2026-01-15-onboarding-flow.json          # dry run
redmine-sync apply redmine/session-updates/2026-01-15-onboarding-flow.json --write  # write
```

Re-running `--write` is safe: each comment carries a
`_redmine-sync: <session>_` line, and issues that already have it are skipped,
so an interrupted run resumes where it stopped.

Name the session `YYYY-MM-DD-<topic>` (e.g. `2026-01-15-onboarding-flow`): the
id is the only part of the marker a reader of the issue sees, and the comment
already carries its date. A bare date still works; the dry-run notes it.

An update file may set `custom_fields` on a row: `{"issue": "EX-01.2", "note":
"...", "status": "Closed", "done_ratio": 100, "custom_fields": {"reviewed":
"Yes"}}`, keyed by the `key` that `.redmine.json`'s `required_fields_on_close`
declares (never the numeric id or the display name). If a row closes an issue at
100% done and that config declares any such fields, `apply` - dry run or
`--write` - reports an error naming each missing field and the values it
accepts, and sends nothing. A value outside the declared list is also an error,
with the accepted ones listed. When the fields are complete they are sent in the
same request that closes the issue and checked on the read-back, like status and
% Done.

## Commands: redmine-backlog (create, relate, repair)

A plan file describes what should exist — features, stories, tasks and the
relations between them:

```json
{
  "project": "your-project-identifier",
  "nodes": [
    {
      "id": "US-01",
      "subject": "US-01 A user story",
      "description": "...",
      "tracker": "User Story",
      "priority": "Normal",
      "parent": null,
      "target_version": "P1",
      "category": "SUPPORT",
      "estimated_hours": 3
    },
    {
      "id": "US-01.1",
      "subject": "US-01.1 A task under it",
      "description": "...",
      "tracker": "Task",
      "priority": "Normal",
      "parent": "US-01"
    }
  ],
  "relations": [
    {"type": "blocks", "from": "US-01.1", "to": "US-01.2"}
  ]
}
```

`id` is never sent to Redmine — there is no portable custom field for it. It
is matched against issues by requiring `subject` to start with that same
`id`; a plan re-applied later finds and skips what it already created. `parent`
and a relation's `from`/`to` are either another node's `id` in the same file,
or `"#1234"` for an issue that already exists. `type` is one of `relates`,
`duplicates`, `blocks`, `precedes`.

```bash
redmine-backlog plan <file>                            # read-only, validate
redmine-backlog apply <file>                            # dry run
redmine-backlog apply <file> --write                     # create
redmine-backlog fix-parents <file>                        # report only
redmine-backlog fix-parents <file> --write                 # fix
redmine-backlog update-descriptions <file> --only=ID,ID          # dry run
redmine-backlog update-descriptions <file> --only=ID,ID --write   # apply
```

`update-descriptions --write` refuses to run without `--only` — unlike
`apply`, it has no other safety net once it writes, so there is no default of
"every node in the file."

## Jira

The Jira skills are `jira-session-close` (CLI `jira-sync`) and `jira-backlog`
(CLI `jira-backlog`). They target Jira Cloud (REST API v3), authenticate with
your Atlassian account email and an API token, and work like their Redmine
counterparts: dry run first, `--write` only after your yes, every write read
back.

### Jira credentials

Once per person. Create an API token at
https://id.atlassian.com/manage-profile/security/api-tokens, then either export
`JIRA_EMAIL` and `JIRA_API_TOKEN`, or put both as `KEY=VALUE` lines in a file
only you can read:

```bash
mkdir -p ~/.config/jira-sync
printf '%s\n' 'JIRA_EMAIL=you@example.com' 'JIRA_API_TOKEN=YOUR-API-TOKEN' > ~/.config/jira-sync/credentials
chmod 600 ~/.config/jira-sync/credentials
```

The CLI refuses to read that file if others can read it. A value that still
starts with `PREENCHE:` is the unfilled template and is reported as "not
filled in", never sent. Skills never read this file or ask for its contents.

### `.jira.json`

Commit one at the repository root (`jira.example.json` is a template with
`PREENCHE:` placeholders):

```json
{
  "url": "https://your-site.atlassian.net",
  "project": "PROJ",
  "updates_dir": "jira/session-updates",
  "story_points_field": "customfield_10016"
}
```

`url` is your Jira Cloud site (https; no trailing slash needed) and `project`
is the project key, the prefix of its issues (`PROJ` in `PROJ-123`).
`updates_dir` is where session-close files go and is optional.
`story_points_field` is optional: the id of the story points field, in the form
`customfield_` plus digits. Without it the field is looked up by exact name
(`Story Points` or `Story point estimate`); if the site has none, or several,
anything that sets story points reports it and asks you to configure the id.

### Commands: jira-sync (session close)

```bash
jira-sync status SCRUM-12 SCRUM-13             # read-only
jira-sync apply jira/session-updates/2026-10-06-onboarding-flow.json          # dry run
jira-sync apply jira/session-updates/2026-10-06-onboarding-flow.json --write  # write
```

`status` prints each issue's status, story points and the transitions
available from where it stands. Re-running `--write` is safe: each comment ends
with a `_jira-sync: <session>_` line, and issues that already have it are
skipped, so an interrupted run resumes where it stopped. Name the session
`YYYY-MM-DD-<topic>`, as for Redmine.

An update file:

```json
{"session": "2026-10-06-onboarding-flow", "updates": [
  {"issue": "SCRUM-12", "note": "...", "status": "Done", "story_points": 3,
   "transition_fields": {"Resolution": "Done"}}
]}
```

- `issue` (required): a Jira issue key.
- `note` (required): the comment.
- `status` (optional): the target status *name*, as Jira shows it. The tool
  finds the transition that leads there; if there is none it reports an error
  listing the transitions that are available.
- `story_points` (optional): a number of 0 or more. Jira has no `% Done`;
  story points take its place, and they change only when given - an issue's
  points are never inferred or touched otherwise.
- `transition_fields` (optional): values for fields the chosen transition asks
  for, keyed by the field's name as Jira shows it. A missing required field is
  an error naming it (and the accepted options, where the field has a fixed
  list) - on the dry run, before anything is sent. Supported types are text,
  number and single-option fields; a field of any other type (user,
  multi-select, version, rich text and the like) is reported as unsupported
  and must be set in Jira.

### Commands: jira-backlog (create, link, repair)

```bash
jira-backlog plan <file>                            # read-only, validate
jira-backlog apply <file>                            # dry run
jira-backlog apply <file> --write                     # create
jira-backlog fix-parents <file>                        # report only
jira-backlog fix-parents <file> --write                 # fix
jira-backlog update-descriptions <file> --only=ID,ID          # dry run
jira-backlog update-descriptions <file> --only=ID,ID --write   # apply
```

The plan file has the same shape as Redmine's, with Jira's vocabulary:

```json
{
  "project": "PROJ",
  "nodes": [
    {"id": "EP-01", "subject": "EP-01 An epic", "description": "...",
     "type": "Epic", "parent": null},
    {"id": "US-01", "subject": "US-01 A story", "description": "...",
     "type": "Story", "priority": "Medium", "story_points": 5,
     "parent": "EP-01"},
    {"id": "US-01.1", "subject": "US-01.1 A sub-task", "description": "...",
     "type": "Sub-task", "parent": "US-01"}
  ],
  "relations": [
    {"type": "blocks", "from": "US-01.1", "to": "#PROJ-42"}
  ]
}
```

- A node's `id` is never sent to Jira; it is matched against existing issues by
  requiring the summary (`subject`) to start with it, so a plan re-applied later
  skips what it already created. `type` is an issue type that exists in the
  project. `priority` and `story_points` are optional - left out, the project's
  default priority applies and no points are set.
- `parent` and a relation's `from`/`to` are another node's `id` in the same
  file, or `#PROJ-123` (the `#` and the key) for an issue that already exists.
- A relation `type` is `relates`, `duplicates` or `blocks`. Jira has no
  `precedes`; a plan that uses it is rejected.
- Descriptions are written and read back only to check that one is present, not
  compared character by character; the report says so. `update-descriptions
  --write` refuses to run without `--only`, as in Redmine.
- `fix-parents --write` exits 1 when a fix did not land (usually the account may
  not change that issue's parent), unlike its Redmine counterpart.

### How far this has been verified

Jira support was developed and tested against an in-memory fake of the Jira
API (`tests/fake_jira.py`), not a live site. Treat your first run against a real
Jira Cloud site as supervised: start read-only and check the result in the Jira
UI. [TESTING.md](TESTING.md) has a checklist.

## What it will not do

Change assignees, custom fields or time entries (apart from the Jira story
points and transition fields described above). None of the skills ever edits a
description as a side effect of something else — the session-close CLIs only
ever post a comment, and the backlog CLIs only touch a description when asked
for by name with `--only`.

## Development

```bash
python3 -m unittest discover -s tests -v
```

Python 3.9+, standard library only. The tests run against in-memory fakes of
Redmine (`tests/fake_redmine.py`) and Jira (`tests/fake_jira.py`).
