from __future__ import annotations

from typing import Collection, Optional


def unknown_keys_problem(row: dict, allowed: Collection[str], where: str) -> Optional[str]:
    unknown = set(row) - set(allowed)
    if not unknown:
        return None
    return f"{where}: unknown key(s): {', '.join(sorted(unknown))}"


def missing_keys_problem(row: dict, required: Collection[str], where: str) -> Optional[str]:
    missing = set(required) - set(row)
    if not missing:
        return None
    return f"{where}: missing required key(s): {', '.join(sorted(missing))}"
