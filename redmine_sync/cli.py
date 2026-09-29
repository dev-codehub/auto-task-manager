from __future__ import annotations

import argparse
import os
import sys
from typing import List, Mapping, Optional, TextIO

from . import __version__
from .apply import apply_plan
from .client import Client, NotFoundError, RedmineError
from .config import (Config, ConfigError, find_config, insecure_url_warning, load_api_key,
                     load_config)
from .plan import IssueIndex, ResolveError, build_plan
from .render import format_plan, format_report
from .updatefile import UpdateFileError, load_update_file


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="redmine-sync",
        description="Reviewed session-close updates to Redmine. "
                    "apply is a dry run unless --write is given.")
    parser.add_argument("--version", action="version", version=f"redmine-sync {__version__}")
    parser.add_argument("--config", help="path to .redmine.json (default: nearest one upward)")
    sub = parser.add_subparsers(dest="command")
    sub.required = True
    status = sub.add_parser("status", help="read-only: status, %% Done and last comment")
    status.add_argument("issues", nargs="+", help="subject prefixes or #numbers")
    apply = sub.add_parser("apply", help="validate an update file and show the plan")
    apply.add_argument("update_file")
    apply.add_argument("--write", action="store_true", help="apply the plan (default: dry run)")
    return parser


def main(argv: Optional[List[str]] = None, environ: Optional[Mapping[str, str]] = None,
         cwd: Optional[str] = None, stdout: Optional[TextIO] = None,
         stderr: Optional[TextIO] = None, credentials_path: Optional[str] = None) -> int:
    out = stdout or sys.stdout
    err = stderr or sys.stderr
    here = cwd or os.getcwd()
    args = _parser().parse_args(argv)
    try:
        config = load_config(args.config or find_config(here))
        warning = insecure_url_warning(config)
        if warning:
            print(f"warning: {warning}", file=err)
        client = Client(config.url, load_api_key(environ, credentials_path))
        try:
            project_id = client.get_project(config.project)["id"]
        except NotFoundError:
            raise ConfigError(f"project '{config.project}' in {config.path} does not exist "
                              f"or is not visible to you") from None
        if args.command == "status":
            return _status(client, config, project_id, args.issues, out)
        path = args.update_file if os.path.isabs(args.update_file) \
            else os.path.join(here, args.update_file)
        return _apply(client, config, project_id, path, args.write, out)
    except (ConfigError, UpdateFileError, RedmineError, OSError) as e:
        print(f"error: {e}", file=err)
        return 1


def _status(client: Client, config: Config, project_id: int, keys: List[str],
            out: TextIO) -> int:
    index = IssueIndex(client, config, project_id)
    failed = False
    for key in keys:
        try:
            issue_id = index.resolve(key)
            issue = client.get_issue(issue_id, include=("journals",))
        except ResolveError as e:
            print(f"{key}: {e}", file=out)
            failed = True
            continue
        except NotFoundError:
            print(f"{key}: does not exist or is not visible to you", file=out)
            failed = True
            continue
        notes = [j["notes"] for j in issue.get("journals", []) if (j.get("notes") or "").strip()]
        last = notes[-1].strip().splitlines()[0] if notes else "(none)"
        done = issue.get("done_ratio")
        print(f"#{issue['id']}  {key}  {issue.get('subject', '')}", file=out)
        print(f"  status  {issue['status']['name']}", file=out)
        print(f"  done    {'-' if done is None else f'{done}%'}", file=out)
        print(f"  last comment: {last}", file=out)
    return 1 if failed else 0


def _apply(client: Client, config: Config, project_id: int, path: str, write: bool,
           out: TextIO) -> int:
    plan = build_plan(client, config, load_update_file(path), project_id)
    print(format_plan(plan), file=out)
    if not plan.ok:
        return 1
    if not write:
        print("\ndry run - nothing written. Re-run with --write to apply.", file=out)
        return 0
    print("\nwriting...", file=out)
    report = apply_plan(client, plan)
    print(format_report(report), file=out)
    return 1 if report.error else 0
