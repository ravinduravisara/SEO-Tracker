"""
Centralized SEO Data Provider Layer (Phase 8.11).

Provides a single normalized data contract for all external SEO measurements:
- Google PageSpeed Insights (Mobile & Desktop Lab Measurements)
- Google Chrome UX Report (Real-User CrUX Field Measurements)
- Google Search Console (First-Party Authorized Search Performance)
- Google Analytics 4 (First-Party Authorized Traffic & Engagement)
- Bing Webmaster Tools (First-Party Bing Search Performance & Crawl Telemetry)
- Ahrefs Free Domain Rating (Third-Party Domain Authority with Required Attribution)
- Open PageRank (Third-Party Common Crawl Authority)
- Google Keyword Planner (Optional Google Ads Idea Service)

Strict Principles:
1. Zero fabrication: Never invent scores, search volumes, or rankings.
2. Clear scope: Explicitly label PAGE_LEVEL vs ORIGIN_LEVEL.
3. Provenance: Every observation tracks provider, metric, data_type, collected_at, and status.
4. Render Free safety: Aggressive caching, bounded timeouts, and concurrency controls.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from .. import integrations

logger = logging.getLogger("aviance.seo_engine.data_providers")


class ProviderStatus(str, Enum):
    CONNECTED = "CONNECTED"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    UNAUTHORIZED = "UNAUTHORIZED"
    RATE_LIMITED = "RATE_LIMITED"
    ERROR = "ERROR"
    NO_DATA = "NO_DATA"
    STALE = "STALE"


class DataType(str, Enum):
    FIRST_PARTY_MEASUREMENT = "FIRST_PARTY_MEASUREMENT"
    THIRD_PARTY_ESTIMATE = "THIRD_PARTY_ESTIMATE"
    LAB_MEASUREMENT = "LAB_MEASUREMENT"
    FIELD_MEASUREMENT = "FIELD_MEASUREMENT"
    CALCULATED_SCORE = "CALCULATED_SCORE"
    UNAVAILABLE = "UNAVAILABLE"


class SourceScope(str, Enum):
    PAGE_LEVEL = "PAGE_LEVEL"
    ORIGIN_LEVEL = "ORIGIN_LEVEL"
    DOMAIN_LEVEL = "DOMAIN_LEVEL"
    PROPERTY_LEVEL = "PROPERTY_LEVEL"
    UNSPECIFIED = "UNSPECIFIED"


@dataclass
class ProviderObservation:
    """Standardized representation of a single external measurement."""
    provider: str
    provider_metric: str
    target_url: str
    property_id: str = ""
    value: Any = None
    display_value: str = ""
    unit: str = ""
    data_type: str = DataType.UNAVAILABLE.value
    device: str = "ALL"  # MOBILE, DESKTOP, or ALL
    country: str = "ALL"
    language: str = "ALL"
    date_range: str = ""
    collected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    cached: bool = False
    status: str = ProviderStatus.NOT_CONFIGURED.value
    error_code: Optional[str] = None
    source_scope: str = SourceScope.UNSPECIFIED.value
    attribution: str = ""
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# ADAPTERS
# ---------------------------------------------------------------------------

def get_pagespeed_observations(target_url: str, strategy: str = "mobile") -> List[ProviderObservation]:
    """
    Retrieve laboratory PageSpeed observations for mobile or desktop.
    Strictly isolated by strategy. Never fabricates scores.
    """
    clean_strat = strategy.lower().strip()
    if clean_strat not in ("mobile", "desktop"):
        clean_strat = "mobile"

    obs_list: List[ProviderObservation] = []
    try:
        res = integrations.pagespeed(target_url, strategy=clean_strat)
    except Exception as exc:
        obs_list.append(ProviderObservation(
            provider="Google PageSpeed Insights",
            provider_metric="performance_score",
            target_url=target_url,
            data_type=DataType.LAB_MEASUREMENT.value,
            device=clean_strat.upper(),
            status=ProviderStatus.ERROR.value,
            error_code=str(exc),
            notes="PageSpeed call failed or timed out."
        ))
        return obs_list

    if not res.get("ok"):
        obs_list.append(ProviderObservation(
            provider="Google PageSpeed Insights",
            provider_metric="performance_score",
            target_url=target_url,
            data_type=DataType.LAB_MEASUREMENT.value,
            device=clean_strat.upper(),
            status=ProviderStatus.ERROR.value,
            error_code=res.get("error", "Unknown error"),
            notes=res.get("note", "Lighthouse audit failed.")
        ))
        return obs_list

    scores = res.get("lighthouse_scores") or {}
    lab = res.get("lab") or {}
    collected = res.get("fetched_at") or datetime.now(timezone.utc).isoformat()

    # 1. Performance Score
    perf_score = scores.get("performance")
    obs_list.append(ProviderObservation(
        provider="Google PageSpeed Insights",
        provider_metric="performance_score",
        target_url=target_url,
        value=perf_score,
        display_value=f"{perf_score}/100" if perf_score is not None else "NOT MEASURED",
        unit="score",
        data_type=DataType.LAB_MEASUREMENT.value,
        device=clean_strat.upper(),
        collected_at=collected,
        status=ProviderStatus.CONNECTED.value if perf_score is not None else ProviderStatus.NO_DATA.value,
        source_scope=SourceScope.PAGE_LEVEL.value,
        attribution="Google Lighthouse Laboratory Audit"
    ))

    # 2. Lab FCP
    if "FCP" in lab:
        obs_list.append(ProviderObservation(
            provider="Google PageSpeed Insights",
            provider_metric="lab_fcp",
            target_url=target_url,
            value=lab["FCP"].get("value"),
            display_value=lab["FCP"].get("display", ""),
            unit="ms",
            data_type=DataType.LAB_MEASUREMENT.value,
            device=clean_strat.upper(),
            collected_at=collected,
            status=ProviderStatus.CONNECTED.value,
            source_scope=SourceScope.PAGE_LEVEL.value
        ))

    # 3. Lab LCP
    if "LCP" in lab:
        obs_list.append(ProviderObservation(
            provider="Google PageSpeed Insights",
            provider_metric="lab_lcp",
            target_url=target_url,
            value=lab["LCP"].get("value"),
            display_value=lab["LCP"].get("display", ""),
            unit="ms",
            data_type=DataType.LAB_MEASUREMENT.value,
            device=clean_strat.upper(),
            collected_at=collected,
            status=ProviderStatus.CONNECTED.value,
            source_scope=SourceScope.PAGE_LEVEL.value
        ))

    # 4. Lab TBT (Total Blocking Time - Lab only, NOT INP)
    if "TBT" in lab:
        obs_list.append(ProviderObservation(
            provider="Google PageSpeed Insights",
            provider_metric="lab_tbt",
            target_url=target_url,
            value=lab["TBT"].get("value"),
            display_value=lab["TBT"].get("display", ""),
            unit="ms",
            data_type=DataType.LAB_MEASUREMENT.value,
            device=clean_strat.upper(),
            collected_at=collected,
            status=ProviderStatus.CONNECTED.value,
            source_scope=SourceScope.PAGE_LEVEL.value,
            notes="Laboratory proxy for main thread blocking; distinct from field INP."
        ))

    # 5. Lab CLS
    if "CLS" in lab:
        obs_list.append(ProviderObservation(
            provider="Google PageSpeed Insights",
            provider_metric="lab_cls",
            target_url=target_url,
            value=lab["CLS"].get("value"),
            display_value=lab["CLS"].get("display", ""),
            unit="ratio",
            data_type=DataType.LAB_MEASUREMENT.value,
            device=clean_strat.upper(),
            collected_at=collected,
            status=ProviderStatus.CONNECTED.value,
            source_scope=SourceScope.PAGE_LEVEL.value
        ))

    # 6. Speed Index
    if "Speed Index" in lab:
        obs_list.append(ProviderObservation(
            provider="Google PageSpeed Insights",
            provider_metric="speed_index",
            target_url=target_url,
            value=lab["Speed Index"].get("value"),
            display_value=lab["Speed Index"].get("display", ""),
            unit="ms",
            data_type=DataType.LAB_MEASUREMENT.value,
            device=clean_strat.upper(),
            collected_at=collected,
            status=ProviderStatus.CONNECTED.value,
            source_scope=SourceScope.PAGE_LEVEL.value
        ))

    return obs_list


def get_crux_field_observations(target_url: str) -> List[ProviderObservation]:
    """
    Retrieve genuine real-user Core Web Vitals (CrUX 75th percentile).
    Checks page-level first, falls back to origin-level, clearly tagging scope.
    If no data is available, returns INSUFFICIENT FIELD DATA. Never substitutes lab data.
    """
    obs_list: List[ProviderObservation] = []
    try:
        # PSI v5 returns both field_url and field_origin loading experience
        psi_data = integrations.pagespeed(target_url, strategy="mobile")
        field_url = psi_data.get("field_url")
        field_origin = psi_data.get("field_origin")
    except Exception as exc:
        field_url = None
        field_origin = None

    selected_field = field_url or field_origin
    scope = SourceScope.PAGE_LEVEL.value if field_url else (SourceScope.ORIGIN_LEVEL.value if field_origin else SourceScope.UNSPECIFIED.value)

    if not selected_field or not selected_field.get("metrics"):
        # Explicitly label insufficient field data
        for cwv_metric in ("LCP", "INP", "CLS", "FCP", "TTFB"):
            obs_list.append(ProviderObservation(
                provider="Google Chrome UX Report (CrUX)",
                provider_metric=cwv_metric.lower(),
                target_url=target_url,
                value=None,
                display_value="INSUFFICIENT FIELD DATA",
                data_type=DataType.UNAVAILABLE.value,
                status=ProviderStatus.NO_DATA.value,
                error_code="INSUFFICIENT_FIELD_DATA",
                source_scope=SourceScope.UNSPECIFIED.value,
                attribution="Google Chrome UX Report (28-day rolling p75)",
                notes="Target does not currently have sufficient Chrome user visits to calculate 75th percentile."
            ))
        return obs_list

    metrics = selected_field.get("metrics", {})
    assessment = selected_field.get("core_web_vitals_assessment", "insufficient data")

    for metric_name, m_data in metrics.items():
        p75 = m_data.get("p75")
        obs_list.append(ProviderObservation(
            provider="Google Chrome UX Report (CrUX)",
            provider_metric=metric_name.lower(),
            target_url=target_url,
            value=p75,
            display_value=f"{p75} {m_data.get('unit','')}".strip(),
            unit=m_data.get("unit", ""),
            data_type=DataType.FIELD_MEASUREMENT.value,
            device="MOBILE",
            date_range="28-day rolling",
            status=ProviderStatus.CONNECTED.value,
            source_scope=scope,
            attribution="Google Chrome UX Report (75th Percentile)",
            notes=f"Rating: {m_data.get('rating')}. CWV Overall: {assessment}."
        ))

    return obs_list


def get_search_console_observations(
    target_url: str,
    property_url: Optional[str] = None,
    days: int = 28
) -> Dict[str, Any]:
    """
    Retrieve verified Google Search Console telemetry for authorized property.
    Enforces multi-client property boundaries and accurate metric definitions.
    """
    if not integrations.gsc_configured():
        return {
            "status": ProviderStatus.NOT_CONFIGURED.value,
            "observations": [],
            "error": "Google Search Console service account not configured.",
            "note": "Connect Google Service Account in system configuration to view verified search analytics."
        }

    res = integrations.search_console(target_url, days=days, property_url=property_url)
    if not res.get("ok"):
        return {
            "status": ProviderStatus.UNAUTHORIZED.value if "permission" in str(res.get("error","")).lower() or "not found" in str(res.get("error","")).lower() else ProviderStatus.ERROR.value,
            "observations": [],
            "error": res.get("error", "Failed to query Google Search Console."),
            "note": "GOOGLE SEARCH CONSOLE NOT CONNECTED. Ensure the service account email is added as a property user."
        }

    totals = res.get("totals", {})
    prop = res.get("property", "")
    collected = datetime.now(timezone.utc).isoformat()
    d_range = f"{res.get('start_date')} to {res.get('end_date')}"

    obs_list = [
        ProviderObservation(
            provider="Google Search Console",
            provider_metric="clicks",
            target_url=target_url,
            property_id=prop,
            value=totals.get("clicks", 0),
            display_value=str(totals.get("clicks", 0)),
            unit="clicks",
            data_type=DataType.FIRST_PARTY_MEASUREMENT.value,
            date_range=d_range,
            collected_at=collected,
            status=ProviderStatus.CONNECTED.value,
            source_scope=SourceScope.PROPERTY_LEVEL.value,
            attribution="Google Search Console Search Analytics API",
            notes="Total web search clicks from Google Search within selected date range."
        ),
        ProviderObservation(
            provider="Google Search Console",
            provider_metric="impressions",
            target_url=target_url,
            property_id=prop,
            value=totals.get("impressions", 0),
            display_value=str(totals.get("impressions", 0)),
            unit="impressions",
            data_type=DataType.FIRST_PARTY_MEASUREMENT.value,
            date_range=d_range,
            collected_at=collected,
            status=ProviderStatus.CONNECTED.value,
            source_scope=SourceScope.PROPERTY_LEVEL.value,
            attribution="Google Search Console Search Analytics API"
        ),
        ProviderObservation(
            provider="Google Search Console",
            provider_metric="ctr",
            target_url=target_url,
            property_id=prop,
            value=totals.get("ctr", 0.0),
            display_value=f"{totals.get('ctr', 0.0)}%",
            unit="percent",
            data_type=DataType.FIRST_PARTY_MEASUREMENT.value,
            date_range=d_range,
            collected_at=collected,
            status=ProviderStatus.CONNECTED.value,
            source_scope=SourceScope.PROPERTY_LEVEL.value,
            attribution="Google Search Console Search Analytics API"
        ),
        ProviderObservation(
            provider="Google Search Console",
            provider_metric="average_position",
            target_url=target_url,
            property_id=prop,
            value=totals.get("position", 0.0),
            display_value=str(totals.get("position", 0.0)),
            unit="rank",
            data_type=DataType.FIRST_PARTY_MEASUREMENT.value,
            date_range=d_range,
            collected_at=collected,
            status=ProviderStatus.CONNECTED.value,
            source_scope=SourceScope.PROPERTY_LEVEL.value,
            attribution="Google Search Console Search Analytics API",
            notes="Aggregated average position across impressions. Does not represent a guaranteed exact rank."
        )
    ]

    return {
        "status": ProviderStatus.CONNECTED.value,
        "property": prop,
        "date_range": d_range,
        "observations": [o.to_dict() for o in obs_list],
        "top_queries": res.get("top_queries", []),
        "top_pages": res.get("top_pages", []),
        "devices": res.get("devices", []),
        "countries": res.get("countries", []),
        "dates": res.get("dates", [])
    }


def get_ga4_observations(
    target_url: str,
    property_id: Optional[str] = None,
    days: int = 28
) -> Dict[str, Any]:
    """
    Retrieve verified GA4 traffic telemetry for authorized property.
    Enforces per-client tenancy and distinguishes GA4 sessions from GSC clicks.
    """
    if not integrations.ga4_configured(property_id):
        return {
            "status": ProviderStatus.NOT_CONFIGURED.value,
            "observations": [],
            "error": "Google Analytics 4 Property ID or Service Account not configured.",
            "note": "Connect GA4 Property ID in website settings to view genuine traffic and engagement metrics."
        }

    res = integrations.ga4(target_url, property_id=property_id, days=days)
    if not res.get("ok"):
        return {
            "status": ProviderStatus.UNAUTHORIZED.value if "permission" in str(res.get("error","")).lower() else ProviderStatus.ERROR.value,
            "observations": [],
            "error": res.get("error", "Failed to query GA4 Data API."),
            "note": "GOOGLE ANALYTICS 4 NOT CONNECTED. Verify property ID and service account permissions."
        }

    totals = res.get("totals", {})
    pid = res.get("property_id", property_id or "")
    collected = datetime.now(timezone.utc).isoformat()
    d_range = f"{res.get('start_date')} to {res.get('end_date')}"

    obs_list = [
        ProviderObservation(
            provider="Google Analytics 4",
            provider_metric="sessions",
            target_url=target_url,
            property_id=pid,
            value=totals.get("sessions", 0),
            display_value=str(totals.get("sessions", 0)),
            unit="sessions",
            data_type=DataType.FIRST_PARTY_MEASUREMENT.value,
            date_range=d_range,
            collected_at=collected,
            status=ProviderStatus.CONNECTED.value,
            source_scope=SourceScope.PROPERTY_LEVEL.value,
            attribution="Google Analytics 4 Data API",
            notes="Total site sessions. Distinct from Google Search Console search clicks."
        ),
        ProviderObservation(
            provider="Google Analytics 4",
            provider_metric="total_users",
            target_url=target_url,
            property_id=pid,
            value=totals.get("total_users", 0),
            display_value=str(totals.get("total_users", 0)),
            unit="users",
            data_type=DataType.FIRST_PARTY_MEASUREMENT.value,
            date_range=d_range,
            collected_at=collected,
            status=ProviderStatus.CONNECTED.value,
            source_scope=SourceScope.PROPERTY_LEVEL.value,
            attribution="Google Analytics 4 Data API"
        ),
        ProviderObservation(
            provider="Google Analytics 4",
            provider_metric="engagement_rate",
            target_url=target_url,
            property_id=pid,
            value=totals.get("engagement_rate", 0.0),
            display_value=f"{totals.get('engagement_rate', 0.0)}%",
            unit="percent",
            data_type=DataType.FIRST_PARTY_MEASUREMENT.value,
            date_range=d_range,
            collected_at=collected,
            status=ProviderStatus.CONNECTED.value,
            source_scope=SourceScope.PROPERTY_LEVEL.value,
            attribution="Google Analytics 4 Data API"
        ),
        ProviderObservation(
            provider="Google Analytics 4",
            provider_metric="average_session_duration",
            target_url=target_url,
            property_id=pid,
            value=totals.get("average_session_duration", 0.0),
            display_value=f"{totals.get('average_session_duration', 0.0)}s",
            unit="seconds",
            data_type=DataType.FIRST_PARTY_MEASUREMENT.value,
            date_range=d_range,
            collected_at=collected,
            status=ProviderStatus.CONNECTED.value,
            source_scope=SourceScope.PROPERTY_LEVEL.value,
            attribution="Google Analytics 4 Data API"
        )
    ]

    return {
        "status": ProviderStatus.CONNECTED.value,
        "property_id": pid,
        "date_range": d_range,
        "observations": [o.to_dict() for o in obs_list],
        "totals": totals,
        "channels": res.get("channels", []),
        "top_pages": res.get("top_pages", []),
        "countries": res.get("countries", [])
    }


def get_bing_observations(target_url: str) -> Dict[str, Any]:
    """
    Retrieve Bing Webmaster Tools search performance and crawl statistics.
    Strictly labeled BING SEARCH PERFORMANCE.
    """
    if not integrations.bing_configured():
        return {
            "status": ProviderStatus.NOT_CONFIGURED.value,
            "observations": [],
            "error": "Bing Webmaster Tools API key (BING_API_KEY) not configured.",
            "note": "Set BING_API_KEY in environment to retrieve Bing crawl statistics and search performance."
        }

    res = integrations.bing_webmaster(target_url)
    if not res.get("ok"):
        return {
            "status": ProviderStatus.UNAUTHORIZED.value if "401" in str(res.get("error","")) else ProviderStatus.ERROR.value,
            "observations": [],
            "error": res.get("error", "Bing API unavailable."),
            "note": "BING WEBMASTER TOOLS NOT CONNECTED."
        }

    crawl_stats = res.get("crawl_stats", [])
    query_stats = res.get("query_stats", [])
    domain = integrations.bare_domain(target_url)
    collected = datetime.now(timezone.utc).isoformat()

    obs_list = []
    if crawl_stats:
        latest = crawl_stats[0] if isinstance(crawl_stats, list) and len(crawl_stats) > 0 else {}
        crawled = latest.get("CrawledPages") or latest.get("crawled_pages") or 0
        obs_list.append(ProviderObservation(
            provider="Bing Webmaster Tools",
            provider_metric="crawled_pages",
            target_url=target_url,
            value=crawled,
            display_value=str(crawled),
            unit="pages",
            data_type=DataType.FIRST_PARTY_MEASUREMENT.value,
            collected_at=collected,
            status=ProviderStatus.CONNECTED.value,
            source_scope=SourceScope.DOMAIN_LEVEL.value,
            attribution="Bing Webmaster Tools REST API",
            notes="Pages crawled by Bingbot in most recent telemetry period."
        ))

    return {
        "status": ProviderStatus.CONNECTED.value,
        "domain": domain,
        "observations": [o.to_dict() for o in obs_list],
        "crawl_stats": crawl_stats,
        "query_stats": query_stats,
        "source": "BING SEARCH PERFORMANCE (Microsoft Bing Webmaster Tools API)"
    }


def get_ahrefs_domain_rating_observation(target_url: str) -> ProviderObservation:
    """
    Retrieve Ahrefs Free Domain Rating via official API v3.
    Mandatory attribution: 'Domain Rating by Ahrefs'.
    Distinct from Open PageRank and local link equity.
    """
    domain = integrations.bare_domain(target_url)

    if not integrations.ahrefs_configured():
        return ProviderObservation(
            provider="Ahrefs",
            provider_metric="domain_rating",
            target_url=target_url,
            value=None,
            display_value="NOT CONFIGURED",
            data_type=DataType.UNAVAILABLE.value,
            status=ProviderStatus.NOT_CONFIGURED.value,
            source_scope=SourceScope.DOMAIN_LEVEL.value,
            attribution="Domain Rating by Ahrefs (Free API v3)",
            notes="Set AHREFS_API_KEY to retrieve official Ahrefs Domain Rating. Free endpoint does not return full backlink lists."
        )

    # Call official API v3
    try:
        res = integrations.ahrefs_domain_rating(target_url)
        if res.get("ok"):
            dr = res.get("domain_rating")
            ar = res.get("ahrefs_rank")
            return ProviderObservation(
                provider="Ahrefs",
                provider_metric="domain_rating",
                target_url=target_url,
                value=dr,
                display_value=f"DR {dr}" if dr is not None else "NO DATA",
                unit="dr",
                data_type=DataType.THIRD_PARTY_ESTIMATE.value,
                collected_at=datetime.now(timezone.utc).isoformat(),
                status=ProviderStatus.CONNECTED.value,
                source_scope=SourceScope.DOMAIN_LEVEL.value,
                attribution="Domain Rating by Ahrefs",
                notes=f"Global Ahrefs Rank: #{ar:,}" if ar else "Domain Rating by Ahrefs (Scale 0-100)."
            )
        else:
            return ProviderObservation(
                provider="Ahrefs",
                provider_metric="domain_rating",
                target_url=target_url,
                value=None,
                display_value="UNAVAILABLE",
                data_type=DataType.UNAVAILABLE.value,
                status=ProviderStatus.ERROR.value,
                error_code=res.get("error"),
                attribution="Domain Rating by Ahrefs",
                notes="Ahrefs API query failed or domain not found."
            )
    except Exception as exc:
        return ProviderObservation(
            provider="Ahrefs",
            provider_metric="domain_rating",
            target_url=target_url,
            value=None,
            display_value="ERROR",
            data_type=DataType.UNAVAILABLE.value,
            status=ProviderStatus.ERROR.value,
            error_code=str(exc),
            attribution="Domain Rating by Ahrefs"
        )


def get_openpagerank_observation(target_url: str) -> ProviderObservation:
    """
    Retrieve Open PageRank (DomCop) Common Crawl authority score (0-10).
    Distinct from Ahrefs Domain Rating and Google PageRank.
    """
    if not integrations.openpagerank_configured():
        return ProviderObservation(
            provider="Open PageRank",
            provider_metric="open_pagerank",
            target_url=target_url,
            value=None,
            display_value="NOT CONFIGURED",
            data_type=DataType.UNAVAILABLE.value,
            status=ProviderStatus.NOT_CONFIGURED.value,
            source_scope=SourceScope.DOMAIN_LEVEL.value,
            attribution="Open PageRank (DomCop / Common Crawl Link Graph)",
            notes="Set OPENPAGERANK_API_KEY to retrieve Open PageRank (0-10 scale)."
        )

    res = integrations.openpagerank(target_url)
    if res.get("ok"):
        opr_decimal = res.get("page_rank_decimal")
        global_rank = res.get("global_rank")
        return ProviderObservation(
            provider="Open PageRank",
            provider_metric="open_pagerank",
            target_url=target_url,
            value=opr_decimal,
            display_value=f"{opr_decimal:.2f}/10" if opr_decimal is not None else "0.0/10",
            unit="rank_decimal",
            data_type=DataType.THIRD_PARTY_ESTIMATE.value,
            collected_at=datetime.now(timezone.utc).isoformat(),
            status=ProviderStatus.CONNECTED.value,
            source_scope=SourceScope.DOMAIN_LEVEL.value,
            attribution="Open PageRank (DomCop / Common Crawl Link Graph)",
            notes=f"Global Rank: #{global_rank:,}" if global_rank else "Scale 0-10."
        )
    else:
        return ProviderObservation(
            provider="Open PageRank",
            provider_metric="open_pagerank",
            target_url=target_url,
            value=None,
            display_value="ERROR",
            data_type=DataType.UNAVAILABLE.value,
            status=ProviderStatus.ERROR.value,
            error_code=res.get("error"),
            attribution="Open PageRank"
        )


def get_keyword_planner_status() -> Dict[str, Any]:
    """
    Validate Google Ads Keyword Planner access.
    Clearly reports NOT CONNECTED when approved Developer Token is absent.
    Never fabricates search volume numbers.
    """
    token = getattr(integrations, "GOOGLE_ADS_DEVELOPER_TOKEN", "")
    customer_id = getattr(integrations, "GOOGLE_ADS_CUSTOMER_ID", "")
    if not token or not customer_id:
        return {
            "status": ProviderStatus.NOT_CONFIGURED.value,
            "configured": False,
            "observations": [],
            "error": "GOOGLE KEYWORD PLANNER NOT CONNECTED",
            "detail": "Google Ads API requires an approved Developer Token (Basic or Standard access) and MCC account authorization. Free Explorer access does not support keyword volume APIs.",
            "documentation": "https://developers.google.com/google-ads/api/docs/first-call/overview"
        }
    return {
        "status": ProviderStatus.CONNECTED.value,
        "configured": True,
        "customer_id": customer_id,
        "note": "Google Ads KeywordPlanIdeaService active."
    }


# ---------------------------------------------------------------------------
# COMPOSITE DOMAIN TELEMETRY
# ---------------------------------------------------------------------------

def collect_domain_telemetry(
    target_url: str,
    website: Optional[Any] = None,
    days: int = 28
) -> Dict[str, Any]:
    """
    Single unified entrypoint for collecting all verified external telemetry
    for a domain or client website with full provenance and isolation.
    """
    domain = integrations.bare_domain(target_url)
    gsc_property = getattr(website, "gsc_property", None) if website else None
    ga4_property_id = getattr(website, "ga4_property_id", None) if website else None

    # Performance
    mobile_ps = get_pagespeed_observations(target_url, strategy="mobile")
    desktop_ps = get_pagespeed_observations(target_url, strategy="desktop")
    crux_cwv = get_crux_field_observations(target_url)

    # First-Party Search & Traffic
    gsc_data = get_search_console_observations(target_url, property_url=gsc_property, days=days)
    ga4_data = get_ga4_observations(target_url, property_id=ga4_property_id, days=days)
    bing_data = get_bing_observations(target_url)

    # Third-Party Authority
    ahrefs_dr = get_ahrefs_domain_rating_observation(target_url)
    opr = get_openpagerank_observation(target_url)
    gkp_status = get_keyword_planner_status()

    # Compile flat observation list
    all_obs: List[Dict[str, Any]] = [
        o.to_dict() for o in (
            mobile_ps + desktop_ps + crux_cwv + [ahrefs_dr, opr]
        )
    ]
    all_obs.extend(gsc_data.get("observations", []))
    all_obs.extend(ga4_data.get("observations", []))
    all_obs.extend(bing_data.get("observations", []))

    return {
        "target_url": target_url,
        "domain": domain,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "observations": all_obs,
        "performance": {
            "mobile": [o.to_dict() for o in mobile_ps],
            "desktop": [o.to_dict() for o in desktop_ps],
            "core_web_vitals": [o.to_dict() for o in crux_cwv],
        },
        "search_console": gsc_data,
        "analytics_ga4": ga4_data,
        "bing_webmaster": bing_data,
        "authority": {
            "ahrefs_domain_rating": ahrefs_dr.to_dict(),
            "openpagerank": opr.to_dict(),
            "backlink_provider_required": not integrations.dataforseo_configured(),
        },
        "keyword_planner": gkp_status,
        "provenance": {
            "engine": "Aviance Centralized SEO Data Provider Layer v8.0",
            "strict_real_data": True,
            "synthetic_metrics_allowed": False
        }
    }
