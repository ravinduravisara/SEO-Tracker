"""
Phase 8: Keyword Rank Tracking & SERP Intelligence Engine
Manages target keywords, scheduled live Google SERP position checks across desktop/mobile,
competitor position benchmarking, position delta tracking (winners/losers),
and alerts for significant ranking volatility.
"""

from __future__ import annotations

import io
import csv
import json
import logging
from datetime import datetime, timezone, timedelta
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
from .database import (
    TrackedKeyword,
    RankingObservation,
    RankingAlert,
    Website,
    Client,
)

logger = logging.getLogger("aviance.rank_tracker")


# -----------------------------------------------------------------------------
# DOMAIN NORMALIZATION & VISIBILITY SCORING
# -----------------------------------------------------------------------------

def bare_domain(url: str) -> str:
    """Normalizes any domain, hostname or URL to clean lower-case hostname."""
    if not url:
        return ""
    raw = str(url).strip().lower()
    if not (raw.startswith("http://") or raw.startswith("https://")):
        raw = "http://" + raw
    try:
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower().strip()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return raw.split("/")[0].replace("www.", "")


def calculate_visibility_score(positions: List[Optional[int]]) -> float:
    """
    Calculates SERP Visibility Index (Share of Voice 0-100%)
    using standard CTR-decay weighting for organic Google search:
    Rank 1: 32%, Rank 2: 18%, Rank 3: 11%, Rank 4-5: 6%, Rank 6-10: 3%, Rank 11-20: 1%
    """
    if not positions:
        return 0.0
    total_ctr = 0.0
    valid_count = 0
    for pos in positions:
        if pos is None or pos <= 0:
            continue
        valid_count += 1
        if pos == 1:
            total_ctr += 32.0
        elif pos == 2:
            total_ctr += 18.0
        elif pos == 3:
            total_ctr += 11.0
        elif pos in (4, 5):
            total_ctr += 6.0
        elif 6 <= pos <= 10:
            total_ctr += 3.0
        elif 11 <= pos <= 20:
            total_ctr += 1.0
        elif 21 <= pos <= 100:
            total_ctr += 0.2

    # Average visibility score per keyword
    return round(total_ctr / len(positions), 2)


# -----------------------------------------------------------------------------
# KEYWORD MANAGEMENT (CRUD)
# -----------------------------------------------------------------------------

def add_tracked_keywords(
    db: Session,
    keywords: List[str],
    target_domain: str,
    client_id: Optional[int] = None,
    website_id: Optional[int] = None,
    location_code: int = 2840,
    location_name: str = "United States",
    language_code: str = "en",
    device: str = "desktop",
    competitor_domains: Optional[List[str]] = None,
    tags: str = "",
    check_frequency: str = "daily"
) -> List[TrackedKeyword]:
    """
    Registers target keywords for live SERP position tracking.
    Avoids duplicate entries for the same keyword and domain.
    """
    clean_domain = bare_domain(target_domain)
    competitors = [bare_domain(c) for c in (competitor_domains or []) if bare_domain(c)]
    device_norm = "mobile" if str(device).lower() == "mobile" else "desktop"

    created = []
    for raw_kw in keywords:
        kw = raw_kw.strip()
        if not kw:
            continue

        existing = db.query(TrackedKeyword).filter(
            TrackedKeyword.target_domain == clean_domain,
            TrackedKeyword.keyword == kw,
            TrackedKeyword.device == device_norm,
            TrackedKeyword.location_code == location_code,
        ).first()

        if existing:
            # Update competitors and tags if changed
            existing.competitor_domains = json.dumps(competitors)
            if tags:
                existing.tags = tags
            existing.is_active = 1
            created.append(existing)
        else:
            tk = TrackedKeyword(
                client_id=client_id,
                website_id=website_id,
                keyword=kw,
                target_domain=clean_domain,
                location_code=location_code,
                location_name=location_name,
                language_code=language_code,
                device=device_norm,
                competitor_domains=json.dumps(competitors),
                check_frequency=check_frequency,
                tags=tags,
                is_active=1,
                alert_enabled=1,
            )
            db.add(tk)
            created.append(tk)

    db.commit()
    for item in created:
        db.refresh(item)
    return created


# -----------------------------------------------------------------------------
# LIVE SERP POSITION CHECKER & OBSERVATION RECORDING
# -----------------------------------------------------------------------------

def check_keyword_ranking(db: Session, tracked_keyword_id: int) -> Dict[str, Any]:
    """
    Performs live Google SERP check for a single tracked keyword.
    Finds exact ranking position for target domain and all competitors.
    Records a timestamped observation, calculates position changes, and generates alerts.
    """
    tk = db.query(TrackedKeyword).filter(TrackedKeyword.id == tracked_keyword_id).first()
    if not tk:
        raise ValueError(f"Tracked keyword #{tracked_keyword_id} not found.")

    keyword = tk.keyword
    target = tk.target_domain
    device = tk.device or "desktop"
    loc_code = tk.location_code or 2840
    lang_code = tk.language_code or "en"
    competitors = json.loads(tk.competitor_domains or "[]")

    # 1. Fetch live Google SERP via integrations
    serp_res = integrations.google_live_serp(
        keyword=keyword,
        location_code=loc_code,
        language_code=lang_code,
        device=device,
        depth=100
    )

    items = serp_res.get("items") or []
    serp_features = serp_res.get("serp_features") or []

    # 2. Extract position and URL for target domain
    new_position: Optional[int] = None
    absolute_position: Optional[int] = None
    ranked_url: str = ""

    # Find earliest organic match for target domain
    for it in items:
        it_domain = bare_domain(it.get("domain") or it.get("url") or "")
        if it_domain == target or it_domain.endswith("." + target):
            new_position = it.get("rank_group")
            absolute_position = it.get("rank_absolute")
            ranked_url = it.get("url", "")
            break

    # 3. Extract positions for competitors
    comp_positions: Dict[str, Optional[int]] = {}
    for comp in competitors:
        comp_positions[comp] = None
        for it in items:
            it_domain = bare_domain(it.get("domain") or it.get("url") or "")
            if it_domain == comp or it_domain.endswith("." + comp):
                comp_positions[comp] = it.get("rank_group")
                break

    # 4. Compute Position Delta
    prev_pos = tk.current_position
    pos_change = 0
    if prev_pos is not None and new_position is not None:
        # Lower rank number = better rank (e.g. rank 10 -> rank 5 is +5 improvement)
        pos_change = prev_pos - new_position
    elif prev_pos is None and new_position is not None:
        # Gained new ranking
        pos_change = 100 - new_position
    elif prev_pos is not None and new_position is None:
        # Dropped out of top 100
        pos_change = -(100 - prev_pos)

    # 5. Record Observation
    now_utc = datetime.now(timezone.utc)
    obs = RankingObservation(
        tracked_keyword_id=tk.id,
        collected_at=now_utc,
        target_domain=target,
        device=device,
        position=new_position,
        absolute_position=absolute_position,
        ranked_url=ranked_url,
        serp_features_json=json.dumps(serp_features),
        competitor_positions_json=json.dumps(comp_positions),
    )
    db.add(obs)

    # 6. Update Tracked Keyword Summary
    tk.previous_position = prev_pos
    tk.current_position = new_position
    tk.position_change = pos_change
    tk.latest_url = ranked_url
    tk.last_checked_at = now_utc

    if new_position is not None:
        if tk.best_position is None or new_position < tk.best_position:
            tk.best_position = new_position

    # 7. Generate Volatility Alerts
    if tk.alert_enabled:
        alerts = _evaluate_ranking_alerts(tk, prev_pos, new_position, pos_change)
        for a in alerts:
            db.add(a)

    db.commit()
    db.refresh(tk)
    db.refresh(obs)

    return {
        "ok": True,
        "tracked_keyword_id": tk.id,
        "keyword": tk.keyword,
        "target_domain": target,
        "device": device,
        "current_position": new_position,
        "previous_position": prev_pos,
        "position_change": pos_change,
        "best_position": tk.best_position,
        "ranked_url": ranked_url,
        "competitor_positions": comp_positions,
        "serp_features": serp_features,
        "collected_at": now_utc.isoformat(),
        "source": serp_res.get("source", "DataForSEO Google Organic SERP API")
    }


def _evaluate_ranking_alerts(
    tk: TrackedKeyword,
    prev_pos: Optional[int],
    new_pos: Optional[int],
    change: int
) -> List[RankingAlert]:
    """Generates ranking volatility alert events based on position boundaries."""
    alerts = []
    kw = tk.keyword
    domain = tk.target_domain

    # 1. Entered Top 3
    if new_pos is not None and new_pos <= 3 and (prev_pos is None or prev_pos > 3):
        alerts.append(RankingAlert(
            tracked_keyword_id=tk.id,
            target_domain=domain,
            keyword=kw,
            alert_type="ENTERED_TOP_3",
            severity="SUCCESS",
            message=f"'{kw}' entered Google Top 3 at rank #{new_pos}!",
            previous_position=prev_pos,
            new_position=new_pos
        ))

    # 2. Entered Top 10 (Page 1)
    elif new_pos is not None and new_pos <= 10 and (prev_pos is None or prev_pos > 10):
        alerts.append(RankingAlert(
            tracked_keyword_id=tk.id,
            target_domain=domain,
            keyword=kw,
            alert_type="ENTERED_TOP_10",
            severity="SUCCESS",
            message=f"'{kw}' reached Page 1 at rank #{new_pos}.",
            previous_position=prev_pos,
            new_position=new_pos
        ))

    # 3. Dropped Out of Top 10
    if prev_pos is not None and prev_pos <= 10 and (new_pos is None or new_pos > 10):
        alerts.append(RankingAlert(
            tracked_keyword_id=tk.id,
            target_domain=domain,
            keyword=kw,
            alert_type="DROPPED_TOP_10",
            severity="WARNING",
            message=f"'{kw}' dropped off Page 1 from #{prev_pos} to #{new_pos or '>100'}.",
            previous_position=prev_pos,
            new_position=new_pos
        ))

    # 4. Major Gain (>= 5 positions)
    if change >= 5 and new_pos is not None:
        alerts.append(RankingAlert(
            tracked_keyword_id=tk.id,
            target_domain=domain,
            keyword=kw,
            alert_type="MAJOR_GAIN",
            severity="SUCCESS",
            message=f"'{kw}' surged +{change} positions to rank #{new_pos}.",
            previous_position=prev_pos,
            new_position=new_pos
        ))

    # 5. Major Drop (<= -5 positions)
    elif change <= -5:
        alerts.append(RankingAlert(
            tracked_keyword_id=tk.id,
            target_domain=domain,
            keyword=kw,
            alert_type="MAJOR_DROP",
            severity="DANGER",
            message=f"'{kw}' fell {abs(change)} positions to rank #{new_pos or '>100'}.",
            previous_position=prev_pos,
            new_position=new_pos
        ))

    return alerts


def check_all_rankings(
    db: Session,
    target_domain: Optional[str] = None,
    website_id: Optional[int] = None
) -> Dict[str, Any]:
    """Runs ranking checks across all registered active keywords."""
    query = db.query(TrackedKeyword).filter(TrackedKeyword.is_active == 1)
    if target_domain:
        query = query.filter(TrackedKeyword.target_domain == bare_domain(target_domain))
    if website_id:
        query = query.filter(TrackedKeyword.website_id == website_id)

    keywords = query.all()
    results = []
    improved = 0
    declined = 0
    unchanged = 0

    for tk in keywords:
        try:
            res = check_keyword_ranking(db, tk.id)
            results.append(res)
            ch = res.get("position_change", 0)
            if ch > 0:
                improved += 1
            elif ch < 0:
                declined += 1
            else:
                unchanged += 1
        except Exception as exc:
            logger.warning("Ranking check failed for keyword #%s (%s): %s", tk.id, tk.keyword, exc)

    return {
        "ok": True,
        "total_checked": len(results),
        "improved_count": improved,
        "declined_count": declined,
        "unchanged_count": unchanged,
        "results": results
    }


# -----------------------------------------------------------------------------
# ANALYTICS, AGGREGATIONS & COMPETITOR BENCHMARKING
# -----------------------------------------------------------------------------

def get_rankings_overview(
    db: Session,
    target_domain: Optional[str] = None,
    website_id: Optional[int] = None,
    device: Optional[str] = None
) -> Dict[str, Any]:
    """
    Constructs high-level SERP analytics overview:
    - Position Distribution (Top 3, 4-10, 11-20, 21-50, 51-100, Unranked)
    - Average Position and Visibility Score (Share of Voice)
    - Top Winners & Losers (largest +/- position deltas)
    - Competitor Benchmark Matrix (head-to-head comparison per keyword)
    - Historical Volatility and Recent Alerts
    """
    query = db.query(TrackedKeyword).filter(TrackedKeyword.is_active == 1)
    clean_target = bare_domain(target_domain) if target_domain else None
    if clean_target:
        query = query.filter(TrackedKeyword.target_domain == clean_target)
    if website_id:
        query = query.filter(TrackedKeyword.website_id == website_id)
    if device:
        query = query.filter(TrackedKeyword.device == device.lower())

    keywords = query.order_by(TrackedKeyword.keyword.asc()).all()
    if not keywords:
        return {
            "ok": True,
            "target_domain": clean_target or "",
            "total_keywords": 0,
            "average_position": 0.0,
            "visibility_score": 0.0,
            "distribution": {"top_3": 0, "top_10": 0, "top_20": 0, "top_50": 0, "top_100": 0, "unranked": 0},
            "winners": [],
            "losers": [],
            "keywords": [],
            "competitor_summary": {},
            "recent_alerts": [],
            "disclaimer": (
                "Data Measurement Boundaries: Live SERP ranking checks represent snapshot positions in organic search "
                "for the selected location, language, and device. Search Console average position represents aggregated "
                "searcher impressions over time and is not an exact live rank on any single user's device."
            )
        }

    # Aggregate positions
    all_positions = [k.current_position for k in keywords]
    ranked_positions = [k.current_position for k in keywords if k.current_position is not None]
    avg_pos = round(sum(ranked_positions) / len(ranked_positions), 1) if ranked_positions else 0.0
    visibility = calculate_visibility_score(all_positions)

    # Buckets
    dist = {"top_3": 0, "top_10": 0, "top_20": 0, "top_50": 0, "top_100": 0, "unranked": 0}
    for pos in all_positions:
        if pos is None:
            dist["unranked"] += 1
        elif pos <= 3:
            dist["top_3"] += 1
            dist["top_10"] += 1
            dist["top_20"] += 1
            dist["top_50"] += 1
            dist["top_100"] += 1
        elif pos <= 10:
            dist["top_10"] += 1
            dist["top_20"] += 1
            dist["top_50"] += 1
            dist["top_100"] += 1
        elif pos <= 20:
            dist["top_20"] += 1
            dist["top_50"] += 1
            dist["top_100"] += 1
        elif pos <= 50:
            dist["top_50"] += 1
            dist["top_100"] += 1
        else:
            dist["top_100"] += 1

    # Winners & Losers
    with_change = [k for k in keywords if k.position_change != 0]
    winners_sorted = sorted([k for k in with_change if k.position_change > 0], key=lambda x: x.position_change, reverse=True)
    losers_sorted = sorted([k for k in with_change if k.position_change < 0], key=lambda x: x.position_change)

    # Format Keyword rows and gather competitor ranks
    kw_rows = []
    competitor_ranks_map: Dict[str, List[int]] = {}

    for k in keywords:
        comps = json.loads(k.competitor_domains or "[]")
        # Grab latest observation to get competitor positions
        latest_obs = db.query(RankingObservation).filter(
            RankingObservation.tracked_keyword_id == k.id
        ).order_by(RankingObservation.collected_at.desc()).first()

        c_positions = json.loads(latest_obs.competitor_positions_json or "{}") if latest_obs else {}

        for c_dom, c_pos in c_positions.items():
            if c_pos:
                competitor_ranks_map.setdefault(c_dom, []).append(c_pos)

        kw_rows.append({
            "id": k.id,
            "keyword": k.keyword,
            "target_domain": k.target_domain,
            "device": k.device,
            "location_name": k.location_name,
            "location_code": k.location_code,
            "language_code": k.language_code,
            "current_position": k.current_position,
            "previous_position": k.previous_position,
            "position_change": k.position_change,
            "best_position": k.best_position,
            "latest_url": k.latest_url,
            "search_volume": k.search_volume,
            "keyword_difficulty": k.keyword_difficulty,
            "tags": k.tags,
            "competitors": c_positions,
            "last_checked_at": k.last_checked_at.isoformat() if k.last_checked_at else None,
        })

    # Competitor Comparison Summary
    competitor_summary = {}
    for c_dom, ranks in competitor_ranks_map.items():
        competitor_summary[c_dom] = {
            "ranked_keywords_count": len(ranks),
            "average_position": round(sum(ranks) / len(ranks), 1) if ranks else 0.0,
            "top_3_count": len([r for r in ranks if r <= 3]),
            "top_10_count": len([r for r in ranks if r <= 10]),
        }

    # Recent Alerts
    alerts_query = db.query(RankingAlert)
    if clean_target:
        alerts_query = alerts_query.filter(RankingAlert.target_domain == clean_target)
    recent_alerts = alerts_query.order_by(RankingAlert.created_at.desc()).limit(15).all()

    alert_rows = [{
        "id": a.id,
        "keyword": a.keyword,
        "alert_type": a.alert_type,
        "severity": a.severity,
        "message": a.message,
        "previous_position": a.previous_position,
        "new_position": a.new_position,
        "is_read": bool(a.is_read),
        "created_at": a.created_at.isoformat() if a.created_at else None,
    } for a in recent_alerts]

    disclaimer = (
        "Google Search Console average position represents aggregated searcher impressions and geographic "
        "query distribution over time. It does not represent an exact live rank on any single user's device. "
        "Live SERP rankings represent real-time organic search result positions retrieved via authorized search APIs."
    )

    return {
        "ok": True,
        "target_domain": clean_target or (keywords[0].target_domain if keywords else ""),
        "total_keywords": len(keywords),
        "average_position": avg_pos,
        "visibility_score": visibility,
        "distribution": dist,
        "winners": [{
            "id": w.id, "keyword": w.keyword, "position": w.current_position, "change": w.position_change
        } for w in winners_sorted[:8]],
        "losers": [{
            "id": l.id, "keyword": l.keyword, "position": l.current_position, "change": l.position_change
        } for l in losers_sorted[:8]],
        "keywords": kw_rows,
        "competitor_summary": competitor_summary,
        "recent_alerts": alert_rows,
        "disclaimer": disclaimer,
    }


def get_keyword_history(db: Session, tracked_keyword_id: int, days: int = 90) -> Dict[str, Any]:
    """Returns chronological ranking trajectory and competitor benchmarks for a single keyword."""
    tk = db.query(TrackedKeyword).filter(TrackedKeyword.id == tracked_keyword_id).first()
    if not tk:
        raise ValueError(f"Tracked keyword #{tracked_keyword_id} not found.")

    since = datetime.now(timezone.utc) - timedelta(days=days)
    observations = db.query(RankingObservation).filter(
        RankingObservation.tracked_keyword_id == tk.id,
        RankingObservation.collected_at >= since
    ).order_by(RankingObservation.collected_at.asc()).all()

    timeline = []
    for obs in observations:
        timeline.append({
            "id": obs.id,
            "collected_at": obs.collected_at.isoformat() if obs.collected_at else None,
            "date": obs.collected_at.strftime("%Y-%m-%d") if obs.collected_at else "",
            "position": obs.position,
            "absolute_position": obs.absolute_position,
            "ranked_url": obs.ranked_url,
            "competitor_positions": json.loads(obs.competitor_positions_json or "{}"),
            "serp_features": json.loads(obs.serp_features_json or "[]"),
        })

    alerts = db.query(RankingAlert).filter(
        RankingAlert.tracked_keyword_id == tk.id
    ).order_by(RankingAlert.created_at.desc()).all()

    return {
        "ok": True,
        "tracked_keyword_id": tk.id,
        "keyword": tk.keyword,
        "target_domain": tk.target_domain,
        "device": tk.device,
        "location_name": tk.location_name,
        "current_position": tk.current_position,
        "best_position": tk.best_position,
        "position_change": tk.position_change,
        "competitors": json.loads(tk.competitor_domains or "[]"),
        "timeline": timeline,
        "alerts": [{
            "id": a.id,
            "alert_type": a.alert_type,
            "severity": a.severity,
            "message": a.message,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        } for a in alerts]
    }


# -----------------------------------------------------------------------------
# MULTI-FORMAT EXPORTERS (CSV, EXCEL XML, VECTOR REPORTLAB PDF)
# -----------------------------------------------------------------------------

def generate_rankings_csv(overview: Dict[str, Any]) -> str:
    """Produces RFC-4180 CSV export of tracked keyword positions."""
    out = io.StringIO()
    writer = csv.writer(out)

    target = overview.get("target_domain", "")
    writer.writerow(["# KEYWORD RANK TRACKING REPORT", target])
    writer.writerow(["Generated At", datetime.now(timezone.utc).isoformat()])
    writer.writerow(["Total Tracked Keywords", overview.get("total_keywords", 0)])
    writer.writerow(["Average SERP Position", overview.get("average_position", 0)])
    writer.writerow(["Visibility Score (Share of Voice)", f"{overview.get('visibility_score', 0)}%"])
    writer.writerow([])

    # Table
    writer.writerow([
        "Keyword", "Target Domain", "Device", "Location", "Current Rank",
        "Previous Rank", "Change", "Best Rank", "Ranking URL", "Search Volume", "KD"
    ])
    for kw in overview.get("keywords", []):
        writer.writerow([
            kw.get("keyword", ""),
            kw.get("target_domain", ""),
            kw.get("device", "desktop"),
            kw.get("location_name", ""),
            kw.get("current_position") if kw.get("current_position") is not None else ">100",
            kw.get("previous_position") if kw.get("previous_position") is not None else ">100",
            f"+{kw.get('position_change')}" if (kw.get("position_change") or 0) > 0 else kw.get("position_change", 0),
            kw.get("best_position") or "-",
            kw.get("latest_url", ""),
            kw.get("search_volume") or "-",
            kw.get("keyword_difficulty") or "-"
        ])

    return out.getvalue()


def generate_rankings_excel_xml(overview: Dict[str, Any]) -> str:
    """Produces Microsoft Excel 2003 XML workbook with multiple worksheets."""
    target = overview.get("target_domain", "")

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
        '   <Interior ss:Color="#4F46E5" ss:Pattern="Solid"/>',
        '   <Alignment ss:Horizontal="Center"/>',
        '  </Style>',
        '  <Style ss:ID="Bold"><Font ss:Bold="1"/></Style>',
        ' </Styles>',
    ]

    # Worksheet 1: Overview
    xml.append(' <Worksheet ss:Name="Overview">')
    xml.append('  <Table>')
    xml.append('   <Column ss:Width="200"/>')
    xml.append('   <Column ss:Width="240"/>')
    xml.append('   <Row ss:StyleID="Header"><Cell ss:MergeAcross="1"><Data ss:Type="String">Keyword Position Tracking Overview</Data></Cell></Row>')
    xml.append(f'   <Row><Cell ss:StyleID="Bold"><Data ss:Type="String">Target Domain</Data></Cell><Cell><Data ss:Type="String">{esc_xml(target)}</Data></Cell></Row>')
    xml.append(f'   <Row><Cell ss:StyleID="Bold"><Data ss:Type="String">Total Keywords</Data></Cell><Cell><Data ss:Type="Number">{overview.get("total_keywords", 0)}</Data></Cell></Row>')
    xml.append(f'   <Row><Cell ss:StyleID="Bold"><Data ss:Type="String">Average Position</Data></Cell><Cell><Data ss:Type="Number">{overview.get("average_position", 0)}</Data></Cell></Row>')
    xml.append(f'   <Row><Cell ss:StyleID="Bold"><Data ss:Type="String">Visibility Score</Data></Cell><Cell><Data ss:Type="String">{overview.get("visibility_score", 0)}%</Data></Cell></Row>')
    xml.append('  </Table>')
    xml.append(' </Worksheet>')

    # Worksheet 2: Tracked Keywords
    xml.append(' <Worksheet ss:Name="Keywords">')
    xml.append('  <Table>')
    xml.append('   <Row ss:StyleID="Header">')
    for h in ("Keyword", "Device", "Location", "Current Rank", "Change", "Best Rank", "Ranking URL"):
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(h)}</Data></Cell>')
    xml.append('   </Row>')

    for kw in overview.get("keywords", []):
        pos_str = str(kw.get("current_position")) if kw.get("current_position") is not None else ">100"
        ch = kw.get("position_change", 0)
        ch_str = f"+{ch}" if ch > 0 else str(ch)
        xml.append('   <Row>')
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(kw.get("keyword"))}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(kw.get("device"))}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(kw.get("location_name"))}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(pos_str)}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(ch_str)}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(str(kw.get("best_position") or "-"))}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(kw.get("latest_url") or "")}</Data></Cell>')
        xml.append('   </Row>')

    xml.append('  </Table>')
    xml.append(' </Worksheet>')
    xml.append('</Workbook>')

    return "\n".join(xml)


class RankTrackerReportCanvas(canvas.Canvas):
    """Two-pass ReportLab canvas for page numbers and running header/footer."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pages = []

    def showPage(self):
        self.pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        page_count = len(self.pages)
        for page in self.pages:
            self.__dict__.update(page)
            self.draw_decorations(page_count)
            super().showPage()
        super().save()

    def draw_decorations(self, page_count: int):
        self.saveState()
        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(colors.HexColor("#4F46E5"))
        self.drawString(14 * mm, 287 * mm, "AVIANCE SEO PRO MAX • KEYWORD RANK TRACKING INTELLIGENCE")

        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748B"))
        self.drawRightString(196 * mm, 287 * mm, datetime.now(timezone.utc).strftime("%B %d, %Y"))

        self.setStrokeColor(colors.HexColor("#E2E8F0"))
        self.setLineWidth(0.5)
        self.line(14 * mm, 284 * mm, 196 * mm, 284 * mm)

        # Footer
        self.line(14 * mm, 14 * mm, 196 * mm, 14 * mm)
        self.drawString(14 * mm, 9 * mm, "Live SERP data • Real-time organic positions • Search Console disclaimers apply")
        self.drawRightString(196 * mm, 9 * mm, f"Page {self._pageNumber} of {page_count}")
        self.restoreState()


def generate_rankings_pdf(overview: Dict[str, Any]) -> bytes:
    """Renders professional multi-page vector ReportLab PDF report."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "RankTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#0F172A")
    )
    subtitle_style = ParagraphStyle(
        "RankSub",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#475569")
    )
    section_title = ParagraphStyle(
        "RankSection",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=17,
        textColor=colors.HexColor("#1E293B"),
        spaceBefore=10,
        spaceAfter=6
    )
    body_style = ParagraphStyle(
        "RankBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#334155")
    )
    disclaimer_style = ParagraphStyle(
        "RankDisc",
        parent=styles["Normal"],
        fontName="Helvetica-Oblique",
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#1E40AF")
    )

    story = []
    target = overview.get("target_domain", "")

    # Header
    story.append(Paragraph(f"Keyword Rank Tracking: {target}", title_style))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph("Live Google SERP position monitoring, competitor benchmarking, and rank volatility analytics.", subtitle_style))
    story.append(Spacer(1, 4 * mm))

    # KPI Scorecard Table
    total_kw = overview.get("total_keywords", 0)
    avg_pos = overview.get("average_position", 0.0)
    vis = overview.get("visibility_score", 0.0)
    dist = overview.get("distribution") or {}

    kpi_data = [
        [
            Paragraph("<b>Tracked Keywords</b>", subtitle_style),
            Paragraph("<b>Avg Position</b>", subtitle_style),
            Paragraph("<b>Visibility (SOV)</b>", subtitle_style),
            Paragraph("<b>Google Top 10</b>", subtitle_style)
        ],
        [
            Paragraph(f"<font size=16><b>{total_kw:,}</b></font>", body_style),
            Paragraph(f"<font size=16 color='#4F46E5'><b>#{avg_pos:.1f}</b></font>", body_style),
            Paragraph(f"<font size=16 color='#10B981'><b>{vis:.1f}%</b></font>", body_style),
            Paragraph(f"<font size=16><b>{dist.get('top_10', 0):,}</b></font>", body_style)
        ]
    ]

    kpi_tbl = Table(kpi_data, colWidths=[45 * mm, 45 * mm, 45 * mm, 47 * mm])
    kpi_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(kpi_tbl)
    story.append(Spacer(1, 4 * mm))

    # Disclaimer Callout Box
    disc_data = [[Paragraph(f"<b>Data Measurement Boundaries:</b> {overview.get('disclaimer', '')}", disclaimer_style)]]
    disc_tbl = Table(disc_data, colWidths=[182 * mm])
    disc_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EFF6FF")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#BFDBFE")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(disc_tbl)
    story.append(Spacer(1, 4 * mm))

    # Keywords Table
    story.append(Paragraph("Tracked Keywords & Organic Positions", section_title))
    keywords = overview.get("keywords", [])
    if keywords:
        kw_rows = [[
            Paragraph("<b>Keyword</b>", subtitle_style),
            Paragraph("<b>Device</b>", subtitle_style),
            Paragraph("<b>Rank</b>", subtitle_style),
            Paragraph("<b>Change</b>", subtitle_style),
            Paragraph("<b>Best</b>", subtitle_style),
            Paragraph("<b>Ranking URL</b>", subtitle_style)
        ]]
        for k in keywords[:30]:
            p = k.get("current_position")
            p_str = f"#{p}" if p is not None else ">100"
            p_col = "#10B981" if (p and p <= 3) else ("#4F46E5" if (p and p <= 10) else "#334155")

            ch = k.get("position_change", 0)
            ch_col = "#10B981" if ch > 0 else ("#EF4444" if ch < 0 else "#64748B")
            ch_str = f"+{ch}" if ch > 0 else str(ch)

            kw_rows.append([
                Paragraph(f"<b>{k.get('keyword', '')}</b>", body_style),
                Paragraph(f"{k.get('device', 'desktop')}", body_style),
                Paragraph(f"<font color='{p_col}'><b>{p_str}</b></font>", body_style),
                Paragraph(f"<font color='{ch_col}'><b>{ch_str}</b></font>", body_style),
                Paragraph(f"#{k.get('best_position') or '-'}", body_style),
                Paragraph(f"<font size=7 color='#64748B'>{k.get('latest_url', '')[:50]}</font>", body_style)
            ])

        kw_tbl = Table(kw_rows, colWidths=[55 * mm, 20 * mm, 20 * mm, 20 * mm, 18 * mm, 49 * mm])
        kw_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F5F9")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(kw_tbl)
    else:
        story.append(Paragraph("<i>No keywords currently registered for tracking.</i>", body_style))

    doc.build(story, canvasmaker=RankTrackerReportCanvas)
    return buf.getvalue()

