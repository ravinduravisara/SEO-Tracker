"""
SEO AUDIT ENGINE — reference scoring implementation (ruleset_version 1.0.0)
Companion to SEO-AUDIT-ENGINE-SPEC.md. Pure functions only: no I/O, no clock,
no randomness, no model calls. Same evidence in -> same score out.
"""
from dataclasses import dataclass, field
from typing import Literal, Optional

RULESET_VERSION = "1.0.0"

# --- PART O.1 constants (VERIFIED from the four source audits) -----------------
WEIGHTS = {
    "technical": 15, "on_page": 12, "content": 12, "keyword": 8,
    "internal_linking": 6, "image": 5, "structured_data": 6, "mobile": 6,
    "page_experience": 8, "local": 8, "vertical": 8, "conversion": 6,
}
assert sum(WEIGHTS.values()) == 100

BANDS = [(90, "Excellent"), (80, "Very Good"), (70, "Good"),
         (60, "Needs Improvement"), (40, "Poor"), (0, "Critical")]

MATURITY = [(80, 4, "Competitive"), (60, 3, "Optimised"), (40, 2, "Managed"),
            (25, 1, "Foundational"), (0, 0, "Pre-foundational")]

CREDIT = {"PASS": 1.0, "WARN": 0.5, "FAIL": 0.0}
CONFIDENCE_CAP_COEFF = 0.5          # tuning knob — see spec E.2 calibration note

THRESHOLDS = {
    "title_max_chars": 60, "title_min_chars": 30,
    "meta_description_max_chars": 155,
    "thin_page_words": 150, "commercial_page_target_words": 400,
    "h1_per_page": 1,
}

Status = Literal["PASS", "WARN", "FAIL", "UNMEASURED", "NOT_APPLICABLE"]


@dataclass
class CheckResult:
    id: str
    category: str
    points: int                  # out of the category's 100
    status: Status
    coverage: Optional[float] = None   # 0..1 for coverage-aggregated checks
    evidence_label: str = "Verified"   # Verified | Inferred | Recommendation | Not verifiable
    unmeasured_reason: Optional[str] = None


@dataclass
class CategoryScore:
    name: str
    weight: int
    score: Optional[int]         # None => UNSCORABLE
    provisional: bool
    measured_points: int
    unmeasured_points: int
    confidence_cap: float
    raw: Optional[float]


def _round_half_up(x: float) -> int:
    from decimal import Decimal, ROUND_HALF_UP
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def band(score: int) -> str:
    for lo, label in BANDS:
        if score >= lo:
            return label
    return "Critical"


def maturity(score: int):
    for lo, lvl, label in MATURITY:
        if score >= lo:
            return lvl, label
    return 0, "Pre-foundational"


def score_category(name: str, checks: list[CheckResult]) -> CategoryScore:
    """Spec PART E.2. UNMEASURED leaves the denominator; the cap is a ceiling, not a penalty."""
    live = [c for c in checks if c.status != "NOT_APPLICABLE"]
    measured = [c for c in live if c.status != "UNMEASURED"]
    unmeasured = [c for c in live if c.status == "UNMEASURED"]

    measured_pts = sum(c.points for c in measured)
    unmeasured_pts = sum(c.points for c in unmeasured)

    if measured_pts == 0:
        return CategoryScore(name, WEIGHTS[name], None, True, 0, unmeasured_pts, 0.0, None)

    earned = 0.0
    for c in measured:
        credit = c.coverage if c.coverage is not None else CREDIT[c.status]
        earned += c.points * credit

    raw = 100.0 * earned / measured_pts
    cap = 100.0 - CONFIDENCE_CAP_COEFF * unmeasured_pts
    s = max(0, min(100, _round_half_up(min(raw, cap))))
    return CategoryScore(name, WEIGHTS[name], s, bool(unmeasured), measured_pts,
                         unmeasured_pts, cap, raw)


def score_site(results: list[CheckResult]) -> dict:
    """Spec PART E.1 + E.5. Redistributes weight when a category is UNSCORABLE."""
    cats = {}
    for cat in WEIGHTS:
        cats[cat] = score_category(cat, [r for r in results if r.category == cat])

    scorable = {k: v for k, v in cats.items() if v.score is not None}
    if not scorable:
        return {"overall": None, "grade": None, "categories": cats,
                "error": "No scorable category"}

    total_w = sum(v.weight for v in scorable.values())
    redistributed = total_w != 100
    weighted_sum = sum(v.weight * v.score for v in scorable.values())
    overall = _round_half_up(weighted_sum / total_w) if redistributed \
        else _round_half_up(weighted_sum / 100)

    lvl, lbl = maturity(overall)
    return {
        "ruleset_version": RULESET_VERSION,
        "overall": overall, "grade": band(overall),
        "maturity_level": lvl, "maturity_label": lbl,
        "weighted_sum": weighted_sum,
        "weight_redistributed": redistributed,
        "categories": cats,
        "provisional_categories": [k for k, v in cats.items() if v.provisional],
    }


def project_potential(potentials: dict[str, int], current_overall: int) -> dict:
    """Spec PART E.4. Never emit this without the disclaimer."""
    assert set(potentials) == set(WEIGHTS), "a potential is required for every category"
    assert all(p < 100 for p in potentials.values()), "never project 100 for a category"
    ws = sum(WEIGHTS[c] * p for c, p in potentials.items())
    pot = _round_half_up(ws / 100)
    imp = pot - current_overall
    return {
        "potential": pot, "grade": band(pot), "weighted_sum": ws,
        "improvement_absolute": imp,
        "improvement_relative_pct": _round_half_up(100 * imp / current_overall),
        "disclaimer_required": True,
        "disclaimer": ("Estimate, not a guarantee. Assumes competent sequential "
                       "implementation. Not a prediction of rankings, traffic or revenue."),
    }


# --- Regression corpus (spec PART M.1) ----------------------------------------
CORPUS = {
    "dreamceylonvibetours.com": {
        "profile": "travel_tourism", "overall": 16, "potential": 80,
        "scores": {"technical": 22, "on_page": 18, "content": 8, "keyword": 12,
                   "internal_linking": 5, "image": 8, "structured_data": 5, "mobile": 35,
                   "page_experience": 35, "local": 15, "vertical": 8, "conversion": 10},
        "potentials": {"technical": 82, "on_page": 84, "content": 76, "keyword": 78,
                       "internal_linking": 80, "image": 76, "structured_data": 86,
                       "mobile": 82, "page_experience": 74, "local": 80, "vertical": 80,
                       "conversion": 84},
    },
    "ranjithautocables.com": {
        "profile": "b2b_product", "overall": 33, "potential": 83,
        "scores": {"technical": 42, "on_page": 38, "content": 28, "keyword": 34,
                   "internal_linking": 35, "image": 15, "structured_data": 4, "mobile": 45,
                   "page_experience": 45, "local": 25, "vertical": 30, "conversion": 32},
        "potentials": {"technical": 85, "on_page": 86, "content": 78, "keyword": 82,
                       "internal_linking": 84, "image": 78, "structured_data": 88,
                       "mobile": 84, "page_experience": 80, "local": 86, "vertical": 82,
                       "conversion": 86},
    },
    "voltedgepower-solutions.com": {
        "profile": "b2b_product", "overall": 47, "potential": 86,
        "scores": {"technical": 62, "on_page": 52, "content": 42, "keyword": 45,
                   "internal_linking": 45, "image": 38, "structured_data": 35, "mobile": 58,
                   "page_experience": 55, "local": 35, "vertical": 32, "conversion": 55},
        "potentials": {"technical": 88, "on_page": 88, "content": 82, "keyword": 85,
                       "internal_linking": 86, "image": 82, "structured_data": 90,
                       "mobile": 86, "page_experience": 82, "local": 86, "vertical": 84,
                       "conversion": 88},
    },
    "gkips.com": {
        "profile": "b2b_product", "overall": 29, "potential": 83,
        "scores": {"technical": 28, "on_page": 24, "content": 25, "keyword": 26,
                   "internal_linking": 20, "image": 10, "structured_data": 28, "mobile": 52,
                   "page_experience": 50, "local": 42, "vertical": 22, "conversion": 20},
        "potentials": {"technical": 82, "on_page": 85, "content": 78, "keyword": 82,
                       "internal_linking": 84, "image": 80, "structured_data": 86,
                       "mobile": 82, "page_experience": 78, "local": 88, "vertical": 82,
                       "conversion": 86},
    },
}


def regression_test() -> bool:
    ok = True
    for site, d in CORPUS.items():
        ws = sum(WEIGHTS[c] * s for c, s in d["scores"].items())
        got = _round_half_up(ws / 100)
        good = got == d["overall"]
        ok &= good
        line = f"{site:<30} sum(W*S)={ws:>5}  ->{got:>3}  expected {d['overall']:>3}  {'OK' if good else 'FAIL'}"
        if "potentials" in d:
            p = project_potential(d["potentials"], d["overall"])
            pgood = p["potential"] == d["potential"]
            ok &= pgood
            line += (f"   | potential {p['potential']:>3} expected {d['potential']:>3} "
                     f"(+{p['improvement_absolute']}, {p['improvement_relative_pct']}%) "
                     f"{'OK' if pgood else 'FAIL'}")
        print(line)
    return bool(ok)


def demo_unmeasured():
    """Page Experience with no PSI connector: P01-P04 UNMEASURED, P05/P06 PASS."""
    checks = [
        CheckResult("P01", "page_experience", 25, "UNMEASURED", unmeasured_reason="capability_missing:psi"),
        CheckResult("P02", "page_experience", 20, "UNMEASURED", unmeasured_reason="capability_missing:psi"),
        CheckResult("P03", "page_experience", 15, "UNMEASURED", unmeasured_reason="capability_missing:psi"),
        CheckResult("P04", "page_experience", 10, "UNMEASURED", unmeasured_reason="capability_missing:psi"),
        CheckResult("P05", "page_experience", 15, "PASS"),
        CheckResult("P06", "page_experience", 15, "PASS"),
    ]
    c = score_category("page_experience", checks)
    print(f"\nPage Experience, no PSI: raw={c.raw:.1f} cap={c.confidence_cap:.1f} "
          f"-> score={c.score} provisional={c.provisional}")
    print("  (corpus analysts published 50-55 here; see spec E.2 calibration note)")


if __name__ == "__main__":
    print(f"SEO scoring engine — ruleset {RULESET_VERSION}\n")
    print("Regression against the four-audit corpus (spec PART M.1):")
    passed = regression_test()
    demo_unmeasured()
    print(f"\nRESULT: {'ALL PASS' if passed else 'FAILURES PRESENT'}")
