"""
Report Service for eSupport SEO Platform
Client-facing report snapshots. Every number shown comes from the spec engine payload
(backend/seo_engine); nothing is recalculated here (spec PART N, step 20).
"""

from __future__ import annotations
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse, quote

from .seo_engine import run_engine
from .seo_engine.scoring import band, maturity
from .seo_knowledge import get_rule

# Grade bands are the spec's (C.3): Excellent 90+, Very Good 80+, Good 70+, Needs Improvement 60+, Poor 40+, Critical below 40.
BAND_COPY = {
    "Excellent": ("#10B981", "Excellent SEO foundation", "The site passes the large majority of measured SEO checks.", "maintain"),
    "Very Good": ("#06B6D4", "Very good SEO foundation", "Core checks pass; a few high-value fixes remain.", "optimize"),
    "Good": ("#2563EB", "Good SEO foundation", "The fundamentals are in place, but several measured checks fail.", "improve"),
    "Needs Improvement": ("#F59E0B", "Needs improvement", "A significant share of measured SEO checks fail.", "improve"),
    "Poor": ("#F97316", "Poor SEO health", "Many measured SEO checks fail, including important ones.", "urgent"),
    "Critical": ("#EF4444", "Critical SEO gaps", "Most measured SEO checks fail; the site is substantially incomplete for search.", "urgent"),
}


def get_score_status(score: Optional[float]) -> dict[str, Any]:
    if score is None:
        return {"status": "NOT SCORED", "grade": "Unscorable", "tier": "unscorable", "color": "#94A3B8", "headline": "Not enough data to score",
                "description": "No category could be measured with the available data.", "cta_headline": "Let us review your website",
                "cta_description": "Our team can complete the checks that could not be measured automatically.", "cta_mode": "improve",
                "whatsapp_button_text": "Talk to eSupport", "email_button_text": "Contact eSupport"}
    grade = band(int(score))
    color, headline, desc, mode = BAND_COPY[grade]
    urgent = mode == "urgent"
    return {
        "status": grade.upper(), "grade": grade, "tier": grade.lower().replace(" ", "_"), "color": color,
        "headline": headline, "description": desc,
        "cta_headline": "Your Website Needs SEO Attention" if urgent else "Your Website Has SEO Improvement Opportunities" if mode == "improve" else "Your Website Has a Strong SEO Foundation",
        "cta_description": "Several important SEO areas require improvement." if urgent else "Our SEO team can help improve the areas holding your website back.",
        "cta_mode": mode,
        "whatsapp_button_text": "Improve My SEO on WhatsApp" if urgent else "Improve My SEO" if mode == "improve" else "Discuss SEO Improvements",
        "email_button_text": "Request SEO Consultation" if urgent else "Contact eSupport",
    }


def engine_payload(audit: dict[str, Any]) -> dict[str, Any]:
    """The engine payload stored on the audit; legacy audits are scored from their stored evidence (pure, no network)."""
    from .seo_engine import RULESET_VERSION
    p = audit.get("seo_engine")
    if isinstance(p, dict) and p.get("ruleset_version") == RULESET_VERSION:
        return p
    return run_engine(audit) if audit.get("pages") else {}


def client_categories(audit: dict[str, Any]) -> list[dict[str, Any]]:
    """The 12 spec categories for client-facing pages, copied directly from the engine payload."""
    payload = engine_payload(audit)
    checks = {c["id"]: c for c in payload.get("checks", [])}
    out = []
    for cat in payload.get("categories", []):
        rows = []
        for cid in cat["check_ids"]:
            ch = checks[cid]
            rows.append({"id": cid, "label": ch["name"], "status": ch["status"].lower() if ch["status"] != "NOT_APPLICABLE" else "not_applicable",
                         "detail": ch["evidence"].get("statement", ""), "evidence_label": ch["evidence"].get("label", ""),
                         "points_available": ch["points_available"], "points_earned": ch["points_earned"],
                         "display_as": ch.get("display_as"), "data_type": ch["tier"],
                         "source_name": "", "source_url": ""})
        score = cat["score"]
        out.append({
            "id": cat["id"], "name": cat["name"], "weight": cat["weight"], "score": score,
            "display": f"{score}%" if score is not None else "Not measured",
            "status": cat["grade"], "grade": cat["grade"],
            "description": cat.get("summary", ""), "provisional": cat.get("provisional", False), "provisional_note": cat.get("provisional_note"),
            "potential_score": cat.get("potential_score"), "ai_summary": cat.get("ai_summary", ""),
            "checks": rows, "checks_passed": cat.get("checks_passed", 0), "checks_total": cat.get("checks_measured", 0),
            "strengths": cat.get("strengths", []), "is_applicable": True, "is_configured": score is not None, "is_estimate": False,
            "data_basis": "Deterministic check scoring (ruleset " + payload.get("ruleset_version", "") + ")",
        })
    return out

# Client-friendly Issue Dictionary
ISSUE_EXPLANATIONS = {
    "missing_title": {
        "title": "Missing Page Title",
        "explanation": "One or more pages do not have a defined HTML title tag.",
        "why_it_matters": "The title tag is one of the most critical on-page ranking factors and is the headline shown in Google search results.",
        "recommended_action": "Add a unique, descriptive title tag (between 40 and 60 characters) to each page."
    },
    "missing_meta_description": {
        "title": "Missing Meta Description",
        "explanation": "Pages are missing a summary description tag in the HTML head.",
        "why_it_matters": "Search engines use meta descriptions as the snippet under your title in search results, directly impacting click-through rates.",
        "recommended_action": "Write an engaging, relevant meta description (between 120 and 160 characters) for each affected page."
    },
    "missing_h1": {
        "title": "Missing Main Heading (H1)",
        "explanation": "The page does not contain a primary H1 heading.",
        "why_it_matters": "Search engines and visitors use the H1 heading to understand the main topic of the page.",
        "recommended_action": "Include exactly one clear, topic-focused H1 heading on each page."
    },
    "missing_canonical": {
        "title": "Missing Canonical URL",
        "explanation": "Some pages do not clearly specify their preferred URL version using a canonical tag.",
        "why_it_matters": "Without canonical tags, search engines may index duplicate variations of the same content (e.g. http vs https, or trailing slashes).",
        "recommended_action": "Add a self-referencing rel='canonical' tag to specify the authoritative URL for each page."
    },
    "broken_internal_links": {
        "title": "Broken Internal Links Detected",
        "explanation": "Links on your site point to pages that return error codes (such as 404 Not Found).",
        "why_it_matters": "Broken links frustrate visitors, waste crawl budget, and signal poor website maintenance to search algorithms.",
        "recommended_action": "Update or remove all broken links so visitors and search bots reach valid pages."
    },
    "broken_link": {
        "title": "Broken Link Target",
        "explanation": "A link on your website leads to an unreachable or failed destination.",
        "why_it_matters": "Damages user experience and interrupts search engine indexation.",
        "recommended_action": "Correct the target URL or redirect the link to relevant active content."
    },
    "missing_alt": {
        "title": "Images Missing ALT Descriptions",
        "explanation": "Images on your website lack descriptive ALT text attributes.",
        "why_it_matters": "Search engines rely on ALT text to understand images, and screen readers require it for accessibility.",
        "recommended_action": "Add concise, descriptive ALT text explaining what each important image depicts."
    },
    "slow_response": {
        "title": "Slow Page Response Time",
        "explanation": "The server took longer than recommended to deliver the page HTML.",
        "why_it_matters": "Page speed is a confirmed Google ranking factor and directly affects bounce rates.",
        "recommended_action": "Optimize server response time, utilize caching, and optimize database queries."
    },
    "malformed_jsonld": {
        "title": "Structured Data Syntax Error",
        "explanation": "Structured data (Schema.org) code on the page contains formatting errors.",
        "why_it_matters": "Search engines will ignore invalid structured data, losing opportunities for rich search snippets.",
        "recommended_action": "Fix the JSON-LD formatting errors so search engines can read your rich snippets."
    },
    "sitemap_missing": {
        "title": "XML Sitemap Not Discoverable",
        "explanation": "An XML sitemap could not be found at standard locations or in robots.txt.",
        "why_it_matters": "XML sitemaps help search engines find and index all valuable pages on your site quickly.",
        "recommended_action": "Generate an XML sitemap and submit it to Google Search Console and robots.txt."
    },
    "robots_missing": {
        "title": "Robots.txt File Missing",
        "explanation": "Your site does not provide a standard /robots.txt file.",
        "why_it_matters": "Robots.txt tells search engines how to crawl your website and references your XML sitemap.",
        "recommended_action": "Create a clean robots.txt file in the root directory specifying crawl rules."
    },
    "redirect_chain": {
        "title": "Multiple Redirect Hops",
        "explanation": "URLs redirect through multiple consecutive steps before reaching the final destination.",
        "why_it_matters": "Redirect chains slow down page loading and dilute search ranking authority.",
        "recommended_action": "Update internal links to point directly to the final destination URL."
    },
    "duplicate_title": {
        "title": "Duplicate Page Titles",
        "explanation": "Multiple pages share the exact same title tag.",
        "why_it_matters": "Makes it difficult for search engines to know which page to rank for relevant search queries.",
        "recommended_action": "Give every indexed page a distinct, unique title reflecting its unique content."
    },
    "client_error": {
        "title": "Client HTTP Error (4xx)",
        "explanation": "The page returned a 4xx error code (such as 404 or 403) when accessed.",
        "why_it_matters": "Error pages cannot rank in search results and prevent users from viewing content.",
        "recommended_action": "Restore the page content or set up a 301 redirect to an appropriate alternative page."
    }
}

SEV_CLASS = {"critical": "danger", "high": "danger", "medium": "warning", "low": "info"}


def translate_issue_to_client_friendly(issue: dict[str, Any]) -> dict[str, Any]:
    """Client view of one engine issue. Text comes from the ruleset; evidence from the check."""
    ev = issue.get("evidence") if isinstance(issue.get("evidence"), dict) else {"statement": issue.get("evidence", ""), "label": issue.get("evidence_label", "")}
    return {
        "id": issue.get("id"),
        "code": issue.get("check_id") or issue.get("code", ""),
        "check_id": issue.get("check_id"),
        "severity": (issue.get("severity") or "").upper(),
        "severity_class": SEV_CLASS.get(issue.get("severity"), "info"),
        "priority": issue.get("priority"),
        "title": issue.get("check_name") or issue.get("title", ""),
        "explanation": ev.get("statement", ""),
        "evidence_label": ev.get("label", ""),
        "why_it_matters": issue.get("seo_impact", ""),
        "business_impact": issue.get("business_impact", ""),
        "recommended_action": issue.get("recommended_fix", ""),
        "references": [],
        "data_type": "observed",
        "technical_details": {
            "category": issue.get("category_name", issue.get("category", "")),
            "code": issue.get("check_id", ""),
            "url": ", ".join((issue.get("urls") or [])[:5]),
            "evidence": ev.get("statement", ""),
            "developer_fix": issue.get("recommended_fix", ""),
        },
    }


def format_top_issues(audit: dict[str, Any], limit: int = 6) -> list[dict[str, Any]]:
    """Top issues in the engine's own deterministic order (severity, category weight, check id)."""
    payload = engine_payload(audit)
    return [translate_issue_to_client_friendly(i) for i in (payload.get("issues") or [])[:limit]]

def _psi_summary(psi: dict[str, Any]) -> dict[str, Any] | None:
    if not psi or not psi.get("ok") or psi.get("mode") != "api":
        return None  # only Google PageSpeed API results are client-facing; local lab runs are not a field measurement
    field = psi.get("field_url") or psi.get("field_origin")
    return {
        "lighthouse_scores": psi.get("lighthouse_scores", {}),
        "field": {
            "scope": field.get("scope"),
            "assessment": field.get("core_web_vitals_assessment"),
            "metrics": {k: {"p75": v["p75"], "unit": v["unit"], "rating": v["rating"]} for k, v in field.get("metrics", {}).items()},
        } if field else None,
        "lab": psi.get("lab", {}),
        "fetched_at": psi.get("fetched_at", ""),
    }


def build_real_data_summary(real_data: dict[str, Any]) -> dict[str, Any]:
    """Compact, client-safe view of measured provider data. Absent integrations are simply omitted."""
    out: dict[str, Any] = {}
    psi = real_data.get("pagespeed") or {}
    mobile, desktop = _psi_summary(psi.get("mobile") or {}), _psi_summary(psi.get("desktop") or {})
    if mobile or desktop:
        out["core_web_vitals"] = {"mobile": mobile, "desktop": desktop,
                                  "source": "Google PageSpeed Insights API - Chrome UX Report field data (75th percentile, last 28 days) and Lighthouse lab run",
                                  "thresholds_source": "https://web.dev/articles/vitals"}
    gsc = real_data.get("search_console") or {}
    if gsc.get("ok"):
        out["search_console"] = {"period": f"{gsc.get('start_date')} to {gsc.get('end_date')}", "totals": gsc.get("totals", {}),
                                 "top_queries": (gsc.get("top_queries") or [])[:10], "top_pages": (gsc.get("top_pages") or [])[:10],
                                 "source": "Google Search Console API"}
    dfs = real_data.get("dataforseo") or {}
    rk = dfs.get("ranked_keywords") or {}
    if rk.get("ok"):
        out["rankings"] = {"total_ranking_keywords": rk.get("total_count", 0), "distribution": rk.get("distribution", {}),
                           "top_keywords": (rk.get("keywords") or [])[:15], "source": "DataForSEO Labs (Google organic)"}
    bl = dfs.get("backlinks") or {}
    if bl.get("ok"):
        out["backlinks"] = {k: bl.get(k) for k in ("backlinks", "referring_domains", "referring_main_domains", "broken_backlinks", "spam_score", "domain_rank", "domain_rank_scale")}
        out["backlinks"]["top_referring_domains"] = (bl.get("top_referring_domains") or [])[:10]
        out["backlinks"]["source"] = "DataForSEO Backlinks API"
    return out


def build_client_report_snapshot(
    audit: dict[str, Any],
    client_name: str = "",
    company: str = "",
    token: str = ""
) -> dict[str, Any]:
    """Frozen, public-safe snapshot of an audit for the client report. All numbers are copied from the engine payload."""
    target = audit.get("target") or audit.get("url") or "https://example.com"
    payload = engine_payload(audit)
    sc = payload.get("score") or {}
    score = sc.get("overall")
    status_info = get_score_status(score)
    categories = client_categories(audit)
    summ = payload.get("issue_summary") or {}
    stats = audit.get("stats", {}) or {}
    pages = audit.get("pages", []) or []
    real_data = audit.get("real_data") or {}
    dfs = real_data.get("dataforseo") or {}
    psi_mobile = (real_data.get("pagespeed") or {}).get("mobile") or {}

    score_display = score if score is not None else "not scored"
    wa_msg = (f"Hello eSupport,\n\nI reviewed my website SEO report.\n\nWebsite:\n{target}\n\nCurrent SEO Score:\n{score_display}/100\n\n"
              f"I would like to discuss improving my website's SEO.\n\nThank you.")
    email_subject = f"SEO Improvement Request - {urlparse(target).hostname or target}"
    email_body = (f"Hello eSupport,\n\nI reviewed my website SEO report.\n\nWebsite:\n{target}\n\nCurrent SEO Score:\n{score_display}/100\n\n"
                  f"I would like assistance improving my website's SEO performance.\n\nThank you.")
    checks = payload.get("checks") or []
    return {
        "token": token,
        "target_url": target,
        "client_name": client_name,
        "company": company,
        "audited_at": audit.get("created_at") or datetime.now(timezone.utc).isoformat(),
        "ruleset_version": payload.get("ruleset_version"),
        "score": score,
        "grade": sc.get("grade"),
        "maturity_level": sc.get("maturity_level"),
        "maturity_label": sc.get("maturity_label"),
        "weighted_sum": sc.get("weighted_sum"),
        "score_status": status_info,
        "categories": categories,
        "potential": sc.get("potential"),
        "summary": {
            "overall_score": score,
            "categories_evaluated": sum(1 for c in categories if c.get("score") is not None),
            "passed_checks": sum(1 for c in checks if c["status"] == "PASS"),
            "measured_checks": sum(1 for c in checks if c["status"] in ("PASS", "WARN", "FAIL")),
            "unmeasured_checks": sum(1 for c in checks if c["status"] == "UNMEASURED"),
            "critical_issues": summ.get("critical", 0),
            "high_issues": summ.get("high", 0),
            "warnings": summ.get("high", 0) + summ.get("medium", 0),
            "improvement_opportunities": summ.get("total", 0),
            "total_pages_crawled": len(pages),
            "broken_links": stats.get("broken_links", 0),
            "missing_alt_images": stats.get("missing_alt_images", 0),
        },
        "top_issues": format_top_issues(audit, limit=8),
        "quick_wins": [q["task"] for q in (payload.get("quick_wins") or [])][:8],
        "quick_win_totals": payload.get("quick_win_totals"),
        "unmeasured": payload.get("unmeasured", []),
        "measurement_coverage": payload.get("measurement_coverage") or {
            "coverage_percentage": round(100.0 * sum(1 for c in checks if c["status"] in ("PASS", "WARN", "FAIL")) / max(1, len(checks)), 1),
            "total_checks": len(checks),
            "checks_measured": sum(1 for c in checks if c["status"] in ("PASS", "WARN", "FAIL")),
            "checks_unmeasured": sum(1 for c in checks if c["status"] == "UNMEASURED"),
            "ranking_disclaimer": "Diagnostic audit score only. Not a Google ranking factor or ranking guarantee.",
        },
        "integrity_statement": (payload.get("integrity") or {}).get("statement"),
        "cta": {
            "headline": status_info["cta_headline"],
            "description": status_info["cta_description"],
            "whatsapp_url": f"https://wa.me/94710690715?text={quote(wa_msg)}",
            "whatsapp_button_text": status_info.get("whatsapp_button_text", "Improve My SEO on WhatsApp"),
            "whatsapp_number_display": "+94 71 069 0715",
            "email_url": f"mailto:prasad@esupport.live?subject={quote(email_subject)}&body={quote(email_body)}",
            "email_button_text": status_info.get("email_button_text", "Request SEO Consultation"),
            "email_address_display": "prasad@esupport.live",
        },
        "integrations": {
            "search_console": "Connected" if (real_data.get("search_console") or {}).get("ok") else "Not connected",
            "google_analytics": "Not connected",
            "backlinks": "Connected (Open PageRank)" if (real_data.get("openpagerank") or {}).get("ok") else "Connected (DataForSEO)" if (dfs.get("backlinks") or {}).get("ok") else "Not configured",
            "core_web_vitals": "Connected (PageSpeed Insights / CrUX)" if psi_mobile.get("ok") and psi_mobile.get("mode") == "api" else "Not connected",
        },
        "real_data": build_real_data_summary(real_data),
        "score_type": "spec_engine",
        "methodology": (
            "Your score comes from a fixed methodology: 12 SEO categories with fixed weights (Technical 15, On-Page 12, Content 12, "
            "Keyword 8, Internal Linking 6, Image 5, Structured Data 6, Mobile 6, Page Experience 8, Local 8, Industry 8, Conversion 6). "
            "Each category is scored from individual checks measured on your live website. Checks that could not be measured are not "
            "counted as failures; they are listed as not measured, and the category is marked provisional. Overall score = "
            "weighted average of the category scores, rounded once. It is a website health score, not a guaranteed Google ranking."
        ),
    }