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


LETTER_GRADES: list[tuple[int, str, str, str]] = [
    (95, "A+", "Exceptional", "#059669"),
    (90, "A", "Excellent", "#10B981"),
    (85, "A-", "Very Good", "#14B8A6"),
    (80, "B+", "Good", "#06B6D4"),
    (75, "B", "Above Average", "#2563EB"),
    (70, "B-", "Moderate", "#3B82F6"),
    (65, "C+", "Fair", "#F59E0B"),
    (60, "C", "Needs Improvement", "#D97706"),
    (50, "D", "Poor", "#F97316"),
    (0, "F", "Critical", "#EF4444"),
]

TECHNICAL_CATEGORIES = {"technical", "page_experience"}
TECHNICAL_CHECK_IDS = {f"T{i:02d}" for i in range(1, 17)} | {"M01", "M02", "M03", "P01", "P02", "P03", "P04", "P05", "P06", "S01", "S03"}


def letter_grade(score: Optional[int]) -> str:
    if score is None:
        return "N/A"
    for lo, grade, _, _ in LETTER_GRADES:
        if score >= lo:
            return grade
    return "F"


def calculate_grade(score: Optional[int]) -> dict[str, str]:
    if score is None:
        return {"letter": "N/A", "band": "Unscorable", "color": "#94A3B8", "description": "Insufficient data to score"}
    for lo, grade, label, color in LETTER_GRADES:
        if score >= lo:
            return {"letter": grade, "band": label, "color": color, "description": f"{label} SEO performance ({grade})"}
    return {"letter": "F", "band": "Critical", "color": "#EF4444", "description": "Critical issues present"}


def score_technical_health(results: list[CheckResult]) -> dict[str, Any]:
    """Computes a dedicated Technical SEO Health Score (0-100%) focused strictly on
    crawlability, indexability, protocol security, server response, mobile rendering, and Core Web Vitals.
    Non-technical checks (e.g. content word count, local hours, conversion CTAs) are excluded.
    """
    tech_checks = [r for r in results if r.id in TECHNICAL_CHECK_IDS or r.category in TECHNICAL_CATEGORIES]
    live = [c for c in tech_checks if c.status != "NOT_APPLICABLE"]
    measured = [c for c in live if c.status != "UNMEASURED"]
    unmeasured = [c for c in live if c.status == "UNMEASURED"]
    meas_pts = sum(c.points for c in measured)
    unmeas_pts = sum(c.points for c in unmeasured)
    total_pts = meas_pts + unmeas_pts
    if meas_pts == 0:
        return {
            "score": None, "grade": "N/A", "letter_grade": "N/A",
            "measured_points": 0, "unmeasured_points": unmeas_pts,
            "passed_checks": 0, "total_checks": len(tech_checks),
            "coverage_pct": 0.0
        }
    earned = sum(c.points * credit_of(c) for c in measured)
    raw = 100.0 * earned / meas_pts
    cap = 100.0 - CONFIDENCE_CAP_COEFF * unmeas_pts
    final_score = max(0, min(100, round_half_up(min(raw, cap))))
    passed_cnt = sum(1 for c in measured if c.status == "PASS")
    return {
        "score": final_score,
        "grade": band(final_score),
        "letter_grade": letter_grade(final_score),
        "measured_points": meas_pts,
        "unmeasured_points": unmeas_pts,
        "points_earned": round(earned, 2),
        "passed_checks": passed_cnt,
        "total_checks": len(tech_checks),
        "coverage_pct": round(100.0 * meas_pts / total_pts, 1) if total_pts > 0 else 0.0
    }
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
    tech_health = score_technical_health(results)
    lg = letter_grade(overall)
    grade_meta = calculate_grade(overall)
    
    total_avail_pts = sum(r.points for r in results if r.status != "NOT_APPLICABLE")
    meas_pts = sum(r.points for r in results if r.status not in ("UNMEASURED", "NOT_APPLICABLE"))
    cov_pct = round(100.0 * meas_pts / total_avail_pts, 1) if total_avail_pts > 0 else 0.0

    return {
        "ruleset_version": RULESET_VERSION,
        "overall": overall,
        "grade": band(overall),
        "letter_grade": lg,
        "grade_details": grade_meta,
        "technical_health_score": tech_health.get("score"),
        "technical_health": tech_health,
        "measurement_coverage_pct": cov_pct,
        "maturity_level": lvl,
        "maturity_label": lbl,
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
