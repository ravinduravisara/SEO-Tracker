"""Load and validate the versioned ruleset (spec PART K.3: ruleset as data, not code)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

RULESET_V1_FILE = Path(__file__).with_name("ruleset_v1.json")
RULESET_V2_FILE = Path(__file__).with_name("ruleset_v2.json")
RULESET_V1_VERSION = "1.0.0"
RULESET_V2_VERSION = "2.0.0"
DEFAULT_RULESET_VERSION = "2.0.0"


class RulesetError(ValueError):
    pass


@lru_cache(maxsize=8)
def load_ruleset(version: str = DEFAULT_RULESET_VERSION) -> dict[str, Any]:
    file = RULESET_V1_FILE if str(version or "").startswith("1.") else RULESET_V2_FILE
    if not file.exists():
        file = RULESET_V1_FILE
    rs = json.loads(file.read_text(encoding="utf-8"))
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


def category_checks(category: str, profile: str, version: str = DEFAULT_RULESET_VERSION) -> list[dict[str, Any]]:
    rs = load_ruleset(version)
    key = f"vertical:{profile}" if category == "vertical" else category
    if key not in rs["checks"]:
        # Fallback to general or b2b_product if profile check set is absent in requested ruleset
        fallback_key = f"vertical:general" if f"vertical:general" in rs["checks"] else "vertical:b2b_product"
        key = fallback_key if category == "vertical" else category
    return rs["checks"][key]


def check_def(category: str, check_id: str, profile: str, version: str = DEFAULT_RULESET_VERSION) -> dict[str, Any]:
    for c in category_checks(category, profile, version):
        if c["id"] == check_id:
            return c
    raise KeyError(check_id)


def threshold(name: str, version: str = DEFAULT_RULESET_VERSION) -> Any:
    return load_ruleset(version)["thresholds"][name]
