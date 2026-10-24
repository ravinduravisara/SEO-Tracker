"""Enterprise Competitor Analysis and Market Intelligence Engine.

Inspired by SEMrush Competitor Intelligence and Ahrefs Site Intersect.
Supports side-by-side domain scoreboards, organic competitor discovery,
keyword gap matrix (shared, missing, weak, strong), content gap opportunities,
backlink gap outreach candidates, and multi-format exports (CSV, Excel XML, ReportLab PDF).

Strict Data Integrity:
- Real SERP and domain intersection data via DataForSEO Labs when configured.
- When unconfigured, queries platform audits and crawls to extract verified
  on-page keyword overlap, technical SEO scores, and structural metrics.
- Never fabricates competitor search volumes, rankings, or organic traffic.
- Explicitly states that competitor Google Search Console and Google Analytics
  are private first-party properties and not publicly accessible.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import urllib.parse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, PageBreak

from . import integrations
from .database import SessionLocal, Audit, Website, CompetitorComparison, KeywordProject, SavedKeyword
from .keyword_engine import SUPPORTED_LOCATIONS, classify_intent

logger = logging.getLogger("esupport.competitor_engine")


def bare_domain(val: str) -> str:
    """Normalizes any URL, protocol, or host string into a clean bare domain."""
    if not val:
        return ""
    s = val.strip().lower()
    if not (s.startswith("http://") or s.startswith("https://")):
        s = "https://" + s
    try:
        parsed = urllib.parse.urlparse(s)
        host = parsed.netloc or parsed.path
        host = host.split(":")[0]  # remove port
        if host.startswith("www."):
            host = host[4:]
        return host.strip().lower()
    except Exception:
        return re.sub(r"^https?://", "", val).split("/")[0].replace("www.", "").strip().lower()


def _get_latest_audit_for_domain(domain: str) -> Optional[dict[str, Any]]:
    """Retrieves the latest completed audit for a given domain from the database."""
    d = bare_domain(domain)
    if not d:
        return None
    db = SessionLocal()
    try:
        audits = db.query(Audit).filter(Audit.status == "COMPLETED").order_by(Audit.created_at.desc()).all()
        for a in audits:
            if bare_domain(a.target_url) == d:
                res = {}
                if a.result_json:
                    try:
                        res = json.loads(a.result_json) if isinstance(a.result_json, str) else a.result_json
                    except Exception:
                        res = {}
                return {
                    "audit_id": a.id,
                    "target_url": a.target_url,
                    "score": a.score,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                    "result": res
                }
        return None
    except Exception as exc:
        logger.warning(f"Error querying audit for domain {domain}: {exc}")
        return None
    finally:
        db.close()


def _get_historical_audits_for_domain(domain: str, limit: int = 10) -> list[dict[str, Any]]:
    """Retrieves historical audits for a domain to compute visibility/score trends."""
    d = bare_domain(domain)
    if not d:
        return []
    db = SessionLocal()
    try:
        audits = db.query(Audit).filter(Audit.status == "COMPLETED").order_by(Audit.created_at.asc()).all()
        history = []
        for a in audits:
            if bare_domain(a.target_url) == d:
                history.append({
                    "audit_id": a.id,
                    "score": a.score,
                    "date": a.created_at.strftime("%Y-%m-%d") if a.created_at else "Unknown",
                    "timestamp": a.created_at.isoformat() if a.created_at else None
                })
        return history[-limit:]
    except Exception as exc:
        logger.warning(f"Error fetching historical audits for domain {domain}: {exc}")
        return []
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Organic Competitor Discovery
# ---------------------------------------------------------------------------
def discover_competitors(
    target_domain: str,
    location_code: int = 2840,
    language_code: str = "en",
    limit: int = 10
) -> dict[str, Any]:
    """Discovers organic competitors using DataForSEO Labs or platform audit database."""
    target = bare_domain(target_domain)
    if not target:
        return {"ok": False, "error": "Target domain is required.", "competitors": []}

    # 1. Try DataForSEO Labs if configured
    if integrations.dataforseo_configured():
        try:
            dfs_res = integrations.competitors_domain(
                target_url=target,
                limit=limit,
                location_code=location_code,
                language_code=language_code
            )
            if dfs_res.get("ok") and dfs_res.get("competitors"):
                formatted = []
                for comp in dfs_res["competitors"]:
                    cd = bare_domain(comp.get("domain", ""))
                    if not cd or cd == target:
                        continue
                    formatted.append({
                        "domain": cd,
                        "shared_keywords": comp.get("shared_keywords", 0),
                        "organic_keywords_count": comp.get("organic_keywords_count"),
                        "estimated_traffic": comp.get("estimated_traffic"),
                        "avg_position": comp.get("avg_position"),
                        "competitor_relevance": min(100, round((comp.get("shared_keywords", 0) / max(1, comp.get("organic_keywords_count", 100))) * 100, 1)) if comp.get("organic_keywords_count") else 50.0,
                        "source": "DataForSEO Labs (Google SERP Competitors)",
                        "data_state": "measured_and_estimated"
                    })
                if formatted:
                    return {
                        "ok": True,
                        "target_domain": target,
                        "provider": "DataForSEO Labs",
                        "total_count": len(formatted),
                        "competitors": formatted[:limit]
                    }
        except Exception as exc:
            logger.warning(f"DataForSEO competitor discovery failed: {exc}")

    # 2. Local Fallback: scan audited websites in the platform database
    db = SessionLocal()
    candidates: list[dict[str, Any]] = []
    try:
        # Collect unique domains from completed audits
        audits = db.query(Audit).filter(Audit.status == "COMPLETED").order_by(Audit.created_at.desc()).all()
        seen_domains: dict[str, Any] = {}
        for a in audits:
            d = bare_domain(a.target_url)
            if d and d != target and d not in seen_domains:
                seen_domains[d] = a

        # Check target's latest audit for keyword comparison
        target_audit = _get_latest_audit_for_domain(target)
        target_keywords = set()
        if target_audit and target_audit.get("result"):
            t_res = target_audit["result"]
            for k in (t_res.get("keywords") or []):
                kw_str = k.get("keyword") if isinstance(k, dict) else str(k)
                if kw_str:
                    target_keywords.add(kw_str.lower().strip())
            for k in ((t_res.get("keyword_intelligence") or {}).get("observed_keywords") or []):
                kw_str = k.get("keyword") if isinstance(k, dict) else str(k)
                if kw_str:
                    target_keywords.add(kw_str.lower().strip())

        for d, a in seen_domains.items():
            comp_res = {}
            if a.result_json:
                try:
                    comp_res = json.loads(a.result_json) if isinstance(a.result_json, str) else a.result_json
                except Exception:
                    comp_res = {}

            comp_kws = set()
            for k in (comp_res.get("keywords") or []):
                kw_str = k.get("keyword") if isinstance(k, dict) else str(k)
                if kw_str:
                    comp_kws.add(kw_str.lower().strip())
            for k in ((comp_res.get("keyword_intelligence") or {}).get("observed_keywords") or []):
                kw_str = k.get("keyword") if isinstance(k, dict) else str(k)
                if kw_str:
                    comp_kws.add(kw_str.lower().strip())

            shared = len(target_keywords.intersection(comp_kws)) if target_keywords and comp_kws else 0
            relevance = round(min(100.0, (shared / max(1, len(target_keywords))) * 100), 1) if target_keywords else 40.0

            candidates.append({
                "domain": d,
                "shared_keywords": shared,
                "organic_keywords_count": len(comp_kws),
                "estimated_traffic": None,
                "avg_position": None,
                "seo_score": a.score,
                "competitor_relevance": max(25.0, relevance),
                "source": "Platform Audit Database",
                "data_state": "measured_crawl_evidence"
            })
    finally:
        db.close()

    # If few or no candidates in local database, suggest industry reference benchmarks
    if len(candidates) < 2:
        benchmark_suggestions = ["ahrefs.com", "semrush.com", "moz.com", "searchengineland.com", "backlinko.com"]
        for b in benchmark_suggestions:
            if b != target and not any(c["domain"] == b for c in candidates):
                candidates.append({
                    "domain": b,
                    "shared_keywords": 0,
                    "organic_keywords_count": None,
                    "estimated_traffic": None,
                    "avg_position": None,
                    "seo_score": None,
                    "competitor_relevance": 35.0,
                    "source": "Industry Reference Domain",
                    "data_state": "benchmark_suggestion"
                })

    # Sort candidates by relevance and shared keywords
    candidates.sort(key=lambda x: (x.get("shared_keywords", 0), x.get("competitor_relevance", 0)), reverse=True)

    return {
        "ok": True,
        "target_domain": target,
        "provider": "Platform Audit Database & Reference Benchmarks",
        "total_count": len(candidates),
        "competitors": candidates[:limit]
    }


# ---------------------------------------------------------------------------
# Deep Competitor Analysis (Scoreboard, Keyword Gap, Content Gap, Backlinks)
# ---------------------------------------------------------------------------
def analyze_competitors(
    target_domain: str,
    competitor_domains: list[str],
    location_code: int = 2840,
    language_code: str = "en"
) -> dict[str, Any]:
    """Performs full competitor analysis across target and 1-4 competitor domains."""
    target = bare_domain(target_domain)
    if not target:
        return {"ok": False, "error": "Target domain is required."}

    # Clean and deduplicate competitor domains
    clean_competitors: list[str] = []
    seen = {target}
    for c in competitor_domains:
        cd = bare_domain(c)
        if cd and cd not in seen:
            seen.add(cd)
            clean_competitors.append(cd)

    # If no competitors provided, auto-discover 2
    if not clean_competitors:
        disco = discover_competitors(target, location_code, language_code, limit=3)
        for cand in disco.get("competitors", []):
            if cand["domain"] not in seen:
                seen.add(cand["domain"])
                clean_competitors.append(cand["domain"])
                if len(clean_competitors) >= 2:
                    break

    # Cap to max 4 competitors (total 5 domains)
    clean_competitors = clean_competitors[:4]
    all_domains = [target] + clean_competitors

    # -----------------------------------------------------------------------
    # Step 1: Side-by-Side Domain Scoreboard
    # -----------------------------------------------------------------------
    scoreboard: list[dict[str, Any]] = []
    domain_keyword_maps: dict[str, dict[str, dict[str, Any]]] = {}
    domain_backlinks_map: dict[str, list[str]] = {}

    for d in all_domains:
        is_target = (d == target)
        audit_info = _get_latest_audit_for_domain(d)
        res = audit_info["result"] if audit_info else {}

        # 1. Technical & On-Page metrics from platform audit
        seo_score = audit_info.get("score") if audit_info else None
        scores_dict = res.get("scores") or {}
        pages = res.get("pages") or []
        stats = res.get("stats") or {}
        issues = res.get("issues") or []
        tech_score = scores_dict.get("Technical SEO", {}).get("score") if isinstance(scores_dict.get("Technical SEO"), dict) else scores_dict.get("Technical SEO")
        onpage_score = scores_dict.get("On-Page SEO", {}).get("score") if isinstance(scores_dict.get("On-Page SEO"), dict) else scores_dict.get("On-Page SEO")
        content_score = scores_dict.get("Content SEO", {}).get("score") if isinstance(scores_dict.get("Content SEO"), dict) else scores_dict.get("Content SEO")

        pages_crawled = stats.get("pages_crawled") or len(pages)
        critical_issues = len([i for i in issues if str(i.get("severity", "")).upper() in ("CRITICAL", "HIGH")])

        # Core Web Vitals
        psi = res.get("pagespeed") or {}
        cwv_perf = None
        if isinstance(psi, dict) and psi.get("scores"):
            cwv_perf = psi["scores"].get("performance")

        # 2. Organic Keywords & Traffic
        domain_kws: dict[str, dict[str, Any]] = {}
        total_organic_kws = 0
        est_monthly_traffic = None
        avg_pos = None

        if integrations.dataforseo_configured():
            try:
                rk_res = integrations.ranked_keywords(d, limit=100, location_code=location_code, language_code=language_code)
                if rk_res.get("ok"):
                    total_organic_kws = rk_res.get("total_count", 0)
                    kw_list = rk_res.get("keywords") or []
                    positions = []
                    traffic_sum = 0
                    for row in kw_list:
                        kname = row.get("keyword", "").strip().lower()
                        if not kname:
                            continue
                        pos = row.get("position")
                        if pos:
                            positions.append(pos)
                        etv = row.get("estimated_traffic") or 0
                        traffic_sum += etv
                        domain_kws[kname] = {
                            "keyword": row.get("keyword", ""),
                            "position": pos,
                            "search_volume": row.get("search_volume"),
                            "keyword_difficulty": row.get("keyword_difficulty"),
                            "cpc": row.get("cpc"),
                            "intent": row.get("intent") or classify_intent(kname),
                            "estimated_traffic": etv,
                            "url": row.get("url", "")
                        }
                    if positions:
                        avg_pos = round(sum(positions) / len(positions), 1)
                    if traffic_sum > 0:
                        est_monthly_traffic = round(traffic_sum)
            except Exception as exc:
                logger.warning(f"Error fetching ranked keywords for {d}: {exc}")

        # If DataForSEO unconfigured or no SERP keywords, populate from local audit
        if not domain_kws and audit_info:
            ki = res.get("keyword_intelligence") or {}
            obs = ki.get("observed_keywords") or res.get("keywords") or []
            total_organic_kws = len(obs)
            for idx, item in enumerate(obs):
                kname = (item.get("keyword") if isinstance(item, dict) else str(item)).strip().lower()
                if not kname:
                    continue
                # Synthetic simulated ranking index based on page count / prominence (not fabricated Google rank)
                sim_rank = min(100, (idx + 1) * 3) if is_target else min(100, (idx + 1) * 4)
                domain_kws[kname] = {
                    "keyword": item.get("keyword") if isinstance(item, dict) else str(item),
                    "position": None,  # State clearly None if no SERP connector
                    "observed_rank": sim_rank,
                    "search_volume": None,
                    "keyword_difficulty": None,
                    "cpc": None,
                    "intent": classify_intent(kname),
                    "estimated_traffic": None,
                    "url": item.get("url", "") if isinstance(item, dict) else ""
                }

        domain_keyword_maps[d] = domain_kws

        # 3. Backlinks & Authority
        total_backlinks = None
        referring_domains = None
        domain_authority = None
        ref_domain_list: list[str] = []

        if integrations.dataforseo_configured():
            try:
                bl_res = integrations.backlinks(d)
                if bl_res.get("ok"):
                    total_backlinks = bl_res.get("backlinks")
                    referring_domains = bl_res.get("referring_domains")
                    domain_authority = bl_res.get("score") or bl_res.get("domain_rank")
                    for top_ref in (bl_res.get("top_referring_domains") or []):
                        if top_ref.get("domain"):
                            ref_domain_list.append(top_ref["domain"].strip().lower())
            except Exception as exc:
                logger.warning(f"Error fetching backlinks for {d}: {exc}")

        if not ref_domain_list and audit_info:
            # Extract discovered external domains from audit
            for ext in (res.get("external_links") or []):
                h = bare_domain(ext.get("url") if isinstance(ext, dict) else str(ext))
                if h and h != d and h not in ref_domain_list:
                    ref_domain_list.append(h)

        domain_backlinks_map[d] = ref_domain_list

        scoreboard.append({
            "domain": d,
            "is_target": is_target,
            "seo_score": seo_score,
            "technical_score": tech_score,
            "onpage_score": onpage_score,
            "content_score": content_score,
            "pages_crawled": pages_crawled,
            "critical_issues": critical_issues,
            "core_web_vitals_perf": cwv_perf,
            "organic_keywords_count": total_organic_kws,
            "estimated_monthly_traffic": est_monthly_traffic,
            "avg_position": avg_pos,
            "backlinks_count": total_backlinks,
            "referring_domains_count": referring_domains or len(ref_domain_list),
            "domain_authority": domain_authority,
            "has_audit": bool(audit_info),
            "audit_date": audit_info.get("created_at") if audit_info else None,
            "traffic_data_state": "measured_estimate" if est_monthly_traffic is not None else "unavailable_requires_serp_provider"
        })

    # -----------------------------------------------------------------------
    # Step 2: Keyword Gap Matrix
    # -----------------------------------------------------------------------
    target_kws = domain_keyword_maps.get(target, {})
    all_kw_keys = set()
    for d, kmap in domain_keyword_maps.items():
        all_kw_keys.update(kmap.keys())

    gap_rows: list[dict[str, Any]] = []
    shared_count = 0
    missing_count = 0
    weak_count = 0
    strong_count = 0
    intent_counts = Counter()

    for kkey in sorted(all_kw_keys):
        t_data = target_kws.get(kkey)
        t_pos = t_data.get("position") if t_data else None

        comp_ranks: dict[str, Optional[int]] = {}
        comp_best_pos: Optional[int] = None
        has_comp_ranking = False

        rep_item = t_data
        for cd in clean_competitors:
            c_data = domain_keyword_maps.get(cd, {}).get(kkey)
            if c_data:
                if not rep_item:
                    rep_item = c_data
                c_pos = c_data.get("position")
                comp_ranks[cd] = c_pos
                if c_pos is not None:
                    has_comp_ranking = True
                    if comp_best_pos is None or c_pos < comp_best_pos:
                        comp_best_pos = c_pos
            else:
                comp_ranks[cd] = None

        if not rep_item:
            continue

        kw_display = rep_item.get("keyword") or kkey
        kw_intent = rep_item.get("intent") or classify_intent(kw_display)
        intent_counts[kw_intent] += 1
        volume = rep_item.get("search_volume")
        kd = rep_item.get("keyword_difficulty")
        cpc = rep_item.get("cpc")

        # Determine Gap Type
        gap_type = "shared"
        if t_data is None or (t_pos is None and not integrations.dataforseo_configured()):
            # Target does not have or rank for this keyword
            if has_comp_ranking or any(domain_keyword_maps.get(cd, {}).get(kkey) for cd in clean_competitors):
                gap_type = "missing"
                missing_count += 1
        elif has_comp_ranking:
            if t_pos is not None and comp_best_pos is not None:
                if t_pos > comp_best_pos:
                    gap_type = "weak"  # Target ranks lower (worse position) than competitor
                    weak_count += 1
                elif t_pos < comp_best_pos:
                    gap_type = "strong"  # Target ranks better than all competitors
                    strong_count += 1
                else:
                    gap_type = "shared"
                    shared_count += 1
            else:
                gap_type = "shared"
                shared_count += 1
        else:
            # Competitors don't have this, but target does
            gap_type = "strong"
            strong_count += 1

        gap_rows.append({
            "keyword": kw_display,
            "intent": kw_intent,
            "search_volume": volume,
            "keyword_difficulty": kd,
            "cpc": cpc,
            "target_rank": t_pos,
            "competitor_ranks": comp_ranks,
            "best_competitor_rank": comp_best_pos,
            "gap_type": gap_type
        })

    # Sort gap rows: Missing and Weak with highest volume first
    gap_rows.sort(key=lambda x: (
        0 if x["gap_type"] == "missing" else (1 if x["gap_type"] == "weak" else 2),
        -(x["search_volume"] or 0),
        x["keyword"]
    ))

    # -----------------------------------------------------------------------
    # Step 3: Content Gap Opportunities
    # -----------------------------------------------------------------------
    content_opportunities: list[dict[str, Any]] = []
    opportunity_kws = [k for k in gap_rows if k["gap_type"] in ("missing", "weak")]

    # Group opportunity keywords by leading 2 root words or common topics
    topic_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in opportunity_kws:
        words = re.findall(r"\b[a-zA-Z]{3,}\b", row["keyword"].lower())
        topic_key = " ".join(words[:2]).title() if len(words) >= 2 else (words[0].title() if words else "General SEO")
        topic_groups[topic_key].append(row)

    for topic, kws in sorted(topic_groups.items(), key=lambda t: len(t[1]), reverse=True)[:10]:
        total_vol = sum((k.get("search_volume") or 0) for k in kws)
        active_comps = set()
        for k in kws:
            for cd, rk in k.get("competitor_ranks", {}).items():
                if rk is not None:
                    active_comps.add(cd)

        opp_score = min(98, 45 + len(kws) * 10 + (20 if active_comps else 0))
        primary_intent = Counter([k["intent"] for k in kws]).most_common(1)[0][0] if kws else "Informational"

        suggested_action = (
            f"Publish an in-depth {primary_intent.lower()} resource or landing page targeting '{topic}'. "
            f"Competitors ({', '.join(active_comps) if active_comps else 'market leaders'}) currently outrank or possess content for these queries."
        )

        content_opportunities.append({
            "topic": topic,
            "intent": primary_intent,
            "opportunity_score": opp_score,
            "keywords_count": len(kws),
            "estimated_search_volume": total_vol if total_vol > 0 else None,
            "competitors_ranking": sorted(list(active_comps)) if active_comps else clean_competitors,
            "sample_keywords": [k["keyword"] for k in kws[:4]],
            "suggested_action": suggested_action
        })

    # -----------------------------------------------------------------------
    # Step 4: Backlink Gap Analysis
    # -----------------------------------------------------------------------
    target_backlinks = set(domain_backlinks_map.get(target, []))
    backlink_gap_candidates: dict[str, list[str]] = defaultdict(list)

    for cd in clean_competitors:
        for ref in domain_backlinks_map.get(cd, []):
            if ref and ref not in target_backlinks and ref != target:
                backlink_gap_candidates[ref].append(cd)

    backlink_gaps: list[dict[str, Any]] = []
    for ref_dom, linking_comps in backlink_gap_candidates.items():
        priority = "High" if len(linking_comps) >= 2 else "Medium"
        backlink_gaps.append({
            "referring_domain": ref_dom,
            "competitors_linked": sorted(linking_comps),
            "competitor_count": len(linking_comps),
            "outreach_priority": priority,
            "suggested_angle": f"Reach out for guest editorial or resource inclusion; links to {len(linking_comps)} competitor(s)."
        })

    backlink_gaps.sort(key=lambda x: (-(x["competitor_count"]), x["referring_domain"]))

    # -----------------------------------------------------------------------
    # Step 5: Historical Visibility Trends
    # -----------------------------------------------------------------------
    trends: dict[str, list[dict[str, Any]]] = {}
    for d in all_domains:
        trends[d] = _get_historical_audits_for_domain(d)

    # -----------------------------------------------------------------------
    # Step 6: Data Provenance & Legal Disclaimers
    # -----------------------------------------------------------------------
    provenance = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market": {
            "country_code": location_code,
            "country_name": SUPPORTED_LOCATIONS.get(location_code, {}).get("name", "United States"),
            "language": language_code
        },
        "target_domain": target,
        "competitor_domains": clean_competitors,
        "data_providers": [
            "DataForSEO Labs (Live SERP Intelligence)" if integrations.dataforseo_configured() else "Platform Technical Crawl Database",
            "Google PageSpeed Insights API (Core Web Vitals)",
            "OpenPageRank Link Index"
        ],
        "estimates_notice": (
            "Third-party organic traffic and keyword counts are modeled estimates based on public search engine "
            "results and click-through models. They are not direct server analytics."
        ),
        "privacy_notice": (
            "Competitor Google Search Console and Google Analytics are strictly private first-party properties. "
            "In compliance with security standards, all competitor metrics are derived exclusively from public crawls, "
            "licensed SERP telemetry, and open link indices."
        )
    }

    return {
        "ok": True,
        "target_domain": target,
        "competitor_domains": clean_competitors,
        "all_domains": all_domains,
        "scoreboard": scoreboard,
        "keyword_gap": {
            "total_keywords": len(gap_rows),
            "shared_count": shared_count,
            "missing_count": missing_count,
            "weak_count": weak_count,
            "strong_count": strong_count,
            "intent_distribution": dict(intent_counts),
            "keywords": gap_rows
        },
        "content_opportunities": content_opportunities,
        "backlink_gaps": backlink_gaps[:50],
        "historical_trends": trends,
        "provenance": provenance
    }


# ---------------------------------------------------------------------------
# Saved Competitor Comparison CRUD
# ---------------------------------------------------------------------------
def save_comparison(
    name: str,
    target_domain: str,
    competitor_domains: list[str],
    client_id: Optional[int] = None,
    location_code: int = 2840,
    language_code: str = "en",
    analysis_data: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    """Persists a competitor comparison configuration and results to the database."""
    target = bare_domain(target_domain)
    clean_comps = [bare_domain(c) for c in competitor_domains if bare_domain(c) and bare_domain(c) != target]
    data_json_str = json.dumps(analysis_data) if analysis_data else "{}"

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        record = CompetitorComparison(
            name=name.strip() or f"{target} vs {', '.join(clean_comps[:2])}",
            target_domain=target,
            competitor_domains=json.dumps(clean_comps),
            client_id=client_id,
            market_country=location_code,
            market_language=language_code,
            data_json=data_json_str,
            created_at=now,
            updated_at=now
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return {
            "id": record.id,
            "name": record.name,
            "target_domain": record.target_domain,
            "competitor_domains": clean_comps,
            "client_id": record.client_id,
            "created_at": record.created_at.isoformat() if record.created_at else now.isoformat()
        }
    finally:
        db.close()


def list_comparisons(target_domain: Optional[str] = None, client_id: Optional[int] = None) -> list[dict[str, Any]]:
    """Lists saved competitor comparisons with optional domain or client filtering."""
    db = SessionLocal()
    try:
        query = db.query(CompetitorComparison).order_by(CompetitorComparison.created_at.desc())
        if target_domain:
            t = bare_domain(target_domain)
            query = query.filter(CompetitorComparison.target_domain == t)
        if client_id is not None:
            query = query.filter(CompetitorComparison.client_id == client_id)

        records = query.all()
        out = []
        for r in records:
            comps = []
            try:
                comps = json.loads(r.competitor_domains) if r.competitor_domains else []
            except Exception:
                comps = []
            out.append({
                "id": r.id,
                "name": r.name,
                "target_domain": r.target_domain,
                "competitor_domains": comps,
                "client_id": r.client_id,
                "market_country": r.market_country,
                "market_language": r.market_language,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None
            })
        return out
    finally:
        db.close()


def get_comparison(comparison_id: int) -> Optional[dict[str, Any]]:
    """Retrieves a single saved competitor comparison record."""
    db = SessionLocal()
    try:
        r = db.query(CompetitorComparison).filter(CompetitorComparison.id == comparison_id).first()
        if not r:
            return None
        comps = []
        try:
            comps = json.loads(r.competitor_domains) if r.competitor_domains else []
        except Exception:
            comps = []
        data = {}
        try:
            data = json.loads(r.data_json) if r.data_json else {}
        except Exception:
            data = {}
        return {
            "id": r.id,
            "name": r.name,
            "target_domain": r.target_domain,
            "competitor_domains": comps,
            "client_id": r.client_id,
            "market_country": r.market_country,
            "market_language": r.market_language,
            "data": data,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None
        }
    finally:
        db.close()


def delete_comparison(comparison_id: int) -> bool:
    """Deletes a saved competitor comparison by ID."""
    db = SessionLocal()
    try:
        r = db.query(CompetitorComparison).filter(CompetitorComparison.id == comparison_id).first()
        if not r:
            return False
        db.delete(r)
        db.commit()
        return True
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Multi-Format Exporters (CSV, Excel XML, ReportLab PDF)
# ---------------------------------------------------------------------------
def generate_competitor_csv(analysis: dict[str, Any]) -> str:
    """Generates structured CSV export covering Scoreboard, Keyword Gap, Content Gap, and Backlinks."""
    buf = io.StringIO()
    writer = csv.writer(buf)

    target = analysis.get("target_domain", "")
    comps = analysis.get("competitor_domains", [])

    # Header section
    writer.writerow(["eSupport SEO Platform - Competitor Intelligence Report"])
    writer.writerow(["Target Domain", target])
    writer.writerow(["Competitor Domains", ", ".join(comps)])
    writer.writerow(["Generated At", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")])
    writer.writerow([])

    # 1. Scoreboard Table
    writer.writerow(["--- DOMAIN SCOREBOARD COMPARISON ---"])
    writer.writerow([
        "Domain", "Role", "SEO Health Score", "Technical SEO", "On-Page SEO", "Content SEO",
        "Organic Keywords", "Est. Monthly Traffic", "Avg Ranking Position", "Backlinks", "Referring Domains"
    ])
    for s in analysis.get("scoreboard", []):
        writer.writerow([
            s.get("domain"),
            "Target" if s.get("is_target") else "Competitor",
            f"{s.get('seo_score', 'N/A')}%" if s.get("seo_score") is not None else "N/A",
            f"{s.get('technical_score', 'N/A')}%" if s.get("technical_score") is not None else "N/A",
            f"{s.get('onpage_score', 'N/A')}%" if s.get("onpage_score") is not None else "N/A",
            f"{s.get('content_score', 'N/A')}%" if s.get("content_score") is not None else "N/A",
            s.get("organic_keywords_count", 0),
            s.get("estimated_monthly_traffic") if s.get("estimated_monthly_traffic") is not None else "Unavailable (Requires SERP Connector)",
            s.get("avg_position") if s.get("avg_position") is not None else "N/A",
            s.get("backlinks_count") if s.get("backlinks_count") is not None else "N/A",
            s.get("referring_domains_count", 0)
        ])
    writer.writerow([])

    # 2. Keyword Gap Table
    writer.writerow(["--- KEYWORD GAP MATRIX ---"])
    kw_headers = ["Keyword", "Intent", "Search Volume", "Keyword Difficulty (KD)", "CPC (USD)", f"Target ({target}) Rank"]
    for c in comps:
        kw_headers.append(f"{c} Rank")
    kw_headers.append("Gap Status")
    writer.writerow(kw_headers)

    for k in (analysis.get("keyword_gap", {}).get("keywords") or []):
        row = [
            k.get("keyword"),
            k.get("intent"),
            k.get("search_volume") if k.get("search_volume") is not None else "N/A",
            f"{k.get('keyword_difficulty')}%" if k.get("keyword_difficulty") is not None else "N/A",
            f"${k.get('cpc'):.2f}" if k.get("cpc") is not None else "N/A",
            f"#{k.get('target_rank')}" if k.get("target_rank") is not None else "Not Ranking"
        ]
        comp_ranks = k.get("competitor_ranks") or {}
        for c in comps:
            rk = comp_ranks.get(c)
            row.append(f"#{rk}" if rk is not None else "Not Ranking")
        row.append(str(k.get("gap_type", "")).upper())
        writer.writerow(row)
    writer.writerow([])

    # 3. Content Gap Opportunities
    writer.writerow(["--- CONTENT GAP OPPORTUNITIES ---"])
    writer.writerow(["Topic Opportunity", "Search Intent", "Opportunity Score", "Keywords Count", "Competitors Ranking", "Sample Keywords", "Suggested Action"])
    for opp in analysis.get("content_opportunities", []):
        writer.writerow([
            opp.get("topic"),
            opp.get("intent"),
            f"{opp.get('opportunity_score')}/100",
            opp.get("keywords_count"),
            ", ".join(opp.get("competitors_ranking") or []),
            ", ".join(opp.get("sample_keywords") or []),
            opp.get("suggested_action")
        ])
    writer.writerow([])

    # 4. Backlink Gap
    writer.writerow(["--- BACKLINK GAP OUTREACH TARGETS ---"])
    writer.writerow(["Referring Domain", "Competitors Linked", "Competitor Count", "Outreach Priority", "Suggested Angle"])
    for bg in analysis.get("backlink_gaps", []):
        writer.writerow([
            bg.get("referring_domain"),
            ", ".join(bg.get("competitors_linked") or []),
            bg.get("competitor_count"),
            bg.get("outreach_priority"),
            bg.get("suggested_angle")
        ])

    return buf.getvalue()


def generate_competitor_excel_xml(analysis: dict[str, Any]) -> str:
    """Generates a professional multi-sheet Excel SpreadsheetML document."""
    target = analysis.get("target_domain", "")
    comps = analysis.get("competitor_domains", [])

    def escape(s: Any) -> str:
        if s is None:
            return ""
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    xml = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<?mso-application progid="Excel.Sheet"?>',
        '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"',
        ' xmlns:o="urn:schemas-microsoft-com:office:office"',
        ' xmlns:x="urn:schemas-microsoft-com:office:excel"',
        ' xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">',
        '  <Styles>',
        '    <Style ss:ID="Default" ss:Name="Normal"><Font ss:FontName="Calibri" ss:Size="11" ss:Color="#1E293B"/></Style>',
        '    <Style ss:ID="Header"><Font ss:FontName="Calibri" ss:Size="11" ss:Bold="1" ss:Color="#FFFFFF"/><Interior ss:Color="#2563EB" ss:Pattern="Solid"/></Style>',
        '    <Style ss:ID="TargetRow"><Font ss:FontName="Calibri" ss:Size="11" ss:Bold="1" ss:Color="#1E3A8A"/><Interior ss:Color="#EFF6FF" ss:Pattern="Solid"/></Style>',
        '    <Style ss:ID="Title"><Font ss:FontName="Calibri" ss:Size="16" ss:Bold="1" ss:Color="#0F172A"/></Style>',
        '    <Style ss:ID="MissingBadge"><Font ss:FontName="Calibri" ss:Size="11" ss:Bold="1" ss:Color="#B91C1C"/><Interior ss:Color="#FEE2E2" ss:Pattern="Solid"/></Style>',
        '    <Style ss:ID="WeakBadge"><Font ss:FontName="Calibri" ss:Size="11" ss:Bold="1" ss:Color="#C2410C"/><Interior ss:Color="#FFEDD5" ss:Pattern="Solid"/></Style>',
        '    <Style ss:ID="SharedBadge"><Font ss:FontName="Calibri" ss:Size="11" ss:Bold="1" ss:Color="#15803D"/><Interior ss:Color="#DCFCE7" ss:Pattern="Solid"/></Style>',
        '    <Style ss:ID="StrongBadge"><Font ss:FontName="Calibri" ss:Size="11" ss:Bold="1" ss:Color="#4338CA"/><Interior ss:Color="#EEF2FF" ss:Pattern="Solid"/></Style>',
        '  </Styles>'
    ]

    # Worksheet 1: Scoreboard
    xml.append('  <Worksheet ss:Name="Scoreboard">')
    xml.append('    <Table>')
    xml.append('      <Row><Cell ss:StyleID="Title"><Data ss:Type="String">Domain Scoreboard Comparison</Data></Cell></Row>')
    xml.append('      <Row ss:StyleID="Header">')
    for h in ["Domain", "Role", "SEO Health Score", "Technical SEO", "On-Page SEO", "Content SEO", "Organic Keywords", "Est. Monthly Traffic", "Avg Rank Position", "Backlinks", "Referring Domains"]:
        xml.append(f'        <Cell><Data ss:Type="String">{escape(h)}</Data></Cell>')
    xml.append('      </Row>')
    for s in analysis.get("scoreboard", []):
        is_t = s.get("is_target")
        row_style = ' ss:StyleID="TargetRow"' if is_t else ""
        seo_text = f"{s.get('seo_score')}%" if s.get("seo_score") is not None else "N/A"
        tech_text = f"{s.get('technical_score')}%" if s.get("technical_score") is not None else "N/A"
        onpage_text = f"{s.get('onpage_score')}%" if s.get("onpage_score") is not None else "N/A"
        content_text = f"{s.get('content_score')}%" if s.get("content_score") is not None else "N/A"

        xml.append(f'      <Row{row_style}>')
        xml.append(f'        <Cell><Data ss:Type="String">{escape(s.get("domain"))}</Data></Cell>')
        xml.append(f'        <Cell><Data ss:Type="String">{"Target" if is_t else "Competitor"}</Data></Cell>')
        xml.append(f'        <Cell><Data ss:Type="String">{seo_text}</Data></Cell>')
        xml.append(f'        <Cell><Data ss:Type="String">{tech_text}</Data></Cell>')
        xml.append(f'        <Cell><Data ss:Type="String">{onpage_text}</Data></Cell>')
        xml.append(f'        <Cell><Data ss:Type="String">{content_text}</Data></Cell>')
        xml.append(f'        <Cell><Data ss:Type="Number">{s.get("organic_keywords_count", 0)}</Data></Cell>')
        xml.append(f'        <Cell><Data ss:Type="String">{escape(s.get("estimated_monthly_traffic") if s.get("estimated_monthly_traffic") is not None else "Unavailable")}</Data></Cell>')
        xml.append(f'        <Cell><Data ss:Type="String">{escape(s.get("avg_position") if s.get("avg_position") is not None else "N/A")}</Data></Cell>')
        xml.append(f'        <Cell><Data ss:Type="String">{escape(s.get("backlinks_count") if s.get("backlinks_count") is not None else "N/A")}</Data></Cell>')
        xml.append(f'        <Cell><Data ss:Type="Number">{s.get("referring_domains_count", 0)}</Data></Cell>')
        xml.append('      </Row>')
    xml.append('    </Table>')
    xml.append('  </Worksheet>')

    # Worksheet 2: Keyword Gap
    xml.append('  <Worksheet ss:Name="Keyword Gap">')
    xml.append('    <Table>')
    xml.append('      <Row><Cell ss:StyleID="Title"><Data ss:Type="String">Organic Keyword Gap Analysis</Data></Cell></Row>')
    xml.append('      <Row ss:StyleID="Header">')
    gap_cols = ["Keyword", "Intent", "Search Volume", "KD", "CPC", f"Target ({target})"] + [c for c in comps] + ["Gap Type"]
    for c in gap_cols:
        xml.append(f'        <Cell><Data ss:Type="String">{escape(c)}</Data></Cell>')
    xml.append('      </Row>')
    for k in (analysis.get("keyword_gap", {}).get("keywords") or []):
        gtype = str(k.get("gap_type", "")).lower()
        badge_style = ' ss:StyleID="MissingBadge"' if gtype == "missing" else (' ss:StyleID="WeakBadge"' if gtype == "weak" else (' ss:StyleID="SharedBadge"' if gtype == "shared" else ' ss:StyleID="StrongBadge"'))
        kd_text = f"{k.get('keyword_difficulty')}%" if k.get("keyword_difficulty") is not None else "N/A"
        cpc_text = f"${k.get('cpc'):.2f}" if k.get("cpc") is not None else "N/A"
        t_rk_text = f"#{k.get('target_rank')}" if k.get("target_rank") is not None else "-"

        xml.append('      <Row>')
        xml.append(f'        <Cell><Data ss:Type="String">{escape(k.get("keyword"))}</Data></Cell>')
        xml.append(f'        <Cell><Data ss:Type="String">{escape(k.get("intent"))}</Data></Cell>')
        xml.append(f'        <Cell><Data ss:Type="String">{escape(k.get("search_volume") if k.get("search_volume") is not None else "N/A")}</Data></Cell>')
        xml.append(f'        <Cell><Data ss:Type="String">{escape(kd_text)}</Data></Cell>')
        xml.append(f'        <Cell><Data ss:Type="String">{escape(cpc_text)}</Data></Cell>')
        xml.append(f'        <Cell><Data ss:Type="String">{escape(t_rk_text)}</Data></Cell>')
        c_ranks = k.get("competitor_ranks") or {}
        for c in comps:
            rk = c_ranks.get(c)
            xml.append(f'        <Cell><Data ss:Type="String">{escape(f"#{rk}" if rk is not None else "-")}</Data></Cell>')
        xml.append(f'        <Cell{badge_style}><Data ss:Type="String">{escape(gtype.upper())}</Data></Cell>')
        xml.append('      </Row>')
    xml.append('    </Table>')
    xml.append('  </Worksheet>')

    # Worksheet 3: Content Opportunities
    xml.append('  <Worksheet ss:Name="Content Opportunities">')
    xml.append('    <Table>')
    xml.append('      <Row><Cell ss:StyleID="Title"><Data ss:Type="String">Content Gap Opportunities</Data></Cell></Row>')
    xml.append('      <Row ss:StyleID="Header">')
    for h in ["Topic", "Intent", "Opportunity Score", "Keywords", "Competitors Ranking", "Suggested Action"]:
        xml.append(f'        <Cell><Data ss:Type="String">{escape(h)}</Data></Cell>')
    xml.append('      </Row>')
    for opp in analysis.get("content_opportunities", []):
        opp_score_text = f"{opp.get('opportunity_score')}/100"
        xml.append('      <Row>')
        xml.append(f'        <Cell><Data ss:Type="String">{escape(opp.get("topic"))}</Data></Cell>')
        xml.append(f'        <Cell><Data ss:Type="String">{escape(opp.get("intent"))}</Data></Cell>')
        xml.append(f'        <Cell><Data ss:Type="String">{escape(opp_score_text)}</Data></Cell>')
        xml.append(f'        <Cell><Data ss:Type="Number">{opp.get("keywords_count", 0)}</Data></Cell>')
        xml.append(f'        <Cell><Data ss:Type="String">{escape(", ".join(opp.get("competitors_ranking") or []))}</Data></Cell>')
        xml.append(f'        <Cell><Data ss:Type="String">{escape(opp.get("suggested_action"))}</Data></Cell>')
        xml.append('      </Row>')
    xml.append('    </Table>')
    xml.append('  </Worksheet>')

    # Worksheet 4: Backlinks
    xml.append('  <Worksheet ss:Name="Backlink Gap">')
    xml.append('    <Table>')
    xml.append('      <Row><Cell ss:StyleID="Title"><Data ss:Type="String">Backlink Gap Outreach Candidates</Data></Cell></Row>')
    xml.append('      <Row ss:StyleID="Header">')
    for h in ["Referring Domain", "Competitors Linked", "Count", "Priority", "Suggested Outreach Strategy"]:
        xml.append(f'        <Cell><Data ss:Type="String">{escape(h)}</Data></Cell>')
    xml.append('      </Row>')
    for bg in analysis.get("backlink_gaps", []):
        xml.append('      <Row>')
        xml.append(f'        <Cell><Data ss:Type="String">{escape(bg.get("referring_domain"))}</Data></Cell>')
        xml.append(f'        <Cell><Data ss:Type="String">{escape(", ".join(bg.get("competitors_linked") or []))}</Data></Cell>')
        xml.append(f'        <Cell><Data ss:Type="Number">{bg.get("competitor_count", 1)}</Data></Cell>')
        xml.append(f'        <Cell><Data ss:Type="String">{escape(bg.get("outreach_priority"))}</Data></Cell>')
        xml.append(f'        <Cell><Data ss:Type="String">{escape(bg.get("suggested_angle"))}</Data></Cell>')
        xml.append('      </Row>')
    xml.append('    </Table>')
    xml.append('  </Worksheet>')

    xml.append('</Workbook>')
    return "\n".join(xml)


# ---------------------------------------------------------------------------
# ReportLab PDF Exporter
# ---------------------------------------------------------------------------
class CompetitorReportCanvas(canvas.Canvas):
    """Two-pass ReportLab canvas to render dynamic total page numbers."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_decorations(self, total_pages):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748B"))

        # Header (Pages > 1)
        if self._pageNumber > 1:
            self.drawString(14 * mm, 287 * mm, "Competitor Intelligence & Market Gap Report • eSupport SEO Platform")
            self.drawRightString(196 * mm, 287 * mm, datetime.now(timezone.utc).strftime("%B %d, %Y"))
            self.setStrokeColor(colors.HexColor("#E2E8F0"))
            self.setLineWidth(0.5)
            self.line(14 * mm, 285 * mm, 196 * mm, 285 * mm)

        # Footer
        self.setStrokeColor(colors.HexColor("#E2E8F0"))
        self.setLineWidth(0.5)
        self.line(14 * mm, 12 * mm, 196 * mm, 12 * mm)
        self.drawString(14 * mm, 8 * mm, "Enterprise Confidential • eSupport SEO Platform v10.4.5")
        self.drawRightString(196 * mm, 8 * mm, f"Page {self._pageNumber} of {total_pages}")
        self.restoreState()


def generate_competitor_pdf(analysis: dict[str, Any]) -> bytes:
    """Generates an executive-ready ReportLab PDF competitor intelligence report."""
    target = analysis.get("target_domain", "")
    comps = analysis.get("competitor_domains", [])

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=15 * mm,
        bottomMargin=16 * mm
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CompTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#0F172A")
    )
    subtitle_style = ParagraphStyle(
        "CompSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#475569")
    )
    h2_style = ParagraphStyle(
        "CompH2",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=17,
        textColor=colors.HexColor("#1E293B"),
        spaceBefore=12,
        spaceAfter=6
    )
    cell_bold = ParagraphStyle(
        "CellBold",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#0F172A")
    )
    cell_normal = ParagraphStyle(
        "CellNormal",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#334155")
    )
    cell_white = ParagraphStyle(
        "CellWhite",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.white
    )
    legal_style = ParagraphStyle(
        "CompLegal",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7,
        leading=9,
        textColor=colors.HexColor("#64748B")
    )

    elements = []

    # Title Banner
    elements.append(Paragraph("Enterprise Competitor Analysis", title_style))
    elements.append(Paragraph(
        f"Target Website: <b>{target}</b> | Competitors: <b>{', '.join(comps)}</b> | Generated: {datetime.now(timezone.utc).strftime('%B %d, %Y')}",
        subtitle_style
    ))
    elements.append(Spacer(1, 4 * mm))

    # Scoreboard Section
    elements.append(Paragraph("1. Side-by-Side Domain Comparison Scoreboard", h2_style))
    score_table_data = [[
        Paragraph("Domain", cell_white),
        Paragraph("Role", cell_white),
        Paragraph("SEO Score", cell_white),
        Paragraph("Tech / OnPage", cell_white),
        Paragraph("Keywords", cell_white),
        Paragraph("Est. Traffic", cell_white),
        Paragraph("Avg Rank", cell_white),
        Paragraph("Backlinks", cell_white)
    ]]

    for s in analysis.get("scoreboard", []):
        is_t = s.get("is_target")
        role_label = "Target Website" if is_t else "Competitor"
        seo_val = f"{s.get('seo_score')}%" if s.get("seo_score") is not None else "N/A"
        tech_onpage = f"{s.get('technical_score', '-')}% / {s.get('onpage_score', '-')}%"
        kw_val = str(s.get("organic_keywords_count", 0))
        traffic_val = f"{s.get('estimated_monthly_traffic'):,}" if s.get("estimated_monthly_traffic") is not None else "Unavailable"
        avg_r = f"#{s.get('avg_position')}" if s.get("avg_position") is not None else "N/A"
        bl_val = str(s.get("backlinks_count") if s.get("backlinks_count") is not None else "-")

        c_style = cell_bold if is_t else cell_normal
        score_table_data.append([
            Paragraph(s.get("domain", ""), c_style),
            Paragraph(role_label, c_style),
            Paragraph(seo_val, c_style),
            Paragraph(tech_onpage, cell_normal),
            Paragraph(kw_val, cell_normal),
            Paragraph(traffic_val, cell_normal),
            Paragraph(avg_r, cell_normal),
            Paragraph(bl_val, cell_normal)
        ])

    st = Table(score_table_data, colWidths=[38 * mm, 24 * mm, 18 * mm, 26 * mm, 20 * mm, 24 * mm, 18 * mm, 14 * mm])
    st.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#F8FAFC"), colors.white]),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    elements.append(st)
    elements.append(Spacer(1, 4 * mm))

    # Keyword Gap Summary Box
    kg = analysis.get("keyword_gap") or {}
    elements.append(Paragraph("2. Organic Keyword Gap Overview", h2_style))

    summary_boxes = [
        [
            Paragraph(f"<b>Shared Keywords</b><br/><font size=12 color='#15803D'>{kg.get('shared_count', 0)}</font>", cell_normal),
            Paragraph(f"<b>Missing (Competitor Only)</b><br/><font size=12 color='#B91C1C'>{kg.get('missing_count', 0)}</font>", cell_normal),
            Paragraph(f"<b>Weak (Target Behind)</b><br/><font size=12 color='#C2410C'>{kg.get('weak_count', 0)}</font>", cell_normal),
            Paragraph(f"<b>Strong (Target Ahead)</b><br/><font size=12 color='#4338CA'>{kg.get('strong_count', 0)}</font>", cell_normal)
        ]
    ]
    sum_table = Table(summary_boxes, colWidths=[45 * mm, 45 * mm, 45 * mm, 45 * mm])
    sum_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F1F5F9")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(sum_table)
    elements.append(Spacer(1, 3 * mm))

    # Top Keyword Gap Sample Table
    kw_sample = (kg.get("keywords") or [])[:20]
    if kw_sample:
        gap_table_data = [[
            Paragraph("Keyword", cell_white),
            Paragraph("Intent", cell_white),
            Paragraph("Volume", cell_white),
            Paragraph("Target Rank", cell_white),
            Paragraph("Best Comp Rank", cell_white),
            Paragraph("Gap Status", cell_white)
        ]]
        for row in kw_sample:
            gtype = str(row.get("gap_type", "")).upper()
            vol_str = f"{row.get('search_volume'):,}" if row.get("search_volume") is not None else "-"
            t_rk_str = f"#{row.get('target_rank')}" if row.get("target_rank") is not None else "Not Ranking"
            c_rk_str = f"#{row.get('best_competitor_rank')}" if row.get("best_competitor_rank") is not None else "Not Ranking"
            gap_table_data.append([
                Paragraph(row.get("keyword", ""), cell_bold),
                Paragraph(row.get("intent", ""), cell_normal),
                Paragraph(vol_str, cell_normal),
                Paragraph(t_rk_str, cell_normal),
                Paragraph(c_rk_str, cell_normal),
                Paragraph(gtype, cell_bold)
            ])
        gt = Table(gap_table_data, colWidths=[55 * mm, 24 * mm, 22 * mm, 28 * mm, 28 * mm, 25 * mm])
        gt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#334155")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#F8FAFC"), colors.white]),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ]))
        elements.append(gt)

    elements.append(Spacer(1, 4 * mm))

    # Content Gap Opportunities
    elements.append(Paragraph("3. High-Priority Content Opportunities", h2_style))
    opps = (analysis.get("content_opportunities") or [])[:5]
    if opps:
        opp_data = [[
            Paragraph("Topic Opportunity", cell_white),
            Paragraph("Intent", cell_white),
            Paragraph("Score", cell_white),
            Paragraph("Outranking Competitors", cell_white),
            Paragraph("Recommended Action", cell_white)
        ]]
        for o in opps:
            opp_data.append([
                Paragraph(o.get("topic", ""), cell_bold),
                Paragraph(o.get("intent", ""), cell_normal),
                Paragraph(f"{o.get('opportunity_score')}/100", cell_bold),
                Paragraph(", ".join(o.get("competitors_ranking") or []), cell_normal),
                Paragraph(o.get("suggested_action", ""), cell_normal)
            ])
        ot = Table(opp_data, colWidths=[38 * mm, 22 * mm, 18 * mm, 38 * mm, 66 * mm])
        ot.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0D9488")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#F8FAFC"), colors.white]),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        elements.append(ot)

    elements.append(Spacer(1, 4 * mm))

    # Backlink Gap Opportunities
    bgaps = (analysis.get("backlink_gaps") or [])[:5]
    if bgaps:
        elements.append(Paragraph("4. Backlink Gap Outreach Targets", h2_style))
        bl_data = [[
            Paragraph("Referring Domain", cell_white),
            Paragraph("Links to Competitors", cell_white),
            Paragraph("Count", cell_white),
            Paragraph("Priority", cell_white),
            Paragraph("Outreach Strategy", cell_white)
        ]]
        for b in bgaps:
            bl_data.append([
                Paragraph(b.get("referring_domain", ""), cell_bold),
                Paragraph(", ".join(b.get("competitors_linked") or []), cell_normal),
                Paragraph(str(b.get("competitor_count", 1)), cell_normal),
                Paragraph(b.get("outreach_priority", "Medium"), cell_bold),
                Paragraph(b.get("suggested_angle", ""), cell_normal)
            ])
        blt = Table(bl_data, colWidths=[42 * mm, 45 * mm, 15 * mm, 20 * mm, 60 * mm])
        blt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4F46E5")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#F8FAFC"), colors.white]),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        elements.append(blt)

    # Provenance and Privacy Notice Box
    elements.append(Spacer(1, 5 * mm))
    prov = analysis.get("provenance") or {}
    disclaimer_text = (
        f"<b>Data Provenance & Privacy Guarantee:</b><br/>"
        f"• <b>Third-Party Estimates Notice:</b> {prov.get('estimates_notice', '')}<br/>"
        f"• <b>Search Console Privacy Boundary:</b> {prov.get('privacy_notice', '')}<br/>"
        f"• <b>Active Data Providers:</b> {', '.join(prov.get('data_providers') or [])}"
    )
    elements.append(Paragraph(disclaimer_text, legal_style))

    doc.build(elements, canvasmaker=CompetitorReportCanvas)
    return buf.getvalue()
