# redmine-sync, for Codex

This repository ships four Agent Skills (the open, cross-tool format —
see https://agentskills.io) under `.agents/skills/`, symlinked to the same
files Claude Code reads from `skills/`: `redmine-session-close` and
`redmine-backlog` for Redmine, `jira-session-close` and `jira-backlog` for
Jira Cloud. There is one copy of each `SKILL.md`; both tools read it as-is.

## Setup

1. **Put `bin/` on PATH.** Claude Code plugins do this automatically; Codex
   does not, so add it yourself, once:

   ```bash
   export PATH="$PATH:/path/to/auto-task-manager/bin"
   ```

   Put that line in your shell profile to make it permanent. Confirm with
   `redmine-sync --version` (and `jira-sync --version` for the Jira skills).

2. **Credentials and `.redmine.json`** are unchanged from the main
   [README](README.md) - same `REDMINE_API_KEY` / `~/.config/redmine-sync/credentials`,
   same per-repository `.redmine.json`. If an instance requires custom
   fields to close an issue, `.redmine.json` declares them under
   `required_fields_on_close` and an update file sets them per row with
   `custom_fields` (see the README); ask the person for those values, do not
   guess them.

3. **Jira** is set up as described in the README's [Jira](README.md#jira)
   section: credentials are `JIRA_EMAIL` /
   `JIRA_API_TOKEN` or `~/.config/jira-sync/credentials` (see "Jira
   credentials" there), and each repository has a `.jira.json`
   (`jira.example.json` is the template). A repository with both
   `.redmine.json` and `.jira.json` is ambiguous: the skills stop and ask
   which tracker is meant. The token is never read, printed or asked for by
   the skill.

4. Codex discovers the skills from `.agents/skills/` at the repository
   root automatically - nothing else to enable.

## Notes

- The `redmine_sync/` and `jira_sync/` CLIs are plain Python 3 standard
  library; nothing about them is Claude-Code-specific.
- `.claude-plugin/` (plugin.json, marketplace.json) is only read by
  Claude Code and can be ignored when using Codex.
