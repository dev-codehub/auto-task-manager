from __future__ import annotations

import json
import os
import stat
import urllib.parse
from dataclasses import dataclass
from typing import Mapping, Optional

from .keys import unknown_keys_problem

CONFIG_NAME = ".redmine.json"
CREDENTIALS_PATH = os.path.join("~", ".config", "redmine-sync", "credentials")
TEXT_FORMATS = ("textile", "markdown")
ISSUE_KEYS = ("subject_prefix", "id_only")
_KNOWN_KEYS = {"url", "project", "text_format", "issue_key", "updates_dir"}


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    url: str
    project: str
    text_format: str = "textile"
    issue_key: str = "subject_prefix"
    updates_dir: str = "redmine/session-updates"
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
    text_format = raw.get("text_format", "textile")
    if text_format not in TEXT_FORMATS:
        raise ConfigError(f"{path}: 'text_format' must be one of {', '.join(TEXT_FORMATS)}")
    issue_key = raw.get("issue_key", "subject_prefix")
    if issue_key not in ISSUE_KEYS:
        raise ConfigError(f"{path}: 'issue_key' must be one of {', '.join(ISSUE_KEYS)}")
    updates_dir = raw.get("updates_dir", "redmine/session-updates")
    if not isinstance(updates_dir, str) or not updates_dir.strip():
        raise ConfigError(f"{path}: 'updates_dir' must be a non-empty string")
    return Config(url=raw["url"].strip().rstrip("/"), project=raw["project"].strip(),
                  text_format=text_format, issue_key=issue_key,
                  updates_dir=updates_dir, path=path)


_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def insecure_url_warning(config: Config) -> Optional[str]:
    parsed = urllib.parse.urlsplit(config.url)
    if parsed.scheme == "http" and (parsed.hostname or "") not in _LOOPBACK:
        return (f"{config.path or 'url'}: {config.url} is plain http - the API key "
                f"is sent in cleartext; use https if the instance offers it")
    return None


def load_api_key(environ: Optional[Mapping[str, str]] = None,
                 credentials_path: Optional[str] = None) -> str:
    env = os.environ if environ is None else environ
    key = env.get("REDMINE_API_KEY", "").strip()
    if key:
        return key
    path = os.path.expanduser(credentials_path or CREDENTIALS_PATH)
    if not os.path.isfile(path):
        raise ConfigError(
            f"no API key: set REDMINE_API_KEY, or put the key alone in "
            f"{CREDENTIALS_PATH} with mode 600")
    mode = stat.S_IMODE(os.stat(path).st_mode)
    if mode & 0o077:
        raise ConfigError(
            f"{path} is readable by other users (mode {mode:o}); "
            f"run: chmod 600 {path}")
    with open(path, encoding="utf-8-sig") as f:
        key = f.read().strip()
    if not key:
        raise ConfigError(f"{path} is empty")
    return key
