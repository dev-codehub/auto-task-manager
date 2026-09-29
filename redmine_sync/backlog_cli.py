from __future__ import annotations

import argparse
import os
import sys
from typing import List, Mapping, Optional, TextIO

from . import __version__
from .backlog_apply import apply_backlog_plan, fix_parents, update_descriptions
from .backlog_file import BacklogFileError, load_backlog_file
from .backlog_plan import build_backlog_plan
from .client import Client, RedmineError
from .config import ConfigError, find_config, insecure_url_warning, load_api_key, load_config
from .render import (format_backlog_plan, format_backlog_report, format_description_report,
                     format_parent_report)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="redmine-backlog",
        description="Create features/stories/tasks, relations, and fix parents from a "
                    "JSON plan file. apply is a dry run unless --write is given.")
    parser.add_argument("--version", action="version", version=f"redmine-backlog {__version__}")
    parser.add_argument("--config", help="path to .redmine.json (default: nearest one upward)")
    sub = parser.add_subparsers(dest="command")
    sub.required = True

    plan_cmd = sub.add_parser("plan", help="read-only: validate a plan file against the instance")
    plan_cmd.add_argument("plan_file")

    apply_cmd = sub.add_parser("apply", help="create issues and relations from a plan file")
    apply_cmd.add_argument("plan_file")
    apply_cmd.add_argument("--write", action="store_true", help="apply (default: dry run)")

    fix_cmd = sub.add_parser("fix-parents", help="report or fix parents against a plan file")
    fix_cmd.add_argument("plan_file")
    fix_cmd.add_argument("--write", action="store_true", help="fix (default: report only)")

    desc_cmd = sub.add_parser("update-descriptions",
                              help="update descriptions of already-created issues")
    desc_cmd.add_argument("plan_file")
    desc_cmd.add_argument("--only", help="comma-separated node ids (required with --write)")
    desc_cmd.add_argument("--write", action="store_true", help="apply (default: dry run)")

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
        if config.issue_key == "id_only":
            raise ConfigError(
                f"{config.path}: 'issue_key' is 'id_only' - redmine-backlog matches a plan "
                f"file's node ids against existing issues by subject prefix and cannot be "
                f"used safely in a repository configured for #number keys only")
        warning = insecure_url_warning(config)
        if warning:
            print(f"warning: {warning}", file=err)
        client = Client(config.url, load_api_key(environ, credentials_path))
        path = args.plan_file if os.path.isabs(args.plan_file) else os.path.join(here, args.plan_file)
        file = load_backlog_file(path)
        if file.project != config.project:
            raise ConfigError(f"{path}: project '{file.project}' does not match "
                              f"'{config.project}' in {config.path}")

        if args.command == "plan":
            return _plan(client, file, out)
        if args.command == "apply":
            return _apply(client, file, args.write, out)
        if args.command == "fix-parents":
            return _fix_parents(client, file, args.write, out)
        if args.command == "update-descriptions":
            return _update_descriptions(client, file, args.only, args.write, out, err)
    except (ConfigError, BacklogFileError, RedmineError, OSError) as e:
        print(f"error: {e}", file=err)
        return 1
    return 1


def _plan(client: Client, file, out: TextIO) -> int:
    plan = build_backlog_plan(client, file)
    print(format_backlog_plan(plan), file=out)
    return 0 if plan.ok else 1


def _apply(client: Client, file, write: bool, out: TextIO) -> int:
    plan = build_backlog_plan(client, file)
    print(format_backlog_plan(plan), file=out)
    if not plan.ok:
        return 1
    if not write:
        print("\ndry run - nothing written. Re-run with --write to apply.", file=out)
        return 0
    print("\nwriting...", file=out)
    report = apply_backlog_plan(client, plan, write=True)
    print(format_backlog_report(report), file=out)
    return 1 if report.error else 0


def _fix_parents(client: Client, file, write: bool, out: TextIO) -> int:
    report = fix_parents(client, file, write=write)
    print(format_parent_report(report), file=out)
    if not write and report.wrong:
        print(f"\nReport only. Re-run with --write to set those {len(report.wrong)} parents.",
             file=out)
    return 1 if report.error else 0


def _update_descriptions(client: Client, file, only: Optional[str], write: bool,
                         out: TextIO, err: TextIO) -> int:
    names = [x.strip() for x in only.split(",") if x.strip()] if only else []
    if write and not names:
        print("error: --write requires --only=ID,ID (at least one id) - this operation "
             "has no other safety net once it writes", file=err)
        return 1
    try:
        report = update_descriptions(client, file, names, write=write)
    except ValueError as e:
        print(f"error: {e}", file=err)
        return 1
    print(format_description_report(report), file=out)
    if not write:
        print("\ndry run - nothing written. Re-run with --write to apply.", file=out)
    return 1 if report.error else 0
