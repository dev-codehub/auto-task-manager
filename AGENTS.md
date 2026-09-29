# redmine-sync, for Codex

This repository ships two Agent Skills (the open, cross-tool format —
see https://agentskills.io) under `.agents/skills/`, symlinked to the same
files Claude Code reads from `skills/`. There is one copy of each
`SKILL.md`; both tools read it as-is.

## Setup

1. **Put `bin/` on PATH.** Claude Code plugins do this automatically; Codex
   does not, so add it yourself, once:

   ```bash
   export PATH="$PATH:/path/to/auto-task-manager/bin"
   ```

   Put that line in your shell profile to make it permanent. Confirm with
   `redmine-sync --version`.

2. **Credentials and `.redmine.json`** are unchanged from the main
   [README](README.md) - same `REDMINE_API_KEY` / `~/.config/redmine-sync/credentials`,
   same per-repository `.redmine.json`.

3. Codex discovers the skills from `.agents/skills/` at the repository
   root automatically - nothing else to enable.

## Notes

- The `redmine_sync/` CLI is plain Python 3 standard library; nothing
  about it is Claude-Code-specific.
- `.claude-plugin/` (plugin.json, marketplace.json) is only read by
  Claude Code and can be ignored when using Codex.
