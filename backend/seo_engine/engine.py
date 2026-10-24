"""SEO audit engine orchestrator: evidence -> checks -> scores -> issues -> payload (spec PART J / N.4.2).

`run_engine` is deterministic for a given evidence set: no clock reads, no randomness, no model calls.
"""
from __future__ import annotations

from typing import Any, Optional

from .checks import evaluate_all
from .context import build_context, detect_profile
from .gate import run_gate
from .issues import quick_wins, summarise, synthesise
from .ruleset import category_checks, load_ruleset
from .scoring import (CONFIDENCE_CAP_COEFF, CREDIT, RULESET_VERSION, WEIGHTS, band, credit_of, maturity, project_potential,
                      projected_category, round_half_up, score_site)
from urllib.parse import urlparse

# Strict Zero-Fabrication Engine: No hardcoded benchmark overrides in production scoring.
# All scores are strictly derived from actual crawl observations and verified checks.
BENCHMARK_CORPUS: dict[str, Any] = {}

ENGINE_VERSION = "1.0.0"
SCHEMA_VERSION = "1.0"

INTEGRITY_STATEMENT = (
    "Statement on data integrity. No rankings, search volumes, organic traffic figures, backlink counts, domain authority scores, "
    "Core Web Vitals measurements, indexed page counts or competitor traffic estimates appear in this report unless they were "
    "returned by a connected data source that is named next to the figure. Where such a metric would normally be quoted and no "
    "source was connected, this report states \"Not directly verifiable from the available data\" and names the tool required."
)

RESOLUTION = {
    "capability_missing:psi": ("Google PageSpeed Insights API (free key)", 20),
    "connector_no_data:psi": ("Chrome UX Report needs more real-user traffic; re-check later", 0),
    "capability_missing:gsc": ("Google Search Console access", 15),
    "capability_missing:ga4": ("Google Analytics 4 access", 15),
    "capability_missing:manual": ("Manual review / business-owner input", 15),
    "capability_missing:render": ("Headless browser run (Playwright + Chrome)", 10),
    "capability_missing:html_raw": ("Google Rich Results Test", 15),
    "not_attempted:probes": ("Run a full site audit (probes are skipped for single-page and legacy audits)", 5),
    "not_determinable:market": ("Publish the business address or LocalBusiness markup", 30),
}


def display_label(reason: Optional[str]) -> str:
    r = reason or ""
    if r.startswith("capability_missing:") and r.split(":", 1)[1] in ("psi", "gsc", "ga4", "backlink", "keyword", "render"):
        return "Integration required"
    if r.startswith("connector_no_data"):
        return "Insufficient data"
    if r.startswith(("not_attempted", "evaluator_error", "not_implemented")):
        return "Not measured"
    return "Not verifiable"


def derive_capabilities(audit: dict[str, Any], probes: Optional[dict], render: Optional[dict]) -> dict[str, Any]:
    rd = audit.get("real_data") or {}
    psi = (rd.get("pagespeed") or {}).get("mobile") or {}
    pages = [p for p in audit.get("pages") or [] if isinstance(p, dict) and not p.get("error")]
    raw = bool(pages) and all((p.get("ev") or {}).get("fetch_method", "raw_http") == "raw_http" for p in pages)
    caps = {
        "http": True,
        "html": bool(pages),
        "html_raw": raw,  # this crawler fetches raw HTML with script tags intact (spec G.2)
        "render": bool(render and render.get("available") and any(x.get("ok") for x in render.get("pages") or [])),
        "psi": bool(psi.get("ok") and psi.get("mode") in ("api", "local_lighthouse")),
        "gsc": bool((rd.get("search_console") or {}).get("ok")),
        "ga4": False,
        "backlink": bool((rd.get("openpagerank") or {}).get("ok") or ((rd.get("dataforseo") or {}).get("backlinks") or {}).get("ok")),
        "keyword": bool(((rd.get("dataforseo") or {}).get("keyword_metrics") or {}).get("ok")),
        "manual": False,
        "probes": bool(probes),
    }
    notes = ["Pages were fetched as raw HTML over HTTP; <script> blocks (JSON-LD) are preserved and inspected."]
    if not caps["psi"]:
        notes.append("No PageSpeed Insights connector: Core Web Vitals (P01-P04) are not measured." +
                     (" A local Lighthouse lab run exists but is not used for scoring." if psi.get("mode") == "local_lighthouse" and psi.get("ok") else ""))
    if not caps["render"]:
        notes.append("No headless-browser render: rendered mobile layout and tap targets (M03, M05) are not measured.")
    if not caps["probes"]:
        notes.append("Host, redirect and negative-URL probes were not run for this audit; dependent checks are not measured.")
    caps["notes"] = notes
    return caps


def run_engine(audit: dict[str, Any], probes: Optional[dict] = None, sitemap_full: Optional[dict] = None, robots_full: Optional[dict] = None,
               sitemap_sample: Optional[dict] = None, render: Optional[dict] = None, profile: Optional[str] = None,
               narrative_texts: tuple[str, ...] = ()) -> dict[str, Any]:
    rs = load_ruleset()
    if profile and profile not in rs["vertical_profiles"]:
        profile = None
    profile_reason = "set explicitly"
    if not profile:
        profile, profile_reason = detect_profile(audit)
    caps = derive_capabilities(audit, probes, render)
    fetched = [p for p in audit.get("pages") or [] if isinstance(p, dict) and int(p.get("status") or 0) > 0]
    if not fetched or all(int(p.get("status") or 0) >= 500 for p in fetched):
        # Spec E.5: 5xx on every URL (or nothing reachable) -> abort, no score.
        return {"schema_version": SCHEMA_VERSION, "ruleset_version": RULESET_VERSION, "engine_version": ENGINE_VERSION,
                "error": "AUDIT_FAILED: site unreachable", "audit": {"target_url": audit.get("target"), "vertical_profile": profile},
                "capabilities": caps, "score": {"overall": None, "grade": None, "potential": None}, "categories": [], "checks": [],
                "issues": [], "issue_summary": {"critical": 0, "high": 0, "medium": 0, "low": 0, "total": 0, "percentages": {}},
                "quick_wins": [], "quick_win_totals": {"item_count": 0, "total_minutes": 0, "total_hours": 0}, "unmeasured": [],
                "missing_pages": [], "integrity": {"statement": INTEGRITY_STATEMENT, "verification_gate": {"passed": True, "failures": []}}}
    ctx = build_context(audit, probes, sitemap_full, robots_full, sitemap_sample, render, caps, profile)
    results = evaluate_all(ctx)
    site = score_site(results)

    defs: dict[str, dict] = {}
    for cat in WEIGHTS:
        for d in category_checks(cat, profile):
            defs[d["id"]] = d
    names = dict(rs["category_names"])
    names["vertical"] = rs["vertical_profiles"][profile]["label"]

    categories = []
    potentials: dict[str, int] = {}
    for cat in WEIGHTS:
        cs = site["categories"][cat]
        cat_results = [r for r in results if r.category == cat]
        measured = [r for r in cat_results if r.status not in ("UNMEASURED", "NOT_APPLICABLE")]
        passed = [r for r in measured if r.status == "PASS"]
        gaps = [defs[r.id]["name"] for r in measured if r.status in ("FAIL", "WARN")]
        potentials[cat] = projected_category(cat, cat_results, cs.score)
        missing = [defs[r.id]["name"] for r in cat_results if r.status == "UNMEASURED"]
        if cs.score is None:
            summary = "UNSCORABLE: no check in this category could be measured with the available data."
        else:
            summary = f"{len(passed)} of {len(measured)} measured checks passed."
            if gaps:
                summary += " Gaps: " + "; ".join(gaps[:4]) + "."
        categories.append({
            "id": cat, "name": names[cat], "weight": cs.weight, "score": cs.score,
            "grade": band(cs.score) if cs.score is not None else "Unscorable",
            "weighted_contribution": cs.weight * cs.score if cs.score is not None else None,
            "potential_score": potentials[cat],
            "provisional": cs.provisional, "unscorable": cs.score is None,
            "measured_points": cs.measured_points, "unmeasured_points": cs.unmeasured_points,
            "confidence_cap": cs.confidence_cap, "raw": None if cs.raw is None else round(cs.raw, 2),
            "checks_passed": len(passed), "checks_measured": len(measured),
            "summary": summary,
            "strengths": [defs[r.id]["name"] for r in passed],
            "unmeasured_checks": missing,
            "provisional_note": (f"Provisional: {', '.join(missing[:4])} could not be measured; the score is capped at {cs.confidence_cap:g} "
                                 f"until that data is connected. Once measured, this score may move up or down.") if cs.provisional and cs.score is not None else None,
            "check_ids": [r.id for r in cat_results],
        })

    checks = []
    for r in results:
        d = defs[r.id]
        measured = r.status not in ("UNMEASURED", "NOT_APPLICABLE")
        earned = round(r.points * credit_of(r), 2) if measured else 0
        entry = {
            "id": r.id, "category": r.category, "name": d["name"], "status": r.status,
            "points_available": r.points, "points_earned": earned, "coverage": r.coverage,
            "credit": None if not measured else (r.coverage if r.coverage is not None else CREDIT[r.status]),
            "tier": d["tier"], "scope": d["scope"], "aggregation": d["aggregation"], "severity_on_fail": d["severity"],
            "reason": d["reason"], "evidence": r.evidence, "excluded_from_denominator": not measured,
            "unmeasured_reason": r.unmeasured_reason,
        }
        if r.status == "UNMEASURED":
            tool, minutes = RESOLUTION.get(r.unmeasured_reason or "", ("See reason", None))
            entry["display_as"] = display_label(r.unmeasured_reason)
            entry["resolution"] = {"tool": tool, "effort_minutes": minutes,
                                   "direction_of_uncertainty": "If this is measured, the category score can move up or down; nothing is assumed."}
        checks.append(entry)

    issues = synthesise(results, defs, names)
    qw, qw_totals = quick_wins(issues)
    overall = site["overall"]
    potential = None
    if overall is not None:
        potential = project_potential(potentials, overall)
        potential["note"] = "Category potentials are projected deterministically (DERIVED rule): every measured gap fixed, unmeasured checks assumed measured, capped at 90."

    total_possible_checks = len(results)
    measured_checks = [r for r in results if r.status not in ("UNMEASURED", "NOT_APPLICABLE")]
    unmeasured_checks = [r for r in results if r.status == "UNMEASURED"]
    na_checks = [r for r in results if r.status == "NOT_APPLICABLE"]
    total_avail_pts = sum(r.points for r in results if r.status != "NOT_APPLICABLE")
    meas_pts = sum(r.points for r in measured_checks)
    unmeas_pts = sum(r.points for r in unmeasured_checks)
    cov_pct = round((meas_pts / total_avail_pts) * 100, 1) if total_avail_pts > 0 else 0

    measurement_coverage = {
        "coverage_percentage": cov_pct,
        "total_checks": total_possible_checks,
        "checks_measured": len(measured_checks),
        "checks_unmeasured": len(unmeasured_checks),
        "checks_not_applicable": len(na_checks),
        "points_available": total_avail_pts,
        "points_measured": meas_pts,
        "points_unmeasured": unmeas_pts,
        "status": "FULL" if unmeas_pts == 0 else "PARTIAL",
        "ranking_disclaimer": "Diagnostic audit score only. This score measures on-site technical compliance and page quality; it is NOT a Google ranking factor and confers no ranking guarantees.",
    }

    probes_list = (probes or {}).get("probes") or []
    payload = {
        "schema_version": SCHEMA_VERSION,
        "ruleset_version": RULESET_VERSION,
        "engine_version": ENGINE_VERSION,
        "audit": {
            "target_url": audit.get("target"),
            "hosts_tested": [h.get("requested") for h in ((probes or {}).get("hosts") or {}).values()],
            "vertical_profile": profile, "vertical_profile_reason": profile_reason,
            "started_at": audit.get("created_at"),
            "pages_evaluated": len(ctx.html), "small_site": ctx.small_site, "render_dependency": ctx.js_site,
            "brand_detected": ctx.brand, "market": ctx.market_code,
        },
        "capabilities": caps,
        "measurement_coverage": measurement_coverage,
        "score": {
            "overall": overall, "grade": site.get("grade"), "band": site.get("grade"),
            "maturity_level": site.get("maturity_level"), "maturity_label": site.get("maturity_label"),
            "weighted_sum": site.get("weighted_sum"), "weight_total": site.get("weight_total"),
            "weight_redistributed": site.get("weight_redistributed"),
            "formula": "round_half_up(sum(weight * category_score) / 100)",
            "confidence_cap_coefficient": CONFIDENCE_CAP_COEFF,
            "potential": potential,
        },
        "categories": categories,
        "checks": checks,
        "issues": issues,
        "issue_summary": summarise(issues),
        "quick_wins": qw,
        "quick_win_totals": qw_totals,
        "unmeasured": [{"check_id": c["id"], "metric": c["name"], "category": c["category"], "reason": c["unmeasured_reason"],
                        "display_as": c["display_as"], "required_source": c["resolution"]["tool"]} for c in checks if c["status"] == "UNMEASURED"],
        "missing_pages": [{"url": p["url"], "status": p["status"], "note": "Expected page returns 404 and nothing links to it: a missing page, not a broken link."}
                          for p in probes_list if not p["control"] and p["status"] in (404, 410)],
        "display_rules": {
            "never_fabricate": ["traffic", "impressions", "clicks", "ctr", "rankings", "search_volume", "keyword_difficulty", "backlinks",
                                "referring_domains", "domain_authority", "indexed_pages", "lcp", "inp", "cls", "ttfb", "lighthouse_score",
                                "conversion_rate", "competitor_traffic"],
            "unmeasured_labels": {"no_connector": "Integration required", "connector_no_data": "Insufficient data",
                                  "not_attempted": "Not measured", "attempted_blocked": "Not verifiable"},
        },
        "integrity": {"statement": INTEGRITY_STATEMENT},
    }
    gate = run_gate(payload, narrative_texts)
    payload["integrity"].update({"verification_gate": gate, "arithmetic_verified": gate["arithmetic_verified"],
                                 "fabrication_scan_run": True, "fabrication_scan_hits": gate["fabrication_scan_hits"]})
    return payload
