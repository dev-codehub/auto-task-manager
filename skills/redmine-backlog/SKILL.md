---
name: redmine-backlog
description: Use to create features, user stories and tasks in Redmine, relate issues to each other, repair parents, or update an issue's description on request. Always shows a dry-run first (plan or a bare apply) and writes only after the person explicitly approves it.
---

# Redmine backlog management

Create and relate Redmine issues from a JSON plan file, or update what
already exists. You prepare the plan; the person approves it; only then is
anything written.

## Before you start

- The CLI is `redmine-backlog`: this plugin's `bin/` is on the Bash tool's
  PATH while the plugin is enabled. If the command is not found, the
  plugin is not enabled - say so and stop.
- `.redmine.json` must exist in the repository (root or a parent
  directory), same file `redmine-sync` uses. If it does not, stop and tell
  the person it needs `url` and `project`; see the plugin README.
- **Never read, print, echo or ask for the API key**, and never open
  `~/.config/redmine-sync/credentials`. If the CLI says there is no key,
  tell the person how to set one up (README, "Credentials") and stop.

## Creating features, stories and tasks

1. **Write the plan file.** One JSON object: `project`, `nodes` (each with
   `id`, `subject` starting with that same `id`, `description`, `tracker`,
   `priority`, `parent` — `null`, another node's `id` in this file, or
   `"#1234"` for an issue that already exists), and `relations` (`type`
   one of `relates`/`duplicates`/`blocks`/`precedes`, `from`, `to`, both a
   node `id` or `#number`). Validate it first, read-only:
   `redmine-backlog plan <file>`. Fix every problem it reports before
   moving on — nothing is created yet.

2. **Dry-run:** `redmine-backlog apply <file>`. Read the output with the
   person: what would be created, what already exists and is skipped,
   what relations would be added. This is still read-only.

3. **Stop and ask:** "Create these N issues and M relations?" Only an
   unambiguous yes counts. If anything should change, edit the file,
   dry-run again (step 2), and ask again. Never run `--write` without
   this yes.

4. **Write:** `redmine-backlog apply <file> --write`. Show the report
   unedited. A `parent was not set on creation` warning means run
   `redmine-backlog fix-parents <file>` next — this can happen even when
   creation itself succeeded, and is not something to silently retry.

5. **Offer to commit the plan file** on its own, so the repository
   records what was asked for. Commit it only if the person agrees.

## Fixing parents

`redmine-backlog fix-parents <file>` reports what is wrong, changing
nothing. Show the person the report. Only run
`redmine-backlog fix-parents <file> --write` after they say yes to fixing
specifically those issues.

## Updating a description

Never do this as part of closing a session — that is `redmine-sync`'s job
and it only ever posts a comment. Use this only when the person explicitly
asks to update one or more descriptions.

1. `redmine-backlog update-descriptions <file> --only=ID,ID` to see what
   would change. `--only` is required — there is no default of "every
   node in the file" for a write, and the CLI refuses `--write` without it.
2. Ask: "Update the description of ID, ID?" Only an explicit yes counts.
3. `redmine-backlog update-descriptions <file> --only=ID,ID --write`. Show
   the report unedited.
