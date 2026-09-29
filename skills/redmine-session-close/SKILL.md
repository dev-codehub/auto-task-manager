---
name: redmine-session-close
description: Use at the close of a working session to report progress to Redmine - one comment per issue the session touched, plus % Done and status where the evidence supports it. Always shows a dry-run first and writes only after the person explicitly approves it.
---

# Redmine session close

Report what this session did to the Redmine issues it touched. You prepare the
update; the person approves it; only then is anything written.

## Before you start

- The CLI is `redmine-sync`: this plugin's `bin/` is on the Bash tool's PATH
  while the plugin is enabled. If the command is not found, the plugin is not
  enabled - say so and stop.
- `.redmine.json` must exist in the repository (root or a parent directory). If
  it does not, stop and tell the person it needs `url` and `project`; see the
  plugin README. Do not guess either value.
- **Never read, print, echo or ask for the API key**, and never open
  `~/.config/redmine-sync/credentials`. If the CLI says there is no key, tell the
  person how to set one up (README, "Credentials") and stop.

## Steps

1. **Decide which issues this session touched.** Use the session's own work:
   commits made, files changed, and what was discussed. Map each to an issue key
   — a subject prefix or `#number`, as `.redmine.json`'s `issue_key` allows. Do
   not include issues the session did not work on. If a mapping is unclear, ask.

2. **Read their current state:** `redmine-sync status <key> <key> ...`. Base
   every change on what this prints, not on memory. Quote `#number` keys
   (`'#1042'`): unquoted, the shell reads `#` as the start of a comment and the
   key silently disappears.

3. **Write the update file** at `<updates_dir>/<session>.json`, where `<session>`
   is today's date `YYYY-MM-DD`, suffixed `-2`, `-3`, ... if that file exists:

   ```json
   {"session": "YYYY-MM-DD", "updates": [
     {"issue": "KEY", "note": "...", "done_ratio": 60, "status": "In Progress"}
   ]}
   ```

   - `note` (required): what changed this session, what remains, and the
     evidence — a commit, a file, a measured result. Do not restate the issue's
     description. Do not invent figures. Write in the language the issue's
     existing comments use, in `.redmine.json`'s `text_format`.
   - `done_ratio` and `status` (optional): only when the evidence supports a
     change; omit them otherwise. Use `Closed` (or the instance's equivalent)
     only when the work is finished and verified.

4. **Dry-run:** `redmine-sync apply <file>`. If it reports errors, fix the file
   and dry-run again. Then show the person the complete output, unedited.

5. **Stop and ask:** "Write these N updates to Redmine?" Only an unambiguous yes
   to the whole set counts. If the person changes or drops any row, edit the
   file, dry-run again, and ask again. Never run `--write` without this yes.

6. **Write:** `redmine-sync apply <file> --write`, and show the report
   unedited. If it stopped part-way, explain why from the report. If the file
   is unchanged and the cause is outside it (network, VPN), re-run the same
   command - finished issues are skipped automatically. If the file has to
   change, that is a new update: dry-run again, show it, and ask again before
   any `--write`.

7. **Offer to commit the update file** on its own, so the repository records
   what each session reported. Commit it only if the person agrees.
