"""Issue synthesis (spec PART H / I.2): every issue is backed by exactly one FAIL or WARN check.

Deterministic: severity comes from the ruleset (step down one level for WARN), priority from the
severity table, ordering from (severity_rank, category_weight desc, check_id). No AI involvement.
"""
from __future__ import annotations

from typing import Any

from .ruleset import load_ruleset
from .scoring import WEIGHTS, CheckResult

SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
BUSINESS_CATEGORIES = {"conversion", "local", "vertical"}


def synthesise(results: list[CheckResult], defs: dict[str, dict[str, Any]], category_names: dict[str, str]) -> list[dict[str, Any]]:
    rs = load_ruleset()
    step = rs["warn_severity_step_down"]
    s2p = rs["severity_to_priority"]
    qw_max = rs["quick_win_max_minutes"]
    rows = []
    for r in results:
        if r.status not in ("FAIL", "WARN"):
            continue
        d = defs[r.id]
        severity = d["severity"] if r.status == "FAIL" else step[d["severity"]]
        effort = int(d.get("effort") or 0)
        rows.append({
            "check_id": r.id,
            "check_name": d["name"],
            "status": "OPEN",
            "title": f"{d['name']}: {r.evidence.get('statement', '')}".strip(),
            "problem_description": f"{d['name']}: {r.evidence.get('statement', '')}".strip(),
            "category": r.category,
            "category_name": category_names.get(r.category, r.category),
            "severity": severity,
            "priority": s2p[severity],
            "priority_diverges_from_severity": False,
            "priority_divergence_reason": None,
            "urls": r.evidence.get("urls", []),
            "affected_url": (r.evidence.get("urls") or [""])[0],
            "seo_impact": d["reason"],
            "business_impact": d["reason"] if r.category in BUSINESS_CATEGORIES else "Indirect: affects how well the page can be found and understood.",
            "evidence": {"label": r.evidence_label, "statement": r.evidence.get("statement", ""), "values": r.evidence.get("values", {}),
                         "urls": r.evidence.get("urls", [])},
            "suggested_correction": d["fix"],
            "recommended_fix": d["fix"],
            "verification_method": f"Re-crawl affected URL(s) and verify check {r.id} ({d['name']}) passes.",
            "effort_minutes": effort or None,
            "needs_developer": bool(d.get("dev")),
            "quick_win": 0 < effort <= qw_max,
            "derived_from_checks": [r.id],
        })
    rows.sort(key=lambda x: (SEV_RANK.get(x["severity"], 3), -WEIGHTS.get(x["category"], 0), x["check_id"]))
    for i, row in enumerate(rows, 1):
        row["id"] = f"{i:02d}"
    return rows


def summarise(issues: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {k: sum(1 for i in issues if i["severity"] == k) for k in ("critical", "high", "medium", "low")}
    total = len(issues)
    pct = {k: (round(100 * v / total) if total else 0) for k, v in counts.items()}
    s = sum(pct.values())
    return {**counts, "total": total, "percentages": pct,
            "percentage_rounding_note": (f"Percentages sum to {s} because of rounding." if total and s != 100 else None)}


def quick_wins(issues: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = [i for i in issues if i["quick_win"]]
    out = []
    for n, i in enumerate(rows, 1):
        out.append({"n": n, "task": i["recommended_fix"], "check_id": i["check_id"], "issue_id": i["id"], "target": ", ".join(i["urls"][:3]) or "Site-wide",
                    "effort_minutes": i["effort_minutes"], "priority": i["priority"], "severity": i["severity"], "needs_developer": i["needs_developer"]})
    total = sum(r["effort_minutes"] or 0 for r in out)  # computed from the table, never from prose (spec I.3)
    return out, {"item_count": len(out), "total_minutes": total, "total_hours": round(total / 60, 2),
                 "critical_issues_closed": sum(1 for r in out if r["severity"] == "critical"),
                 "items_needing_no_developer": [r["n"] for r in out if not r["needs_developer"]]}
