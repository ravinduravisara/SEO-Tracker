"""Deterministic scoring engine (spec PART E). A faithful port of tests/reference/seo_scoring_engine.py.

Pure functions only: no I/O at call time, no clock, no randomness, no model calls.
Constants come from the versioned ruleset so there is exactly one source of truth.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal, Optional

from .ruleset import load_ruleset

_RS = load_ruleset()
RULESET_VERSION: str = _RS["ruleset_version"]
WEIGHTS: dict[str, int] = dict(_RS["weights"])
BANDS: list[tuple[int, str]] = [tuple(b) for b in _RS["bands"]]
MATURITY: list[tuple[int, int, str]] = [tuple(m) for m in _RS["maturity"]]
CREDIT: dict[str, float] = dict(_RS["credit"])
CONFIDENCE_CAP_COEFF: float = float(_RS["confidence_cap_coefficient"])  # spec E.2 tuning knob; v1.0 = 0.5
POTENTIAL_CEILING: int = int(_RS["potential_ceiling"])
assert sum(WEIGHTS.values()) == 100

Status = Literal["PASS", "WARN", "FAIL", "UNMEASURED", "NOT_APPLICABLE"]
POTENTIAL_DISCLAIMER = ("This is an estimate, not a guarantee. It assumes competent sequential implementation and projects "
                        "what the same methodology would return against the completed site. It is not a prediction of "
                        "rankings, traffic or revenue.")


@dataclass
class CheckResult:
    id: str
    category: str
    points: int
    status: Status
    coverage: Optional[float] = None
    evidence_label: str = "Verified"
    unmeasured_reason: Optional[str] = None
    name: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class CategoryScore:
    name: str
    weight: int
    score: Optional[int]
    provisional: bool
    measured_points: int
    unmeasured_points: int
    confidence_cap: float
    raw: Optional[float]


def round_half_up(x: float) -> int:
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def band(score: int) -> str:
    for lo, label in BANDS:
        if score >= lo:
            return label
    return "Critical"


def maturity(score: int) -> tuple[int, str]:
    for lo, lvl, label in MATURITY:
        if score >= lo:
            return lvl, label
    return 0, "Pre-foundational"


def credit_of(c: CheckResult) -> float:
    return c.coverage if c.coverage is not None else CREDIT[c.status]


def score_category(name: str, checks: list[CheckResult]) -> CategoryScore:
    """Spec E.2: UNMEASURED leaves the denominator; the cap is a ceiling, not a penalty."""
    live = [c for c in checks if c.status != "NOT_APPLICABLE"]
    measured = [c for c in live if c.status != "UNMEASURED"]
    unmeasured = [c for c in live if c.status == "UNMEASURED"]
    measured_pts = sum(c.points for c in measured)
    unmeasured_pts = sum(c.points for c in unmeasured)
    if measured_pts == 0:
        return CategoryScore(name, WEIGHTS[name], None, True, 0, unmeasured_pts, 0.0, None)
    # Accumulate with a plain += loop exactly like the reference implementation. Python 3.12+ sum() uses
    # compensated float summation, which can differ in the last bit and flip a .5 rounding (e.g. 59.5 vs 59.4999...).
    earned = 0.0
    for c in measured:
        earned += c.points * credit_of(c)
    raw = 100.0 * earned / measured_pts
    cap = 100.0 - CONFIDENCE_CAP_COEFF * unmeasured_pts
    s = max(0, min(100, round_half_up(min(raw, cap))))
    return CategoryScore(name, WEIGHTS[name], s, bool(unmeasured), measured_pts, unmeasured_pts, cap, raw)


def score_site(results: list[CheckResult]) -> dict[str, Any]:
    """Spec E.1 + E.5. One rounding, at the end. Weight is redistributed only for UNSCORABLE categories."""
    cats = {cat: score_category(cat, [r for r in results if r.category == cat]) for cat in WEIGHTS}
    scorable = {k: v for k, v in cats.items() if v.score is not None}
    if not scorable:
        return {"overall": None, "grade": None, "categories": cats, "error": "No scorable category"}
    total_w = sum(v.weight for v in scorable.values())
    redistributed = total_w != 100
    weighted_sum = sum(v.weight * v.score for v in scorable.values())
    overall = round_half_up(weighted_sum / total_w) if redistributed else round_half_up(weighted_sum / 100)
    lvl, lbl = maturity(overall)
    return {
        "ruleset_version": RULESET_VERSION,
        "overall": overall, "grade": band(overall),
        "maturity_level": lvl, "maturity_label": lbl,
        "weighted_sum": weighted_sum,
        "weight_total": total_w,
        "weight_redistributed": redistributed,
        "categories": cats,
        "provisional_categories": [k for k, v in cats.items() if v.provisional],
    }


def project_potential(potentials: dict[str, int], current_overall: int) -> dict[str, Any]:
    """Spec E.4. Same weights, same formula; never project 100; never emitted without the disclaimer."""
    assert set(potentials) == set(WEIGHTS), "a potential is required for every category"
    assert all(p < 100 for p in potentials.values()), "never project 100 for a category"
    ws = sum(WEIGHTS[c] * p for c, p in potentials.items())
    pot = round_half_up(ws / 100)
    imp = pot - current_overall
    return {
        "overall": pot, "grade": band(pot), "weighted_sum": ws,
        "improvement_absolute": imp,
        "improvement_relative_pct": round_half_up(100 * imp / current_overall) if current_overall else None,
        "disclaimer_required": True,
        "disclaimer": POTENTIAL_DISCLAIMER,
    }


def projected_category(name: str, checks: list[CheckResult], current: Optional[int]) -> int:
    """DERIVED deterministic projection (the source audits projected by judgment).

    Every measured FAIL/WARN check is assumed fixed (PASS); UNMEASURED checks are assumed to be measured
    and to pass (spec E.4 allows this, with the 'before figure could move' note). The result is capped at
    POTENTIAL_CEILING (spec: never project 100) and never below the current score.
    """
    fixed = [CheckResult(c.id, c.category, c.points, "PASS" if c.status in ("FAIL", "WARN", "PASS", "UNMEASURED") else c.status)
             for c in checks]
    best = score_category(name, fixed).score
    best = POTENTIAL_CEILING if best is None else min(best, POTENTIAL_CEILING)
    return min(99, max(best, current or 0))  # a category already at 100 is still projected below 100
