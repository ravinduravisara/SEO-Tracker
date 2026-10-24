"""
Enterprise Backlink Analytics & Intelligence Engine (Phase 6)
Inspired by Ahrefs Site Explorer & SEMrush Backlink Analytics.

Features:
- Total indexed backlinks, referring domains, referring main domains, IPs, and pages.
- Dofollow vs nofollow distribution & link velocity trends.
- Anchor text profiling & classification (Branded, Exact Match, Partial Match, Generic, Naked URL).
- Anchor over-optimization warning & toxicity radar.
- Referring domains explorer with status & link-type filtering.
- Internal Page Equity Score (IPES) & Platform Authority Index (PAI) using iterative PageRank (d=0.85).
- Competitor backlink gap intelligence.
- Multi-format exports: CSV, Excel XML, and executive ReportLab PDF.
- Persistent snapshot storage via BacklinkSnapshot model.
"""

from __future__ import annotations

import io
import csv
import json
import math
import re
from collections import defaultdict, Counter
from datetime import datetime, timezone
from typing import Any, Optional, Dict, List, Tuple
from urllib.parse import urlparse

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, PageBreak
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas
from sqlalchemy.orm import Session

from . import integrations
from .database import Audit, Client, BacklinkSnapshot, SessionLocal


# -----------------------------------------------------------------------------
# DOMAIN NORMALIZATION & HELPERS
# -----------------------------------------------------------------------------

def bare_domain(url_or_domain: str) -> str:
    """Normalize input URL or domain string to a lowercase bare hostname without 'www.'."""
    raw = (url_or_domain or "").strip()
    if not raw:
        return ""
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    try:
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return raw.lower().removeprefix("www.")


# -----------------------------------------------------------------------------
# ANCHOR TEXT CLASSIFICATION & OVER-OPTIMIZATION RADAR
# -----------------------------------------------------------------------------

GENERIC_ANCHOR_TERMS = {
    "click here", "here", "read more", "learn more", "visit", "website", "site",
    "link", "source", "more", "this page", "view", "details", "info", "homepage",
    "home", "online", "continue", "official site", "web", "page", "check here"
}

RISKY_TLDS = {
    ".xyz", ".top", ".tk", ".work", ".click", ".buzz", ".loan", ".racing", ".men",
    ".date", ".stream", ".trade", ".party", ".bid", ".club", ".online", ".guru"
}


def classify_anchor(
    anchor: str,
    target_domain: str,
    target_keywords: Optional[List[str]] = None
) -> Tuple[str, str]:
    """
    Classify anchor text into one of 5 distinct SEO categories:
    - Branded: matches target domain root or brand tokens
    - Naked URL: contains http/https/www or domain matches
    - Generic: call-to-action or generic navigational terms
    - Exact Match: matches known seed or target keywords exactly
    - Partial Match: contains target keywords alongside other terms
    Returns (category, badge_color_hex)
    """
    text = (anchor or "").strip()
    if not text or text == "<empty>":
        return "Empty / Image", "#94A3B8"

    lower = text.lower()
    dom_clean = bare_domain(target_domain)
    brand_tokens = [tok for tok in re.split(r"[\.\-_]", dom_clean) if len(tok) >= 3 and tok not in ("com", "org", "net", "edu", "gov", "lk", "io", "co")]

    # 1. Naked URL
    if lower.startswith(("http://", "https://", "www.")) or dom_clean in lower:
        return "Naked URL", "#06B6D4"

    # 2. Generic Anchor
    if lower in GENERIC_ANCHOR_TERMS:
        return "Generic", "#64748B"

    # 3. Branded
    for tok in brand_tokens:
        if tok in lower:
            return "Branded", "#10B981"

    # 4. Keyword Matches
    keywords = [k.lower().strip() for k in (target_keywords or []) if k.strip()]
    if keywords:
        for kw in keywords:
            if lower == kw:
                return "Exact Match", "#EF4444"
            if kw in lower:
                return "Partial Match", "#F59E0B"

    # Default heuristic if no explicit keywords list is passed
    words = lower.split()
    if len(words) <= 3 and any(len(w) >= 4 for w in words):
        return "Target Commercial", "#8B5CF6"

    return "Partial Match", "#F59E0B"


# -----------------------------------------------------------------------------
# INTERNAL LINK AUTHORITY MODELING (Platform Authority Index / IPES)
# Published Mathematical Methodology: Iterative PageRank (d=0.85) with crawl-depth
# damping and HTTP status-code equity weighting.
# -----------------------------------------------------------------------------

def calculate_internal_equity(pages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Computes Internal Page Equity Scores (IPES) and Platform Authority Index (PAI)
    across the internal crawl link graph.

    Methodology:
    1. Graph construction: internal inlinks and outlinks mapped across canonical URLs.
    2. Power iteration: PageRank algorithm with damping factor d=0.85, 30 iterations.
    3. Status weighting: HTTP 200 = 1.0, 3xx redirects = 0.5, 4xx/5xx errors = 0.0.
    4. Depth penalty: pages at crawl depth >= 4 suffer a 15% damping reduction.
    5. Normalization: scaled 0 to 100 with a baseline floor of 10 for accessible pages.
    6. Orphan detection: pages with 0 internal inbound links flagged with IPES = 0.
    """
    if not pages:
        return {
            "platform_authority_index": 0.0,
            "internal_pages_evaluated": 0,
            "orphan_pages_count": 0,
            "top_equity_pages": [],
            "orphan_pages": [],
            "anchor_distribution": [],
            "methodology": "No crawled pages available for internal equity modeling."
        }

    url_set = {p.get("url") for p in pages if p.get("url")}
    N = max(1, len(url_set))

    # Build adjacency: outlinks and inlinks
    outlinks_map: Dict[str, List[str]] = defaultdict(list)
    inlinks_map: Dict[str, List[str]] = defaultdict(list)
    status_map: Dict[str, int] = {}
    depth_map: Dict[str, int] = {}
    title_map: Dict[str, str] = {}
    anchor_counter: Counter[str] = Counter()

    for p in pages:
        u = p.get("url")
        if not u:
            continue
        status_map[u] = int(p.get("status") or 200)
        depth_map[u] = int(p.get("depth") or 1)
        title_map[u] = p.get("title") or ""

        # Internal link edges
        internal_links = p.get("internal_links") or []
        cleaned_targets = []
        for target in internal_links:
            # target can be dict or str
            t_url = target.get("url") if isinstance(target, dict) else str(target)
            t_anchor = (target.get("text") or target.get("anchor") or "").strip() if isinstance(target, dict) else ""
            if t_anchor and len(t_anchor) < 100:
                anchor_counter[t_anchor] += 1
            if t_url in url_set and t_url != u:
                cleaned_targets.append(t_url)

        # Unique outgoing edges to prevent artificial multi-link inflation
        unique_targets = list(set(cleaned_targets))
        outlinks_map[u] = unique_targets
        for tgt in unique_targets:
            inlinks_map[tgt].append(u)

    # PageRank Iteration
    d = 0.85
    base_pr = (1.0 - d) / N
    pr: Dict[str, float] = {u: 1.0 / N for u in url_set}

    for _ in range(30):
        next_pr: Dict[str, float] = {}
        sink_sum = sum(pr[u] for u in url_set if not outlinks_map.get(u))
        sink_share = (d * sink_sum) / N

        for u in url_set:
            rank_sum = 0.0
            for inbound_u in inlinks_map.get(u, []):
                out_deg = len(outlinks_map[inbound_u])
                if out_deg > 0:
                    # Status code weight
                    st = status_map.get(inbound_u, 200)
                    weight = 1.0 if st == 200 else (0.5 if 300 <= st < 400 else 0.0)
                    rank_sum += (pr[inbound_u] / out_deg) * weight

            dp = depth_map.get(u, 1)
            depth_multiplier = 0.85 if dp >= 4 else (0.92 if dp == 3 else 1.0)
            next_pr[u] = (base_pr + sink_share + d * rank_sum) * depth_multiplier
        pr = next_pr

    # Detect Orphans and scale to 0-100
    pr_vals = list(pr.values())
    min_pr = min(pr_vals) if pr_vals else 0.0
    max_pr = max(pr_vals) if pr_vals else 1.0
    rng = max_pr - min_pr if (max_pr - min_pr) > 1e-9 else 1.0

    scored_pages = []
    orphan_pages = []

    for u in url_set:
        in_count = len(inlinks_map.get(u, []))
        out_count = len(outlinks_map.get(u, []))
        dp = depth_map.get(u, 1)
        st = status_map.get(u, 200)

        if in_count == 0 and dp > 1:
            score = 0.0
            is_orphan = True
            orphan_pages.append({
                "url": u,
                "title": title_map.get(u, ""),
                "depth": dp,
                "status": st
            })
        else:
            is_orphan = False
            # Normalized 0-100 scale with baseline 10
            normalized = ((pr[u] - min_pr) / rng) * 90.0 + 10.0
            score = round(max(0.0, min(100.0, normalized)), 1)

        scored_pages.append({
            "url": u,
            "title": title_map.get(u, "") or u,
            "internal_equity_score": score,
            "inbound_internal_links": in_count,
            "outbound_internal_links": out_count,
            "depth": dp,
            "status": st,
            "is_orphan": is_orphan
        })

    # Sort pages by equity score descending
    scored_pages.sort(key=lambda x: (x["internal_equity_score"], x["inbound_internal_links"]), reverse=True)

    # Domain Platform Authority Index: Average of top 10% highest equity hubs
    top_n = max(1, int(len(scored_pages) * 0.15))
    top_scores = [p["internal_equity_score"] for p in scored_pages[:top_n]]
    domain_pai = round(sum(top_scores) / len(top_scores), 1) if top_scores else 0.0

    # Internal anchor distribution summary
    top_anchors = [{"anchor": k, "count": v} for k, v in anchor_counter.most_common(20)]

    return {
        "platform_authority_index": domain_pai,
        "internal_pages_evaluated": len(scored_pages),
        "orphan_pages_count": len(orphan_pages),
        "top_equity_pages": scored_pages[:50],
        "orphan_pages": orphan_pages[:20],
        "anchor_distribution": top_anchors,
        "methodology": (
            "Platform Authority Index (PAI) and Internal Page Equity Score (IPES) are calculated using "
            "an iterative PageRank simulation (d=0.85, 30 power iterations) over the crawl graph. "
            "Edges are weighted by HTTP status codes (200=1.0, 3xx=0.5, 4xx/5xx=0.0) with depth penalties "
            "applied beyond crawl depth 3. Pages with 0 internal inbound links are classified as orphan pages."
        )
    }


# -----------------------------------------------------------------------------
# TOXICITY RADAR & SUSPICIOUS PATTERN RECOGNITION
# -----------------------------------------------------------------------------

def evaluate_toxicity_radar(
    total_backlinks: int,
    referring_domains: int,
    spam_score: Optional[float],
    referring_domain_items: List[Dict[str, Any]],
    anchor_items: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Detect potentially suspicious link patterns and compute a Link Toxicity Radar.
    Evaluates:
    - Backlinks-to-referring-domains ratio (> 100:1 suggests sitewide/footer spam).
    - Spam score from backlink index.
    - Risky or low-trust TLD presence in referring domains.
    - Exact-match commercial anchor over-optimization.
    """
    flags = []
    risk_score = 0

    # 1. Sitewide link ratio
    if referring_domains > 0:
        ratio = round(total_backlinks / referring_domains, 1)
        if ratio > 150:
            flags.append({
                "severity": "HIGH",
                "code": "TOX_RATIO_CRITICAL",
                "title": "Severe Sitewide / Footer Link Skew",
                "detail": f"Ratio is {ratio}:1 ({total_backlinks:,} backlinks across only {referring_domains:,} domains). Suggests automated footer or sitewide spam."
            })
            risk_score += 40
        elif ratio > 60:
            flags.append({
                "severity": "MEDIUM",
                "code": "TOX_RATIO_WARN",
                "title": "Elevated Backlinks per Domain Ratio",
                "detail": f"Ratio is {ratio}:1, indicating repetitive links from single domains."
            })
            risk_score += 20
    else:
        ratio = 0.0

    # 2. Backlink Index Spam Score
    if spam_score is not None:
        if spam_score >= 40:
            flags.append({
                "severity": "HIGH",
                "code": "TOX_SPAM_SCORE_HIGH",
                "title": "High External Spam Score",
                "detail": f"The indexed spam score is {spam_score:.0f}/100. Audit backlink sources and disavow malicious referrers."
            })
            risk_score += 35
        elif spam_score >= 20:
            flags.append({
                "severity": "MEDIUM",
                "code": "TOX_SPAM_SCORE_MED",
                "title": "Moderate Spam Score",
                "detail": f"Spam score is {spam_score:.0f}/100. Monitor inbound link profiles closely."
            })
            risk_score += 15

    # 3. Risky TLDs
    risky_doms = []
    for d in referring_domain_items:
        dom_str = (d.get("domain") or "").lower()
        if any(dom_str.endswith(tld) for tld in RISKY_TLDS):
            risky_doms.append(dom_str)

    if len(risky_doms) >= 3:
        flags.append({
            "severity": "MEDIUM",
            "code": "TOX_RISKY_TLD",
            "title": "Low-Trust TLD Concentration",
            "detail": f"Detected {len(risky_doms)} referring domains from high-risk TLDs ({', '.join(risky_doms[:4])})."
        })
        risk_score += 20

    # 4. Anchor text over-optimization
    exact_count = 0
    total_anchor_links = 0
    for a in anchor_items:
        cat = a.get("category", "")
        bl = int(a.get("backlinks") or 0)
        total_anchor_links += bl
        if cat in ("Exact Match", "Target Commercial"):
            exact_count += bl

    if total_anchor_links > 0:
        exact_ratio = (exact_count / total_anchor_links) * 100
        if exact_ratio > 35:
            flags.append({
                "severity": "HIGH",
                "code": "TOX_ANCHOR_OVERFIT",
                "title": "Aggressive Commercial Anchor Profile",
                "detail": f"{exact_ratio:.1f}% of indexed anchor links are commercial exact matches. Natural link profiles typically feature > 50% branded/naked URLs."
            })
            risk_score += 30

    risk_level = "HIGH" if risk_score >= 50 else ("MODERATE" if risk_score >= 25 else "LOW")

    return {
        "risk_level": risk_level,
        "risk_score": min(100, risk_score),
        "backlinks_per_domain_ratio": ratio,
        "flags": flags,
        "flags_count": len(flags)
    }


# -----------------------------------------------------------------------------
# CORE BACKLINK PROFILE COMPOSER
# -----------------------------------------------------------------------------

def get_backlink_profile(
    target_url: str,
    db: Optional[Session] = None,
    refresh: bool = False
) -> Dict[str, Any]:
    """
    Build complete, honest Backlink Analytics intelligence for a target URL.
    - If DataForSEO or OpenPageRank credentials exist, queries real third-party indexes.
    - If unconfigured, clearly states provider status without inventing fake backlinks.
    - Always computes internal link authority modeling (PAI & IPES) from on-site crawl evidence.
    """
    domain = bare_domain(target_url)
    if not domain:
        return {"ok": False, "error": "Invalid target URL or domain provided."}

    # 1. Query external backlink index providers
    has_dfs = integrations.dataforseo_configured()
    has_opr = integrations.openpagerank_configured()

    ext_summary = {}
    ref_domains: List[Dict[str, Any]] = []
    anchors: List[Dict[str, Any]] = []
    timeseries: List[Dict[str, Any]] = []
    pages_ext: List[Dict[str, Any]] = []
    domain_authority: Optional[float] = None
    da_provider = "None"

    if has_dfs:
        ext_summary = integrations.backlinks(domain)
        ref_domains_resp = integrations.backlinks_referring_domains(domain, limit=100)
        ref_domains = ref_domains_resp.get("items", [])
        anchors_resp = integrations.backlinks_anchors(domain, limit=60)
        anchors = anchors_resp.get("items", [])
        ts_resp = integrations.backlinks_timeseries(domain)
        timeseries = ts_resp.get("items", [])
        pgs_resp = integrations.backlinks_pages(domain, limit=50)
        pages_ext = pgs_resp.get("items", [])

        rank = ext_summary.get("domain_rank")
        if rank is not None:
            domain_authority = float(ext_summary.get("score") or rank)
            da_provider = "DataForSEO Domain Rank (0-100)"
    elif has_opr:
        opr_res = integrations.openpagerank(domain)
        if opr_res.get("ok"):
            domain_authority = float(opr_res.get("rank") or 0.0)
            da_provider = "OpenPageRank Common Crawl Authority (0-10)"

    # Classified Anchors
    classified_anchors = []
    for a in anchors:
        text = a.get("anchor") or ""
        cat, color = classify_anchor(text, domain)
        classified_anchors.append({
            **a,
            "category": cat,
            "badge_color": color
        })

    # 2. Extract on-site crawl evidence for Internal Equity Modeling
    latest_pages = []
    observed_keywords = []
    if db is not None:
        latest_audit = (
            db.query(Audit)
            .filter(Audit.target_url.contains(domain))
            .order_by(Audit.created_at.desc())
            .first()
        )
        if latest_audit:
            try:
                res = json.loads(latest_audit.result_json) if isinstance(latest_audit.result_json, str) else (latest_audit.result_json or {})
                latest_pages = res.get("pages") or []
                observed_keywords = res.get("keywords") or []
            except Exception:
                latest_pages = []

    internal_equity = calculate_internal_equity(latest_pages)

    # If external anchors were empty, construct internal anchor profile from crawl graph
    if not classified_anchors and internal_equity.get("anchor_distribution"):
        for it in internal_equity["anchor_distribution"]:
            cat, color = classify_anchor(it["anchor"], domain, observed_keywords)
            classified_anchors.append({
                "anchor": it["anchor"],
                "backlinks": it["count"],
                "referring_domains": 1,
                "dofollow": it["count"],
                "nofollow": 0,
                "first_seen": "On-Site Internal Crawl",
                "category": cat,
                "badge_color": color,
                "is_internal": True
            })

    # Summary Metrics
    total_bl = ext_summary.get("backlinks")
    ref_dom_count = ext_summary.get("referring_domains")
    ref_ips = ext_summary.get("referring_ips")
    ref_main = ext_summary.get("referring_main_domains")
    dofollow_bl = ext_summary.get("dofollow_backlinks")
    broken_bl = ext_summary.get("broken_backlinks")
    spam_score = ext_summary.get("spam_score")

    # Toxicity Radar
    toxicity = evaluate_toxicity_radar(
        total_backlinks=total_bl or 0,
        referring_domains=ref_dom_count or 0,
        spam_score=spam_score,
        referring_domain_items=ref_domains,
        anchor_items=classified_anchors
    )

    is_live_external = bool(has_dfs and ext_summary.get("ok"))
    provider_note = (
        "Live external backlink index connected via DataForSEO API."
        if is_live_external else
        ("Live authority score connected via OpenPageRank API." if has_opr else
         "Live external backlink indexes require a connected provider (DataForSEO Backlinks API or OpenPageRank). "
         "Internal link equity and anchor profiles are measured from verified on-site crawl evidence.")
    )

    return {
        "ok": True,
        "target_domain": domain,
        "target_url": f"https://{domain}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "has_external_provider": is_live_external or has_opr,
        "data_provider_note": provider_note,
        "domain_authority": {
            "score": domain_authority,
            "provider": da_provider,
            "is_measured": domain_authority is not None
        },
        "platform_authority_index": {
            "score": internal_equity.get("platform_authority_index", 0.0),
            "label": "Platform Authority Index (PAI)",
            "methodology": internal_equity.get("methodology"),
            "pages_evaluated": internal_equity.get("internal_pages_evaluated", 0)
        },
        "overview": {
            "total_backlinks": total_bl,
            "referring_domains": ref_dom_count,
            "referring_main_domains": ref_main,
            "referring_ips": ref_ips,
            "dofollow_backlinks": dofollow_bl,
            "nofollow_backlinks": (total_bl - dofollow_bl) if (total_bl is not None and dofollow_bl is not None) else None,
            "dofollow_percentage": round((dofollow_bl / total_bl) * 100, 1) if (total_bl and dofollow_bl) else None,
            "broken_backlinks": broken_bl,
            "spam_score": spam_score,
            "external_data_available": is_live_external
        },
        "referring_domains": ref_domains,
        "anchor_profile": classified_anchors,
        "link_history": timeseries,
        "top_linked_pages": pages_ext or internal_equity.get("top_equity_pages", []),
        "internal_equity": internal_equity,
        "toxicity_radar": toxicity
    }


# -----------------------------------------------------------------------------
# COMPETITOR BACKLINK GAP ANALYSIS
# -----------------------------------------------------------------------------

def analyze_backlink_gap(
    target_domain: str,
    competitor_domains: List[str],
    db: Optional[Session] = None
) -> Dict[str, Any]:
    """
    Identifies referring domains that point to competitors but NOT to the target domain.
    """
    clean_target = bare_domain(target_domain)
    clean_comps = [bare_domain(c) for c in competitor_domains if bare_domain(c) and bare_domain(c) != clean_target][:4]

    if not clean_target:
        return {"ok": False, "error": "Target domain is required."}
    if not clean_comps:
        return {"ok": False, "error": "At least one competitor domain is required for backlink gap analysis."}

    # Gather referring domains for target and competitors
    target_domains_set = set()
    target_profile = integrations.backlinks_referring_domains(clean_target, limit=150)
    for it in target_profile.get("items", []):
        if it.get("domain"):
            target_domains_set.add(it["domain"].lower())

    gaps_map: Dict[str, Dict[str, Any]] = {}

    for comp in clean_comps:
        comp_profile = integrations.backlinks_referring_domains(comp, limit=150)
        for it in comp_profile.get("items", []):
            ref_dom = (it.get("domain") or "").lower()
            if not ref_dom or ref_dom in target_domains_set or ref_dom == clean_target:
                continue

            if ref_dom not in gaps_map:
                gaps_map[ref_dom] = {
                    "referring_domain": ref_dom,
                    "rank": it.get("rank"),
                    "backlinks_to_competitors": 0,
                    "competitor_links": {},
                    "first_seen": it.get("first_seen")
                }
            gaps_map[ref_dom]["backlinks_to_competitors"] += int(it.get("backlinks") or 1)
            gaps_map[ref_dom]["competitor_links"][comp] = int(it.get("backlinks") or 1)

    gap_list = list(gaps_map.values())
    for g in gap_list:
        g["competitors_count"] = len(g["competitor_links"])

    # Sort gaps: priority given to domains that link to MULTIPLE competitors
    gap_list.sort(key=lambda x: (x["competitors_count"], x["backlinks_to_competitors"], x.get("rank") or 0), reverse=True)

    return {
        "ok": True,
        "target_domain": clean_target,
        "competitor_domains": clean_comps,
        "total_backlink_gaps": len(gap_list),
        "target_referring_domains_count": len(target_domains_set),
        "high_priority_gaps_count": sum(1 for g in gap_list if g["competitors_count"] >= 2),
        "gaps": gap_list[:100]
    }


# -----------------------------------------------------------------------------
# SNAPSHOT CRUD OPERATIONS
# -----------------------------------------------------------------------------

def save_backlink_snapshot(
    db: Session,
    target_domain: str,
    profile_data: Dict[str, Any],
    client_id: Optional[int] = None
) -> BacklinkSnapshot:
    """Persist a point-in-time backlink intelligence snapshot into the database."""
    dom = bare_domain(target_domain)
    ov = profile_data.get("overview") or {}
    da = profile_data.get("domain_authority") or {}
    pai = profile_data.get("platform_authority_index") or {}
    tox = profile_data.get("toxicity_radar") or {}

    snap = BacklinkSnapshot(
        target_domain=dom,
        client_id=client_id,
        data_provider=da.get("provider", "DataForSEO / Internal Engine"),
        total_backlinks=int(ov.get("total_backlinks") or 0),
        referring_domains=int(ov.get("referring_domains") or 0),
        referring_main_domains=int(ov.get("referring_main_domains") or 0),
        referring_ips=int(ov.get("referring_ips") or 0),
        dofollow_backlinks=int(ov.get("dofollow_backlinks") or 0),
        nofollow_backlinks=int(ov.get("nofollow_backlinks") or 0),
        domain_authority=float(da.get("score")) if da.get("score") is not None else None,
        internal_equity_score=float(pai.get("score")) if pai.get("score") is not None else None,
        spam_score=float(ov.get("spam_score")) if ov.get("spam_score") is not None else None,
        data_json=json.dumps(profile_data)
    )
    db.add(snap)
    db.commit()
    db.refresh(snap)
    return snap


def list_backlink_snapshots(
    db: Session,
    target_domain: Optional[str] = None,
    client_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """List stored backlink snapshots ordered by creation date descending."""
    q = db.query(BacklinkSnapshot)
    if target_domain:
        q = q.filter(BacklinkSnapshot.target_domain == bare_domain(target_domain))
    if client_id:
        q = q.filter(BacklinkSnapshot.client_id == client_id)

    snapshots = q.order_by(BacklinkSnapshot.created_at.desc()).all()
    out = []
    for s in snapshots:
        out.append({
            "id": s.id,
            "target_domain": s.target_domain,
            "client_id": s.client_id,
            "data_provider": s.data_provider,
            "total_backlinks": s.total_backlinks,
            "referring_domains": s.referring_domains,
            "dofollow_backlinks": s.dofollow_backlinks,
            "domain_authority": s.domain_authority,
            "platform_authority_index": s.internal_equity_score,
            "created_at": s.created_at.isoformat() if s.created_at else None
        })
    return out


def get_backlink_snapshot(db: Session, snapshot_id: int) -> Optional[Dict[str, Any]]:
    """Retrieve full backlink snapshot including parsed JSON payload."""
    snap = db.query(BacklinkSnapshot).filter(BacklinkSnapshot.id == snapshot_id).first()
    if not snap:
        return None
    data = json.loads(snap.data_json) if snap.data_json else {}
    return {
        "id": snap.id,
        "target_domain": snap.target_domain,
        "client_id": snap.client_id,
        "created_at": snap.created_at.isoformat() if snap.created_at else None,
        "data": data
    }


def delete_backlink_snapshot(db: Session, snapshot_id: int) -> bool:
    """Delete a saved backlink snapshot by ID."""
    snap = db.query(BacklinkSnapshot).filter(BacklinkSnapshot.id == snapshot_id).first()
    if not snap:
        return False
    db.delete(snap)
    db.commit()
    return True


# -----------------------------------------------------------------------------
# EXPORTERS (CSV, EXCEL XML, PDF)
# -----------------------------------------------------------------------------

def generate_backlink_csv(profile: Dict[str, Any]) -> str:
    """Export referring domains and anchor profiles to RFC-4180 CSV format."""
    out = io.StringIO()
    writer = csv.writer(out)

    target = profile.get("target_domain", "")
    ov = profile.get("overview") or {}
    da = profile.get("domain_authority") or {}
    pai = profile.get("platform_authority_index") or {}

    # Section 1: Executive KPI Summary
    writer.writerow(["# BACKLINK ANALYTICS INTELLIGENCE REPORT", target])
    writer.writerow(["Generated At", profile.get("timestamp", "")])
    writer.writerow(["Total Backlinks", ov.get("total_backlinks") or "N/A"])
    writer.writerow(["Referring Domains", ov.get("referring_domains") or "N/A"])
    writer.writerow(["Dofollow Backlinks", ov.get("dofollow_backlinks") or "N/A"])
    writer.writerow(["Dofollow Ratio (%)", f"{ov.get('dofollow_percentage', 'N/A')}%"])
    writer.writerow(["Domain Authority Score", da.get("score") if da.get("score") is not None else "N/A"])
    writer.writerow(["Domain Authority Provider", da.get("provider", "N/A")])
    writer.writerow(["Platform Authority Index (PAI)", pai.get("score", "N/A")])
    writer.writerow([])

    # Section 2: Referring Domains
    writer.writerow(["# REFERRING DOMAINS EXPLORER"])
    writer.writerow(["Domain", "Rank", "Backlinks", "Dofollow", "Nofollow", "First Seen", "TLD", "IP Address"])
    for r in profile.get("referring_domains", []):
        writer.writerow([
            r.get("domain", ""),
            r.get("rank", ""),
            r.get("backlinks", 0),
            r.get("dofollow", 0),
            r.get("nofollow", 0),
            r.get("first_seen", ""),
            r.get("tld", ""),
            r.get("ip", "")
        ])
    writer.writerow([])

    # Section 3: Anchor Text Profile
    writer.writerow(["# ANCHOR TEXT PROFILE & CLASSIFICATION"])
    writer.writerow(["Anchor Text", "Classification", "Backlinks", "Referring Domains", "Dofollow", "First Seen"])
    for a in profile.get("anchor_profile", []):
        writer.writerow([
            a.get("anchor", ""),
            a.get("category", ""),
            a.get("backlinks", 0),
            a.get("referring_domains", 0),
            a.get("dofollow", 0),
            a.get("first_seen", "")
        ])
    writer.writerow([])

    # Section 4: Internal Link Equity Graph
    writer.writerow(["# INTERNAL LINK EQUITY SCORE (IPES)"])
    writer.writerow(["Page URL", "Internal Equity Score", "Inbound Links", "Outbound Links", "Crawl Depth", "Status", "Is Orphan"])
    for p in (profile.get("internal_equity") or {}).get("top_equity_pages", []):
        writer.writerow([
            p.get("url", ""),
            p.get("internal_equity_score", 0),
            p.get("inbound_internal_links", 0),
            p.get("outbound_internal_links", 0),
            p.get("depth", 1),
            p.get("status", 200),
            "YES" if p.get("is_orphan") else "NO"
        ])

    return out.getvalue()


def generate_backlink_excel_xml(profile: Dict[str, Any]) -> str:
    """Generate professional Microsoft Excel XML workbook with multiple worksheets."""
    target = profile.get("target_domain", "")
    ov = profile.get("overview") or {}
    da = profile.get("domain_authority") or {}
    pai = profile.get("platform_authority_index") or {}
    ref_doms = profile.get("referring_domains", [])
    anchors = profile.get("anchor_profile", [])
    internal_pgs = (profile.get("internal_equity") or {}).get("top_equity_pages", [])

    def esc_xml(val: Any) -> str:
        s = str(val if val is not None else "")
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    xml = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<?mso-application progid="Excel.Sheet"?>',
        '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"',
        ' xmlns:o="urn:schemas-microsoft-com:office:office"',
        ' xmlns:x="urn:schemas-microsoft-com:office:excel"',
        ' xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"',
        ' xmlns:html="http://www.w3.org/TR/REC-html40">',
        ' <Styles>',
        '  <Style ss:ID="Header">',
        '   <Font ss:Bold="1" ss:Color="#FFFFFF"/>',
        '   <Interior ss:Color="#2563EB" ss:Pattern="Solid"/>',
        '   <Alignment ss:Horizontal="Center"/>',
        '  </Style>',
        '  <Style ss:ID="SubHeader">',
        '   <Font ss:Bold="1" ss:Color="#0F172A"/>',
        '   <Interior ss:Color="#E2E8F0" ss:Pattern="Solid"/>',
        '  </Style>',
        '  <Style ss:ID="Bold"><Font ss:Bold="1"/></Style>',
        ' </Styles>',
    ]

    # Sheet 1: Executive Overview
    xml.append(' <Worksheet ss:Name="Overview">')
    xml.append('  <Table>')
    xml.append('   <Column ss:Width="220"/>')
    xml.append('   <Column ss:Width="260"/>')
    xml.append('   <Row ss:StyleID="Header"><Cell ss:MergeAcross="1"><Data ss:Type="String">eSupport SEO • Backlink Intelligence Overview</Data></Cell></Row>')
    xml.append(f'   <Row><Cell ss:StyleID="Bold"><Data ss:Type="String">Target Domain</Data></Cell><Cell><Data ss:Type="String">{esc_xml(target)}</Data></Cell></Row>')
    xml.append(f'   <Row><Cell ss:StyleID="Bold"><Data ss:Type="String">Total Backlinks</Data></Cell><Cell><Data ss:Type="String">{esc_xml(ov.get("total_backlinks", "Requires Provider"))}</Data></Cell></Row>')
    xml.append(f'   <Row><Cell ss:StyleID="Bold"><Data ss:Type="String">Referring Domains</Data></Cell><Cell><Data ss:Type="String">{esc_xml(ov.get("referring_domains", "Requires Provider"))}</Data></Cell></Row>')
    xml.append(f'   <Row><Cell ss:StyleID="Bold"><Data ss:Type="String">Dofollow Backlinks</Data></Cell><Cell><Data ss:Type="String">{esc_xml(ov.get("dofollow_backlinks", "Requires Provider"))}</Data></Cell></Row>')
    xml.append(f'   <Row><Cell ss:StyleID="Bold"><Data ss:Type="String">Domain Authority Score</Data></Cell><Cell><Data ss:Type="String">{esc_xml(da.get("score", "N/A"))} ({esc_xml(da.get("provider", "N/A"))})</Data></Cell></Row>')
    xml.append(f'   <Row><Cell ss:StyleID="Bold"><Data ss:Type="String">Platform Authority Index (PAI)</Data></Cell><Cell><Data ss:Type="String">{esc_xml(pai.get("score", 0))}/100 (Internal Equity Simulation)</Data></Cell></Row>')
    xml.append('  </Table>')
    xml.append(' </Worksheet>')

    # Sheet 2: Referring Domains
    xml.append(' <Worksheet ss:Name="Referring Domains">')
    xml.append('  <Table>')
    xml.append('   <Row ss:StyleID="Header">')
    for col in ["Domain", "Rank", "Backlinks", "Dofollow", "Nofollow", "First Seen"]:
        xml.append(f'    <Cell><Data ss:Type="String">{col}</Data></Cell>')
    xml.append('   </Row>')
    for r in ref_doms:
        xml.append('   <Row>')
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(r.get("domain"))}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="Number">{r.get("rank") or 0}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="Number">{r.get("backlinks") or 0}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="Number">{r.get("dofollow") or 0}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="Number">{r.get("nofollow") or 0}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(r.get("first_seen"))}</Data></Cell>')
        xml.append('   </Row>')
    xml.append('  </Table>')
    xml.append(' </Worksheet>')

    # Sheet 3: Anchors
    xml.append(' <Worksheet ss:Name="Anchor Profile">')
    xml.append('  <Table>')
    xml.append('   <Row ss:StyleID="Header">')
    for col in ["Anchor Text", "Classification", "Backlinks", "Referring Domains", "Dofollow"]:
        xml.append(f'    <Cell><Data ss:Type="String">{col}</Data></Cell>')
    xml.append('   </Row>')
    for a in anchors:
        xml.append('   <Row>')
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(a.get("anchor"))}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(a.get("category"))}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="Number">{a.get("backlinks") or 0}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="Number">{a.get("referring_domains") or 0}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="Number">{a.get("dofollow") or 0}</Data></Cell>')
        xml.append('   </Row>')
    xml.append('  </Table>')
    xml.append(' </Worksheet>')

    # Sheet 4: Internal Equity
    xml.append(' <Worksheet ss:Name="Internal Link Equity">')
    xml.append('  <Table>')
    xml.append('   <Row ss:StyleID="Header">')
    for col in ["Page URL", "Equity Score (0-100)", "Inlinks", "Outlinks", "Depth", "Orphan"]:
        xml.append(f'    <Cell><Data ss:Type="String">{col}</Data></Cell>')
    xml.append('   </Row>')
    for p in internal_pgs:
        xml.append('   <Row>')
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(p.get("url"))}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="Number">{p.get("internal_equity_score") or 0}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="Number">{p.get("inbound_internal_links") or 0}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="Number">{p.get("outbound_internal_links") or 0}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="Number">{p.get("depth") or 1}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="String">{"YES" if p.get("is_orphan") else "NO"}</Data></Cell>')
        xml.append('   </Row>')
    xml.append('  </Table>')
    xml.append(' </Worksheet>')

    xml.append('</Workbook>')
    return "\n".join(xml)


class BacklinkReportCanvas(canvas.Canvas):
    """ReportLab two-pass canvas for professional running headers and page numbers."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pages: List[Any] = []

    def showPage(self):
        self.pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total_pages = len(self.pages)
        for p in self.pages:
            self.__dict__.update(p)
            self.draw_header_footer(total_pages)
            super().showPage()
        super().save()

    def draw_header_footer(self, total_pages: int):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748B"))

        # Header on later pages
        if self._pageNumber > 1:
            self.drawString(14 * mm, 287 * mm, "Backlink Analytics & Link Equity Report • eSupport SEO Platform")
            self.drawRightString(196 * mm, 287 * mm, datetime.now(timezone.utc).strftime("%B %d, %Y"))
            self.setStrokeColor(colors.HexColor("#E2E8F0"))
            self.setLineWidth(0.5)
            self.line(14 * mm, 285 * mm, 196 * mm, 285 * mm)

        # Footer
        self.setStrokeColor(colors.HexColor("#E2E8F0"))
        self.setLineWidth(0.5)
        self.line(14 * mm, 12 * mm, 196 * mm, 12 * mm)
        self.drawString(14 * mm, 8 * mm, "Enterprise Confidential • eSupport SEO Platform v10.4.6")
        self.drawRightString(196 * mm, 8 * mm, f"Page {self._pageNumber} of {total_pages}")
        self.restoreState()


def generate_backlink_pdf(profile: Dict[str, Any]) -> bytes:
    """Generates an executive-ready ReportLab vector PDF backlink analytics report."""
    target = profile.get("target_domain", "")
    ov = profile.get("overview") or {}
    da = profile.get("domain_authority") or {}
    pai = profile.get("platform_authority_index") or {}
    tox = profile.get("toxicity_radar") or {}

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
        "BLTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#0F172A")
    )
    subtitle_style = ParagraphStyle(
        "BLSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#64748B")
    )
    section_title = ParagraphStyle(
        "BLSection",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#1E293B"),
        spaceBefore=14,
        spaceAfter=6
    )
    body_style = ParagraphStyle(
        "BLBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#334155")
    )
    method_style = ParagraphStyle(
        "BLMethod",
        parent=styles["Normal"],
        fontName="Helvetica-Oblique",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#475569")
    )

    story: List[Any] = []

    # Title Banner
    story.append(Paragraph("Backlink Analytics & Link Equity Report", title_style))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(
        f"Target Domain: <b>{target}</b> | Generated: {datetime.now(timezone.utc).strftime('%B %d, %Y')} | "
        f"Engine: eSupport SEO Platform v10.4.6",
        subtitle_style
    ))
    story.append(Spacer(1, 4 * mm))

    # Executive Scoreboard KPI Table
    bl_str = f"{ov.get('total_backlinks'):,}" if ov.get("total_backlinks") is not None else "Requires Provider"
    rd_str = f"{ov.get('referring_domains'):,}" if ov.get("referring_domains") is not None else "Requires Provider"
    df_str = f"{ov.get('dofollow_percentage', 'N/A')}%" if ov.get("dofollow_percentage") is not None else "N/A"
    pai_str = f"{pai.get('score', 0):.1f} / 100"
    da_str = f"{da.get('score'):.1f} / 100" if da.get("score") is not None else "Unavailable"

    kpi_data = [
        [
            Paragraph("<b>TOTAL BACKLINKS</b>", subtitle_style),
            Paragraph("<b>REFERRING DOMAINS</b>", subtitle_style),
            Paragraph("<b>DOFOLLOW RATIO</b>", subtitle_style),
            Paragraph("<b>PLATFORM AUTH. INDEX</b>", subtitle_style)
        ],
        [
            Paragraph(f"<font size=14 color='#2563EB'><b>{bl_str}</b></font>", title_style),
            Paragraph(f"<font size=14 color='#10B981'><b>{rd_str}</b></font>", title_style),
            Paragraph(f"<font size=14 color='#06B6D4'><b>{df_str}</b></font>", title_style),
            Paragraph(f"<font size=14 color='#8B5CF6'><b>{pai_str}</b></font>", title_style)
        ],
        [
            Paragraph(f"Provider: DataForSEO Index", subtitle_style),
            Paragraph(f"Main Domains: {ov.get('referring_main_domains') or 'N/A'}", subtitle_style),
            Paragraph(f"Dofollow: {ov.get('dofollow_backlinks') or 'N/A'}", subtitle_style),
            Paragraph(f"Internal Equity Score (IPES)", subtitle_style)
        ]
    ]

    kpi_table = Table(kpi_data, colWidths=[45 * mm, 45 * mm, 45 * mm, 47 * mm])
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(kpi_table)
    story.append(Spacer(1, 4 * mm))

    # Methodology Disclosure Box
    method_data = [[
        Paragraph(
            f"<b>Measurement Boundary & Methodology:</b> {profile.get('data_provider_note', '')}<br/>"
            f"<b>Platform Authority Index (PAI) Methodology:</b> {pai.get('methodology', '')}",
            method_style
        )
    ]]
    method_table = Table(method_data, colWidths=[182 * mm])
    method_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EFF6FF")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#BFDBFE")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(method_table)
    story.append(Spacer(1, 4 * mm))

    # Toxicity Radar Alert
    risk_level = tox.get("risk_level", "LOW")
    risk_color = "#10B981" if risk_level == "LOW" else ("#F59E0B" if risk_level == "MODERATE" else "#EF4444")
    flags = tox.get("flags") or []

    tox_intro = (
        f"Toxicity Risk Level: <font color='{risk_color}'><b>{risk_level}</b></font> (Score: {tox.get('risk_score', 0)}/100). "
        f"Backlinks-to-Domain Ratio: <b>{tox.get('backlinks_per_domain_ratio', 0)}:1</b>."
    )
    if flags:
        tox_intro += f" Detected <b>{len(flags)}</b> risk flag(s)."
    else:
        tox_intro += " No toxic link patterns detected."

    story.append(Paragraph("Link Toxicity & Suspicious Pattern Radar", section_title))
    story.append(Paragraph(tox_intro, body_style))
    story.append(Spacer(1, 2 * mm))

    # Top Referring Domains Table
    story.append(Paragraph("Top Referring Domains", section_title))
    ref_list = profile.get("referring_domains") or []
    if ref_list:
        ref_rows = [[
            Paragraph("<b>Domain</b>", subtitle_style),
            Paragraph("<b>Rank</b>", subtitle_style),
            Paragraph("<b>Backlinks</b>", subtitle_style),
            Paragraph("<b>Dofollow</b>", subtitle_style),
            Paragraph("<b>First Seen</b>", subtitle_style)
        ]]
        for r in ref_list[:10]:
            ref_rows.append([
                Paragraph(f"<b>{r.get('domain', '')}</b>", body_style),
                Paragraph(str(r.get("rank") or "—"), body_style),
                Paragraph(f"{r.get('backlinks', 0):,}", body_style),
                Paragraph(f"{r.get('dofollow', 0):,}", body_style),
                Paragraph(str(r.get("first_seen") or "—")[:10], body_style)
            ])
        ref_tbl = Table(ref_rows, colWidths=[65 * mm, 25 * mm, 30 * mm, 30 * mm, 32 * mm])
        ref_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F5F9")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(ref_tbl)
    else:
        story.append(Paragraph("<i>No third-party referring domains available without a connected DataForSEO API provider.</i>", body_style))

    story.append(Spacer(1, 4 * mm))

    # Anchor Text Breakdown
    story.append(Paragraph("Anchor Text Distribution & Classification", section_title))
    anc_list = profile.get("anchor_profile") or []
    if anc_list:
        anc_rows = [[
            Paragraph("<b>Anchor Text</b>", subtitle_style),
            Paragraph("<b>Classification</b>", subtitle_style),
            Paragraph("<b>Backlinks</b>", subtitle_style),
            Paragraph("<b>Ref. Domains</b>", subtitle_style)
        ]]
        for a in anc_list[:8]:
            anc_rows.append([
                Paragraph(f"\"{a.get('anchor', '')}\"", body_style),
                Paragraph(f"<b>{a.get('category', '')}</b>", body_style),
                Paragraph(f"{a.get('backlinks', 0):,}", body_style),
                Paragraph(f"{a.get('referring_domains', 0):,}", body_style)
            ])
        anc_tbl = Table(anc_rows, colWidths=[80 * mm, 40 * mm, 32 * mm, 30 * mm])
        anc_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F5F9")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(anc_tbl)
    else:
        story.append(Paragraph("<i>No anchor profile observed.</i>", body_style))

    doc.build(story, canvasmaker=BacklinkReportCanvas)
    return buf.getvalue()

