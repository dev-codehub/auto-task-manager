---
name: jira-session-close
description: Use at the close of a working session, in a repository with a `.jira.json`, to report progress to Jira - one comment per issue the session touched, plus a status move and story points where the person asks for them. Always shows a dry-run first and writes only after the person explicitly approves it.
---

# Jira session close

Report what this session did to the Jira issues it touched. You prepare the
update; the person approves it; only then is anything written.

## Before you start

- The CLI is `jira-sync`: it must be on PATH (in Claude Code, this
  plugin's `bin/` is added automatically while it is enabled; elsewhere,
  this repository's `bin/` must be on PATH). If the command is not found,
  say so and stop - see the plugin README for setup.
- `.jira.json` must exist in the repository (root or a parent directory). If
  it does not, do nothing in Jira: this skill is for Jira repositories only.
  If it exists but is wrong, stop and tell the person it needs `url` and
  `project`; see the plugin README. Do not guess either value.
- **If `.redmine.json` is also present, stop and ask which tracker the person
  means** - Jira or Redmine - and wait for the answer. Never pick one yourself.
- **Never read, print, echo or ask for the Jira email or API token**, and
  never open `~/.config/jira-sync/credentials`. If the CLI says there are no
  credentials, or that they are "not filled in", tell the person how to set
  them up (plugin README, Jira credentials) and stop.

## Steps

1. **Decide which issues this session touched.** Use the session's own work:
   commits made, files changed, and what was discussed. Map each to a Jira
   issue key such as `SCRUM-12` (in a commit message, a branch name, or what
   the person said). Do not include issues the session did not work on. If a
   mapping is unclear, ask.

2. **Read their current state:** `jira-sync status <key> <key> ...`. It prints
   each issue's status, story points and the transitions available from where
   it stands. Base every change on what this prints, not on memory. Quote the
   keys if the shell could misread them; a plain key like `SCRUM-12` needs no
   quotes.

3. **Write the update file** at `<updates_dir>/<session>.json`, where
   `<updates_dir>` is `.jira.json`'s `updates_dir` (default
   `jira/session-updates`) and `<session>` is today's date plus a short topic,
   `YYYY-MM-DD-<topic>` (lowercase, hyphens, e.g. `2026-10-06-onboarding-flow`).
   The session id is printed at the end of every comment as
   `_jira-sync: <session>_`, and the comment already carries its own date, so a
   bare date tells the reader of the issue nothing; the topic says what the
   update was and names its file. Use a different topic for a second update on
   the same day, not `-2`. (A bare date still works; the dry-run only notes it.)

   ```json
   {"session": "YYYY-MM-DD-<topic>", "updates": [
     {"issue": "SCRUM-12", "note": "...", "status": "In Progress"}
   ]}
   ```

   Jira has no `% Done`. Progress on an issue is its status plus the comment.

   - `note` (required): what changed this session, what remains, and the
     evidence - a commit, a file, a measured result. Do not restate the issue's
     description. Do not invent figures. Write in the language the issue's
     existing comments use.
   - `status` (optional): the target status name, as Jira shows it (for
     example `In Progress` or `Done`). Give only the name; the tool finds the
     transition that leads there and reports an error, listing the transitions
     that are available, if there is none. Set it only when the evidence
     supports a move; omit it otherwise. Move to a finished status (`Done` or
     the instance's equivalent) only when the work is finished and verified.
   - `story_points` (optional, a number of 0 or more): set only when the person
     gives a value, and never inferred from the work done. A story point is an
     estimate, not progress. Without a value from the person, leave it out and
     the issue's points stay as they are.
   - `transition_fields` (optional, an object): values for the fields the chosen
     transition asks for, keyed by the field's name as Jira shows it. A
     transition can require fields (for example a resolution); `jira-sync
     apply` reports an error naming each missing field and, where the field has
     a fixed list, the options it accepts, rather than sending an incomplete
     write. Ask the person for these values rather than guessing; the dry-run
     lists each field it will set, and its errors list what is missing and the
     accepted options. Values are text or numbers. A field of a type the tool
     cannot set (user, multi-select, version, rich text and the like) is
     reported as "field not supported, set it in Jira": tell the person, and
     they set it in Jira themselves.

4. **Dry-run:** `jira-sync apply <file>`. If it reports errors, fix the file
   (asking the person for any missing value) and dry-run again. Then show the
   person the complete output, unedited.

5. **Stop and ask:** "Write these N updates to Jira?" Only an unambiguous yes
   to the whole set counts. If the person changes or drops any row, edit the
   file, dry-run again, and ask again. Never run `--write` without this yes.

6. **Write:** `jira-sync apply <file> --write`, and show the report unedited.
   If it stopped part-way, explain why from the report. Resume after a stop
   only by re-running the dry-run and asking again before writing - never by
   re-running `--write` straight away. If the file is unchanged and the cause
   is outside it (network, VPN), the dry-run will show the same plan, and once
   the person says yes, `--write` skips the issues already finished. If the
   file has to change, that is a new update: dry-run again, show it, and ask
   again before any `--write`.

7. **Offer to commit the update file** on its own, so the repository records
   what each session reported. Commit it only if the person agrees.
