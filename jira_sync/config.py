from __future__ import annotations

import json
import os
import re
import stat
import urllib.parse
from dataclasses import dataclass
from typing import Mapping, Optional, Tuple

from redmine_sync.keys import unknown_keys_problem

CONFIG_NAME = ".jira.json"
CREDENTIALS_PATH = os.path.join("~", ".config", "jira-sync", "credentials")
_KNOWN_KEYS = {"url", "project", "updates_dir", "story_points_field"}
_CUSTOM_FIELD = re.compile(r"customfield_\d+")
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}
_PLACEHOLDER = "PREENCHE:"


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    url: str
    project: str
    updates_dir: str = "jira/session-updates"
    story_points_field: Optional[str] = None
    path: str = ""


def find_config(start: str) -> str:
    here = os.path.abspath(start)
    while True:
        candidate = os.path.join(here, CONFIG_NAME)
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(here)
        if parent == here:
            raise ConfigError(
                f"no {CONFIG_NAME} found in {start} or any parent directory - "
                f"create one with 'url' and 'project'")
        here = parent


def load_config(path: str) -> Config:
    try:
        with open(path, encoding="utf-8-sig") as f:
            raw = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path}: not valid JSON ({e})") from None
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: must be a JSON object")
    problem = unknown_keys_problem(raw, _KNOWN_KEYS, path)
    if problem:
        raise ConfigError(problem)
    for key in ("url", "project"):
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(f"{path}: '{key}' is required")
    url = raw["url"].strip().rstrip("/")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme == "http" and (parsed.hostname or "") not in _LOOPBACK:
        raise ConfigError(
            f"{path}: {url} is plain http - the API token would be sent in "
            f"cleartext; use https")
    updates_dir = raw.get("updates_dir", "jira/session-updates")
    if not isinstance(updates_dir, str) or not updates_dir.strip():
        raise ConfigError(f"{path}: 'updates_dir' must be a non-empty string")
    points = raw.get("story_points_field")
    if isinstance(points, str) and points.startswith(_PLACEHOLDER):
        raise ConfigError(
            f"{path}: 'story_points_field' is not filled in - set it to the field id "
            f"(for example customfield_10016) or delete the line")
    if points is not None and (not isinstance(points, str)
                               or not _CUSTOM_FIELD.fullmatch(points)):
        raise ConfigError(
            f"{path}: 'story_points_field' must look like customfield_10016 "
            f"(customfield_ and digits)")
    return Config(url=url, project=raw["project"].strip(), updates_dir=updates_dir,
                  story_points_field=points, path=path)


def load_credentials(environ: Optional[Mapping[str, str]] = None,
                     credentials_path: Optional[str] = None) -> Tuple[str, str]:
    """Return (email, token): from the environment when both are set, else from
    the credentials file (two KEY=VALUE lines, mode 600). A value still starting
    with PREENCHE: is the unfilled template and is reported, never returned."""
    env = os.environ if environ is None else environ
    email = env.get("JIRA_EMAIL", "").strip()
    token = env.get("JIRA_API_TOKEN", "").strip()
    if email and token:
        _refuse_placeholder(email, token, "the environment")
        return email, token
    path = os.path.expanduser(credentials_path or CREDENTIALS_PATH)
    if not os.path.isfile(path):
        raise ConfigError(
            f"no Jira credentials: set JIRA_EMAIL and JIRA_API_TOKEN, or put "
            f"JIRA_EMAIL=... and JIRA_API_TOKEN=... on two lines in "
            f"{CREDENTIALS_PATH} with mode 600")
    mode = stat.S_IMODE(os.stat(path).st_mode)
    if mode & 0o077:
        raise ConfigError(
            f"{path} is readable by other users (mode {mode:o}); "
            f"run: chmod 600 {path}")
    values = {}
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            values[name.strip()] = value.strip()
    email, token = values.get("JIRA_EMAIL", ""), values.get("JIRA_API_TOKEN", "")
    for name, value in (("JIRA_EMAIL", email), ("JIRA_API_TOKEN", token)):
        if not value:
            raise ConfigError(f"{path}: {name}=... is missing or empty")
    _refuse_placeholder(email, token, path)
    return email, token


def _refuse_placeholder(email: str, token: str, where: str) -> None:
    if email.startswith(_PLACEHOLDER) or token.startswith(_PLACEHOLDER):
        raise ConfigError(
            f"Jira credentials in {where} are not filled in - replace the "
            f"{_PLACEHOLDER} values with your email and API token")
