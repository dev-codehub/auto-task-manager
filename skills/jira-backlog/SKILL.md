---
name: jira-backlog
description: Use, in a repository with a `.jira.json`, to create epics, stories and tasks in Jira, link issues to each other, repair parents, or update an issue's description on request. Always shows a dry-run first (plan or a bare apply) and writes only after the person explicitly approves it.
---

# Jira backlog management

Create and link Jira issues from a JSON plan file, or update what already
exists. You prepare the plan; the person approves it; only then is anything
written.

## Before you start

- The CLI is `jira-backlog`: it must be on PATH (in Claude Code, this
  plugin's `bin/` is added automatically while it is enabled; elsewhere,
  this repository's `bin/` must be on PATH). If the command is not found,
  say so and stop - see the plugin README for setup.
- `.jira.json` must exist in the repository (root or a parent directory),
  the same file `jira-sync` uses. If it does not, do nothing in Jira: this
  skill is for Jira repositories only. If it exists but is wrong, stop and
  tell the person it needs `url` and `project`; see the plugin README.
- **If `.redmine.json` is also present, stop and ask which tracker the person
  means** - Jira or Redmine - and wait for the answer. Never pick one yourself.
- **Never read, print, echo or ask for the Jira email or API token**, and
  never open `~/.config/jira-sync/credentials`. If the CLI says there are no
  credentials, or that they are "not filled in", tell the person how to set
  them up (plugin README, Jira credentials) and stop.

## Creating epics, stories and tasks

The order is always: validate (`plan`), dry-run (`apply`), ask, and only then
`apply --write`.

1. **Write the plan file.** One JSON object: `project` (the same key as in
   `.jira.json`), `nodes`, and `relations`. Each node has `id`, `subject`
   (starting with that same `id`), `description`, `type` (an issue type that
   exists in the project, such as `Epic`, `Story` or `Task`), `parent`
   (`null`, another node's `id` in this file, or `"#PROJ-123"` for an issue
   that already exists - the `#` and the key are what tell it from a node
   id), and optionally `priority` (leave it out to take the project's default)
   and `story_points` (a number of 0 or more; set it only when the person
   gives a value). A `relations` entry has `type` (one of
   `relates`/`duplicates`/`blocks` - Jira has no `precedes`), `from` and `to`,
   each a node `id` or `#PROJ-123`. A node is matched to an issue by its `id`:
   an issue in the project whose summary's first word (up to any `:`) is that
   id, in any case (for example `ST-01 Login page` or `st-01: Login page` for
   `ST-01`), is reported as already there and skipped;
   more than one such issue is an error, never a pick. Validate the file first,
   read-only: `jira-backlog plan <file>`. Fix every problem it reports before
   moving on - nothing is created yet.

2. **Dry-run:** `jira-backlog apply <file>`. Read the output with the person:
   what would be created, what already exists and is skipped, what links would
   be added. This is still read-only.

3. **Stop and ask:** "Create these N issues and M links?" Only an
   unambiguous yes counts. If anything should change, edit the file, dry-run
   again (step 2), and ask again. Never run `--write` without this yes.

4. **Write:** `jira-backlog apply <file> --write`. Show the report unedited.
   Each issue is read back after it is written. A description is verified only
   as present: the report says "description written, content not compared",
   which is a note, not a full check - do not describe it as verified. A
   warning that a parent reads back wrong means run
   `jira-backlog fix-parents <file>` next - this can happen even when creation
   itself succeeded, and is not something to silently retry. If the run
   stopped part-way, re-run the dry-run, show it and ask again before writing;
   what already exists is skipped.

5. **Offer to commit the plan file** on its own, so the repository records
   what was asked for. Commit it only if the person agrees.

## Fixing parents

`jira-backlog fix-parents <file>` reports what is wrong, changing nothing.
Show the person the report. Only run `jira-backlog fix-parents <file> --write`
after they say yes to fixing specifically those issues.

Unlike its Redmine counterpart, `fix-parents --write` exits 1 when a fix did
not land: the report marks such an issue "write sent but did not land". Show
that report, do not retry in a loop, and tell the person it usually means the
account lacks permission to change that issue's parent, or the edit screen
does not offer the parent field; they fix it in Jira or ask a project admin.

## Updating a description

Never do this as part of closing a session - that is `jira-sync`'s job and it
only ever posts a comment. Use this only when the person explicitly asks to
update one or more descriptions.

1. `jira-backlog update-descriptions <file> --only=ID,ID` to see what would
   change. `--only` is required for a write: there is no default of "every
   node in the file", and the CLI refuses `--write` without it (it requires
   `--only` with at least one node id).
2. Ask: "Update the description of ID, ID?" Only an explicit yes counts.
3. `jira-backlog update-descriptions <file> --only=ID,ID --write`. Show the
   report unedited. As above, the description is checked only as present, not
   compared.
