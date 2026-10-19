# Jira Cloud support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `jira-session-close` and `jira-backlog` skills, with their CLIs `jira-sync` and `jira-backlog`, for Jira Cloud, next to the Redmine ones.

**Architecture:** A new stdlib-only package `jira_sync/` beside `redmine_sync/`, mirroring its module layout (config, client, updatefile, plan, apply, render, backlog_*). Redmine modules are not touched; only the tracker-agnostic `redmine_sync.keys` helpers and `__version__` are imported. Tests run against an in-memory `tests/fake_jira.py`, as the Redmine tests do against `tests/fake_redmine.py`.

**Tech Stack:** Python 3 standard library, `unittest`, Jira Cloud REST API v3.

**Spec:** `docs/superpowers/specs/2026-10-19-jira-support-design.md` (approved 2026-10-19). Read it first; this plan only records the decisions the spec leaves open.

## Global Constraints

- Python 3 standard library only; tests need no network.
- Redmine code, behaviour and tests are untouched. Baseline before starting: `python3 -m unittest discover -s tests` runs 197 tests, all passing.
- Config file `.jira.json` (found by walking up). Credentials: `JIRA_EMAIL` and `JIRA_API_TOKEN` in the environment, or both as `KEY=VALUE` lines in `~/.config/jira-sync/credentials` (mode 600, refused otherwise). A value starting `PREENCHE:` is the unfilled template: report "not filled in", never send it.
- The HTTP client refuses redirects, so the token never goes to another host.
- Every write is dry-run first, approved, then read back and verified. Comments carry the marker line `_jira-sync: <session>_` and a row is skipped when the current account's own comment already has it. Session ids are `YYYY-MM-DD-<topic>`; a bare date is noted in the dry-run.
- Story points replace `% Done`; they change only when the row or node sets them. No `% Done` substitute.
- `transition_fields`: text, number and single-option only; any other type blocks the row with "field not supported, set it in Jira".
- The skills never read, print or ask for the credentials.
- Version 0.4.0 in `plugin.json`, `marketplace.json` and `__version__`, applied in the final shared-files commit (Task 9). Edits to `README.md`, `AGENTS.md`, `plugin.json`, `marketplace.json` go only in that commit.
- The test Jira site (`https://lj-test-jira.atlassian.net`, project `SCRUM`) is used only in Task 10, only when the requester says so.

## Review Focus

Each line has its test in the task named.

1. A comment carrying the session marker written by another account must not make a row "already applied" (Task 4).
2. Two transitions leading to the same target status: error listing the transition names, never pick one silently (Task 4).
3. A backlog run that fails halfway: re-running creates only what is missing and duplicates nothing (Task 7).
4. Story points sent but not on the issue's edit screen, so Jira ignores them: reported as a failure, not success (Task 5).
5. A description that is empty, or Markdown with an unclosed code fence: still valid ADF, never dropped or rejected locally (Task 3).

---

## File structure

- `jira_sync/__init__.py`: `__version__` imported from `redmine_sync` (one number to bump).
- `jira_sync/config.py`, `client.py`, `adf.py`, `updatefile.py`, `plan.py`, `apply.py`, `render.py`, `cli.py`, `backlog_file.py`, `backlog_plan.py`, `backlog_apply.py`, `backlog_cli.py`.
- `bin/jira-sync`, `bin/jira-backlog`: same 8-line launchers as the Redmine ones.
- `skills/jira-session-close/SKILL.md`, `skills/jira-backlog/SKILL.md`, plus `.agents/skills/` symlinks.
- `tests/fake_jira.py` and one `tests/test_jira_*.py` per module.

Every test command is `python3 -m unittest tests.<module> -v`; "all tests" is `python3 -m unittest discover -s tests`.

## Jira endpoints (checked against the Atlassian Jira Cloud REST v3 OpenAPI spec in Task 2)

Task 2 step 1 checked each row against the published v3 spec (`swagger-v3.v3.json`). Rows marked "corrected" differ from what the plan first assumed; later tasks follow this table.

| Need | Call |
|---|---|
| Current account | `GET /rest/api/3/myself` (`accountId`) |
| Project | `GET /rest/api/3/project/{key}` |
| Issue types of a project | `GET /rest/api/3/issue/createmeta/{key}/issuetypes`; corrected: the answer is a page `{startAt, maxResults, total, issueTypes: [...]}` (`startAt` default 0, `maxResults` default 50, max 200), so the client pages until `total`; each item has `id`, `name`, `subtask`, `hierarchyLevel` |
| Create-screen fields | `GET /rest/api/3/issue/createmeta/{key}/issuetypes/{typeId}`; corrected: a page `{startAt, maxResults, total, fields: [...]}` (also paged, max 200), each item `fieldId`, `key`, `name`, `required`, `operations`, `hasDefaultValue`, `allowedValues` |
| Search | `POST /rest/api/3/search/jql` `{jql, fields, maxResults, nextPageToken}` (confirmed); answer `{issues, nextPageToken, isLast}` - `nextPageToken` is null on the last page, so stop when it is absent; the old `/search` is not used |
| Issue | `GET/PUT /rest/api/3/issue/{key}`, `POST /rest/api/3/issue` (answer `{id, key, self}`) |
| Comments | `GET /rest/api/3/issue/{key}/comment` (corrected: paged, `{startAt, maxResults, total, comments: [...]}`), `POST` same path with the ADF `Comment` body, answer 201 with the comment (ADF body, `author.accountId`) |
| Transitions | `GET /rest/api/3/issue/{key}/transitions?expand=transitions.fields` answers `{transitions: [{id, name, to, hasScreen, isAvailable, fields: {fieldId: {required, name, schema, operations, allowedValues}}}]}` (corrected: `fields` is a map keyed by field id, not a list); `POST` same path `{transition:{id}, fields}` answers 204 |
| Fields | `GET /rest/api/3/field` |
| Link types, links | `GET /rest/api/3/issueLinkType` answers `{issueLinkTypes: [{id, name, inward, outward}]}`; `POST /rest/api/3/issueLink` `{type:{name}, inwardIssue:{key}, outwardIssue:{key}}` answers 201 with no body; existing links are in the issue's `issuelinks` |

Auth: HTTP Basic, `base64(email:token)`.

---

### Task 1: Package, config and credentials

**Files:**
- Create: `jira_sync/__init__.py`, `jira_sync/config.py`, `tests/test_jira_config.py`

**Interfaces:**
- Produces, in `jira_sync/config.py`:
  - `class ConfigError(Exception)`
  - `CONFIG_NAME = ".jira.json"`, `CREDENTIALS_PATH = "~/.config/jira-sync/credentials"`
  - `@dataclass(frozen=True) class Config: url: str; project: str; updates_dir: str = "jira/session-updates"; story_points_field: Optional[str] = None; path: str = ""`
  - `find_config(start: str) -> str`, `load_config(path: str) -> Config`
  - `load_credentials(environ: Optional[Mapping[str, str]] = None, credentials_path: Optional[str] = None) -> Tuple[str, str]`, returning `(email, token)`.

- [ ] **Step 1: Branch.** `git switch -c feat/jira-support` from `docs/jira-support-design`.
- [ ] **Step 2: Write failing tests** in `tests/test_jira_config.py`, modelled on `tests/test_config.py`:
  - `test_loads_url_project_and_defaults`: url is stripped of a trailing `/`; `updates_dir` defaults to `jira/session-updates`; `story_points_field` is `None`.
  - `test_unknown_key_is_rejected` (via `redmine_sync.keys.unknown_keys_problem`); `test_url_and_project_are_required`.
  - `test_http_url_is_rejected_unless_loopback`: `http://jira.example.com` raises, `http://127.0.0.1:8080` loads.
  - `test_story_points_field_must_look_like_customfield_digits`.
  - `test_credentials_from_environment_win`; `test_credentials_file_with_two_lines`.
  - `test_credentials_file_readable_by_others_is_refused` (mode 644 raises, message names `chmod 600`).
  - `test_placeholder_credentials_are_reported_not_filled_in`: a value starting `PREENCHE:` raises `ConfigError` containing "not filled in" and never returns it.
  - `test_missing_credentials_message_names_both_ways`.
- [ ] **Step 3: Run** `python3 -m unittest tests.test_jira_config -v`. Expected: FAIL, `ModuleNotFoundError: jira_sync`.
- [ ] **Step 4: Implement** `jira_sync/config.py` after `redmine_sync/config.py` (same walk-up, same mode check, same BOM handling). `jira_sync/__init__.py`: `from redmine_sync import __version__`.
- [ ] **Step 5: Run** the module again. Expected: PASS.
- [ ] **Step 6: Commit** `git add jira_sync tests/test_jira_config.py && git commit -m "Jira: package, config and credentials"`.

### Task 2: Fake Jira server and client

**Files:**
- Create: `tests/fake_jira.py`, `jira_sync/client.py`, `tests/test_jira_client.py`

**Interfaces:**
- Produces, in `jira_sync/client.py`:
  - Errors: `JiraError`; subclasses `AuthError`, `ForbiddenError`, `NotFoundError`, `RejectedError`, `TransportError` (same meaning as the Redmine ones; `RejectedError` carries Jira's `errorMessages` and `errors` text).
  - `class Client(base_url: str, email: str, token: str, timeout: float = 30)` with: `myself() -> dict`, `get_project(key) -> dict`, `issue_types(project) -> List[dict]`, `create_screen_fields(project, type_id) -> List[dict]`, `search(jql: str, fields: Sequence[str]) -> List[dict]` (follows `nextPageToken` to the end), `get_issue(key, fields: Sequence[str] = ("*all",)) -> dict`, `create_issue(fields: dict) -> dict`, `update_issue(key, fields: dict) -> None`, `list_comments(key) -> List[dict]`, `add_comment(key, adf: dict) -> dict`, `transitions(key) -> List[dict]` (with `expand=transitions.fields`), `do_transition(key, transition_id: str, fields: dict) -> None`, `list_fields() -> List[dict]`, `link_types() -> List[dict]`, `create_link(type_name, inward_key, outward_key) -> None`, `write_and_reread(key, fields) -> dict` (`update_issue` then `get_issue`).
- Produces, in `tests/fake_jira.py`: `class FakeJira` with `.start()` (returns self), `.stop()`, `.url`, `.email`, `.token`, and state the tests set directly (`projects`, `issue_types`, `issues`, `workflow`, `link_types`, `fields`); `demo_fake() -> FakeJira` seeded with project `SCRUM`, types Epic/Story/Task/Sub-task, workflow To Do → In Progress → Done, one account. Behaviours the fake must reproduce on purpose: `ignored_fields: Set[str]` (a PUT or POST succeeds but a listed field is silently not stored, the way Jira treats a field absent from the edit screen); `answer_html`; `redirect_to`; paged search of 2 issues per page; `requests` log of every call.

- [ ] **Step 1: Confirm the endpoint table.** Read the Atlassian Jira Cloud REST v3 docs for each row, edit the table above wherever it differs (search, createmeta, transition fields are the likely ones), and commit that edit with the plan.
- [ ] **Step 2: Write failing tests** in `tests/test_jira_client.py`, modelled on `tests/test_client.py`:
  - `test_basic_auth_header_carries_email_and_token`; `test_wrong_token_raises_auth_error`.
  - `test_search_follows_every_page` (5 issues, page size 2, all 5 returned).
  - `test_redirect_is_refused_and_the_token_is_not_followed`; `test_html_answer_raises_transport_error_naming_the_url`.
  - `test_400_raises_rejected_error_with_jira_message`; `test_404_raises_not_found`; `test_403_raises_forbidden`.
  - `test_write_and_reread_returns_the_stored_issue_not_the_sent_one` (with an ignored field the returned issue lacks it).
- [ ] **Step 3: Run** the module. Expected: FAIL on import.
- [ ] **Step 4: Implement** `tests/fake_jira.py` and `jira_sync/client.py`. The transport and redirect refusal follow `redmine_sync/client.py` (`_RefuseRedirects`, error mapping), with Basic auth and `/rest/api/3` paths.
- [ ] **Step 5: Run** the module. Expected: PASS.
- [ ] **Step 6: Commit** `Jira: fake server and client`.

### Task 3: Markdown to ADF

**Files:**
- Create: `jira_sync/adf.py`, `tests/test_jira_adf.py`

**Interfaces:**
- Produces: `markdown_to_adf(text: str) -> dict` (an ADF `doc`, version 1) and `adf_lines(node: dict) -> List[str]` (the text of each top-level block, one string per paragraph or heading, for marker detection).

- [ ] **Step 1: Write failing tests:**
  - `test_headings_paragraphs_lists_code_bold_inline_code_links`: each construct maps to its ADF node type (`heading` with `level`, `paragraph`, `bulletList`/`orderedList`, `codeBlock`, marks `strong`, `code`, `link`).
  - `test_unsupported_markdown_becomes_a_plain_paragraph_never_dropped`: a table row's text is still in the output.
  - `test_empty_text_gives_a_valid_empty_doc` and `test_unclosed_code_fence_is_closed_at_end` (Review Focus 5): the result has `type: "doc"`, `version: 1` and a `content` list.
  - `test_adf_lines_round_trips_a_marker_paragraph`: `adf_lines(markdown_to_adf("hi\n\n_jira-sync: s_"))[-1] == "_jira-sync: s_"`. The marker's underscores are literal text, not emphasis.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** a small line-based converter for the subset in the spec. Inline marks are parsed with regexes on `**x**`, `` `x` `` and `[t](u)`; the marker paragraph is built by the caller as one plain text node, so the converter does not treat `_..._` as emphasis.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `Jira: Markdown to ADF`.

### Task 4: Update file and session-close plan

**Files:**
- Create: `jira_sync/updatefile.py`, `jira_sync/plan.py`, `tests/test_jira_updatefile.py`, `tests/test_jira_plan.py`

**Interfaces:**
- Consumes: `Client` (Task 2), `Config` (Task 1), `adf_lines` (Task 3).
- Produces:
  - `updatefile.py`: `@dataclass(frozen=True) class Update: issue: str; note: str; status: Optional[str] = None; story_points: Optional[float] = None; transition_fields: Dict[str, Any]`; `UpdateFile(session, updates)`; `load_update_file(path)`, `parse_update_file(text, source)`, `UpdateFileError`. Row keys: `issue, note, status, story_points, transition_fields`; `issue` must match `[A-Z][A-Z0-9_]*-\d+`; `story_points` is a non-bool number >= 0; field values are non-empty strings or non-bool numbers.
  - `plan.py`: `marker_line(session) -> str` (`_jira-sync: <session>_`), `with_marker_adf(note: str, session: str) -> dict`, `has_marker(comments: List[dict], session: str, account_id: str) -> bool`, `session_warnings(session) -> List[str]`, `@dataclass Row` (update, `subject`, `current_status`, `transition_id: Optional[str]`, `transition_name`, `target_status`, `fields: Dict[str, Any]` ready for the API keyed by field id, `field_labels: List[Tuple[str, Any]]`, `story_points_target: Optional[float]`, `already_applied: bool`, `warnings: List[str]`), `@dataclass Plan` (session, rows, errors, account_id, warnings, `ok`), `build_plan(client, config, update_file) -> Plan`.

- [ ] **Step 1: Write failing tests**, modelled on `tests/test_updatefile.py` and `tests/test_plan.py`:
  - Updatefile: `test_rejects_unknown_keys`, `test_issue_must_be_a_jira_key` (`#12`, `scrum 1`, `EX-01.2` all rejected), `test_story_points_must_be_a_non_bool_number`, `test_transition_fields_values_must_be_text_or_number`.
  - Plan: `test_a_comment_with_the_marker_from_another_account_does_not_skip_the_row` (Review Focus 1); `test_own_marker_marks_the_row_already_applied`.
  - `test_status_is_reached_through_the_transition_that_leads_there`: row asks for "Done", the plan holds that transition's id and name.
  - `test_unreachable_status_lists_the_statuses_reachable_now`.
  - `test_two_transitions_to_the_same_status_are_an_error_listing_both_names` (Review Focus 2).
  - `test_missing_required_transition_field_blocks_and_lists_the_options` (a required `Resolution` with allowedValues Done / Won't Do).
  - `test_option_value_not_in_allowed_values_is_an_error`.
  - `test_unsupported_field_type_blocks_with_set_it_in_jira` (a required user-picker field).
  - `test_story_points_field_taken_from_config_else_found_by_exact_name_else_error` (two matches, zero matches).
  - `test_issue_of_another_project_is_an_error`; `test_two_rows_for_one_issue_are_an_error`; `test_bare_date_session_is_noted`.
  - `test_no_status_row_never_asks_for_transition_fields`.
- [ ] **Step 2: Run both modules.** Expected: FAIL.
- [ ] **Step 3: Implement.** Supported transition field = schema `string` with no `allowedValues`, schema `number`, or any non-array field with `allowedValues` (option, resolution, priority). Options match on the value's `name` or `value`, casefolded. Everything else is unsupported. A transition's `fields` entry counts as required when `required` is true and it has no default.
- [ ] **Step 4: Run both modules.** Expected: PASS.
- [ ] **Step 5: Commit** `Jira: update file and session-close plan`.

### Task 5: Session-close apply, render and `jira-sync`

**Files:**
- Create: `jira_sync/apply.py`, `jira_sync/render.py`, `jira_sync/cli.py`, `bin/jira-sync`, `tests/test_jira_apply.py`, `tests/test_jira_cli.py`

**Interfaces:**
- Consumes: `Plan`, `Row` (Task 4), `Client` (Task 2), `markdown_to_adf` (Task 3).
- Produces: `apply_plan(client, plan) -> Report` (`Report(outcomes, error)`; `Outcome(issue_key, key, result, verified, warnings)`); `render.format_plan(plan) -> str`, `format_report(report) -> str`; `cli.main(argv=None, environ=None, cwd=None, stdout=None, stderr=None, credentials_path=None) -> int` with commands `status <key>...` and `apply <file> [--write]`, plus `--config` and `--version` (prints `jira-sync <version>`).

- [ ] **Step 1: Write failing tests**, modelled on `tests/test_apply.py` and `tests/test_cli.py`:
  - `test_write_transitions_then_comments_and_verifies_each`: report lists `status To Do -> Done`, `comment recorded`, and each transition field.
  - `test_a_transition_that_did_not_land_stops_before_writing_anything_else_to_that_issue`.
  - `test_story_points_that_do_not_read_back_are_a_failure` (fake `ignored_fields={"customfield_10016"}`; Review Focus 4).
  - `test_story_points_untouched_when_the_row_does_not_set_them`.
  - `test_rerun_skips_rows_already_applied`.
  - `test_failure_midway_reports_how_many_were_written_and_says_to_rerun`.
  - Cli: `test_dry_run_writes_nothing` (the fake's `requests` log has no POST/PUT); `test_apply_write_exits_0`; `test_status_prints_status_points_and_available_transitions`; `test_unfilled_credentials_exit_1_with_not_filled_in`; `test_version_flag`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** Order per row: transition with its fields, read back (status, then each field exactly); comment as ADF ending in the marker paragraph, verified by `has_marker`; story points via `write_and_reread`, verified exactly. `format_plan` shows current status, the transition it would use, satisfied and missing required fields, story points, and the first 3 note lines, in the layout of `redmine_sync/render.py`. `bin/jira-sync` copies `bin/redmine-sync` with `jira_sync.cli`.
- [ ] **Step 4: Run both modules.** Expected: PASS.
- [ ] **Step 5: Commit** `Jira: session-close apply, render and jira-sync`.

### Task 6: Backlog file and backlog plan

**Files:**
- Create: `jira_sync/backlog_file.py`, `jira_sync/backlog_plan.py`, `tests/test_jira_backlog_file.py`, `tests/test_jira_backlog_plan.py`

**Interfaces:**
- Consumes: `Client` (Task 2).
- Produces:
  - `backlog_file.py`: `Node(id, subject, description, type, priority: Optional[str], parent: Optional[str], story_points: Optional[float])`, `Relation(type, from_id, to_id)`, `BacklogFile(project, nodes, relations)`, `BacklogFileError`, `load_backlog_file(path)`, `parse_backlog_file(text, source)`. Same validation as `redmine_sync/backlog_file.py` with these differences: node key `type` replaces `tracker`; `priority` and `story_points` optional; an existing issue is referenced as `#PROJ-123` (so a node id like `EX-01` never collides with a Jira key); relation types are `relates`, `duplicates`, `blocks`, and `precedes` fails with "Jira has no 'precedes' link".
  - `backlog_plan.py`: `PlannedNode(node, exists, issue_key, type_id, parent_ref)`, `PlannedRelation(relation, exists)`, `BacklogPlan(project_key, order, relations, errors, ok)`, `index_by_key(issues) -> Dict[str, List[str]]`, `resolve_key(index, key) -> Tuple[Optional[str], Optional[str]]`, `build_backlog_plan(client, file) -> BacklogPlan`.

- [ ] **Step 1: Write failing tests**, modelled on `tests/test_backlog_file.py` and `tests/test_backlog_plan.py`:
  - File: `test_precedes_is_rejected_with_a_clear_message`; `test_existing_issue_reference_is_hash_plus_key`; `test_priority_and_story_points_are_optional`; `test_subject_must_start_with_the_node_id`; `test_cycle_in_parents_is_an_error`.
  - Plan: `test_unknown_type_lists_the_projects_types`; `test_priority_set_but_not_on_the_create_screen_is_an_error_naming_node_and_field`; `test_priority_left_out_sends_and_reports_nothing`; `test_story_points_set_but_field_not_on_the_create_screen_is_an_error`.
  - `test_story_under_a_sub_task_is_a_hierarchy_error` and `test_sub_task_under_story_is_allowed` (rule: the child's `hierarchyLevel` must be lower than the parent's; an existing `#KEY` parent is fetched for its type).
  - `test_existing_node_found_by_summary_prefix_and_skipped`; `test_two_issues_with_the_same_prefix_are_ambiguous_not_picked`.
  - `test_link_type_missing_on_the_site_lists_what_the_site_has`; `test_relation_already_present_in_issuelinks_is_marked_existing`.
- [ ] **Step 2: Run both modules.** Expected: FAIL.
- [ ] **Step 3: Implement.** Existing nodes are found by listing the project with JQL and matching the summary prefix with `redmine_sync.plan.subject_key`-style logic (copy the 4-line function; do not import Redmine's plan module). Relation types map by link-type name, casefolded: `relates`→Relates, `duplicates`→Duplicate, `blocks`→Blocks.
- [ ] **Step 4: Run both modules.** Expected: PASS.
- [ ] **Step 5: Commit** `Jira: backlog file and plan`.

### Task 7: Backlog apply, parents, descriptions and `jira-backlog`

**Files:**
- Create: `jira_sync/backlog_apply.py`, `jira_sync/backlog_cli.py`, `bin/jira-backlog`, `tests/test_jira_backlog_apply.py`, `tests/test_jira_backlog_cli.py`; Modify: `jira_sync/render.py` (add the four backlog formatters).

**Interfaces:**
- Consumes: `BacklogPlan` (Task 6), `Client`, `markdown_to_adf`.
- Produces: `apply_backlog_plan(client, plan, write: bool) -> BacklogReport`, `fix_parents(client, file, write) -> ParentReport`, `update_descriptions(client, file, only: List[str], write) -> DescriptionReport`; `render.format_backlog_plan`, `format_backlog_report`, `format_parent_report`, `format_description_report`; `backlog_cli.main(...)` with `plan`, `apply [--write]`, `fix-parents [--write]`, `update-descriptions [--only IDS] [--write]` (`--write` requires `--only`), as `redmine_sync/backlog_cli.py`.

- [ ] **Step 1: Write failing tests**, modelled on `tests/test_backlog_apply.py` and `tests/test_backlog_cli.py`:
  - `test_creates_parents_before_children_and_reads_back_type_parent_priority_points`.
  - `test_failure_on_the_second_node_then_rerun_creates_only_the_missing_one` (Review Focus 3): after the first run stops, the second run reports the first as skipped and creates exactly one issue.
  - `test_parent_that_did_not_land_warns_to_run_fix_parents`.
  - `test_relation_direction_blocks`: after creating `A blocks B`, reading A back shows the link with B as outward issue. This pins the direction in the fake; Task 10 checks it on the real site.
  - `test_description_is_verified_only_as_present_and_the_report_says_content_not_compared`; `test_empty_description_is_not_verified_and_not_an_error`.
  - `test_fix_parents_reports_then_fixes_and_flags_unconfirmed`; `test_update_descriptions_write_requires_only`.
  - Cli: `test_dry_run_creates_nothing`; `test_project_mismatch_between_plan_and_config_exits_1`; `test_plan_exit_code_is_1_when_it_has_problems`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** after `redmine_sync/backlog_apply.py`. Create sends `fields` with `project.key`, `issuetype.id`, `summary`, ADF `description` (omitted when empty), `parent.key` (when set), `priority.name` and the story points field (only when the node sets them). Relations: `POST /issueLink`, direction chosen so the test above passes.
- [ ] **Step 4: Run both modules, then all tests.** Expected: PASS, Redmine's 197 included.
- [ ] **Step 5: Commit** `Jira: backlog apply and jira-backlog`.

### Task 8: Skills

**Files:**
- Create: `skills/jira-session-close/SKILL.md`, `skills/jira-backlog/SKILL.md`, `.agents/skills/jira-session-close`, `.agents/skills/jira-backlog` (symlinks, as the Redmine ones), `tests/test_jira_skill.py`

- [ ] **Step 1: Write failing tests** in `tests/test_jira_skill.py`, in the style of `tests/test_skill.py` (pin what the text says):
  - each skill's description names `.jira.json`, and its before-you-start section says to act only when `.jira.json` exists and to **stop and ask which tracker** when `.redmine.json` is also present;
  - neither skill mentions opening the credentials file; both say never to read, print or ask for them;
  - `jira-session-close`: asks the person for `transition_fields` values rather than guessing, says story points are set only when the person gives a value, and says to resume after a stop only by re-running the dry-run and asking again;
  - `jira-backlog`: states the validate, dry-run, ask order and that `#PROJ-123` references existing issues;
  - `.agents/skills/jira-*` are symlinks to `../../skills/jira-*`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Write both `SKILL.md` files** following the structure of the Redmine ones (same sections and safety rules, Jira commands and file formats from Tasks 4 to 7); create the symlinks with `ln -s`.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `Jira: skills`.

### Task 9: Docs and version (shared files, own commit)

**Files:**
- Modify: `README.md`, `AGENTS.md`, `TESTING.md`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `jira.example.json` (add `story_points_field` placeholder), `tests/test_version.py`

- [ ] **Step 1: Extend `tests/test_version.py`** with `test_jira_cli_version_matches_the_plugin_version` (`jira_sync.__version__ == plugin.json version`). Run it. Expected: PASS already (it imports Redmine's), proving the single source.
- [ ] **Step 2: Bump** `plugin.json` and `marketplace.json` to `0.4.0` and `redmine_sync/__init__.py` `__version__` to `"0.4.0"`; update both descriptions to mention Redmine and Jira Cloud.
- [ ] **Step 3: Docs.** README gains a Jira section: setup (token URL `https://id.atlassian.com/manage-profile/security/api-tokens`, credentials file lines, `.jira.json` with `story_points_field`), the two commands, the update-file and plan-file formats, the supported transition field types, and that `#PROJ-123` references existing issues. `AGENTS.md` and `TESTING.md` mention the new skills, `jira.example.json` and `jira-sync --version`. `jira.example.json` gains `"story_points_field": "PREENCHE: id do campo, ex. customfield_10016 (opcional; sem ele procura-se pelo nome)"`, and `load_config` must accept a `PREENCHE:` value there only as "not filled in" (test in `tests/test_jira_config.py`, `test_unfilled_story_points_field_is_reported`).
- [ ] **Step 4: Run all tests.** Expected: all pass.
- [ ] **Step 5: Commit** `Jira: docs and version 0.4.0`.

### Task 10: Live verification on the test site (only when the requester says go)

**Files:** none changed unless a defect is found; defects get a failing test in the owning task's module first.

- [ ] **Step 1: Ask the requester** for a go-ahead and confirm `.jira.json` in `Test files/test-auto-task-manager-jira/` and their filled credentials. Never open the credentials file.
- [ ] **Step 2:** From that folder run `jira-sync status SCRUM-1` (read-only). Expected: status, story points, transitions.
- [ ] **Step 3:** Run `jira-backlog plan` then `apply` on a 3-node plan (Epic, Story, Sub-task, one `blocks` relation, story points on the Story); show the dry-run to the requester; `--write` only after their yes. Check in Jira's UI: types, parents, points, and the **direction of the blocks link**; if reversed, fix the direction with a failing test first.
- [ ] **Step 4:** Run `jira-sync apply` with one row moving a story to Done with `story_points`, dry-run, requester's yes, then `--write`. Check status, comment with marker, points. Re-run `--write`; expected: row skipped.
- [ ] **Step 5:** Record what differed from the fake (endpoint shapes, ignored fields) as corrections to `tests/fake_jira.py`, each with a test. Commit.

## Execution notes

The three open PRs must merge before this branch becomes a PR; open it against `main` once they have.
