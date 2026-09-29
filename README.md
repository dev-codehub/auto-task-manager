# redmine-sync

Redmine task management from Claude Code: two skills, both dry-run first,
written only after you say yes.

**`redmine-session-close`** — at the end of a working session, writes one
update per issue the session touched: a comment, and optionally `% Done` and
status.

**`redmine-backlog`** — creates features, user stories and tasks from a JSON
plan file, relates issues to each other, repairs parents, and updates
descriptions on request.

Every write, in either skill, is read back, because Redmine can accept a
change and silently ignore a field your role may not set.

## Setup

**The plugin.** Install it from your plugin marketplace, or load a local copy
for testing with `claude --plugin-dir path/to/auto-task-manager`. While it is
enabled, its `bin/` is on the Bash tool's PATH, so `redmine-sync` runs by name.

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
  "updates_dir": "redmine/session-updates"
}
```

`project` is the identifier in the project's URL. `text_format` is `textile` or
`markdown`, matching your instance. `issue_key` is `subject_prefix` (issues are
named by the first word of their subject, e.g. `EX-01.2`) or `id_only`
(`#1042` only). `#number` always works.

`redmine-backlog` always matches a plan file's node ids against existing
issues by subject prefix (see below), so it refuses to run at all in a
repository configured with `issue_key: "id_only"`.

## Commands: redmine-sync (session close)

```bash
redmine-sync status EX-01.2 '#1042'            # read-only
redmine-sync apply redmine/session-updates/2026-01-15.json          # dry run
redmine-sync apply redmine/session-updates/2026-01-15.json --write  # write
```

Re-running `--write` is safe: each comment carries a
`_redmine-sync: <session>_` line, and issues that already have it are skipped,
so an interrupted run resumes where it stopped.

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

## What it will not do

Change assignees, custom fields or time entries. Neither skill ever edits a
description as a side effect of something else — `redmine-sync` only ever
posts a comment, and `redmine-backlog` only touches a description when asked
for by name with `--only`.

## Development

```bash
cd tools/redmine-sync && python3 -m unittest discover -s tests -v
```

Python 3.9+, standard library only. The tests run against an in-memory fake
Redmine (`tests/fake_redmine.py`).
