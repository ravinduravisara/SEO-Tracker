"""Evidence probes (spec PART B steps 2, 3, 7 and the RENDER tier).

Network functions are injected by the caller (the crawler's own fetch/parse helpers) so this module
stays free of the web app and can be tested with fakes. Every probe records what was requested,
the status observed and when, so each derived check can cite its evidence.
"""
from __future__ import annotations

import concurrent.futures
import random
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlparse

PROBE_PATHS = ["/about", "/contact", "/products", "/services", "/blog", "/privacy", "/terms"]
CONTROL_PATH = "/this-page-does-not-exist-seo-test-55512"
MOBILE_UA = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/124.0 Mobile Safari/537.36 eSupportSEO-mobile-parity")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hop(res: dict[str, Any]) -> dict[str, Any]:
    hist = res.get("history") or []
    first = hist[0] if hist else {}
    return {"status": first.get("status"), "location": first.get("location")}


def _host_probe(url: str, fetch: Callable, make_session: Callable, parse_page: Callable) -> dict[str, Any]:
    res = fetch(make_session(), url, timeout=10, max_body=1_500_000, retries=0)
    out = {"requested": url, "status": int(res.get("status") or 0), "final_url": res.get("url") or url,
           "first_hop": _hop(res), "error": res.get("error"), "fetched_at": _now()}
    if res.get("ok") and int(res.get("status") or 0) < 400:
        page = parse_page(url, res)
        out.update({"title": page.get("title", ""), "h1": (page.get("h1") or [""])[0], "canonical": page.get("canonical", "")})
    return out


def collect_site_probes(start_url: str, fetch: Callable, make_session: Callable, parse_page: Callable) -> dict[str, Any]:
    """Host resolution, HTTP->HTTPS redirect, negative probes, 404 control and mobile parity fetch."""
    p = urlparse(start_url)
    host = (p.hostname or "").lower()
    apex = host[4:] if host.startswith("www.") else host
    origin = f"{p.scheme}://{p.netloc}"
    jobs: dict[str, Any] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        jobs["apex"] = ex.submit(_host_probe, f"https://{apex}/", fetch, make_session, parse_page)
        jobs["www"] = ex.submit(_host_probe, f"https://www.{apex}/", fetch, make_session, parse_page)
        jobs["http"] = ex.submit(fetch, make_session(), f"http://{host}/", 10, 200_000, 0)
        for path in PROBE_PATHS + [CONTROL_PATH]:
            jobs["probe:" + path] = ex.submit(fetch, make_session(), origin + path, 10, 200_000, 0)

        def mobile_fetch():
            s = make_session()
            s.headers["User-Agent"] = MOBILE_UA
            r = fetch(s, start_url, 12, 3_000_000, 0)
            return parse_page(start_url, r) if r.get("ok") else {"error": r.get("error"), "status": r.get("status")}
        jobs["mobile"] = ex.submit(mobile_fetch)
        done = {k: f.result() for k, f in jobs.items()}

    http = done["http"]
    probes = []
    for path in PROBE_PATHS + [CONTROL_PATH]:
        r = done["probe:" + path]
        final = r.get("url") or origin + path
        probes.append({
            "path": path, "url": origin + path, "status": int(r.get("status") or 0), "final_url": final,
            "redirected": bool(r.get("history")),
            "redirected_home": urlparse(final).path in ("", "/") and path not in ("", "/"),
            "control": path == CONTROL_PATH, "error": r.get("error"), "fetched_at": _now(),
        })
    mobile = done["mobile"]
    return {
        "fetched_at": _now(),
        "hosts": {"apex": done["apex"], "www": done["www"]},
        "http_redirect": {"requested": f"http://{host}/", "status": int(http.get("status") or 0),
                          "final_url": http.get("url"), "first_hop": _hop(http), "error": http.get("error")},
        "probes": probes,
        "mobile": {"status": int(mobile.get("status") or 0), "word_count": mobile.get("word_count"),
                   "error": mobile.get("error"), "user_agent": MOBILE_UA},
    }


def sample_sitemap_locs(urls: list[str], fetch: Callable, make_session: Callable, limit: int = 40) -> dict[str, Any]:
    """Spec T08: fetch a deterministic sample of sitemap <loc> URLs and record their status."""
    if not urls:
        return {"sampled": 0, "results": []}
    sample = sorted(urls)[:limit] if len(urls) <= limit else sorted(random.Random(len(urls)).sample(sorted(urls), limit))
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda u: (u, fetch(make_session(), u, 10, 50_000, 0)), sample))
    rows = [{"url": u, "status": int(r.get("status") or 0), "redirected": bool(r.get("history")), "error": r.get("error")} for u, r in results]
    return {"sampled": len(rows), "total": len(urls), "results": rows, "fetched_at": _now()}


RENDER_JS = """() => {
  const vw = window.innerWidth;
  const doc = document.documentElement;
  const overflow = Math.max(doc.scrollWidth, document.body ? document.body.scrollWidth : 0) - vw;
  const els = Array.from(document.querySelectorAll('a[href], button, input:not([type=hidden]), select, textarea, [role=button]'));
  let visible = 0, small = 0; const samples = [];
  for (const el of els) {
    const r = el.getBoundingClientRect(); const st = getComputedStyle(el);
    if (r.width === 0 || r.height === 0 || st.visibility === 'hidden' || st.display === 'none') continue;
    visible++;
    if (r.width < 48 || r.height < 48) { small++; if (samples.length < 8) samples.push((el.innerText || el.getAttribute('aria-label') || el.tagName).trim().slice(0, 40) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height)); }
  }
  return {viewport: vw, overflow_px: overflow, tap_targets: visible, small_targets: small, samples};
}"""


def render_mobile_probe(urls: list[str], timeout_ms: int = 30000) -> dict[str, Any]:
    """RENDER tier (M03, M05): load pages in a real browser at a 360px viewport. Unavailable -> capability missing."""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as exc:
        return {"available": False, "error": f"playwright not installed: {exc}"}
    out: dict[str, Any] = {"available": False, "pages": [], "fetched_at": _now()}
    try:
        with sync_playwright() as pw:
            browser = None
            for channel in ("chrome", "msedge", None):
                try:
                    browser = pw.chromium.launch(channel=channel, headless=True) if channel else pw.chromium.launch(headless=True)
                    break
                except Exception:
                    continue
            if browser is None:
                return {"available": False, "error": "No Chromium/Chrome browser could be launched"}
            ctx = browser.new_context(viewport={"width": 360, "height": 780}, device_scale_factor=2, is_mobile=True, has_touch=True)
            out["available"] = True
            for url in urls[:2]:
                page = ctx.new_page()
                try:
                    # 'networkidle' never fires on pages with chat widgets / long-polling, so wait for 'load' and let layout settle.
                    page.goto(url, wait_until="domcontentloaded", timeout=max(timeout_ms, 45000))
                    page.wait_for_timeout(3000)
                    data = page.evaluate(RENDER_JS)
                    data.update({"url": url, "ok": True})
                except Exception as exc:
                    data = {"url": url, "ok": False, "error": str(exc)[:300]}
                finally:
                    page.close()
                out["pages"].append(data)
            browser.close()
    except Exception as exc:
        out.update({"available": False, "error": str(exc)[:300]})
    return out
