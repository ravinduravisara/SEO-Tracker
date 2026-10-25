"""Issue synthesis (spec PART H / I.2): every issue is backed by exactly one FAIL or WARN check.

Deterministic: severity comes from the ruleset (step down one level for WARN), priority from the
severity table, ordering from (severity_rank, category_weight desc, check_id). No AI involvement.
Enhanced in Phase 7 for dual-level issue counting (Unique Issues vs Affected Instances)
and structured Finding model.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional

from .ruleset import load_ruleset
from .scoring import WEIGHTS, CheckResult

SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "notice": 4, "unmeasured": 5}
BUSINESS_CATEGORIES = {"conversion", "local", "vertical"}

# Standardized severity enumeration
SEVERITY_LEVELS = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "NOTICE", "UNMEASURED")


@dataclass
class Finding:
    """Standardized 16-field evidence-based Finding model (Phase 7.13)."""
    finding_id: str
    audit_id: Optional[str | int]
    check_id: str
    category: str
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW, NOTICE, UNMEASURED
    status: str    # OPEN, RESOLVED, FAIL, WARN, UNMEASURED
    affected_url: str
    observed_value: Any
    expected_condition: str
    evidence: dict[str, Any]
    evidence_source: str
    collected_at: str
    ruleset_version: str
    recommendation: str
    verification_method: str
    instance_count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def synthesise(
    results: list[CheckResult],
    defs: dict[str, dict[str, Any]],
    category_names: dict[str, str],
    audit_id: Optional[str | int] = None,
    collected_at: Optional[str] = None
) -> list[dict[str, Any]]:
    rs = load_ruleset()
    step = rs.get("warn_severity_step_down", {"critical": "high", "high": "medium", "medium": "low", "low": "low"})
    s2p = rs.get("severity_to_priority", {"critical": "P1", "high": "P2", "medium": "P3", "low": "P4"})
    qw_max = rs.get("quick_win_max_minutes", 60)
    ruleset_ver = rs.get("ruleset_version", "ruleset_v1.0.0")
    rows = []
    
    for r in results:
        if r.status not in ("FAIL", "WARN"):
            continue
        d = defs.get(r.id, {})
        base_sev = d.get("severity", "medium").lower()
        severity = base_sev if r.status == "FAIL" else step.get(base_sev, "medium")
        effort = int(d.get("effort") or 0)
        urls = r.evidence.get("urls", [])
        aff_url = urls[0] if urls else ""
        instance_count = max(1, len(urls))
        
        row = {
            "check_id": r.id,
            "check_name": d.get("name", r.id),
            "status": "OPEN",
            "title": f"{d.get('name', r.id)}: {r.evidence.get('statement', '')}".strip(),
            "problem_description": f"{d.get('name', r.id)}: {r.evidence.get('statement', '')}".strip(),
            "category": r.category,
            "category_name": category_names.get(r.category, r.category),
            "severity": severity,
            "severity_standard": severity.upper(),
            "priority": s2p.get(severity, "P3"),
            "priority_diverges_from_severity": False,
            "priority_divergence_reason": None,
            "urls": urls,
            "affected_url": aff_url,
            "instance_count": instance_count,
            "seo_impact": d.get("reason", ""),
            "business_impact": d.get("reason", "") if r.category in BUSINESS_CATEGORIES else "Indirect: affects how well the page can be found and understood.",
            "evidence": {
                "label": r.evidence_label,
                "statement": r.evidence.get("statement", ""),
                "values": r.evidence.get("values", {}),
                "urls": urls
            },
            "suggested_correction": d.get("fix", ""),
            "recommended_fix": d.get("fix", ""),
            "verification_method": f"Re-crawl affected URL(s) and verify check {r.id} ({d.get('name', r.id)}) passes.",
            "effort_minutes": effort or None,
            "needs_developer": bool(d.get("dev")),
            "quick_win": 0 < effort <= qw_max,
            "derived_from_checks": [r.id],
            "ruleset_version": ruleset_ver,
        }
        if collected_at:
            row["collected_at"] = collected_at
        if audit_id is not None:
            row["audit_id"] = audit_id
        rows.append(row)
        
    rows.sort(key=lambda x: (SEV_RANK.get(x["severity"], 3), -WEIGHTS.get(x["category"], 0), x["check_id"]))
    for i, row in enumerate(rows, 1):
        row["id"] = f"{i:02d}"
        row["finding_id"] = f"FINDING-{row['check_id']}-{i:02d}"
    return rows


def summarise(issues: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate both unique issue counts and affected instance counts (Phase 7.3)."""
    counts = {k: sum(1 for i in issues if i["severity"] == k) for k in ("critical", "high", "medium", "low")}
    counts["notice"] = sum(1 for i in issues if i.get("severity") == "notice")
    total_unique = len(issues)
    
    # Calculate affected instance counts
    instance_counts = {
        "critical": sum(i.get("instance_count", len(i.get("urls", [])) or 1) for i in issues if i["severity"] == "critical"),
        "high": sum(i.get("instance_count", len(i.get("urls", [])) or 1) for i in issues if i["severity"] == "high"),
        "medium": sum(i.get("instance_count", len(i.get("urls", [])) or 1) for i in issues if i["severity"] == "medium"),
        "low": sum(i.get("instance_count", len(i.get("urls", [])) or 1) for i in issues if i["severity"] == "low"),
        "notice": sum(i.get("instance_count", len(i.get("urls", [])) or 1) for i in issues if i.get("severity") == "notice"),
    }
    total_instances = sum(instance_counts.values())
    instance_counts["total"] = total_instances
    instance_counts["warnings"] = instance_counts["high"] + instance_counts["medium"]
    
    pct = {k: (round(100 * v / total_unique) if total_unique else 0) for k, v in counts.items() if k in ("critical", "high", "medium", "low")}
    s = sum(pct.values())
    
    return {
        **counts,
        "total": total_unique,
        "percentages": pct,
        "percentage_rounding_note": (f"Percentages sum to {s} because of rounding." if total_unique and s != 100 else None),
        # Dual-counting metrics (Phase 7.3)
        "unique_issue_count": total_unique,
        "total_affected_instances": total_instances,
        "warnings": counts["high"] + counts["medium"],
        "critical_issues": counts["critical"],
        "instance_counts": instance_counts,
    }


def quick_wins(issues: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = [i for i in issues if i.get("quick_win")]
    out = []
    for n, i in enumerate(rows, 1):
        out.append({
            "n": n,
            "task": i["recommended_fix"],
            "check_id": i["check_id"],
            "issue_id": i["id"],
            "target": ", ".join(i.get("urls", [])[:3]) or "Site-wide",
            "effort_minutes": i.get("effort_minutes"),
            "priority": i.get("priority"),
            "severity": i.get("severity"),
            "needs_developer": i.get("needs_developer")
        })
    total = sum(r.get("effort_minutes") or 0 for r in out)
    return out, {
        "item_count": len(out),
        "total_minutes": total,
        "total_hours": round(total / 60, 2),
        "critical_issues_closed": sum(1 for r in out if r.get("severity") == "critical"),
        "items_needing_no_developer": [r["n"] for r in out if not r.get("needs_developer")]
    }
