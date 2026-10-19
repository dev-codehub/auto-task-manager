from __future__ import annotations

import argparse
import os
import sys
from typing import List, Mapping, Optional, TextIO

from . import __version__
from .apply import apply_plan, display
from .client import Client, JiraError, NotFoundError
from .config import Config, ConfigError, find_config, load_config, load_credentials
from .plan import _story_points_field, build_plan
from .render import format_plan, format_report
from .updatefile import UpdateFileError, load_update_file


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jira-sync",
        description="Reviewed session-close updates to Jira Cloud. "
                    "apply is a dry run unless --write is given.")
    parser.add_argument("--version", action="version", version=f"jira-sync {__version__}")
    parser.add_argument("--config", help="path to .jira.json (default: nearest one upward)")
    sub = parser.add_subparsers(dest="command")
    sub.required = True
    status = sub.add_parser("status",
                            help="read-only: status, story points and available transitions")
    status.add_argument("issues", nargs="+", help="issue keys such as SCRUM-12")
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
        email, token = load_credentials(environ, credentials_path)
        client = Client(config.url, email, token)
        try:
            client.get_project(config.project)
        except NotFoundError:
            raise ConfigError(f"project '{config.project}' in {config.path} does not exist "
                              f"or is not visible to you") from None
        if args.command == "status":
            return _status(client, config, args.issues, out)
        path = args.update_file if os.path.isabs(args.update_file) \
            else os.path.join(here, args.update_file)
        return _apply(client, config, path, args.write, out)
    except (ConfigError, UpdateFileError, JiraError, OSError) as e:
        print(f"error: {e}", file=err)
        return 1


def _status(client: Client, config: Config, keys: List[str], out: TextIO) -> int:
    points_field, points_problem = _story_points_field(client, config)
    wanted = ("summary", "status") + ((points_field,) if points_field else ())
    failed = False
    for key in keys:
        try:
            fields = client.get_issue(key, wanted).get("fields") or {}
            transitions = client.transitions(key)
        except NotFoundError:
            print(f"{key}: does not exist or is not visible to you", file=out)
            failed = True
            continue
        if points_field is None:
            points = f"unknown - {points_problem}"
        else:
            value = fields.get(points_field)
            points = "-" if value is None else display(value)
        moves = ", ".join(f"{t.get('name')} -> {(t.get('to') or {}).get('name')}"
                          for t in transitions) or "(none)"
        print(f"{key}  {fields.get('summary', '')}".rstrip(), file=out)
        print(f"  status        {(fields.get('status') or {}).get('name', '?')}", file=out)
        print(f"  story points  {points}", file=out)
        print(f"  transitions   {moves}", file=out)
    return 1 if failed else 0


def _apply(client: Client, config: Config, path: str, write: bool, out: TextIO) -> int:
    plan = build_plan(client, config, load_update_file(path))
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
