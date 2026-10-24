"""Real-data integrations: Google PageSpeed Insights (CrUX field + Lighthouse lab data),
Google Search Console (Search Analytics) and DataForSEO (keyword metrics, rankings, backlinks).

Every value returned here comes straight from the provider API. Nothing is estimated:
when an integration is not configured or fails, its section reports that state instead.

Environment variables:
  PAGESPEED_API_KEY                 Google API key with the PageSpeed Insights API enabled (optional, raises quota)
  GSC_SERVICE_ACCOUNT_FILE          Path to a Google service-account JSON key, or
  GSC_SERVICE_ACCOUNT_JSON          the JSON key content itself
  DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD   DataForSEO API credentials
  DATAFORSEO_LOCATION_CODE          Default 2144 (Sri Lanka). 2840 = United States, 2826 = United Kingdom
  DATAFORSEO_LANGUAGE_CODE          Default "en"
  INTEGRATION_CACHE_HOURS           Cache identical API calls (default 24) so paid calls are not repeated
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests

from .seo_knowledge import CWV_THRESHOLDS, get_rule, rate_cwv

logger = logging.getLogger("aviance.integrations")

PAGESPEED_API_KEY = os.getenv("PAGESPEED_API_KEY", "").strip()
PAGESPEED_TIMEOUT = float(os.getenv("PAGESPEED_TIMEOUT", "90"))
GSC_SERVICE_ACCOUNT_FILE = os.getenv("GSC_SERVICE_ACCOUNT_FILE", "").strip()
GSC_SERVICE_ACCOUNT_JSON = os.getenv("GSC_SERVICE_ACCOUNT_JSON", "").strip()
DATAFORSEO_LOGIN = os.getenv("DATAFORSEO_LOGIN", "").strip()
DATAFORSEO_PASSWORD = os.getenv("DATAFORSEO_PASSWORD", "").strip()
DATAFORSEO_LOCATION_CODE = int(os.getenv("DATAFORSEO_LOCATION_CODE", "2144"))
DATAFORSEO_LANGUAGE_CODE = os.getenv("DATAFORSEO_LANGUAGE_CODE", "en")
CACHE_TTL = float(os.getenv("INTEGRATION_CACHE_HOURS", "24")) * 3600
OPENPAGERANK_API_KEY = os.getenv("OPENPAGERANK_API_KEY", "").strip()
OPR_ENDPOINT = "https://openpagerank.com/api/v1.0/getPageRank"
BING_API_KEY = os.getenv("BING_API_KEY", "").strip()
BING_BASE = "https://ssl.bing.com/webmaster/api.svc/json"

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
GSC_BASE = "https://www.googleapis.com/webmasters/v3"
GSC_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
DFS_BASE = "https://api.dataforseo.com/v3"

EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=6)


class IntegrationError(Exception):
    pass


# ---------------------------------------------------------------------------
# Small TTL cache so repeated audits do not re-spend API quota / money
# ---------------------------------------------------------------------------
_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_LOCK = threading.Lock()


def _cached(namespace: str, key_obj: Any, fn):
    key = namespace + ":" + hashlib.sha256(json.dumps(key_obj, sort_keys=True, default=str).encode()).hexdigest()
    now = time.time()
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and now - hit[0] < CACHE_TTL:
            return {**hit[1], "cached": True}
    value = fn()
    with _CACHE_LOCK:
        _CACHE[key] = (now, value)
    return value


def bare_domain(url: str) -> str:
    host = (urlparse(url if "://" in url else "https://" + url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------
def gsc_configured() -> bool:
    return bool(GSC_SERVICE_ACCOUNT_JSON or (GSC_SERVICE_ACCOUNT_FILE and os.path.exists(GSC_SERVICE_ACCOUNT_FILE)))


def dataforseo_configured() -> bool:
    return bool(DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD)


def bing_configured() -> bool:
    return bool(BING_API_KEY)


def update_credentials(*, pagespeed_api_key: str | None = None, openpagerank_api_key: str | None = None, bing_api_key: str | None = None) -> dict[str, Any]:
    global PAGESPEED_API_KEY, OPENPAGERANK_API_KEY, BING_API_KEY
    if pagespeed_api_key is not None:
        PAGESPEED_API_KEY = pagespeed_api_key.strip()
        os.environ["PAGESPEED_API_KEY"] = PAGESPEED_API_KEY
    if openpagerank_api_key is not None:
        OPENPAGERANK_API_KEY = openpagerank_api_key.strip()
        os.environ["OPENPAGERANK_API_KEY"] = OPENPAGERANK_API_KEY
    if bing_api_key is not None:
        BING_API_KEY = bing_api_key.strip()
        os.environ["BING_API_KEY"] = BING_API_KEY
    return status()


def status() -> dict[str, Any]:
    gsc_email = ""
    if gsc_configured():
        try:
            gsc_email = _gsc_info().get("client_email", "")
        except Exception:
            gsc_email = ""
    ps_mode = "api" if PAGESPEED_API_KEY else ("local_lighthouse" if local_lighthouse_available() else "api_public")
    ps_note = (
        "Connected via Google PageSpeed Insights API (Dedicated Key)."
        if PAGESPEED_API_KEY
        else ("Connected via local Lighthouse engine + Google PSI API."
              if local_lighthouse_available()
              else "Connected via Google PageSpeed Insights API (Public Quota). Optional: click Key to set custom API key.")
    )
    return {
        "pagespeed": {"configured": True, "has_api_key": bool(PAGESPEED_API_KEY),
                      "mode": ps_mode,
                      "note": ps_note},
        "search_console": {"configured": gsc_configured(), "service_account_email": gsc_email,
                           "note": "Add the service-account email as a user on each Search Console property."},
        "bing_webmaster": {"configured": bing_configured(),
                           "note": "Free. Real Bing crawl stats and query telemetry. Set BING_API_KEY in .env."},
        "openpagerank": {"configured": openpagerank_configured(),
                         "note": "Free. Domain link authority (0-10) from the Common Crawl link graph. Get a key at openpagerank.com."},
        "dataforseo": {"configured": dataforseo_configured(), "location_code": DATAFORSEO_LOCATION_CODE,
                       "language_code": DATAFORSEO_LANGUAGE_CODE,
                       "note": "Paid API: every uncached call costs credits. Backlinks needs a Backlinks API subscription."},
        "ollama": {"configured": ollama_configured(), "model": OLLAMA_MODEL,
                   "has_api_key": bool(OLLAMA_API_KEY),
                   "note": f"Ollama model '{OLLAMA_MODEL}' connected."},
    }


# ---------------------------------------------------------------------------
# Google PageSpeed Insights (CrUX field data + Lighthouse lab data)
# ---------------------------------------------------------------------------
PSI_FIELD_METRICS = {
    "LARGEST_CONTENTFUL_PAINT_MS": "LCP",
    "INTERACTION_TO_NEXT_PAINT": "INP",
    "CUMULATIVE_LAYOUT_SHIFT_SCORE": "CLS",
    "FIRST_CONTENTFUL_PAINT_MS": "FCP",
    "EXPERIMENTAL_TIME_TO_FIRST_BYTE": "TTFB",
}
PSI_LAB_AUDITS = {
    "largest-contentful-paint": "LCP",
    "cumulative-layout-shift": "CLS",
    "first-contentful-paint": "FCP",
    "total-blocking-time": "TBT",
    "speed-index": "Speed Index",
    "server-response-time": "Server response",
}


def _parse_field(block: dict[str, Any] | None) -> dict[str, Any] | None:
    metrics = (block or {}).get("metrics") or {}
    if not metrics:
        return None
    out: dict[str, Any] = {}
    for api_key, name in PSI_FIELD_METRICS.items():
        m = metrics.get(api_key)
        if not m or m.get("percentile") is None:
            continue
        value = float(m["percentile"])
        if name == "CLS":
            value = value / 100.0  # PSI reports CLS x100
        out[name] = {
            "p75": value,
            "unit": CWV_THRESHOLDS[name]["unit"],
            "rating": rate_cwv(name, value),
            "distribution": [round(float(d.get("proportion", 0)) * 100, 1) for d in m.get("distributions", [])],
        }
    core = [out[k]["rating"] for k in ("LCP", "INP", "CLS") if k in out]
    return {
        "metrics": out,
        "core_web_vitals_assessment": ("passed" if core and all(r == "good" for r in core) else "failed") if len(core) == 3 else "insufficient data",
        "scope": "origin" if block.get("origin_fallback") else "url",
        "id": block.get("id", ""),
    }


def _parse_lighthouse(lh: dict[str, Any], url: str, strategy: str) -> dict[str, Any]:
    audits = lh.get("audits") or {}
    categories = {k: (round(v["score"] * 100) if v.get("score") is not None else None) for k, v in (lh.get("categories") or {}).items()}
    lab = {}
    for audit_id, name in PSI_LAB_AUDITS.items():
        a = audits.get(audit_id) or {}
        if a.get("numericValue") is not None:
            lab[name] = {"value": round(float(a["numericValue"]), 3 if name == "CLS" else 0), "display": a.get("displayValue", "")}
    failed_seo = []
    for ref in ((lh.get("categories") or {}).get("seo") or {}).get("auditRefs", []):
        a = audits.get(ref.get("id")) or {}
        if a.get("score") == 0 and ref.get("weight", 0) > 0:
            failed_seo.append({"id": ref.get("id"), "title": a.get("title", ""), "description": a.get("description", "")})
    return {
        "ok": True,
        "strategy": strategy,
        "url": url,
        "final_url": lh.get("finalDisplayedUrl") or lh.get("finalUrl") or url,
        "fetched_at": lh.get("fetchTime", ""),
        "lighthouse_version": lh.get("lighthouseVersion", ""),
        "lab": lab,
        "lighthouse_scores": categories,
        "failed_seo_audits": failed_seo,
    }


def _psi_call(url: str, strategy: str) -> dict[str, Any]:
    params: list[tuple[str, str]] = [("url", url), ("strategy", strategy)]
    params += [("category", c) for c in ("performance", "seo", "accessibility", "best-practices")]
    if PAGESPEED_API_KEY:
        params.append(("key", PAGESPEED_API_KEY))
    r = requests.get(PSI_ENDPOINT, params=params, timeout=PAGESPEED_TIMEOUT)
    if r.status_code != 200:
        try:
            msg = r.json().get("error", {}).get("message", r.text[:300])
        except ValueError:
            msg = r.text[:300]
        raise IntegrationError(f"PageSpeed API HTTP {r.status_code}: {msg}")
    data = r.json()
    out = _parse_lighthouse(data.get("lighthouseResult") or {}, url, strategy)
    out.update({
        "field_url": _parse_field(data.get("loadingExperience")),
        "field_origin": _parse_field(data.get("originLoadingExperience")),
        "source": "Google PageSpeed Insights API v5 (CrUX field data, 28-day rolling, 75th percentile + Lighthouse lab run)",
        "mode": "api",
    })
    return out


# Local Lighthouse: the same engine PageSpeed Insights uses, run on this machine with Chrome. Free, no API key.
LIGHTHOUSE_CLI = Path(__file__).resolve().parents[1] / "tools" / "lighthouse" / "node_modules" / "lighthouse" / "cli" / "index.js"
LIGHTHOUSE_TIMEOUT = float(os.getenv("LIGHTHOUSE_TIMEOUT", "420"))
_LIGHTHOUSE_LOCK = threading.Lock()  # one run at a time: Lighthouse is CPU-heavy


LIGHTHOUSE_CALIBRATION = LIGHTHOUSE_CLI.parents[3] / "benchmark.json"


def _find_node() -> str | None:
    for candidate in [shutil.which("node"), "/usr/local/bin/node", "/opt/homebrew/bin/node", "/usr/bin/node"]:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def local_lighthouse_available() -> bool:
    return LIGHTHOUSE_CLI.is_file() and _find_node() is not None


def pagespeed_configured() -> bool:
    """Google PageSpeed Insights is always available via Google's free API endpoint or local Lighthouse engine."""
    return True


def _cpu_slowdown() -> float:
    """CPU throttling calibrated to this machine (Lighthouse docs: docs/throttling.md#cpu-throttling).
    The default 4x assumes a fast desktop; on a slow machine it would exaggerate how slow websites are."""
    override = os.getenv("LIGHTHOUSE_CPU_SLOWDOWN", "").strip()
    if override:
        return float(override)
    try:
        index = float(json.loads(LIGHTHOUSE_CALIBRATION.read_text(encoding="utf-8"))["benchmarkIndex"])
    except (OSError, ValueError, KeyError):
        return 4.0  # Lighthouse default until this machine has been measured once
    return 4.0 if index >= 1500 else 2.0 if index >= 1000 else 1.0


def _local_lighthouse_call(url: str, strategy: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        out_file = Path(tmp) / "report.json"
        node_bin = _find_node() or "node"
        cmd = [node_bin, str(LIGHTHOUSE_CLI), url, "--output=json", f"--output-path={out_file}", "--quiet",
               "--only-categories=performance,seo,accessibility,best-practices", "--max-wait-for-load=45000",
               "--chrome-flags=--headless=new --no-sandbox --disable-gpu"]
        if strategy == "desktop":
            cmd.append("--preset=desktop")
        else:
            cmd.append(f"--throttling.cpuSlowdownMultiplier={_cpu_slowdown()}")
        with _LIGHTHOUSE_LOCK:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=LIGHTHOUSE_TIMEOUT)
        if not out_file.is_file():
            raise IntegrationError(f"Local Lighthouse failed: {(proc.stderr or proc.stdout or '').strip()[-300:]}")
        lh = json.loads(out_file.read_text(encoding="utf-8"))
    bench = (lh.get("environment") or {}).get("benchmarkIndex")
    if bench:
        try:
            LIGHTHOUSE_CALIBRATION.write_text(json.dumps({"benchmarkIndex": bench, "measured_at": lh.get("fetchTime", "")}), encoding="utf-8")
        except OSError:
            pass
    if (lh.get("runtimeError") or {}).get("code"):
        raise IntegrationError(f"Lighthouse could not load the page: {lh['runtimeError'].get('message', lh['runtimeError']['code'])}")
    out = _parse_lighthouse(lh, url, strategy)
    out.update({"field_url": None, "field_origin": None, "mode": "local_lighthouse",
                "source": "Google Lighthouse run locally (lab data). Real-user Core Web Vitals need a PageSpeed API key."})
    return out


def pagespeed(url: str, strategy: str = "mobile") -> dict[str, Any]:
    """PageSpeed Insights API when a key is set or available; otherwise local Lighthouse engine with resilient fallback."""
    use_api_first = bool(PAGESPEED_API_KEY) or not local_lighthouse_available()
    if use_api_first:
        try:
            return _cached("psi", [url, strategy], lambda: _psi_call(url, strategy))
        except Exception as exc:
            logger.warning("Google PageSpeed Insights API call failed, attempting local Lighthouse fallback: %s", exc)
            if local_lighthouse_available():
                try:
                    return _cached("lighthouse_local", [url, strategy], lambda: _local_lighthouse_call(url, strategy))
                except Exception as lh_exc:
                    return {"ok": False, "strategy": strategy, "url": url, "error": f"PageSpeed API ({exc}) and Local Lighthouse ({lh_exc}) failed."}
            return {"ok": False, "strategy": strategy, "url": url, "error": str(exc)}
    else:
        try:
            return _cached("lighthouse_local", [url, strategy], lambda: _local_lighthouse_call(url, strategy))
        except Exception as exc:
            logger.warning("Local Lighthouse failed, attempting Google PageSpeed Insights API fallback: %s", exc)
            try:
                return _cached("psi", [url, strategy], lambda: _psi_call(url, strategy))
            except Exception as psi_exc:
                return {"ok": False, "strategy": strategy, "url": url, "error": f"Local Lighthouse ({exc}) and PageSpeed API ({psi_exc}) failed."}

# ---------------------------------------------------------------------------
# Google Search Console (Search Analytics API, service account)
# ---------------------------------------------------------------------------
_GSC_CREDS = None
_GSC_LOCK = threading.Lock()


def _gsc_info() -> dict[str, Any]:
    if GSC_SERVICE_ACCOUNT_JSON:
        return json.loads(GSC_SERVICE_ACCOUNT_JSON)
    with open(GSC_SERVICE_ACCOUNT_FILE, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _gsc_token() -> str:
    global _GSC_CREDS
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request as GoogleAuthRequest
    except ImportError as exc:
        raise IntegrationError("google-auth is not installed. Run: pip install -r requirements.txt") from exc
    with _GSC_LOCK:
        if _GSC_CREDS is None:
            _GSC_CREDS = service_account.Credentials.from_service_account_info(_gsc_info(), scopes=[GSC_SCOPE])
        if not _GSC_CREDS.valid:
            _GSC_CREDS.refresh(GoogleAuthRequest())
        return _GSC_CREDS.token


def _gsc_request(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    r = requests.request(method, GSC_BASE + path, headers={"Authorization": f"Bearer {_gsc_token()}"}, json=body, timeout=45)
    if r.status_code != 200:
        try:
            msg = r.json().get("error", {}).get("message", r.text[:300])
        except ValueError:
            msg = r.text[:300]
        raise IntegrationError(f"Search Console API HTTP {r.status_code}: {msg}")
    return r.json()


def gsc_sites() -> list[dict[str, Any]]:
    return _gsc_request("GET", "/sites").get("siteEntry", []) or []


def gsc_match_property(target_url: str) -> str | None:
    """Pick the Search Console property covering target_url (domain property preferred)."""
    host = (urlparse(target_url).hostname or "").lower()
    bare = bare_domain(target_url)
    sites = [s for s in gsc_sites() if s.get("permissionLevel") != "siteUnverifiedUser"]
    for s in sites:
        if s.get("siteUrl", "").lower() == f"sc-domain:{bare}":
            return s["siteUrl"]
    for s in sites:
        su = s.get("siteUrl", "")
        if su.startswith("sc-domain:") and (host == su[10:].lower() or host.endswith("." + su[10:].lower())):
            return su
    for s in sites:
        su = s.get("siteUrl", "")
        if not su.startswith("sc-domain:") and (urlparse(su).hostname or "").lower() == host:
            return su
    return None


def _gsc_query(site: str, start: str, end: str, dimensions: list[str], row_limit: int) -> list[dict[str, Any]]:
    body = {"startDate": start, "endDate": end, "dimensions": dimensions, "rowLimit": row_limit, "dataState": "final"}
    rows = _gsc_request("POST", f"/sites/{quote(site, safe='')}/searchAnalytics/query", body).get("rows", []) or []
    out = []
    for row in rows:
        item = {"clicks": int(row.get("clicks", 0)), "impressions": int(row.get("impressions", 0)),
                "ctr": round(float(row.get("ctr", 0)) * 100, 2), "position": round(float(row.get("position", 0)), 1)}
        for i, dim in enumerate(dimensions):
            item[dim] = row.get("keys", [""] * len(dimensions))[i]
        out.append(item)
    return out


def search_console(target_url: str, days: int = 28) -> dict[str, Any]:
    if not gsc_configured():
        return {"ok": False, "configured": False, "error": "Search Console service account not configured."}
    days = max(1, min(int(days), 480))
    # Search Console data is final roughly 2-3 days after the fact.
    end = date.today() - timedelta(days=3)
    start = end - timedelta(days=days - 1)

    def run() -> dict[str, Any]:
        site = gsc_match_property(target_url)
        if not site:
            email = _gsc_info().get("client_email", "the service account")
            raise IntegrationError(f"No Search Console property found for {bare_domain(target_url)}. Add {email} as a user on the property in Search Console.")
        s, e = start.isoformat(), end.isoformat()
        totals = _gsc_query(site, s, e, [], 1)
        return {
            "ok": True, "configured": True, "property": site, "start_date": s, "end_date": e, "days": days,
            "totals": totals[0] if totals else {"clicks": 0, "impressions": 0, "ctr": 0.0, "position": 0.0},
            "top_queries": _gsc_query(site, s, e, ["query"], 100),
            "top_pages": _gsc_query(site, s, e, ["page"], 100),
            "devices": _gsc_query(site, s, e, ["device"], 10),
            "countries": _gsc_query(site, s, e, ["country"], 15),
            "source": "Google Search Console Search Analytics API (web search, final data)",
        }

    try:
        return _cached("gsc", [target_url, days, start.isoformat()], run)
    except (requests.RequestException, IntegrationError, ValueError, OSError) as exc:
        return {"ok": False, "configured": True, "error": str(exc)}


# ---------------------------------------------------------------------------
# Open PageRank (free): link-authority score from the Common Crawl link graph
# ---------------------------------------------------------------------------
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate").strip()
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3").strip()
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "").strip()


def ollama_configured() -> bool:
    return bool(OLLAMA_URL)


def openpagerank_configured() -> bool:
    return bool(OPENPAGERANK_API_KEY)


def openpagerank(target_url: str) -> dict[str, Any]:
    domain = bare_domain(target_url)
    if not openpagerank_configured():
        return {"ok": False, "target": domain, "error": "OPENPAGERANK_API_KEY not configured."}

    def run() -> dict[str, Any]:
        r = requests.get(OPR_ENDPOINT, params={"domains[]": domain}, headers={"API-OPR": OPENPAGERANK_API_KEY}, timeout=20)
        try:
            data = r.json()
        except ValueError:
            raise IntegrationError(f"Open PageRank HTTP {r.status_code}: {r.text[:200]}")
        if r.status_code != 200 or int(data.get("status_code") or 0) != 200:
            raise IntegrationError(f"Open PageRank HTTP {r.status_code}: {data.get('error') or data}")
        row = (data.get("response") or [{}])[0]
        if int(row.get("status_code") or 0) != 200:
            raise IntegrationError(f"Open PageRank: {row.get('error') or 'domain not found'}")
        decimal = row.get("page_rank_decimal")
        return {
            "ok": True, "target": domain,
            "page_rank_decimal": float(decimal) if decimal not in (None, "") else None,
            "page_rank_integer": row.get("page_rank_integer"),
            "global_rank": row.get("rank"),
            "source": "Open PageRank (DomCop) - computed from the Common Crawl link graph, scale 0-10",
        }

    try:
        return _cached("opr", [domain], run)
    except (requests.RequestException, IntegrationError) as exc:
        return {"ok": False, "target": domain, "error": str(exc)}


# ---------------------------------------------------------------------------
# Bing Webmaster Tools (free)
# ---------------------------------------------------------------------------
def bing_webmaster(target_url: str) -> dict[str, Any]:
    """Query Bing Webmaster Tools API for crawl and search telemetry."""
    if not bing_configured():
        return {
            "ok": False,
            "configured": False,
            "status": "Requires Connection",
            "source": "Bing Webmaster Tools API",
            "note": "Connect Bing Webmaster Tools API key (BING_API_KEY) in .env for Bing indexation telemetry."
        }
    domain = bare_domain(target_url)
    site_url = f"https://{domain}"

    def run() -> dict[str, Any]:
        try:
            r = requests.get(
                f"{BING_BASE}/GetCrawlStats",
                params={"siteUrl": site_url, "apikey": BING_API_KEY},
                timeout=30
            )
            if r.status_code == 200:
                data = r.json()
                return {
                    "ok": True,
                    "configured": True,
                    "site_url": site_url,
                    "crawl_stats": data.get("d", []),
                    "source": "Bing Webmaster Tools JSON API",
                }
            else:
                return {
                    "ok": False,
                    "configured": True,
                    "status": "Unavailable",
                    "error": f"Bing API returned status HTTP {r.status_code}",
                    "source": "Bing Webmaster Tools JSON API",
                }
        except Exception as exc:
            return {
                "ok": False,
                "configured": True,
                "status": "Unavailable",
                "error": str(exc),
                "source": "Bing Webmaster Tools JSON API",
            }

    try:
        return _cached("bing", [domain], run)
    except Exception as exc:
        return {"ok": False, "configured": True, "error": str(exc)}


# ---------------------------------------------------------------------------
# DataForSEO
# ---------------------------------------------------------------------------
def _dfs_post(path: str, task: dict[str, Any]) -> tuple[list[dict[str, Any]], float]:
    if not dataforseo_configured():
        raise IntegrationError("DataForSEO credentials not configured.")
    r = requests.post(f"{DFS_BASE}/{path}", auth=(DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD), json=[task], timeout=90)
    try:
        data = r.json()
    except ValueError:
        raise IntegrationError(f"DataForSEO HTTP {r.status_code}: {r.text[:300]}")
    if data.get("status_code") != 20000:
        raise IntegrationError(f"DataForSEO {data.get('status_code')}: {data.get('status_message')}")
    t = (data.get("tasks") or [{}])[0]
    if t.get("status_code") != 20000:
        raise IntegrationError(f"DataForSEO {t.get('status_code')}: {t.get('status_message')}")
    return t.get("result") or [], float(data.get("cost") or 0)


def _loc(location_code: int | None, language_code: str | None) -> dict[str, Any]:
    return {"location_code": int(location_code or DATAFORSEO_LOCATION_CODE), "language_code": language_code or DATAFORSEO_LANGUAGE_CODE}


def keyword_metrics(keywords: list[str], location_code: int | None = None, language_code: str | None = None) -> dict[str, Any]:
    """Real Google search volume, CPC, competition, keyword difficulty and search intent."""
    clean = []
    for k in keywords:
        k = " ".join(str(k).lower().split())[:80]
        if k and k not in clean and len(k.split()) <= 10:
            clean.append(k)
    clean = clean[:700]
    if not clean:
        return {"ok": False, "error": "No keywords supplied."}
    loc = _loc(location_code, language_code)

    def run() -> dict[str, Any]:
        result, cost = _dfs_post("dataforseo_labs/google/keyword_overview/live", {"keywords": clean, **loc})
        items = (result[0].get("items") if result else None) or []
        rows = []
        for it in items:
            info = it.get("keyword_info") or {}
            props = it.get("keyword_properties") or {}
            intent = it.get("search_intent_info") or {}
            rows.append({
                "keyword": it.get("keyword", ""),
                "search_volume": info.get("search_volume"),
                "cpc": info.get("cpc"),
                "competition": info.get("competition"),
                "competition_level": info.get("competition_level"),
                "keyword_difficulty": props.get("keyword_difficulty"),
                "intent": intent.get("main_intent"),
                "monthly_searches": [{"year": m.get("year"), "month": m.get("month"), "volume": m.get("search_volume")} for m in (info.get("monthly_searches") or [])[:12]],
            })
        found = {r["keyword"] for r in rows}
        return {"ok": True, **loc, "keywords": rows, "not_found": [k for k in clean if k not in found], "cost_usd": cost,
                "source": "DataForSEO Labs - Google keyword overview (Google Ads volume, DataForSEO keyword difficulty)"}

    try:
        return _cached("dfs_kw", [clean, loc], run)
    except (requests.RequestException, IntegrationError) as exc:
        return {"ok": False, "error": str(exc)}


def ranked_keywords(target_url: str, limit: int = 100, location_code: int | None = None, language_code: str | None = None) -> dict[str, Any]:
    """Real keywords the domain ranks for in Google organic results, with positions."""
    domain = bare_domain(target_url)
    loc = _loc(location_code, language_code)
    limit = max(1, min(int(limit), 1000))

    def run() -> dict[str, Any]:
        result, cost = _dfs_post("dataforseo_labs/google/ranked_keywords/live", {
            "target": domain, **loc, "limit": limit, "item_types": ["organic"],
            "order_by": ["keyword_data.keyword_info.search_volume,desc"],
        })
        r0 = result[0] if result else {}
        rows = []
        for it in r0.get("items") or []:
            kd = it.get("keyword_data") or {}
            serp = (it.get("ranked_serp_element") or {}).get("serp_item") or {}
            rows.append({
                "keyword": kd.get("keyword", ""),
                "position": serp.get("rank_group"),
                "absolute_position": serp.get("rank_absolute"),
                "url": serp.get("url", ""),
                "search_volume": (kd.get("keyword_info") or {}).get("search_volume"),
                "keyword_difficulty": (kd.get("keyword_properties") or {}).get("keyword_difficulty"),
                "intent": (kd.get("search_intent_info") or {}).get("main_intent"),
                "estimated_traffic": serp.get("etv"),
            })
        organic = ((r0.get("metrics") or {}).get("organic") or {})
        return {
            "ok": True, "target": domain, **loc, "total_count": r0.get("total_count", 0), "keywords": rows,
            "distribution": {k: organic.get(k) for k in ("pos_1", "pos_2_3", "pos_4_10", "pos_11_20", "pos_21_30", "pos_31_40", "pos_41_50", "pos_51_60", "pos_61_70", "pos_71_80", "pos_81_90", "pos_91_100", "count", "etv")},
            "cost_usd": cost,
            "source": "DataForSEO Labs - Google ranked keywords (organic). Positions come from DataForSEO's SERP database, not Search Console.",
        }

    try:
        return _cached("dfs_rank", [domain, loc, limit], run)
    except (requests.RequestException, IntegrationError) as exc:
        return {"ok": False, "target": domain, "error": str(exc)}


def competitors_domain(target_url: str, limit: int = 10, location_code: int | None = None, language_code: str | None = None) -> dict[str, Any]:
    """Finds organic Google SERP competitors for a domain via DataForSEO Labs."""
    domain = bare_domain(target_url)
    loc = _loc(location_code, language_code)
    limit = max(1, min(int(limit), 100))

    def run() -> dict[str, Any]:
        result, cost = _dfs_post("dataforseo_labs/google/competitors_domain/live", {
            "target": domain, **loc, "limit": limit
        })
        r0 = result[0] if result else {}
        items = r0.get("items") or []
        rows = []
        for it in items:
            comp_domain = it.get("target") or it.get("full_domain") or ""
            metrics = (it.get("metrics") or {}).get("organic") or {}
            rows.append({
                "domain": comp_domain,
                "avg_position": metrics.get("avg_position"),
                "estimated_traffic": metrics.get("etv"),
                "organic_keywords_count": metrics.get("count"),
                "shared_keywords": it.get("intersections") or 0,
            })
        return {
            "ok": True,
            "target": domain,
            **loc,
            "total_count": len(rows),
            "competitors": rows,
            "cost_usd": cost,
            "source": "DataForSEO Labs - Google Competitors Domain",
        }

    try:
        return _cached("dfs_comp", [domain, loc, limit], run)
    except (requests.RequestException, IntegrationError) as exc:
        return {"ok": False, "target": domain, "error": str(exc), "competitors": []}


def domain_intersection(target1: str, target2: str, limit: int = 100, location_code: int | None = None, language_code: str | None = None) -> dict[str, Any]:
    """Compares shared ranking keywords between two domains using DataForSEO Labs."""
    d1 = bare_domain(target1)
    d2 = bare_domain(target2)
    loc = _loc(location_code, language_code)
    limit = max(1, min(int(limit), 500))

    def run() -> dict[str, Any]:
        result, cost = _dfs_post("dataforseo_labs/google/domain_intersection/live", {
            "target1": d1, "target2": d2, **loc, "limit": limit, "item_types": ["organic"]
        })
        r0 = result[0] if result else {}
        items = r0.get("items") or []
        rows = []
        for it in items:
            kd = it.get("keyword_data") or {}
            first_domain_serp = (it.get("first_domain_serp_element") or {}).get("serp_item") or {}
            second_domain_serp = (it.get("second_domain_serp_element") or {}).get("serp_item") or {}
            rows.append({
                "keyword": kd.get("keyword", ""),
                "target1_position": first_domain_serp.get("rank_group"),
                "target2_position": second_domain_serp.get("rank_group"),
                "search_volume": (kd.get("keyword_info") or {}).get("search_volume"),
                "keyword_difficulty": (kd.get("keyword_properties") or {}).get("keyword_difficulty"),
                "cpc": (kd.get("keyword_info") or {}).get("cpc"),
                "intent": (kd.get("search_intent_info") or {}).get("main_intent"),
            })
        return {
            "ok": True,
            "target1": d1,
            "target2": d2,
            **loc,
            "total_count": len(rows),
            "keywords": rows,
            "cost_usd": cost,
            "source": "DataForSEO Labs - Domain Intersection",
        }

    try:
        return _cached("dfs_intersect", [d1, d2, loc, limit], run)
    except (requests.RequestException, IntegrationError) as exc:
        return {"ok": False, "target1": d1, "target2": d2, "error": str(exc), "keywords": []}


def backlinks(target_url: str) -> dict[str, Any]:
    """Real backlink profile summary and top referring domains."""
    domain = bare_domain(target_url)

    def run() -> dict[str, Any]:
        cost_total = 0.0
        scale = 100
        try:
            result, cost = _dfs_post("backlinks/summary/live", {"target": domain, "include_subdomains": True, "rank_scale": "one_hundred"})
        except IntegrationError as exc:
            if "rank_scale" not in str(exc).lower():
                raise
            result, cost = _dfs_post("backlinks/summary/live", {"target": domain, "include_subdomains": True})
            scale = 1000
        cost_total += cost
        s = result[0] if result else {}
        try:
            ref_result, cost = _dfs_post("backlinks/referring_domains/live", {"target": domain, "limit": 25, "order_by": ["rank,desc"], "exclude_internal_backlinks": True})
            cost_total += cost
            ref_items = (ref_result[0].get("items") if ref_result else None) or []
        except IntegrationError:
            ref_items = []
        rank = s.get("rank")
        return {
            "ok": True, "connected": True, "target": domain,
            "domain_rank": rank, "domain_rank_scale": scale,
            "score": round(rank * 100 / scale) if isinstance(rank, (int, float)) else None,
            "backlinks": s.get("backlinks"),
            "referring_domains": s.get("referring_domains"),
            "referring_main_domains": s.get("referring_main_domains"),
            "referring_ips": s.get("referring_ips"),
            "dofollow_backlinks": (s.get("referring_links_attributes") or {}).get("dofollow") if isinstance(s.get("referring_links_attributes"), dict) else None,
            "broken_backlinks": s.get("broken_backlinks"),
            "broken_pages": s.get("broken_pages"),
            "spam_score": s.get("backlinks_spam_score"),
            "first_seen": s.get("first_seen"),
            "top_referring_domains": [{"domain": x.get("domain"), "rank": x.get("rank"), "backlinks": x.get("backlinks"), "first_seen": x.get("first_seen")} for x in ref_items],
            "cost_usd": cost_total,
            "source": "DataForSEO Backlinks API (DataForSEO's own link index; rank is DataForSEO's metric, not a Google metric)",
        }

    try:
        return _cached("dfs_bl", [domain], run)
    except (requests.RequestException, IntegrationError) as exc:
        return {"ok": False, "connected": False, "target": domain, "error": str(exc)}


# ---------------------------------------------------------------------------
# Audit enrichment
# ---------------------------------------------------------------------------
# Core Web Vitals findings are produced by the scoring engine (checks P01-P04), not here.

class Enrichment:
    """Starts slow provider calls in the background while the crawl runs."""

    def __init__(self, target: str, use_pagespeed: bool, use_search_console: bool, use_dataforseo: bool,
                 location_code: int | None = None, language_code: str | None = None,
                 pagespeed_strategies: tuple[str, ...] = ("mobile", "desktop"), use_openpagerank: bool = True):
        self.target = target
        self.use_dataforseo = use_dataforseo and dataforseo_configured()
        self.location_code = location_code
        self.language_code = language_code
        self.futures: dict[str, concurrent.futures.Future] = {}
        if use_pagespeed:
            if not PAGESPEED_API_KEY:
                pagespeed_strategies = ("mobile",)  # local Lighthouse is slow on small machines: mobile only
            for strategy in pagespeed_strategies:
                self.futures[f"psi_{strategy}"] = EXECUTOR.submit(pagespeed, target, strategy)
        if use_openpagerank and openpagerank_configured():
            self.futures["opr"] = EXECUTOR.submit(openpagerank, target)
        if bing_configured():
            self.futures["bing"] = EXECUTOR.submit(bing_webmaster, target)
        if use_search_console and gsc_configured():
            self.futures["gsc"] = EXECUTOR.submit(search_console, target, 28)
        if self.use_dataforseo:
            self.futures["ranked"] = EXECUTOR.submit(ranked_keywords, target, 100, location_code, language_code)
            self.futures["backlinks"] = EXECUTOR.submit(backlinks, target)
        self.requested = {"pagespeed": use_pagespeed, "search_console": use_search_console, "dataforseo": use_dataforseo, "bing": bing_configured()}

    def _get(self, name: str, timeout: float) -> dict[str, Any] | None:
        fut = self.futures.get(name)
        if fut is None:
            return None
        try:
            return fut.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            return {"ok": False, "error": f"Timed out after waiting {int(timeout)} s"}
        except Exception as exc:  # defensive: never break the audit
            return {"ok": False, "error": str(exc)}

    def finish(self, observed_keywords: list[str], timeout: float | None = None) -> dict[str, Any]:
        if timeout is None:
            timeout = 120 if PAGESPEED_API_KEY else LIGHTHOUSE_TIMEOUT + 30
        out: dict[str, Any] = {"requested": self.requested, "status": status()}
        mobile, desktop = self._get("psi_mobile", timeout), self._get("psi_desktop", timeout)
        if mobile or desktop:
            out["pagespeed"] = {"mobile": mobile, "desktop": desktop}
        gsc = self._get("gsc", timeout)
        if gsc:
            out["search_console"] = gsc
        bing_data = self._get("bing", timeout)
        if bing_data:
            out["bing_webmaster"] = bing_data
        elif bing_configured():
            out["bing_webmaster"] = {"ok": False, "status": "Unavailable"}
        else:
            out["bing_webmaster"] = {"ok": False, "status": "Requires Connection"}
        opr = self._get("opr", timeout)
        if opr:
            out["openpagerank"] = opr
        if self.use_dataforseo:
            dfs: dict[str, Any] = {"ranked_keywords": self._get("ranked", timeout), "backlinks": self._get("backlinks", timeout)}
            # Prefer real queries from Search Console; fall back to terms observed on the site.
            seeds = [q.get("query", "") for q in (gsc or {}).get("top_queries", [])[:60]] if gsc and gsc.get("ok") else []
            if len(seeds) < 20:
                seeds += observed_keywords
            dfs["keyword_metrics"] = keyword_metrics(seeds[:100], self.location_code, self.language_code)
            dfs["cost_usd"] = round(sum(float((v or {}).get("cost_usd") or 0) for v in dfs.values() if isinstance(v, dict) and not v.get("cached")), 4)
            out["dataforseo"] = dfs
        elif self.requested["dataforseo"]:
            out["dataforseo"] = {"ok": False, "error": "DataForSEO credentials not configured."}
        return out
