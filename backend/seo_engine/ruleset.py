"""Load and validate the versioned ruleset (spec PART K.3: ruleset as data, not code)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

RULESET_FILE = Path(__file__).with_name("ruleset_v1.json")


class RulesetError(ValueError):
    pass


@lru_cache(maxsize=1)
def load_ruleset() -> dict[str, Any]:
    rs = json.loads(RULESET_FILE.read_text(encoding="utf-8"))
    weights = rs["weights"]
    if sum(weights.values()) != 100:
        raise RulesetError(f"Category weights must sum to 100, got {sum(weights.values())}")
    for key, checks in rs["checks"].items():
        total = sum(c["points"] for c in checks)
        if total != 100:
            raise RulesetError(f"Checks in '{key}' must sum to 100 points, got {total}")
        ids = [c["id"] for c in checks]
        if len(ids) != len(set(ids)):
            raise RulesetError(f"Duplicate check id in '{key}'")
    for profile, spec in rs["vertical_profiles"].items():
        if f"vertical:{profile}" not in rs["checks"]:
            raise RulesetError(f"Vertical profile '{profile}' has no check set")
    return rs


def category_checks(category: str, profile: str) -> list[dict[str, Any]]:
    rs = load_ruleset()
    key = f"vertical:{profile}" if category == "vertical" else category
    return rs["checks"][key]


def check_def(category: str, check_id: str, profile: str) -> dict[str, Any]:
    for c in category_checks(category, profile):
        if c["id"] == check_id:
            return c
    raise KeyError(check_id)


def threshold(name: str) -> Any:
    return load_ruleset()["thresholds"][name]
