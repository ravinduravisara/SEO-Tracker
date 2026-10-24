"""Pre-release verification gate (spec I.10) and fabrication scan (spec G.4).

Re-derives every number in the payload from its inputs and scans text for invented metrics.
A report must not be released when the gate fails.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from .scoring import WEIGHTS, round_half_up

FABRICATION_PATTERNS = {
    "domain/page authority": r"(?:domain|page)\s+(?:authority|rating)\s*(?:of|:|=)?\s*\d",
    "search volume": r"\b\d[\d,]*\s*(?:monthly\s+)?(?:searches|search volume)",
    "traffic figure": r"\b\d[\d,]*\s*(?:organic\s+)?(?:visits|visitors|sessions|pageviews)",
    "backlinks": r"\b\d[\d,]*\s*(?:backlinks|referring domains|inbound links)",
    "ranking position": r"\brank(?:s|ed|ing)?\s*(?:at|#|number|no\.?|position)\s*\d",
    "position N": r"\bposition\s+#?\d+\b",
    "page 1 of Google": r"\bpage\s*(?:one|1)\s+of\s+Google\b",
    "CWV seconds": r"\b(?:LCP|INP|FID|TTFB)\b[^.<]{0,24}\d+(?:\.\d+)?\s*(?:s|ms|seconds)",
    "CLS value": r"\bCLS\b[^.<]{0,24}0\.\d",
    "lighthouse score": r"\b(?:Lighthouse|PageSpeed)\s*(?:score)?\s*(?:of|:|=)?\s*\d{1,3}\b",
    "indexed pages": r"\b\d[\d,]*\s*(?:pages?\s+)?indexed\b",
    "keyword difficulty": r"\b(?:keyword\s+)?difficulty\b[^.<]{0,20}\d",
    "CTR figure": r"\bCTR\b[^.<]{0,20}\d+(?:\.\d+)?\s*%",
    "conversion rate": r"\bconversion rate\b[^.<]{0,24}\d+(?:\.\d+)?\s*%",
}
_COMPILED = {k: re.compile(v, re.I) for k, v in FABRICATION_PATTERNS.items()}


def fabrication_hits(texts: Iterable[str], allowed_marker: str = "Source:") -> list[dict[str, str]]:
    """Return every pattern hit. Lines carrying a verified-source citation are adjudicated as permitted."""
    hits = []
    for t in texts:
        for line in str(t or "").splitlines():
            for name, rx in _COMPILED.items():
                m = rx.search(line)
                if m:
                    hits.append({"pattern": name, "match": m.group(0), "line": line[:200],
                                 "permitted": allowed_marker in line or "Not directly verifiable" in line or "not measured" in line.lower()})
    return hits


def run_gate(payload: dict[str, Any], narrative_texts: Iterable[str] = ()) -> dict[str, Any]:
    failures: list[str] = []
    score = payload["score"]
    cats = payload["categories"]

    # Gate 2: weighted arithmetic re-derived.
    if sum(c["weight"] for c in cats) != 100 or sum(WEIGHTS.values()) != 100:
        failures.append("Category weights do not sum to 100.")
    scorable = [c for c in cats if c["score"] is not None]
    for c in scorable:
        if c["weighted_contribution"] != c["weight"] * c["score"]:
            failures.append(f"{c['id']}: W*S mismatch.")
    ws = sum(c["weight"] * c["score"] for c in scorable)
    total_w = sum(c["weight"] for c in scorable)
    if scorable:
        expected = round_half_up(ws / 100) if total_w == 100 else round_half_up(ws / total_w)
        if ws != score["weighted_sum"] or expected != score["overall"]:
            failures.append(f"Overall score mismatch: recomputed {expected} from {ws}, payload {score['overall']}.")

    # Category scores re-derived from their checks.
    from .scoring import CheckResult, score_category
    by_cat: dict[str, list[CheckResult]] = {}
    for ch in payload["checks"]:
        by_cat.setdefault(ch["category"], []).append(CheckResult(ch["id"], ch["category"], ch["points_available"], ch["status"], ch.get("coverage")))
        if ch["status"] in ("UNMEASURED", "NOT_APPLICABLE") and ch["points_earned"] != 0:
            failures.append(f"{ch['id']}: unmeasured/not-applicable check earned points.")
    for c in cats:
        again = score_category(c["id"], by_cat.get(c["id"], [])).score
        if again != c["score"]:
            failures.append(f"{c['id']}: category score {c['score']} does not re-derive ({again}).")

    # Gate 3: potential re-derived.
    pot = score.get("potential")
    if pot:
        pws = sum(c["weight"] * c["potential_score"] for c in cats)
        if pws != pot["weighted_sum"] or round_half_up(pws / 100) != pot["overall"]:
            failures.append("Potential score does not re-derive.")
        if any(c["potential_score"] >= 100 for c in cats):
            failures.append("A category potential is 100 (never project 100).")
        if not pot.get("disclaimer"):
            failures.append("Potential score emitted without its disclaimer.")

    # Gates 4, 5, 7: quick-win totals, severity counts, issue IDs and backing checks.
    issues = payload["issues"]
    ids = [i["id"] for i in issues]
    if ids != [f"{n:02d}" for n in range(1, len(ids) + 1)]:
        failures.append("Issue IDs are not sequential/unique.")
    status_by_check = {c["id"]: c["status"] for c in payload["checks"]}
    for i in issues:
        if status_by_check.get(i["check_id"]) not in ("FAIL", "WARN"):
            failures.append(f"Issue {i['id']} has no failed/warned backing check.")
    summ = payload["issue_summary"]
    for k in ("critical", "high", "medium", "low"):
        if summ[k] != sum(1 for i in issues if i["severity"] == k):
            failures.append(f"Severity count '{k}' does not match the issue table.")
    qw_total = sum(q["effort_minutes"] or 0 for q in payload.get("quick_wins", []))
    if qw_total != payload.get("quick_win_totals", {}).get("total_minutes", qw_total):
        failures.append("Quick-win total does not match the table.")

    # Gate 8: fabrication scan over narrative text (numbers are only allowed from the engine).
    hits = fabrication_hits(narrative_texts)
    blocking = [h for h in hits if not h["permitted"]]
    if blocking:
        failures.append(f"{len(blocking)} unadjudicated fabrication-pattern hit(s) in narrative text.")

    return {"passed": not failures, "failures": failures, "fabrication_scan_hits": len(hits),
            "fabrication_blocking_hits": blocking[:10], "arithmetic_verified": not any("mismatch" in f or "re-derive" in f for f in failures)}
