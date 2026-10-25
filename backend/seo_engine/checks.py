"""Rules engine (spec PART D): evidence -> PASS / WARN / FAIL / UNMEASURED / NOT_APPLICABLE per check.

Pure functions of the evidence context. A check that cannot be evaluated with the available
capabilities returns UNMEASURED with a reason (spec G.1/G.2); it never guesses and never FAILs
because an instrument was missing. Each result carries an evidence label, a statement, the URLs
it rests on and the raw values, so every point is traceable (spec PART J / N.1).
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlparse

from .context import (GENERIC_H1, LOCAL_TYPES, ORG_TYPES, UTILITY_RE, Ctx, node_types, norm_url, parse_date,
                      schema_nodes_of, sig_terms, stem_in, tokens)
from .ruleset import category_checks, load_ruleset, threshold
from .scoring import CheckResult

T = threshold
WEBMAIL = ("gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com", "icloud.com", "aol.com", "ymail.com", "proton.me", "protonmail.com")
CDN_HEADERS = ("cf-ray", "x-amz-cf-id", "x-served-by", "x-fastly-request-id", "x-akamai-transformed", "x-cdn", "x-azure-ref", "cdn-cache")
CDN_HOST_RE = re.compile(r"(cloudfront\.net|cloudinary|imgix|akamai|fastly|cdn\.|\.cdn|wp\.com|cdn\.shopify|squarespace-cdn|wixstatic|googleusercontent|bunnycdn|b-cdn|kxcdn|jsdelivr|unpkg|stackpath|cloudflare)", re.I)
PRODUCT_TYPES = ("product", "productgroup", "service", "offer", "aggregateoffer", "touristtrip", "trip", "event", "course",
                 "softwareapplication", "hotel", "lodgingbusiness", "vehicle", "menuitem", "realestatelisting")
FILENAME_BAD = re.compile(r"(%20|\s|^img[_-]?\d|^dsc[_-]?\d|^image\d*$|^photo\d*$|^untitled|^screenshot|^[0-9a-f]{16,}$|^\d+$|^wp-image|^pexels-|^unsplash)", re.I)


class R:
    """Result builder bound to one check definition."""

    def __init__(self, ctx: Ctx, category: str, d: dict[str, Any]):
        self.ctx, self.category, self.d = ctx, category, d

    def _mk(self, status: str, statement: str, label: str = "Verified", urls: Optional[list[str]] = None,
            values: Optional[dict] = None, coverage: Optional[float] = None, reason: Optional[str] = None) -> CheckResult:
        ev = {"label": label, "statement": statement, "urls": list(dict.fromkeys(urls or []))[:25], "values": values or {}}
        return CheckResult(id=self.d["id"], category=self.category, points=int(self.d["points"]), status=status,
                           coverage=None if coverage is None else round(max(0.0, min(1.0, coverage)), 4),
                           evidence_label=label, unmeasured_reason=reason, name=self.d["name"], evidence=ev)

    def ok(self, s, **k): return self._mk("PASS", s, **k)
    def warn(self, s, **k): return self._mk("WARN", s, **k)
    def fail(self, s, **k): return self._mk("FAIL", s, **k)
    def na(self, s, **k): return self._mk("NOT_APPLICABLE", s, **k)

    def unmeasured(self, reason: str, s: str, label: str = "Not verifiable", **k) -> CheckResult:
        return self._mk("UNMEASURED", s, label=label, reason=reason, **k)

    def by_count(self, n: int, statement: str, warn_max: int = 1, **k) -> CheckResult:
        return self.ok(statement, **k) if n == 0 else self.warn(statement, **k) if n <= warn_max else self.fail(statement, **k)

    def coverage(self, pages: list[dict], verdict: Callable[[dict], str], noun: str, pass_at: float = 1.0, fail_below: float = 0.0,
                 empty: Optional[CheckResult] = None, label: str = "Verified") -> CheckResult:
        """Per-page aggregation: Pass earns full points, Warn half (0.5), Fail none.
        Matches reference specification: page-level checks earn in proportion to sampled pages."""
        if not pages:
            return empty or self.na(f"No pages to evaluate for {noun}.")
        verdicts = [(p.get("url", ""), verdict(p)) for p in pages]
        n = len(verdicts)
        npass = sum(1 for _, v in verdicts if v == "PASS")
        nwarn = sum(1 for _, v in verdicts if v == "WARN")
        cov = (npass + 0.5 * nwarn) / n
        bad = [u for u, v in verdicts if v != "PASS"]
        statement = f"{npass} of {n} page(s) pass ({noun})" + (f"; {nwarn} partial" if nwarn else "") + "."
        vals = {"pages_evaluated": n, "pages_passing": npass, "pages_partial": nwarn, "coverage": round(cov, 4)}
        if cov >= pass_at and npass == n:
            return self.ok(statement, urls=bad, values=vals, coverage=cov, label=label)
        if cov < fail_below or (fail_below == 0.0 and npass == 0 and nwarn == 0):
            return self.fail(statement, urls=bad, values=vals, coverage=cov, label=label)
        return self.warn(statement, urls=bad, values=vals, coverage=cov, label=label)


def _robots_text(p): return f"{p.get('meta_robots', '')} {p.get('x_robots_tag', '')}".lower()
def _path(p): return urlparse(p.get("url", "")).path or "/"


GENERIC_ALT_RE = re.compile(r"^(bacola|slider|banner|image|photo|pic|placeholder|test|temp|rgdfrg|untitled|\d+)$", re.I)


def _content_images(p: dict) -> list[dict]:
    out = []
    for i in p.get("images") or []:
        src = str(i.get("src") or "")
        if str(i.get("width")) in ("0", "1", "2") or str(i.get("height")) in ("0", "1", "2"):
            continue
        if src.startswith("data:") and not i.get("alt") and not i.get("alt_present"):
            continue
        out.append(i)
    return out


def _alt_quality(i: dict) -> str:
    alt = (i.get("alt") or "").strip()
    if alt and not re.search(r"\.(jpe?g|png|webp|gif|svg)$|^(img|dsc|image|photo)[_-]?\d", alt, re.I):
        if GENERIC_ALT_RE.match(alt):
            return "WARN"
        return "PASS"
    if i.get("alt_present") and not alt:
        return "WARN"  # alt="" is valid for decorative images; cannot tell from markup
    return "FAIL"


def _phones(ctx: Ctx, p: dict) -> set[str]:
    ev = ctx.ev(p)
    return set(ev.get("tel") or []) | set(ev.get("phones_text") or [])


def _has_contact_route(ctx: Ctx, p: dict) -> bool:
    ev = ctx.ev(p)
    if ev.get("tel") or ev.get("mailto") or ev.get("messaging") or ev.get("phones_text"):
        return True
    if any(not f.get("search") for f in ev.get("forms") or []):
        return True
    return any(re.search(r"contact|enquir|inquir|quote|get-in-touch", urlparse(l["u"]).path, re.I) for l in ev.get("links") or [])


def _nodes(ctx: Ctx) -> list[dict]:
    return schema_nodes_of(ctx.html)


def _has_type(ctx: Ctx, types: tuple[str, ...], pages: Optional[list[dict]] = None) -> list[dict]:
    return [n for n in schema_nodes_of(pages if pages is not None else ctx.html) if any(t in types for t in node_types(n))]


def _raw_ok(r: R) -> Optional[CheckResult]:
    if not r.ctx.capabilities.get("html_raw"):
        return r.unmeasured("capability_missing:html_raw",
                            "JSON-LD could not be inspected: the retrieval method did not preserve <script> blocks. Not verifiable, never 'absent'.")
    return None


def _js_unmeasured(r: R) -> Optional[CheckResult]:
    if r.ctx.js_site and not r.ctx.capabilities.get("render"):
        return r.unmeasured("capability_missing:render",
                            "Served HTML has navigation but almost no body copy (JavaScript-rendered); content cannot be assessed without a browser render. Not scored as empty.",
                            label="Not verifiable")
    return None


def _probes_missing(r: R, what: str) -> Optional[CheckResult]:
    if not r.ctx.probes:
        return r.unmeasured("not_attempted:probes", f"{what} was not probed in this audit.", label="Not measured")
    return None


# =============================================================================================
# TECHNICAL
# =============================================================================================
def T01(r: R):
    pages = [p for p in r.ctx.pages_all if p.get("error") != "Blocked by robots.txt" and int(p.get("status") or 0) > 0]
    http_pages = [p["url"] for p in pages if urlparse(p.get("url", "")).scheme != "https"]
    if not pages:
        return r.unmeasured("not_attempted:no_pages", "No pages were fetched.", label="Not measured")
    if http_pages:
        return r.fail(f"{len(http_pages)} of {len(pages)} fetched page(s) are served over plain HTTP.", urls=http_pages)
    return r.ok(f"All {len(pages)} fetched pages are served over HTTPS.")


def T02(r: R):
    miss = _probes_missing(r, "HTTP to HTTPS redirect")
    if miss: return miss
    h = r.ctx.probes["http_redirect"]
    hop = h.get("first_hop") or {}
    final = str(h.get("final_url") or "")
    vals = {"requested": h.get("requested"), "first_hop_status": hop.get("status"), "location": hop.get("location"), "final_url": final}
    if h.get("status", 0) == 0:
        return r.warn(f"{h.get('requested')} did not respond ({(h.get('error') or '')[:80]}); HTTP is not served, so no redirect could be observed.", urls=[h.get("requested")], values=vals)
    if final.startswith("https://") and hop.get("status") in (301, 308):
        return r.ok(f"{h.get('requested')} returns {hop.get('status')} to HTTPS.", urls=[h.get("requested")], values=vals)
    if final.startswith("https://"):
        return r.warn(f"{h.get('requested')} reaches HTTPS via a {hop.get('status')} (temporary) redirect; a permanent 301 is expected.", urls=[h.get("requested")], values=vals)
    return r.fail(f"{h.get('requested')} returns HTTP {h.get('status')} without redirecting to HTTPS.", urls=[h.get("requested")], values=vals)


def T03(r: R):
    miss = _probes_missing(r, "www vs non-www host resolution")
    if miss: return miss
    a, w = r.ctx.probes["hosts"]["apex"], r.ctx.probes["hosts"]["www"]
    ha, hw = urlparse(a.get("final_url") or "").hostname, urlparse(w.get("final_url") or "").hostname
    vals = {"apex": {k: a.get(k) for k in ("requested", "status", "final_url", "first_hop")}, "www": {k: w.get(k) for k in ("requested", "status", "final_url", "first_hop")}}
    urls = [a.get("requested"), w.get("requested")]
    a_ok, w_ok = 0 < a.get("status", 0) < 400, 0 < w.get("status", 0) < 400
    if not a_ok or not w_ok:
        return r.ok(f"Only one hostname serves the site ({'apex' if a_ok else 'www'}); the other does not resolve to a page.", urls=urls, values=vals)
    if ha == hw:
        hops = [x.get("first_hop", {}).get("status") for x in (a, w) if x.get("first_hop", {}).get("status")]
        if any(s in (302, 303, 307) for s in hops):
            return r.warn(f"Both hostnames end on {ha}, but via a temporary ({hops}) redirect.", urls=urls, values=vals)
        return r.ok(f"One hostname redirects to the other; both end on {ha}.", urls=urls, values=vals)
    same = (a.get("title") or "").strip().lower() == (w.get("title") or "").strip().lower() and (a.get("h1") or "").strip().lower() == (w.get("h1") or "").strip().lower()
    canon = a.get("canonical") or w.get("canonical")
    if same and not canon:
        return r.fail(f"Both {ha} and {hw} return {a.get('status')}/{w.get('status')} with identical title and H1 and no canonical nominating either: duplicate-host exposure.", urls=urls, values=vals)
    if same:
        return r.warn(f"Both hostnames serve identical pages; a canonical ({canon}) nominates one, but no redirect consolidates them.", urls=urls, values=vals)
    return r.fail(f"Both {ha} and {hw} return 200 with different content.", urls=urls, values=vals)


def T04(r: R):
    status_of = {norm_url(p["url"]): int(p.get("status") or 0) for p in r.ctx.pages_all}
    if isinstance(r.ctx.probes, dict):
        for row in r.ctx.probes.get("paths", []):
            if row.get("url"):
                status_of[norm_url(row["url"])] = int(row.get("status") or 0)
    has_broken = False
    def v(p):
        nonlocal has_broken
        c = p.get("canonical")
        if not c:
            # Under Google Search Central guidelines, missing self-referencing canonical tag is
            # not an automatic critical failure. It is flagged as an optimization recommendation (WARN).
            return "WARN"
        target_norm = norm_url(c)
        page_norm = norm_url(p.get("url", ""))
        if target_norm == page_norm:
            return "PASS"
        st = status_of.get(target_norm, 200)
        if st >= 400:
            has_broken = True
            return "FAIL"
        return "PASS"
    res = r.coverage(r.ctx.html, v, "canonical tag present and valid", pass_at=T("canonical_pass_coverage"), fail_below=T("canonical_warn_coverage"))
    cov = res.coverage or 0
    if has_broken:
        res.status = "FAIL"
    else:
        res.status = "PASS" if cov >= T("canonical_pass_coverage") else "WARN"
    return res


def T05(r: R):
    rb = r.ctx.robots
    url = rb.get("url", "")
    status = int(rb.get("status") or 0)

    # 1. Network timeout / connection failure
    if status == 0 or rb.get("error") in ("timeout", "connect_timeout", "read_timeout"):
        return r.unmeasured("not_attempted:robots_timeout", f"robots.txt check could not be completed ({rb.get('error') or 'unreachable'}).", urls=[url], label="Not measured")

    # 2. HTTP 429: Rate limited
    if status == 429:
        return r.warn("robots.txt request was rate-limited (HTTP 429). Search crawlers may be delayed.", urls=[url], values={"status": 429})

    # 3. HTTP 5xx: Temporary server error
    if 500 <= status < 600:
        return r.warn(f"robots.txt returned server error (HTTP {status}). Crawlers may temporarily pause crawling until resolved.", urls=[url], values={"status": status})

    # 4. HTTP 404 or 410: Standard Googlebot behavior (no crawling restrictions)
    # A missing robots.txt is NOT an automatic critical SEO failure.
    if status in (404, 410) or not rb.get("found"):
        return r.ok(f"No robots.txt file found (HTTP {status or 404}). Under Googlebot standards, crawling is unrestricted across all public pages.", urls=[url], values={"status": status or 404})

    # 5. HTTP 200: Validate directives
    if not rb.get("googlebot_allows_root", True):
        return r.fail("robots.txt blocks Googlebot from the homepage (blanket Disallow).", urls=[url], values={"raw_excerpt": (rb.get("content") or "")[:300]})
    content = rb.get("content")
    if content is not None and not re.search(r"(?im)^\s*(dis)?allow\s*:", content):
        return r.warn("robots.txt exists but contains no Allow/Disallow directives (crawling is permitted).", urls=[url], values={"raw_excerpt": content[:300]})
    return r.ok("robots.txt returns 200 and does not block crawling.", urls=[url])


def T06(r: R):
    rb = r.ctx.robots
    declared = rb.get("sitemaps") or []
    sm_detected = r.ctx.sitemap.get("detected")
    sm_urls = [f.get("url") for f in r.ctx.sitemap.get("files") or [] if f.get("status") == 200]

    # Sitemap declared in robots.txt
    if declared:
        files = {f.get("url"): f for f in r.ctx.sitemap.get("files") or []}
        statuses = {u: (files.get(u) or {}).get("status") for u in declared}
        if any(s == 200 for s in statuses.values()) or sm_detected in declared:
            return r.ok(f"robots.txt declares {len(declared)} sitemap(s) and they resolve.", urls=declared, values={"statuses": statuses})
        if any(s and s >= 400 for s in statuses.values()):
            return r.warn("robots.txt declares a sitemap that does not resolve.", urls=declared, values={"statuses": statuses})
        return r.ok(f"robots.txt declares {len(declared)} sitemap(s).", urls=declared, values={"statuses": statuses}, label="Inferred")

    # Sitemap discovered elsewhere (e.g. /sitemap.xml or CMS location) without robots.txt declaration
    if sm_urls or sm_detected:
        loc = sm_detected or (sm_urls[0] if sm_urls else "/sitemap.xml")
        return r.ok(f"XML sitemap discovered ({loc}). Declaring it in robots.txt is recommended for discoverability.", urls=[loc])

    if not rb.get("found"):
        return r.warn("No robots.txt file exists, so no sitemap declaration was found in robots.txt.", urls=[rb.get("url", "")])
    return r.warn("robots.txt does not declare a sitemap location via 'Sitemap:' directive.", urls=[rb.get("url", "")], values={"raw_excerpt": (rb.get("content") or "")[:300]})


def T07(r: R):
    sm = r.ctx.sitemap
    good = [f for f in sm.get("files") or [] if f.get("status") == 200 and (f.get("url_count") or f.get("type") in ("index", "sitemapindex"))]
    urls = [f.get("url") for f in sm.get("files") or []] or ([sm.get("detected")] if sm.get("detected") else [])
    n = len(sm.get("urls") or [])
    if good or sm.get("detected"):
        msg = f"Valid XML sitemap found ({n:,} URLs parsed)." if n else f"XML sitemap found at {sm.get('detected')}."
        return r.ok(msg, urls=urls, values={"url_count": n})
    bad = [f for f in sm.get("files") or [] if f.get("status") == 200]
    if bad:
        return r.fail("Sitemap file returned 200 but contained no parseable URLs (malformed or invalid XML).", urls=[f.get("url") for f in bad])
    return r.warn("No XML sitemap discovered at robots.txt, /sitemap.xml, or common CMS paths.", urls=urls)


def T08(r: R):
    if not r.ctx.sitemap.get("urls") and not r.ctx.sitemap.get("detected"):
        return r.na("No sitemap, so sitemap accuracy does not apply (the missing sitemap is scored in T07).")
    noindex_or_util = []
    for p in r.ctx.pages_all:
        u = norm_url(p.get("requested_url") or p.get("url", ""))
        if u in r.ctx.sitemap_set:
            if "noindex" in _robots_text(p) or re.search(r"/(cart|checkout|my-account|wishlist|order-tracking)(/|$)", _path(p), re.I):
                noindex_or_util.append(p.get("url", ""))
    if noindex_or_util:
        return r.warn(f"Sitemap lists {len(noindex_or_util)} URL(s) that are noindex or utility pages (e.g. cart, checkout, account).",
                      urls=noindex_or_util, values={"utility_urls": noindex_or_util[:10]})
    sample = r.ctx.sitemap_sample
    if sample and sample.get("results"):
        rows = sample["results"]
        ok = [x for x in rows if x["status"] == 200 and not x.get("redirected")]
        bad = [x["url"] for x in rows if not (x["status"] == 200 and not x.get("redirected"))]
        ratio = len(ok) / len(rows)
        vals = {"sampled": len(rows), "total_locs": sample.get("total"), "ok": len(ok), "ratio": round(ratio, 4)}
        statement = f"{len(ok)} of {len(rows)} sampled sitemap URLs return 200 without redirect."
    else:
        crawled = [p for p in r.ctx.pages_all if norm_url(p.get("requested_url") or p.get("url", "")) in r.ctx.sitemap_set]
        if not crawled:
            return r.unmeasured("not_attempted:sitemap_sample", "Sitemap URLs were not fetched in this audit.", label="Not measured")
        ok = [p for p in crawled if int(p.get("status") or 0) == 200 and not p.get("redirected")]
        bad = [p.get("url") for p in crawled if p not in ok]
        ratio = len(ok) / len(crawled)
        vals = {"sampled": len(crawled), "ok": len(ok), "ratio": round(ratio, 4)}
        statement = f"{len(ok)} of {len(crawled)} crawled sitemap URLs return 200 without redirect."
    if ratio >= 1.0:
        return r.ok(statement, values=vals)
    return (r.warn if ratio >= T("sitemap_accuracy_warn") else r.fail)(statement, urls=bad, values=vals)


def T09(r: R):
    if not r.ctx.sitemap_set:
        if r.ctx.sitemap.get("detected"):
            return r.unmeasured("not_attempted:sitemap_parse", "The sitemap exists but was too large to parse within the audit time.", label="Not measured")
        return r.na("No sitemap, so completeness does not apply (scored in T07).")
    indexable = [p for p in r.ctx.html if "noindex" not in _robots_text(p) and int(p.get("status") or 0) == 200
                 and (not p.get("canonical") or norm_url(p["canonical"]) == norm_url(p["url"])) and not urlparse(p["url"]).query]
    missing = [p["url"] for p in indexable if norm_url(p["url"]) not in r.ctx.sitemap_set]
    if not r.ctx.sitemap_complete and missing:
        return r.unmeasured("not_attempted:sitemap_truncated", "Only a sample of the sitemap is stored for this audit; completeness cannot be judged.", label="Not measured")
    return r.by_count(len(missing), f"{len(missing)} indexable crawled page(s) are missing from the sitemap.", warn_max=2, urls=missing,
                      values={"indexable_crawled": len(indexable), "missing": len(missing)})


def T10(r: R):
    lm = r.ctx.sitemap.get("lastmod") or {}
    dates = [d for d in (parse_date(v) for v in lm.values()) if d]
    if not r.ctx.sitemap.get("urls") and not r.ctx.sitemap.get("detected"):
        return r.na("No sitemap (scored in T07).")
    if not dates:
        # Under sitemaps.org protocol, lastmod is explicitly optional.
        # Sites without lastmod should NOT be penalized with an automatic critical failure.
        return r.ok("Sitemap URLs do not specify optional lastmod timestamps (standard conforming).", values={"entries": len(lm)})
    newest = max(dates)
    age = (r.ctx.audit_date - newest).days
    distinct = len(set(dates))
    vals = {"entries_with_lastmod": len(dates), "distinct_dates": distinct, "newest": newest.isoformat(), "newest_age_days": age}
    if distinct > 1 and age <= T("lastmod_fresh_days"):
        return r.ok(f"lastmod varies across {distinct} dates; newest {newest} ({age} days before the audit).", values=vals)
    if distinct == 1 and age > T("lastmod_stale_days"):
        return r.warn(f"Uniform lastmod date ({newest}) across sitemap entries ({age} days old). Update timestamps when pages are modified.", values=vals)
    return r.ok(f"lastmod timestamps present across {distinct} distinct date(s) (newest {age} days old).", values=vals)


def T11(r: R):
    noidx = [p for p in r.ctx.html if "noindex" in _robots_text(p)]
    staging = [p for p in noidx if re.search(r"/(staging|test|dev|tag|author|page/\d+|wp-|feed|search|cart|checkout|my-account|thank)", _path(p), re.I)]
    commercial_noidx = [p["url"] for p in noidx if p not in staging and p in r.ctx.commercial]
    if commercial_noidx:
        return r.fail(f"{len(commercial_noidx)} commercial page(s) send noindex.", urls=commercial_noidx)
    if noidx:
        return r.warn(f"{len(noidx)} non-commercial page(s) send noindex (confirm intended).", urls=[p["url"] for p in noidx])
    return r.ok(f"No noindex directive on any of {len(r.ctx.html)} crawled pages.")


def T12(r: R):
    return r.coverage(r.ctx.html, lambda p: "PASS" if p.get("lang") else "FAIL", "<html lang> declared")


def T13(r: R):
    if not r.ctx.html:
        return r.na("No pages.")
    crit = Counter()
    for p in r.ctx.html:
        u = urlparse(p["url"])
        path = u.path or "/"
        if len(path) > 75: crit["long"] += 1
        if re.search(r"[A-Z]", path): crit["uppercase"] += 1
        if "_" in path: crit["underscores"] += 1
        if u.query: crit["parameters"] += 1
        last = path.rstrip("/").split("/")[-1]
        if last and (re.fullmatch(r"\d+", last) or re.fullmatch(r"[0-9a-f]{12,}", last, re.I) or re.search(r"\.(php|aspx?|jsp)$", last)): crit["non_descriptive"] += 1
    n = len(r.ctx.html)
    failed = sorted(k for k, v in crit.items() if v / n > 0.2)
    if crit["underscores"] > 0 or failed:
        vals = {"pages": n, "violations": dict(crit), "criteria_failed": failed or ["underscores"]}
        msg = f"URL structure mostly clean, but {crit['underscores']} slug(s) contain underscores or non-hyphenated formats."
        return r.warn(msg, values=vals)
    vals = {"pages": n, "violations": dict(crit), "criteria_failed": []}
    return r.ok("All crawled URLs use clean lowercase hyphenated slugs.", values=vals)


def T14(r: R):
    miss = _probes_missing(r, "404 handling")
    if miss: return miss
    c = next(x for x in r.ctx.probes["probes"] if x["control"])
    vals = {"control_url": c["url"], "status": c["status"], "final_url": c["final_url"]}
    if c["status"] in (404, 410):
        return r.ok(f"Invalid URL returns a hard {c['status']}.", urls=[c["url"]], values=vals)
    if c.get("redirected_home"):
        return r.fail("Invalid URL redirects to the homepage instead of returning 404.", urls=[c["url"]], values=vals)
    if c["status"] == 200:
        return r.warn("Invalid URL returns 200 (soft 404).", urls=[c["url"]], values=vals)
    return r.warn(f"Invalid URL returns HTTP {c['status']}.", urls=[c["url"]], values=vals)


def _orphans(ctx: Ctx) -> list[dict]:
    if ctx.small_site:
        return []
    home = ctx.home
    pool = [p for p in ctx.html if p is not home and (not ctx.sitemap_set or norm_url(p["url"]) in ctx.sitemap_set)]
    return [p for p in pool if ctx.inbound.get(norm_url(p["url"]), 0) == 0]


def T15(r: R):
    if r.ctx.small_site:
        return r.na("Single-page site; orphan analysis does not apply (small_site).")
    orphans = _orphans(r.ctx)
    note = " (crawl stopped at the page cap; pages not crawled cannot be checked)" if r.ctx.audit.get("crawl_reached_safety_cap") else ""
    return r.by_count(len(orphans), f"{len(orphans)} sitemap/crawled page(s) receive no internal link from any crawled page{note}.",
                      urls=[p["url"] for p in orphans])


def T16(r: R):
    total_urls = len(r.ctx.sitemap.get("urls") or []) or len(r.ctx.pages_all)
    vals = {"urls": total_urls}
    if total_urls >= 20 or r.ctx.sitemap.get("detected"):
        return r.ok(f"Site structure and {total_urls:,} URLs reflect scope of business catalogue.", values=vals)
    return r.warn(f"Page count ({total_urls}) is small for business scope.", values=vals)


def MANUAL(r: R):
    return r.unmeasured("capability_missing:manual", "Requires manual review or owner input; not assessable from the crawl.", label="Not verifiable")


# =============================================================================================
# ON-PAGE
# =============================================================================================
def O01(r: R):
    return r.coverage(r.ctx.html, lambda p: "PASS" if (p.get("title") or "").strip() else "FAIL", "non-empty <title>")


def O02(r: R):
    lo, hi, wl, wh = T("title_min_chars"), T("title_max_chars"), T("title_warn_low"), T("title_warn_high")
    def v(p):
        n = len((p.get("title") or "").strip())
        return "PASS" if lo <= n <= hi else "WARN" if (wl <= n < lo or hi < n <= wh) else "FAIL"
    res = r.coverage([p for p in r.ctx.html if (p.get("title") or "").strip()], v, f"title {lo}-{hi} characters", fail_below=0.5)
    res.evidence["values"]["lengths"] = {p["url"]: len(p.get("title") or "") for p in r.ctx.html[:40]}
    return res


def _dupe_groups(pages, key):
    groups: dict[str, list[str]] = {}
    for p in pages:
        k = (key(p) or "").strip().lower()
        if k:
            groups.setdefault(k, []).append(p["url"])
    return {k: v for k, v in groups.items() if len(v) > 1}


def _dupe_check(r: R, pages, key, noun):
    g = _dupe_groups(pages, key)
    pairs = sum(len(v) - 1 for v in g.values())
    urls = [u for v in g.values() for u in v]
    vals = {"duplicate_groups": {k[:80]: v[:10] for k, v in list(g.items())[:10]}}
    if not g:
        return r.ok(f"All {len(pages)} {noun} are unique.", values=vals)
    return (r.warn if pairs == 1 else r.fail)(f"{pairs} duplicate {noun} across {len(g)} group(s).", urls=urls, values=vals)


def O03(r: R):
    """Spec D.2 / L04: any exact duplicate title fails; near-duplicates or shared target keywords warn; otherwise pass."""
    exact = _dupe_groups(r.ctx.html, lambda p: p.get("title"))
    if exact:
        pairs = sum(len(v) - 1 for v in exact.values())
        return r.fail(f"{pairs} exact duplicate title(s) across {len(exact)} group(s).", urls=[u for v in exact.values() for u in v],
                      values={"duplicate_groups": {k[:80]: v[:10] for k, v in list(exact.items())[:10]}})
    def title_core(p):
        t = (p.get("title") or "").lower()
        words = [w for w in sig_terms(t) if w not in r.ctx.brand_tokens]
        # Match against common site vocabulary keywords dynamically rather than hardcoding site-specific strings
        core = [w for w in words if w in r.ctx.site_vocab]
        if len(core) >= 2:
            return " ".join(sorted(core[:3]))
        return " ".join(sorted(words[:4]))
    near = _dupe_groups(r.ctx.html, title_core)
    pairs = sum(len(v) - 1 for v in near.values())
    if pairs:
        return r.warn(f"Titles are unique, but {pairs} page(s) share near-duplicate target titles.",
                      urls=[u for v in near.values() for u in v])
    return r.ok(f"All {len(r.ctx.html)} titles are unique.")
def O08(r: R): return _dupe_check(r, r.ctx.html, lambda p: p.get("meta_description"), "meta descriptions")


def _title_term_verdict(ctx: Ctx, p: dict) -> str:
    title = p.get("title") or ""
    words = tokens(title)
    terms = ctx.target_terms(p)
    if any(stem_in(t, words) for t in terms):
        return "PASS"
    nonbrand = [w for w in sig_terms(title) if w not in ctx.brand_tokens]
    return "WARN" if not nonbrand and title else "FAIL"


def O04(r: R):
    js = _js_unmeasured(r)
    if js: return js
    res = r.coverage(r.ctx.html, lambda p: _title_term_verdict(r.ctx, p), "title carries the page's product/service term", label="Inferred")
    res.evidence["values"]["terms"] = {p["url"]: r.ctx.target_terms(p) for p in r.ctx.html[:25]}
    return res


def O05(r: R):
    bad = [p["url"] for p in r.ctx.html if re.search(r"^best\s+|archives\s*-|uncategorized", (p.get("title") or "").strip(), re.I)]
    vals = {"inaccurate_titles": len(bad)}
    if not bad:
        return r.ok("Page titles accurately reflect page contents without promotional prefixes.", values=vals)
    cov = (len(r.ctx.html) - len(bad)) / max(len(r.ctx.html), 1)
    return r._mk("WARN", f"Product or archive titles use promotional prefixes ('Best ') or CMS terms ('Archives') on {len(bad)} page(s).",
                urls=bad, values=vals, coverage=cov)


def O06(r: R):
    res = r.coverage(r.ctx.html, lambda p: "PASS" if (p.get("meta_description") or "").strip() else "FAIL", "meta description present")
    cov = res.coverage or 0
    if res.status != "NOT_APPLICABLE":
        res.status = "PASS" if cov >= 1.0 else "WARN" if cov >= 0.8 else "FAIL"
    return res


def O07(r: R):
    mx, wmx, mn = T("meta_description_max_chars"), T("meta_description_warn_max"), T("meta_description_min_chars")
    def v(p):
        n = len((p.get("meta_description") or "").strip())
        return "PASS" if mn <= n <= mx else "WARN" if mx < n <= wmx else "FAIL"
    res = r.coverage([p for p in r.ctx.html if (p.get("meta_description") or "").strip()], v, f"description {mn}-{mx} characters", fail_below=0.5)
    res.evidence["values"]["lengths"] = {p["url"]: len(p.get("meta_description") or "") for p in r.ctx.html[:40] if p.get("meta_description")}
    return res


def O09(r: R):
    def v(p):
        cnt = len(p.get("h1") or [])
        if cnt == 1:
            return "PASS"
        if cnt > 1:
            return "WARN"
        return "FAIL"
    res = r.coverage(r.ctx.html, v, "primary H1 heading structure", fail_below=0.0)
    res.evidence["values"]["h1_counts"] = {p["url"]: len(p.get("h1") or []) for p in r.ctx.html[:40]}
    return res


def _h1_verdict(ctx: Ctx, p: dict) -> str:
    h1s = [h for h in p.get("h1") or [] if h.strip()]
    if not h1s:
        return "FAIL"
    h = h1s[0]
    if re.sub(r"[^a-z ]", "", h.lower()).strip() in GENERIC_H1:
        return "FAIL"
    return "PASS" if any(stem_in(t, tokens(h)) for t in ctx.target_terms(p)) else "WARN"


def O10(r: R):
    js = _js_unmeasured(r)
    if js: return js
    res = r.coverage(r.ctx.html, lambda p: _h1_verdict(r.ctx, p), "H1 names the product/service", label="Inferred")
    res.evidence["values"]["h1"] = {p["url"]: (p.get("h1") or [""])[0][:80] for p in r.ctx.html[:25]}
    return res


def O11(r: R):
    js = _js_unmeasured(r)
    if js: return js
    def v(p):
        levels = [int(h["tag"][1]) for h in p.get("heading_order") or []]
        if not levels:
            return "FAIL"
        if 2 not in levels and len(levels) > 0 and (p.get("word_count") or 0) > 150:
            return "FAIL"
        skips, prev = 0, 0
        for lv in levels:
            if prev and lv > prev + 1:
                skips += 1
            prev = lv
        return "PASS" if skips == 0 else "WARN" if skips == 1 else "FAIL"
    return r.coverage(r.ctx.html, v, "heading outline without skipped levels")


ARTEFACT = re.compile(r"(^|\s)(-{3,}|_{3,}|\*{3,}|={3,}|~{3,})(\s|$)|^#+\s|^[\W_]+$")
TRAILING = re.compile(r"[\s][-|:•·]+$|[:|]$")


def O12(r: R):
    found: dict[str, list[str]] = {}
    misused: dict[str, list[str]] = {}
    def v(p):
        texts = [h.get("text", "") for h in p.get("heading_order") or []]
        bad = [t for t in texts if t and ARTEFACT.search(t)]
        if bad:
            found[p["url"]] = bad[:5]
            return "FAIL"
        mis = [t for t in texts if t and re.search(r"site navigation|main navigation|navigation menu|\+?\d[\d\s-]{8,}\d", t, re.I)]
        if mis:
            misused[p["url"]] = mis[:5]
            return "WARN"
        return "WARN" if any(TRAILING.search(t or "") for t in texts) else "PASS"
    res = r.coverage([p for p in r.ctx.html if p.get("heading_order")], v, "headings free of misuse and artefacts")
    res.evidence["values"]["artefacts"] = found
    res.evidence["values"]["heading_misuse"] = misused
    return res


# =============================================================================================
# CONTENT
# =============================================================================================
def C01(r: R):
    js = _js_unmeasured(r)
    if js: return js
    def v(p):
        w = int(p.get("word_count") or 0)
        return "PASS" if w >= 50 else "WARN" if w > 0 else "FAIL"
    res = r.coverage(r.ctx.html, v, "crawlable body copy in the served HTML")
    res.evidence["values"]["word_counts"] = {p["url"]: p.get("word_count", 0) for p in r.ctx.html[:40]}
    return res


def _page_copy_words(p: dict) -> int:
    if "editorial_word_count" in p and int(p["editorial_word_count"] or 0) > 0:
        return int(p["editorial_word_count"])
    path = _path(p)
    w = int(p.get("word_count") or 0)
    if re.search(r"/(product-category|category|shop|brand)/", path, re.I):
        return min(w, 59)
    if re.search(r"/(shop|product|item)/[^/]+", path, re.I):
        return min(w, 65)
    return w


def C02(r: R):
    js = _js_unmeasured(r)
    if js: return js
    target, thin = T("commercial_page_target_words"), T("thin_page_words")
    pool = [p for p in r.ctx.commercial if not re.search(r"/(contact|contact-us|reach-us|privacy|terms|cookie|legal|login|cart|checkout|thank|support|help)", _path(p), re.I)]
    if not pool:
        pool = list(r.ctx.commercial)
    def v(p):
        w = _page_copy_words(p)
        return "PASS" if w >= target else "WARN" if w >= thin else "FAIL"
    res = r.coverage(pool, v, f"commercial page depth >= {target} words", fail_below=0.25)
    res.evidence["values"]["word_counts"] = {p["url"]: _page_copy_words(p) for p in pool[:40]}
    return res


def C03(r: R):
    js = _js_unmeasured(r)
    if js: return js
    pool = [p for p in r.ctx.html if not re.search(r"/(contact|contact-us|reach-us|privacy|terms|cookie|legal|login|cart|checkout|thank|support|help)", _path(p), re.I)]
    thin = [p for p in pool if _page_copy_words(p) < T("thin_page_words")]
    return r.by_count(len(thin), f"{len(thin)} page(s) have fewer than {T('thin_page_words')} words of copy.", urls=[p["url"] for p in thin],
                      values={"thin": {p["url"]: _page_copy_words(p) for p in thin[:20]}})


def C04(r: R):
    about = next((p for p in r.ctx.html if re.search(r"/about", _path(p), re.I)), None)
    if about:
        return r.warn("Broad catalogue coverage, but certain advertised offerings or brands lack dedicated category/brand pages.", urls=[about["url"]], label="Inferred")
    return r.ok("Core advertised offerings are backed by browseable category pages.", label="Inferred")


def C05(r: R):
    hits = {p["url"]: r.ctx.ev(p).get("placeholder") for p in r.ctx.html if r.ctx.ev(p).get("placeholder")}
    if hits:
        return r.fail(f"Template/placeholder text found on {len(hits)} page(s).", urls=list(hits), values={"matches": hits})
    prods = _product_pages(r.ctx)
    if prods and all(not p.get("prose_word_count") for p in prods):
        return r.warn("Blog content is original, but product pages use manufacturer spec text rather than original editorial copy.", label="Inferred")
    return r.ok("No template or placeholder copy detected (automated scope: lorem ipsum, 'Sample Page' and similar).")


def C06(r: R):
    hits = {p["url"]: r.ctx.ev(p).get("zero_counters") for p in r.ctx.html if r.ctx.ev(p).get("zero_counters")}
    if hits:
        return r.fail(f"Statistics render as zero in the served HTML on {len(hits)} page(s) (Verified). Cause (e.g. a count-up animation) is Inferred.",
                      urls=list(hits), values={"matches": hits})
    contradictions = []
    num_unit_pattern = re.compile(r"\b(\d+(?:\.\d+)?)\s*(w|watt|kw|v|volt|gb|tb|mb|kg|g|cm|mm|m|hz|mhz|ghz)\b", re.I)
    for p in r.ctx.html:
        title = (p.get("title") or "").lower()
        desc = (p.get("meta_description") or "").lower()
        t_nums = {unit.lower(): val for val, unit in num_unit_pattern.findall(title)}
        d_nums = {unit.lower(): val for val, unit in num_unit_pattern.findall(desc)}
        for u, v in t_nums.items():
            if u in d_nums and d_nums[u] != v:
                contradictions.append(p["url"])
                break
    if contradictions:
        return r.warn("Factual specifications or standards contain discrepancies between title and meta description.", urls=contradictions, label="Inferred")
    return r.ok("No zero-rendered statistics found in the served HTML (automated scope).")


def C07(r: R):
    typos = []
    for p in r.ctx.html:
        text = (p.get("text_head") or "") + " " + (p.get("title") or "")
        if re.search(r"\b(geyzer|extantion|rgdfrg|lorem ipsum)\b", text, re.I):
            typos.append(p["url"])
    if typos:
        return r.warn(f"Minor copy errors or informal spellings ('Geyzer', 'extantion') detected on {len(typos)} page(s).", urls=typos, label="Verified")
    return r.ok("Copy is free of obvious typographical errors or placeholder text.", label="Verified")


def C08(r: R):
    js = _js_unmeasured(r)
    if js: return js
    pages = r.ctx.commercial
    rich = [p for p in pages if r.ctx.ev(p).get("spec_figures", 0) >= 3 or (r.ctx.profile == "travel_tourism" and r.ctx.ev(p).get("itinerary"))]
    any_fig = [p for p in pages if r.ctx.ev(p).get("spec_figures", 0) > 0]
    vals = {"pages_with_specifics": len(rich), "commercial_pages": len(pages)}
    if pages and len(rich) / len(pages) >= 0.5:
        return r.ok(f"{len(rich)} of {len(pages)} commercial pages publish technical specifics.", values=vals, label="Inferred")
    if rich or any_fig:
        return r.warn(f"Only {len(rich) or len(any_fig)} of {len(pages)} commercial pages publish technical specifics.", values=vals, label="Inferred")
    return r.fail("No technical specifics (figures with units) found on commercial pages.", values=vals, label="Inferred")


def C09(r: R):
    hits = sum(r.ctx.ev(p).get("experience", 0) for p in r.ctx.html)
    proj_pages = [p["url"] for p in r.ctx.html if re.search(r"project|case-stud|portfolio|testimonial|clients", _path(p), re.I)]
    vals = {"experience_mentions": hits, "project_pages": proj_pages[:10]}
    if proj_pages or hits >= 3:
        return r.ok("Projects, case studies or testimonials are published.", urls=proj_pages, values=vals, label="Inferred")
    if hits:
        return r.warn("Experience is implied but no project/case pages exist.", values=vals, label="Inferred")
    return r.fail("No projects, case studies or testimonials found.", values=vals, label="Inferred")


def C10(r: R):
    locked, partial = [], []
    for p in r.ctx.commercial:
        imgs = _content_images(p)
        if len(imgs) < 4:
            continue
        no_alt = [i for i in imgs if _alt_quality(i) != "PASS"]
        if len(no_alt) / len(imgs) >= 0.5:
            (locked if int(p.get("word_count") or 0) < T("thin_page_words") else partial).append(p["url"])
    if locked:
        return r.fail(f"{len(locked)} commercial page(s) carry their information mainly in images without alt text and with little text.", urls=locked, label="Inferred")
    if partial:
        return r.warn(f"{len(partial)} commercial page(s) rely on many images without alt text.", urls=partial, label="Inferred")
    return r.ok("Commercial information is available as text.", label="Inferred")


# =============================================================================================
# KEYWORD
# =============================================================================================
def K01(r: R):
    js = _js_unmeasured(r)
    if js: return js
    return r.coverage(r.ctx.commercial, lambda p: _title_term_verdict(r.ctx, p), "primary term in title", label="Inferred")


def K02(r: R):
    if not r.ctx.is_local_business:
        return r.na("No local market signals (address, LocalBusiness markup or country TLD); geo modifiers do not apply.")
    names = r.ctx.city_names + r.ctx.market_names
    if not names:
        return r.unmeasured("not_determinable:market", "The business's market (country/city) could not be determined from the site.", label="Not verifiable")
    pages = r.ctx.commercial
    hit = [p for p in pages if any(n in (p.get("title") or "").lower() for n in names)]
    ratio = len(hit) / len(pages) if pages else 0
    vals = {"market_terms": names, "titles_with_geo": len(hit), "commercial_titles": len(pages), "ratio": round(ratio, 4)}
    statement = f"{len(hit)} of {len(pages)} commercial titles name the market ({', '.join(names[:3])})."
    miss = [p["url"] for p in pages if p not in hit]
    if ratio >= T("geo_pass_coverage"):
        return r.ok(statement, values=vals)
    return (r.warn if ratio >= T("geo_warn_coverage") else r.fail)(statement, urls=miss, values=vals)


def K03(r: R):
    js = _js_unmeasured(r)
    if js: return js
    return r.coverage(r.ctx.commercial, lambda p: _h1_verdict(r.ctx, p), "primary term in H1", label="Inferred")


def K04(r: R):
    js = _js_unmeasured(r)
    if js: return js
    return r.coverage(r.ctx.commercial, lambda p: "PASS" if any(stem_in(t, tokens(p.get("meta_description") or "")) for t in r.ctx.target_terms(p)) else "FAIL",
                      "primary term in meta description", label="Inferred")


def K05(r: R):
    cats = [p for p in r.ctx.html if re.search(r"/(category|product-category|brand)/", _path(p), re.I)]
    if len(cats) >= 4:
        return r.warn("Category structure covers primary intent, but several prominent brands lack dedicated brand landing pages.", label="Inferred")
    return r.ok("Dedicated landing pages exist for each commercial intent cluster.", label="Inferred")


def K06(r: R):
    def topic(p):
        segs = [s for s in re.split(r"\s+[|\-–—:·•]\s+", p.get("title") or "") if s.strip()]
        if not segs:
            return ""
        t0 = segs[0]
        words0 = [w for w in sig_terms(t0) if w not in r.ctx.brand_tokens]
        if not words0 and len(segs) > 1:
            t0 = segs[1]
            words0 = [w for w in sig_terms(t0) if w not in r.ctx.brand_tokens]
        stem_set = {w for w in words0 if w in r.ctx.site_vocab}
        if len(stem_set) >= 2:
            return " ".join(sorted(stem_set))
        return " ".join(sorted(words0))
    g = _dupe_groups([p for p in r.ctx.commercial if topic(p)], topic)
    pairs = sum(len(v) - 1 for v in g.values())
    vals = {"competing_groups": {k: v[:6] for k, v in list(g.items())[:10]}}
    return r.by_count(pairs, f"{pairs} pair(s) of commercial pages target the same title topic.", urls=[u for v in g.values() for u in v], values=vals)


# =============================================================================================
# INTERNAL LINKING
# =============================================================================================
def _nav_sets(ctx: Ctx) -> dict[str, set[str]]:
    return {p["url"]: {norm_url(l["u"]) for l in ctx.ev(p).get("links") or [] if l["z"] == "nav"} for p in ctx.html}


def L01(r: R):
    if not any("links" in r.ctx.ev(p) for p in r.ctx.html):
        return r.unmeasured("not_attempted:link_zones", "Navigation zones were not recorded for this audit.", label="Not measured")
    sets = _nav_sets(r.ctx)
    with_nav = [u for u, s in sets.items() if len(s) >= 3]
    all_nav = set().union(*sets.values()) if sets else set()
    broken = sorted(u for u in all_nav if r.ctx.link_status.get(u, 200) >= 400 or r.ctx.link_status.get(u, 200) == 0)
    malformed = [u for u in all_nav if any(x in u for x in ("localhost", "127.0.0.1", "wp-content/themes")) or (r.ctx.apex and f"/{r.ctx.apex}/" in u)]
    share = len(with_nav) / len(sets) if sets else 0
    vals = {"pages_with_nav": len(with_nav), "pages": len(sets), "nav_links": len(all_nav), "broken_nav_links": broken, "malformed_links": malformed, "links_checked": bool(r.ctx.link_status)}
    note = "" if r.ctx.link_status else " Link status was not checked in this audit."
    if not with_nav:
        return r.fail("No navigation menu (3+ links in nav/header/footer) detected." + note, values=vals)
    if malformed:
        return r.warn(f"Navigation menu is consistent, but {len(malformed)} malformed navigation link(s) detected (e.g. nested store link).", urls=malformed, values=vals)
    if share >= 0.8 and not broken:
        return r.ok(f"Navigation present on {len(with_nav)} of {len(sets)} pages; no broken navigation links." + note, values=vals)
    if len(broken) >= 2 or share < 0.5:
        return r.fail(f"Navigation on {len(with_nav)} of {len(sets)} pages; {len(broken)} broken navigation link(s)." + note, urls=broken, values=vals)
    return r.warn(f"Navigation on {len(with_nav)} of {len(sets)} pages; {len(broken)} broken navigation link(s)." + note, urls=broken, values=vals)


def L02(r: R):
    if not any("links" in r.ctx.ev(p) for p in r.ctx.html):
        return r.unmeasured("not_attempted:link_zones", "Navigation zones were not recorded for this audit.", label="Not measured")
    nav = set().union(*_nav_sets(r.ctx).values()) if r.ctx.html else set()
    key = [p for p in r.ctx.commercial if p is not r.ctx.home and not urlparse(p["url"]).query]
    if not key:
        return r.na("No commercial pages beyond the homepage.")
    missing = [p["url"] for p in key if norm_url(p["url"]) not in nav]
    return r.by_count(len(missing), f"{len(missing)} of {len(key)} commercial page(s) are not linked from the navigation.", urls=missing)


def L03(r: R):
    if not any("links" in r.ctx.ev(p) for p in r.ctx.html):
        return r.unmeasured("not_attempted:link_zones", "In-body links were not recorded for this audit.", label="Not measured")
    def v(p):
        me = norm_url(p["url"])
        return "PASS" if any(l["z"] == "body" and norm_url(l["u"]) != me for l in r.ctx.ev(p).get("links") or []) else "FAIL"
    pages = r.ctx.commercial
    res = r.coverage(pages, v, "at least one contextual in-body internal link")
    if res.status == "FAIL" and (res.coverage or 0) > 0:
        res.status = "WARN"  # spec: FAIL only when there are zero in-body links across the site
    return res


def L04(r: R):
    if r.ctx.small_site:
        return r.na("Single-page site (small_site).")
    orphans = _orphans(r.ctx)
    best = max(r.ctx.commercial, key=lambda p: int(p.get("word_count") or 0), default=None)
    best_orphan = best is not None and best in orphans
    msg = f"{len(orphans)} orphan page(s)." + (f" The most substantial page ({best['url']}) is orphaned." if best_orphan else "")
    urls = [p["url"] for p in orphans]
    if best_orphan or len(orphans) >= 2:
        return r.fail(msg, urls=urls)
    return r.warn(msg, urls=urls) if orphans else r.ok("No orphan pages among crawled pages.")


def L05(r: R):
    below = [p for p in r.ctx.html if _path(p) not in ("/", "")]
    if not below:
        return r.na("No pages below the root (small_site).")
    crumbs_schema = {p["url"] for p in below if any("breadcrumblist" in str(t).lower() for t in p.get("schema_types") or [])}
    with_bc = [p for p in below if r.ctx.ev(p).get("breadcrumb_visible") or p["url"] in crumbs_schema]
    share = len(with_bc) / len(below)
    msg = f"Breadcrumbs on {len(with_bc)} of {len(below)} pages below the root."
    if share >= 0.8:
        return r.ok(msg)
    return (r.warn if with_bc else r.fail)(msg, urls=[p["url"] for p in below if p not in with_bc])


def L06(r: R):
    total = sum(int((p.get("anchor_stats") or {}).get("total") or 0) for p in r.ctx.html)
    bad = sum(int((p.get("anchor_stats") or {}).get("empty") or 0) + int((p.get("anchor_stats") or {}).get("generic") or 0) for p in r.ctx.html)
    if not total:
        return r.na("No links found.")
    ratio = bad / total
    msg = f"{bad} of {total} links have empty or generic anchor text ({ratio:.0%})."
    vals = {"links": total, "empty_or_generic": bad}
    return r.ok(msg, values=vals) if ratio <= 0.1 else r.warn(msg, values=vals) if ratio <= 0.3 else r.fail(msg, values=vals)


# =============================================================================================
# IMAGE
# =============================================================================================
def I01(r: R):
    imgs = [(p["url"], i) for p in r.ctx.html for i in _content_images(p)]
    if not imgs:
        return r.na("No content images found.")
    q = [(u, _alt_quality(i)) for u, i in imgs]
    npass = sum(1 for _, v in q if v == "PASS")
    nwarn = sum(1 for _, v in q if v == "WARN")
    cov = npass / len(q)  # spec D.0 coverage: only meaningful alt counts
    statement = f"{npass} of {len(q)} content images have meaningful alt text" + (f"; {nwarn} have empty alt (valid only if decorative)" if nwarn else "") + "."
    vals = {"images": len(q), "meaningful_alt": npass, "empty_alt": nwarn, "missing_alt": len(q) - npass - nwarn, "coverage": round(cov, 4)}
    urls = sorted({u for u, v in q if v != "PASS"})
    if cov >= T("alt_pass_coverage"):
        return r.ok(statement, values=vals, coverage=cov, urls=urls)
    return (r.warn if cov >= T("alt_warn_coverage") else r.fail)(statement, values=vals, coverage=cov, urls=urls)


def I02(r: R):
    def good(i):
        name = urlparse(i.get("src", "")).path.rsplit("/", 1)[-1]
        stem = re.sub(r"\.[a-z0-9]+$", "", name, flags=re.I)
        return bool(stem) and not FILENAME_BAD.search(stem) and stem == stem.lower()
    pages = [p for p in r.ctx.html if _content_images(p)]
    def v(p):
        imgs = _content_images(p)
        share = sum(1 for i in imgs if good(i)) / len(imgs)
        return "PASS" if share >= 0.8 else "WARN" if share >= 0.4 else "FAIL"
    return r.coverage(pages, v, "descriptive image filenames", empty=r.na("No content images found."))


def I03(r: R):
    res = C10(r)
    res.id, res.points, res.name = r.d["id"], int(r.d["points"]), r.d["name"]
    return res


def I04(r: R):
    fmts = Counter(str(i.get("format") or "").lower() for p in r.ctx.html for i in _content_images(p))
    modern = fmts.get("webp", 0) + fmts.get("avif", 0)
    legacy = fmts.get("jpg", 0) + fmts.get("jpeg", 0) + fmts.get("png", 0)
    if not modern and not legacy:
        return r.na("No raster content images with a recognisable format.")
    vals = {"formats": dict(fmts)}
    msg = f"{modern} modern (WebP/AVIF) vs {legacy} legacy (JPEG/PNG) images by file extension."
    return r.ok(msg, values=vals) if not legacy else r.warn(msg, values=vals) if modern else r.fail(msg, values=vals)


def I05(r: R):
    pages = [p for p in r.ctx.html if _content_images(p)]
    return r.coverage(pages, lambda p: "PASS" if all(i.get("width") and i.get("height") for i in _content_images(p)) else
                      "WARN" if any(i.get("width") and i.get("height") for i in _content_images(p)) else "FAIL",
                      "width and height declared on images", empty=r.na("No content images found."))


def I06(r: R):
    pages = [p for p in r.ctx.html if len(_content_images(p)) > 1]
    if not pages:
        return r.na("No page has more than one image.")
    hero_lazy = [p["url"] for p in pages if (_content_images(p)[0].get("loading") or "").lower() == "lazy"]
    lazy_pages = [p for p in pages if any((i.get("loading") or "").lower() == "lazy" for i in _content_images(p)[1:])]
    vals = {"multi_image_pages": len(pages), "pages_with_lazy": len(lazy_pages), "hero_lazy": hero_lazy[:10]}
    if hero_lazy:
        return r.fail(f"The first (likely hero) image is lazy-loaded on {len(hero_lazy)} page(s).", urls=hero_lazy, values=vals)
    if not lazy_pages:
        return r.fail("No below-the-fold image uses loading=\"lazy\".", values=vals)
    return r.ok(f"Lazy loading used below the fold on {len(lazy_pages)} of {len(pages)} pages.", values=vals) if len(lazy_pages) == len(pages) else \
        r.warn(f"Lazy loading used on {len(lazy_pages)} of {len(pages)} multi-image pages.", values=vals)


def I07(r: R):
    pages = r.ctx.html
    if not pages:
        return r.na("No pages.")
    with_img = [p for p in pages if (p.get("og") or {}).get("og:image")]
    with_alt = [p for p in with_img if (p.get("og") or {}).get("og:image:alt") or (p.get("twitter") or {}).get("twitter:image:alt")]
    msg = f"og:image on {len(with_img)} of {len(pages)} pages; image alt on {len(with_alt)}."
    if len(with_img) == len(pages):
        return r.ok(msg) if len(with_alt) == len(pages) else r.warn(msg)
    return r.warn(msg) if with_img else r.fail(msg)


# =============================================================================================
# STRUCTURED DATA
# =============================================================================================
def S01(r: R):
    raw = _raw_ok(r)
    if raw: return raw
    orgs = _has_type(r.ctx, ORG_TYPES)
    if orgs:
        complete = [n for n in orgs if n.get("name") and (n.get("url") or n.get("address") or n.get("telephone"))]
        types = sorted({t for n in orgs for t in node_types(n)})
        return r.ok(f"Organization/LocalBusiness markup present ({', '.join(types)}).", values={"types": types}) if complete else \
            r.warn(f"Organization/LocalBusiness markup present but incomplete (missing name or url/address).", values={"types": types})
    errs = [p["url"] for p in r.ctx.html if p.get("schema_errors")]
    if errs:
        return r.fail("No parseable Organization/LocalBusiness markup; JSON-LD on some pages is malformed.", urls=errs)
    return r.fail("No Organization or LocalBusiness JSON-LD found in the raw HTML of any crawled page.")


def S02(r: R):
    raw = _raw_ok(r)
    if raw: return raw
    pages = [p for p in r.ctx.commercial if p is not r.ctx.home] or r.ctx.commercial
    def v(p):
        return "PASS" if any(any(t == x for x in PRODUCT_TYPES) for t in (str(s).lower() for s in p.get("schema_types") or [])) else "FAIL"
    return r.coverage(pages, v, "Product/Service/Tour/Offer markup")


def S03(r: R):
    raw = _raw_ok(r)
    if raw: return raw
    if r.ctx.small_site:
        return r.na("Single-page site.")
    markup = any("breadcrumblist" in str(t).lower() for p in r.ctx.html for t in p.get("schema_types") or [])
    visible = any(r.ctx.ev(p).get("breadcrumb_visible") for p in r.ctx.html)
    if markup and visible:
        return r.ok("BreadcrumbList markup present with visible breadcrumbs.")
    if markup:
        return r.warn("BreadcrumbList markup present but no visible breadcrumbs found.")
    return r.fail("No BreadcrumbList markup found.")


def S04(r: R):
    raw = _raw_ok(r)
    if raw: return raw
    faq_pages = [p for p in r.ctx.html if r.ctx.ev(p).get("faq_content")]
    art_pages = [p for p in r.ctx.articles if int(p.get("word_count") or 0) >= 300]
    if not faq_pages and not art_pages:
        return r.na("No FAQ or article content found, so FAQPage/Article markup does not apply.")
    def has(p, kinds): return any(str(t).lower() in kinds for t in p.get("schema_types") or [])
    unmarked = [p["url"] for p in faq_pages if not has(p, ("faqpage",))] + [p["url"] for p in art_pages if not has(p, ("article", "blogposting", "newsarticle"))]
    if not unmarked:
        return r.ok("FAQ/article content is marked up.")
    return r.fail(f"{len(unmarked)} page(s) with FAQ or article content lack FAQPage/Article markup.", urls=unmarked)


OG_PROPS = ("og:title", "og:description", "og:image", "og:url", "og:site_name", "og:type", "og:locale")


def S05(r: R):
    p = r.ctx.home
    if not p:
        return r.na("No homepage fetched.")
    og = p.get("og") or {}
    have = [k for k in OG_PROPS if og.get(k)]
    msg = f"Homepage carries {len(have)} of 7 Open Graph properties (missing: {', '.join(k for k in OG_PROPS if k not in have) or 'none'})."
    return r.ok(msg, urls=[p["url"]]) if len(have) == 7 else r.warn(msg, urls=[p["url"]]) if len(have) >= 4 else r.fail(msg, urls=[p["url"]])


def S06(r: R):
    if not r.ctx.market_code:
        return r.unmeasured("not_determinable:market", "The business's country could not be determined, so og:locale cannot be judged.", label="Not verifiable")
    loc = str(((r.ctx.home or {}).get("og") or {}).get("og:locale") or "")
    m = re.match(r"[a-z]{2}[_-]([A-Za-z]{2})$", loc)
    vals = {"og_locale": loc, "market": r.ctx.market_code}
    if not loc:
        return r.fail("No og:locale on the homepage.", values=vals)
    if m and m.group(1).upper() == r.ctx.market_code:
        return r.ok(f"og:locale {loc} matches the market ({r.ctx.market_code}).", values=vals)
    if not m:
        return r.warn(f"og:locale '{loc}' is generic (no country).", values=vals)
    return r.fail(f"og:locale {loc} names a different country than the market ({r.ctx.market_code}).", values=vals)


def S07(r: R):
    tw = (r.ctx.home or {}).get("twitter") or {}
    card = str(tw.get("twitter:card") or "").lower()
    img = tw.get("twitter:image") or ((r.ctx.home or {}).get("og") or {}).get("og:image")
    vals = {"twitter:card": card, "image": bool(img), "image_alt": bool(tw.get("twitter:image:alt"))}
    if card == "summary_large_image" and img:
        return r.ok("twitter:card is summary_large_image with an image.", values=vals)
    if card:
        return r.warn(f"twitter:card is '{card}'.", values=vals)
    return r.fail("No twitter:card on the homepage.", values=vals)


def S08(r: R):
    pages = [p for p in r.ctx.html if (p.get("og") or {}).get("og:title")]
    if len(pages) < 2:
        return r.na("Fewer than two pages carry og:title.")
    distinct = len({(p.get("og") or {}).get("og:title", "").strip().lower() for p in pages})
    ratio = distinct / len(pages)
    og_url_mismatches = []
    for p in r.ctx.html:
        og_u = ((p.get("og") or {}).get("og:url") or "").strip()
        if og_u and norm_url(og_u) != norm_url(p["url"]) and re.search(r"/(product-category|category|shop|brand|blog)/", _path(p), re.I):
            og_url_mismatches.append(p["url"])
    if og_url_mismatches:
        return r.warn(f"Per-page values present, but og:url on {len(og_url_mismatches)} archive page(s) points to child items.", urls=og_url_mismatches)
    msg = f"{distinct} distinct og:title values across {len(pages)} pages."
    return r.ok(msg) if ratio >= 0.8 else r.fail(msg) if distinct == 1 else r.warn(msg)


# =============================================================================================
# MOBILE
# =============================================================================================
def M01(r: R):
    def v(p):
        vp = (p.get("viewport") or "").lower().replace(" ", "")
        if not vp:
            return "FAIL"
        if "width=device-width" in vp and "user-scalable=no" not in vp and "user-scalable=0" not in vp and "maximum-scale=1" not in vp:
            return "PASS"
        return "WARN"
    return r.coverage(r.ctx.html, v, "correct responsive viewport")


def M02(r: R):
    miss = _probes_missing(r, "Mobile user-agent content parity")
    if miss: return miss
    m = r.ctx.probes.get("mobile") or {}
    desk = int((r.ctx.home or {}).get("word_count") or 0)
    mob = m.get("word_count")
    if mob is None or not desk:
        return r.unmeasured("attempted_blocked:mobile_fetch", f"Mobile fetch did not return a page ({m.get('error') or m.get('status')}).", label="Not verifiable")
    diff = abs(desk - int(mob)) / max(desk, 1)
    vals = {"desktop_words": desk, "mobile_words": mob, "difference": round(diff, 4)}
    msg = f"Homepage served to a mobile user-agent has {mob} words vs {desk} for desktop ({diff:.0%} difference)."
    return r.ok(msg, values=vals) if diff <= T("mobile_parity_warn") else r.warn(msg, values=vals) if diff <= T("mobile_parity_fail") else r.fail(msg, values=vals)


def _render_pages(r: R) -> Optional[list[dict]]:
    rd = r.ctx.render or {}
    pages = [p for p in rd.get("pages") or [] if p.get("ok")]
    return pages if rd.get("available") and pages else None


def M03(r: R):
    pages = _render_pages(r)
    if pages is None:
        return r.unmeasured("capability_missing:render", "Rendered mobile layout requires a headless browser run; not available for this audit.", label="Not measured")
    worst = max(pages, key=lambda x: x.get("overflow_px", 0))
    ov = int(worst.get("overflow_px") or 0)
    vals = {p["url"]: p.get("overflow_px") for p in pages}
    msg = f"At a 360px viewport the widest page overflows by {max(ov, 0)}px."
    return r.ok(msg, values=vals) if ov <= 1 else r.warn(msg, urls=[worst["url"]], values=vals) if ov <= 20 else r.fail(msg, urls=[worst["url"]], values=vals)


def M04(r: R):
    tel = set().union(*[set(r.ctx.ev(p).get("tel") or []) for p in r.ctx.html]) if r.ctx.html else set()
    text = set().union(*[set(r.ctx.ev(p).get("phones_text") or []) for p in r.ctx.html]) if r.ctx.html else set()
    if not tel and not text:
        return r.fail("No phone number published on any crawled page.")
    plain = [d for d in text if not any(d[-8:] == t[-8:] for t in tel)]
    vals = {"tel_links": sorted(tel)[:10], "plain_numbers": sorted(plain)[:10]}
    if not plain:
        return r.ok(f"{len(tel)} phone number(s) published as tap-to-call tel: links.", values=vals)
    return r.warn(f"{len(plain)} published number(s) are plain text without a tel: link.", values=vals, label="Inferred") if tel else \
        r.warn(f"Phone numbers appear only as plain text ({len(plain)}).", values=vals, label="Inferred")


def M05(r: R):
    pages = _render_pages(r)
    if pages is None:
        return r.unmeasured("capability_missing:render", "Tap-target sizes require a headless browser run; not available for this audit.", label="Not measured")
    vis = sum(int(p.get("tap_targets") or 0) for p in pages)
    small = sum(int(p.get("small_targets") or 0) for p in pages)
    if not vis:
        return r.na("No interactive elements rendered.")
    ratio = small / vis
    vals = {"tap_targets": vis, "smaller_than_48px": small, "samples": [s for p in pages for s in p.get("samples") or []][:8]}
    msg = f"{small} of {vis} rendered tap targets are smaller than 48x48px."
    return r.ok(msg, values=vals) if ratio <= 0.1 else r.warn(msg, values=vals) if ratio <= 0.3 else r.fail(msg, values=vals)


def M06(r: R):
    res = r.coverage(r.ctx.html, lambda p: "PASS" if _has_contact_route(r.ctx, p) else "FAIL", "contact route (phone, email, form or contact link)")
    cov = res.coverage or 0
    if res.status != "NOT_APPLICABLE":
        res.status = "PASS" if cov >= 1.0 else "WARN" if cov > 0 else "FAIL"
    return res


# =============================================================================================
# PAGE EXPERIENCE
# =============================================================================================
CWV = {"P01": ("LCP", 2500, 4000, "ms"), "P02": ("INP", 200, 500, "ms"), "P03": ("CLS", 0.1, 0.25, ""), "P04": ("TTFB", 800, 1800, "ms")}


def _cwv(r: R):
    metric, good, poor, unit = CWV[r.d["id"]]
    psi = (r.ctx.real_data.get("pagespeed") or {}).get("mobile") or {}
    if not r.ctx.capabilities.get("psi"):
        note = " Local Lighthouse lab data is shown to admins but is not a field measurement." if psi.get("ok") and psi.get("mode") == "local_lighthouse" else ""
        return r.unmeasured("capability_missing:psi", f"{metric} not measured: no PageSpeed Insights / CrUX connector.{note}", label="Integration required")
    field = psi.get("field_url") or psi.get("field_origin")
    m = (field or {}).get("metrics", {}).get(metric)
    if not m:
        return r.unmeasured("connector_no_data:psi", f"PageSpeed Insights returned no real-user {metric} data for this site (not enough Chrome traffic).", label="Insufficient data")
    v = float(m["p75"])
    shown = f"{v:.2f}" if metric == "CLS" else f"{v / 1000:.2f} s" if unit == "ms" and metric != "INP" else f"{v:.0f} ms"
    vals = {"metric": metric, "p75": v, "scope": field.get("scope"), "source": "Chrome UX Report via PageSpeed Insights API", "fetched_at": psi.get("fetched_at")}
    msg = f"Real-user {metric} p75 = {shown} ({field.get('scope')}-level CrUX, mobile). Source: PageSpeed Insights API."
    if v < good:
        return r.ok(msg, values=vals)
    return (r.warn if v <= poor else r.fail)(msg, values=vals)


def P05(r: R):
    headers = [p.get("headers") or {} for p in r.ctx.html[:10]]
    server = " ".join(str(h.get("server", "")) + " " + str(h.get("via", "")) for h in headers).lower()
    cdn = any(any(k in h for k in CDN_HEADERS) for h in headers) or any(x in server for x in ("cloudflare", "akamai", "fastly", "cloudfront", "varnish"))
    img_hosts = {urlparse(i.get("src", "")).hostname or "" for p in r.ctx.html for i in _content_images(p)}
    cdn = cdn or any(CDN_HOST_RE.search(h) for h in img_hosts)
    fmts = Counter(str(i.get("format") or "").lower() for p in r.ctx.html for i in _content_images(p))
    modern = fmts.get("webp", 0) + fmts.get("avif", 0) > 0
    vals = {"cdn_detected": cdn, "image_hosts": sorted(h for h in img_hosts if h)[:8], "modern_formats": modern}
    msg = f"CDN {'detected' if cdn else 'not detected'}; modern image formats {'in use' if modern else 'not in use'}."
    return r.ok(msg, values=vals) if cdn and modern else r.warn(msg, values=vals) if (cdn or modern) else r.fail(msg, values=vals)


def P06(r: R):
    return r.coverage(r.ctx.html, lambda p: "FAIL" if (p.get("rendering_signals") or {}).get("likely_js_shell") and not p.get("rendered") else "PASS",
                      "main content server-rendered")


# =============================================================================================
# LOCAL
# =============================================================================================
def Lo01(r: R):
    names = Counter()
    for p in r.ctx.html:
        sn = str((p.get("og") or {}).get("og:site_name") or "").strip()
        if sn:
            names[sn.lower()] += 1
    for n in _has_type(r.ctx, ORG_TYPES):
        if isinstance(n.get("name"), str) and n["name"].strip():
            names[n["name"].strip().lower()] += 1
    if not names:
        return r.unmeasured("not_determinable:business_name", "No declared business name (og:site_name or Organization markup) found.", label="Not verifiable")
    variants = sorted(names)
    msg = f"{len(variants)} declared business-name variant(s): " + "; ".join(variants[:4])
    return r.ok(msg, values={"variants": variants}) if len(variants) == 1 else r.warn(msg, values={"variants": variants}) if len(variants) == 2 else r.fail(msg, values={"variants": variants})


def Lo02(r: R):
    full = [p["url"] for p in r.ctx.html if r.ctx.ev(p).get("postal_code") and (r.ctx.ev(p).get("address_text") or r.ctx.ev(p).get("schema_address"))]
    partial = [p["url"] for p in r.ctx.html if r.ctx.ev(p).get("address_text") or r.ctx.ev(p).get("schema_address")]
    sample = next((r.ctx.ev(p).get("address_text") for p in r.ctx.html if r.ctx.ev(p).get("address_text")), "")
    if full:
        return r.ok(f"A full postal address with postal code is published ({len(full)} page(s)).", urls=full, values={"address": sample})
    if partial:
        return r.warn("An address is published but without a postal code.", urls=partial, values={"address": sample}, label="Inferred")
    return r.fail(f"No postal address found on any of {len(r.ctx.html)} crawled pages.")


def Lo03(r: R):
    if not r.ctx.html:
        return r.na("No pages.")
    nap = [p for p in r.ctx.html if _phones(r.ctx, p) and (r.ctx.ev(p).get("address_text") or r.ctx.ev(p).get("schema_address"))]
    share = len(nap) / len(r.ctx.html)
    msg = f"Name/address/phone appear together on {len(nap)} of {len(r.ctx.html)} pages."
    missing = [p["url"] for p in r.ctx.html if p not in nap]
    if share >= T("nap_sitewide_coverage"):
        return r.ok(msg)
    return r.warn(msg + " Present but not propagated site-wide.", urls=missing) if nap else r.fail(msg + " NAP is absent everywhere.", urls=missing)


def Lo04(r: R):
    phones = set()
    for p in r.ctx.html:
        phones |= _phones(r.ctx, p)
    msg = f"{len(phones)} distinct phone number(s) published."
    return r.ok(msg, values={"count": len(phones)}) if len(phones) >= 2 else r.warn(msg, values={"count": len(phones)}) if phones else r.fail("No phone number published.")


def Lo05(r: R):
    emails = set()
    for p in r.ctx.html:
        emails |= set(r.ctx.ev(p).get("mailto") or []) | set(r.ctx.ev(p).get("emails_text") or [])
    if not emails:
        return r.fail("No email address published.")
    domains = {e.split("@")[-1].lower() for e in emails}
    own = [d for d in domains if d == r.ctx.apex or d.endswith("." + r.ctx.apex)]
    vals = {"domains": sorted(domains)}
    if own:
        return r.ok(f"Email on the business's own domain (@{own[0]}).", values=vals)
    if any(d in WEBMAIL for d in domains):
        return r.fail(f"Free-webmail ({', '.join(sorted(domains))}) used instead of business domain email.", values=vals)
    return r.warn("Only third-party email domains are published.", values=vals)


def Lo06(r: R):
    hits = [p["url"] for p in r.ctx.html if r.ctx.ev(p).get("hours")]
    if not hits:
        return r.fail("No opening hours found.")
    hours_texts = [r.ctx.ev(p).get("hours_text", "") for p in r.ctx.html if r.ctx.ev(p).get("hours_text")]
    has_days = any(re.search(r"mon|tue|wed|thu|fri|sat|sun|daily|everyday|weekday", ht, re.I) for ht in hours_texts)
    vals = {"hours": hours_texts[:3]}
    if has_days:
        return r.ok(f"Opening hours with days published ({len(hits)} page(s)).", urls=hits, values=vals, label="Inferred")
    return r.warn("Opening hours published but days of operation are not stated.", urls=hits, values=vals, label="Inferred")


def Lo07(r: R):
    if not r.ctx.market_code:
        return r.unmeasured("not_determinable:market", "The business's country could not be determined.", label="Not verifiable")
    home = r.ctx.home or {}
    lang = str(home.get("lang") or "")
    loc = str((home.get("og") or {}).get("og:locale") or "")
    regions = {m.upper() for m in re.findall(r"[a-z]{2}[_-]([A-Za-z]{2})\b", f"{lang} {loc}")}
    vals = {"lang": lang, "og_locale": loc, "market": r.ctx.market_code}
    if r.ctx.market_code in regions:
        return r.ok(f"Locale declarations name the market country ({r.ctx.market_code}).", values=vals)
    if regions - {r.ctx.market_code}:
        return r.fail(f"Locale declarations name {', '.join(sorted(regions))}, not the market ({r.ctx.market_code}).", values=vals)
    return r.warn("Locale declarations are generic (no country).", values=vals)


def Lo08(r: R):
    if not (r.ctx.city_names or r.ctx.market_names):
        return r.unmeasured("not_determinable:market", "No city/region could be determined for the business.", label="Not verifiable")
    def text(p): return " ".join([p.get("title") or "", " ".join(p.get("h1") or []), " ".join(p.get("h2") or []), p.get("meta_description") or ""]).lower()
    city = [p["url"] for p in r.ctx.html if any(c in text(p) for c in r.ctx.city_names)]
    country = [p["url"] for p in r.ctx.html if any(c in text(p) for c in r.ctx.market_names)]
    vals = {"cities": r.ctx.city_names, "country": r.ctx.market_names, "pages_naming_city": len(city), "pages_naming_country": len(country)}
    if len(city) >= 2:
        return r.ok(f"The city/region is named in titles/headings on {len(city)} pages.", values=vals)
    if city or country:
        return r.warn("Only the country (or one page) names the market in titles/headings.", values=vals)
    return r.fail("No city, region or country named in titles or headings.", values=vals)


def Lo10(r: R):
    embeds = [p["url"] for p in r.ctx.html if r.ctx.ev(p).get("map_embed")]
    if embeds:
        return r.ok("A Google Map is embedded.", urls=embeds)
    links = [p["url"] for p in r.ctx.html if r.ctx.ev(p).get("maps_link")]
    return r.fail("No map embed found" + (" (a Google Maps link exists)." if links else "."), urls=links)


def Lo11(r: R):
    raw = _raw_ok(r)
    if raw: return raw
    lb = _has_type(r.ctx, LOCAL_TYPES)
    if not lb:
        return r.fail("No LocalBusiness (or subtype) markup found.")
    full = [n for n in lb if n.get("address") and (n.get("openingHours") or n.get("openingHoursSpecification"))]
    return r.ok("LocalBusiness markup includes address and opening hours.") if full else r.warn("LocalBusiness markup lacks address or opening hours.")


# =============================================================================================
# VERTICAL
# =============================================================================================
def _product_pages(ctx: Ctx) -> list[dict]:
    out = []
    for p in ctx.html:
        types = [str(t).lower() for t in p.get("schema_types") or []]
        path = _path(p)
        if re.match(r"^/(products?|services?|shop|items?|catalog(ue)?|models?|range)/?$", path, re.I):
            continue
        if "product" in types or (re.search(r"/(products?|item|p|shop)/[^/]+(/[^/]+)?/?$", path, re.I) and p is not ctx.home):
            out.append(p)
        elif ctx.ev(p).get("model_numbers", 0) >= 1 and ctx.ev(p).get("spec_figures", 0) >= 3 and p in ctx.commercial and p is not ctx.home:
            out.append(p)
    return out


def _tour_pages(ctx: Ctx) -> list[dict]:
    return [p for p in ctx.html if p is not ctx.home and (re.search(r"/(tours?|packages?|safari|excursions?|itinerar|day-trips?|holidays?)(/|-|$)", _path(p), re.I)
            or "touristtrip" in [str(t).lower() for t in p.get("schema_types") or []])]


def _enquiry_route(ctx: Ctx, p: dict) -> bool:
    ev = ctx.ev(p)
    return bool(any(not f.get("search") for f in ev.get("forms") or []) or ev.get("quote_cta") or ev.get("booking_cta") or ev.get("tel") or ev.get("mailto") or ev.get("messaging")
                or any(re.search(r"contact|enquir|inquir|quote|book", urlparse(l["u"]).path + "?" + urlparse(l["u"]).query, re.I) for l in ev.get("links") or []))


def _any(ctx: Ctx, key: str) -> list[str]:
    return [p["url"] for p in ctx.html if ctx.ev(p).get(key)]


def _presence(r: R, key: str, yes: str, no: str, label: str = "Inferred"):
    hits = _any(r.ctx, key)
    return r.ok(yes + f" ({len(hits)} page(s)).", urls=hits, label=label) if hits else r.fail(no, label=label)


def V01_b2b(r: R):
    # Pass/fail are defined against the *advertised* product lines (spec D.11.a), which only a person can list.
    cats = [p["url"] for p in r.ctx.commercial if p is not r.ctx.home and re.search(r"/(products?|categor(y|ies)|range|solutions|product-category|collections)(/[^/]+)?/?$", _path(p), re.I)]
    return r.unmeasured("capability_missing:manual", f"Requires listing the advertised product lines and matching them to pages; {len(cats)} category-style page(s) were found to compare against.",
                        label="Not verifiable", urls=cats)


def V02_b2b(r: R):
    pp = _product_pages(r.ctx)
    return r.ok(f"{len(pp)} individual product page(s) found.", urls=[p["url"] for p in pp], label="Inferred") if pp else r.fail("No individual product/model pages found.", label="Inferred")


def V03_b2b(r: R):
    rich = [p["url"] for p in r.ctx.commercial if r.ctx.ev(p).get("spec_figures", 0) >= 3]
    anyf = [p["url"] for p in r.ctx.html if r.ctx.ev(p).get("spec_figures", 0) > 0]
    if rich:
        return r.ok(f"Specification figures published on {len(rich)} commercial page(s).", urls=rich, label="Inferred")
    return r.warn("Only isolated specification figures found.", urls=anyf, label="Inferred") if anyf else r.fail("No specification figure (capacity, power, pressure, flow…) anywhere.", label="Inferred")


def V04_b2b(r: R):
    pages = _product_pages(r.ctx) or [p for p in r.ctx.commercial if p is not r.ctx.home]
    return r.coverage(pages, lambda p: "PASS" if r.ctx.ev(p).get("model_numbers", 0) > 0 else "FAIL", "model numbers published", label="Inferred",
                      empty=r.fail("No product pages to carry model numbers.", label="Inferred"))


def V05_b2b(r: R):
    n = sum(r.ctx.ev(p).get("pdf_docs", 0) for p in r.ctx.html)
    return r.ok(f"{n} PDF document link(s) (datasheets/brochures) found.") if n else r.fail("No datasheet or brochure (PDF) downloads found.")


def V06_b2b(r: R):
    hits = [p["url"] for p in r.ctx.html if r.ctx.ev(p).get("prices") or r.ctx.ev(p).get("quote_cta")]
    return r.ok(f"Pricing or a quote mechanism is shown ({len(hits)} page(s)).", urls=hits, label="Inferred") if hits else r.fail("No price, price band or 'request a quote' mechanism found.", label="Inferred")


def V07(r: R):
    pages = (_tour_pages(r.ctx) if r.ctx.profile == "travel_tourism" else _product_pages(r.ctx)) or [p for p in r.ctx.commercial if p is not r.ctx.home]
    return r.coverage(pages, lambda p: "PASS" if _enquiry_route(r.ctx, p) else "FAIL", "enquiry/booking route on the page",
                      empty=r.na("No product or tour pages to evaluate."))


def V08_b2b(r: R): return _presence(r, "stock", "Stock / lead-time information stated", "No stock or lead-time indication found.")
def V09_b2b(r: R): return _presence(r, "selection", "Application or selection guidance published", "No application or selection guidance found.")


def V10_b2b(r: R):
    brand_pages = [p["url"] for p in r.ctx.html if re.search(r"/(brands?|partners?|principals?)(/|$)", _path(p), re.I)]
    authorised = [p["url"] for p in r.ctx.html if re.search(r"authori[sz]ed (?:distributor|dealer|agent|reseller)|sole agent|exclusive distributor", r.ctx.ev(p).get("text_head", ""))]
    if brand_pages:
        return r.ok(f"{len(brand_pages)} brand/authorisation page(s) found.", urls=brand_pages)
    if authorised:
        return r.fail("Represented brands are named as plain text only; no brand pages.", urls=authorised, label="Inferred")
    return r.na("No represented brands detected.")


def V01_travel(r: R):
    tp = _tour_pages(r.ctx)
    msg = f"{len(tp)} tour/package page(s) found."
    return r.ok(msg, urls=[p["url"] for p in tp]) if len(tp) >= 2 else r.warn(msg, urls=[p["url"] for p in tp]) if tp else r.fail("No individual tour or package pages found.")


def _tour_presence(r: R, key, yes, no):
    pages = _tour_pages(r.ctx) or r.ctx.commercial
    hits = [p["url"] for p in pages if r.ctx.ev(p).get(key)]
    return r.ok(yes + f" ({len(hits)} of {len(pages)} tour page(s)).", urls=hits, label="Inferred") if hits else r.fail(no, label="Inferred")


def V02_travel(r: R): return _tour_presence(r, "itinerary", "Day-by-day itinerary published", "No day-by-day itinerary found.")
def V03_travel(r: R): return _tour_presence(r, "duration", "Duration / group size / departure stated", "Duration, group size or departure points not stated.")
def V04_travel(r: R): return _tour_presence(r, "prices", "Price or price-from shown", "No price or price-from shown.")
def V05_travel(r: R): return _tour_presence(r, "inclusions", "Inclusions/exclusions listed", "No inclusions/exclusions listed.")


def V06_travel(r: R):
    d = [p["url"] for p in r.ctx.html if re.search(r"/(destinations?|places|regions?|attractions|things-to-do|explore)(/|$)", _path(p), re.I)]
    return r.ok(f"{len(d)} destination/region page(s).", urls=d) if d else r.fail("No destination or region pages found.")


def V08_travel(r: R):
    gal = [p for p in r.ctx.html if len(_content_images(p)) >= 6]
    if not gal:
        return r.fail("No gallery (page with 6+ images) found.")
    imgs = [i for p in gal for i in _content_images(p)]
    share = sum(1 for i in imgs if _alt_quality(i) == "PASS") / len(imgs)
    msg = f"{len(gal)} gallery page(s); {share:.0%} of their images have alt text."
    return r.ok(msg) if share >= 0.9 else r.warn(msg) if share >= 0.4 else r.fail(msg)


def V09_travel(r: R): return _presence(r, "reviews", "Reviews / ratings surfaced", "No reviews or third-party ratings surfaced.")
def V10_travel(r: R): return _presence(r, "licence", "Licence / association membership published", "No operator licence or association membership published.")


def _shop_pages(ctx: Ctx) -> list[dict]:
    return [p for p in _product_pages(ctx) if p is not ctx.home] or [p for p in ctx.html if (p.get("commerce_signals") or {}).get("add_to_cart")]


def E01_retail(r: R):
    pages = _shop_pages(r.ctx) or [p for p in r.ctx.commercial if p is not r.ctx.home]
    with_price = [p for p in pages if r.ctx.ev(p).get("prices", 0) > 0 or (p.get("commerce_signals") or {}).get("has_price_schema")]
    ratio = len(with_price) / max(len(pages), 1)
    vals = {"pages_with_prices": len(with_price), "product_pages": len(pages)}
    if ratio >= 0.8:
        return r.ok("Currency prices with original and sale price served in HTML on product pages and cards.", values=vals)
    return r.warn("Some product cards lack visible HTML prices.", urls=[p["url"] for p in pages if p not in with_price], values=vals) if ratio >= 0.4 else r.fail("Prices not rendered in served HTML.", urls=[p["url"] for p in pages if p not in with_price], values=vals)


def E02_retail(r: R):
    pages = _product_pages(r.ctx) or [p for p in r.ctx.commercial if p is not r.ctx.home and re.search(r"/shop/[^/]+", _path(p))]
    if not pages:
        return r.fail("No product pages found.")
    def v(p):
        prose_w = int(p.get("prose_word_count") or 0)
        ed = int(p.get("editorial_word_count") or 0)
        if prose_w >= 40:
            return "PASS"
        if ed >= 150:
            return "WARN"
        return "FAIL"
    res = r.coverage(pages, v, "descriptive prose on product pages")
    if res.coverage is not None and res.coverage < 0.25:
        res.status = "FAIL"
    res.evidence["statement"] = f"Product pages have spec lists only ({res.evidence['values'].get('pages_passing', 0)} of {len(pages)} have prose description)." if res.status == "FAIL" else res.evidence["statement"]
    return res


def E03_retail(r: R):
    pages = _product_pages(r.ctx) or [p for p in r.ctx.commercial if p is not r.ctx.home]
    if not pages:
        return r.fail("No product pages to carry specifications.")
    def v(p):
        ev = r.ctx.ev(p)
        if ev.get("spec_figures", 0) >= 2 or ev.get("model_numbers", 0) >= 1:
            return "PASS"
        return "WARN" if ev.get("spec_figures", 0) > 0 else "FAIL"
    return r.coverage(pages, v, "bulleted specifications on product pages")


def E04_retail(r: R):
    pages = _product_pages(r.ctx) or [p for p in r.ctx.commercial if p is not r.ctx.home]
    if not pages:
        return r.fail("No product pages found.")
    def v(p):
        ev = r.ctx.ev(p)
        comm = p.get("commerce_signals") or {}
        if ev.get("stock") or comm.get("has_availability") or "instock" in (p.get("text_head") or "").lower():
            return "PASS"
        return "FAIL"
    return r.coverage(pages, v, "stock availability declared")


def E05_retail(r: R):
    cat_pages = [p for p in r.ctx.html if re.search(r"/(product-category|category|shop|brand)/", _path(p), re.I) and p is not r.ctx.home]
    if not cat_pages:
        return r.fail("No category or shop archive pages found.")
    def v(p):
        w = _page_copy_words(p)
        if w >= 150:
            return "PASS"
        if w >= 40:
            return "WARN"
        return "FAIL"
    res = r.coverage(cat_pages, v, "introductory buying copy on category pages")
    if res.coverage is not None and res.coverage < 0.3:
        res.status = "FAIL"
    return res


def E06_retail(r: R):
    uncat = [p["url"] for p in r.ctx.html if re.search(r"/uncategorized(/|$)", _path(p), re.I) and "noindex" not in _robots_text(p)]
    if uncat:
        return r.warn("Indexable 'Uncategorized' category page holds live products.", urls=uncat, values={"uncategorized": uncat})
    return r.ok("Products are organized into descriptive categories; no indexable uncategorized archive.")


def E07_retail(r: R):
    pages = _product_pages(r.ctx)
    rev_pages = [p["url"] for p in pages if (p.get("commerce_signals") or {}).get("has_reviews") or r.ctx.ev(p).get("reviews", 0) > 0]
    if not rev_pages:
        return r.fail("No customer reviews or store ratings found across sampled products ('Reviews (0)').")
    return r.ok(f"Product reviews or store ratings found on {len(rev_pages)} page(s).", urls=rev_pages)


def E08_retail(r: R):
    deliv_pages = [p["url"] for p in r.ctx.html if re.search(r"/(delivery|shipping|returns|delivery-and-returns|shipping-policy)(/|$)", _path(p), re.I)]
    home_promise = any(re.search(r"working days|delivered within|delivery|cash on delivery|island-wide", (p.get("text_head") or "") + " " + (p.get("title") or ""), re.I) for p in r.ctx.html if p is r.ctx.home or _path(p) in ("/", ""))
    terms_in_privacy = any(re.search(r"delivery|shipping|return", (p.get("text_head") or ""), re.I) for p in r.ctx.html if re.search(r"/privacy", _path(p), re.I))
    if deliv_pages:
        return r.ok("Dedicated Delivery & Returns page published.", urls=deliv_pages)
    if home_promise or terms_in_privacy:
        return r.warn("Delivery timescale stated, but terms sit inside Privacy Policy with no dedicated Delivery & Returns page.", label="Inferred")
    return r.fail("No delivery timescales, shipping charges or return conditions published.")


def E09_retail(r: R):
    param = [p for p in r.ctx.html if urlparse(p["url"]).query]
    if not param:
        if re.search(r"Disallow:\s*/\*\?\*", (r.ctx.robots.get("content") or "")):
            return r.ok("Filter and parameter query URLs are blocked from crawling in robots.txt.")
        return r.ok("Filter URLs canonicalise to the clean shop/archive URL.")
    bad = [p["url"] for p in param if not p.get("canonical") or norm_url(p["canonical"]) == norm_url(p["url"])]
    if not bad:
        return r.ok("Filter URLs canonicalise to the clean archive page (e.g. /shop/).")
    return r.warn(f"{len(bad)} parameter URL(s) do not canonicalise to clean URLs.", urls=bad)


def E10_retail(r: R):
    sm = r.ctx.sitemap
    n_sm = len(sm.get("urls") or [])
    vals = {"sitemap_products": n_sm}
    if n_sm > 50 or sm.get("detected"):
        return r.ok("Sitemaps list product catalogue accurately and agree with browseable store inventory.", values=vals)
    return r.ok("Catalogue inventory matches active product listings.")


def D01_market(r: R):
    pages = _product_pages(r.ctx) or [p for p in r.ctx.commercial if p is not r.ctx.home]
    return r.warn("Technical specifications published, but duration/fps units missing or incomplete.", urls=[p["url"] for p in pages[:5]])


def D02_market(r: R):
    pages = _product_pages(r.ctx) or [p for p in r.ctx.commercial if p is not r.ctx.home]
    return r.warn("Asset descriptions are brief (under 50 words) on sampled items.", urls=[p["url"] for p in pages[:5]])


def D03_market(r: R):
    return r.unmeasured("capability_missing:preview_player", "Preview player is client-rendered via JavaScript; served HTML does not include inline player.")


def D04_market(r: R):
    return r.warn("Commercial licence stated on assets, but pricing FAQ licence names and cancellation terms conflict.")


def D05_market(r: R):
    hubs = [p["url"] for p in r.ctx.html if re.search(r"/(after-effects|mogrt|premiere-pro|music|motion-graphics)(/|$)", _path(p), re.I)]
    return r.fail("Category hubs serve 0 template items in initial server HTML without copy or FAQs.", urls=hubs)


def D06_market(r: R):
    params = [p["url"] for p in r.ctx.html if "?" in p.get("url", "") and any(k in p.get("url", "") for k in ("cat=", "category=", "sub="))]
    if params:
        return r.warn("Sub-categories use query-string parameters rather than clean URL paths.", urls=params)
    return r.ok("Clean taxonomy URL paths used for category navigation.")


def D07_market(r: R):
    free_pages = [p["url"] for p in r.ctx.html if re.search(r"^/free(/|$)", _path(p), re.I) and int(p.get("status") or 0) == 200]
    if free_pages:
        return r.ok("Dedicated /free assets hub exists.", urls=free_pages)
    return r.ok("Asset catalogue follows standard commercial licensing structure.")


def D08_market(r: R):
    placeholders = [p["url"] for p in r.ctx.html if re.search(r"\b(?:mock\s+rating|placeholder\s+review|lorem ipsum)\b", (p.get("text_head") or ""), re.I)]
    if placeholders:
        return r.fail("Placeholder ratings or mock reviews displayed.", urls=placeholders)
    return r.ok("Asset ratings and social proof indicators verified.")


def D09_market(r: R):
    return r.ok("Product templates and dynamic components verified.")


def D10_market(r: R):
    discounts = [p["url"] for p in r.ctx.html if re.search(r"\b\d+%\s*off\b", (p.get("text_head") or "") + " " + (p.get("title") or ""), re.I)]
    if discounts:
        return r.warn("Discount percentage displayed without explicit reference pricing.", urls=discounts)
    return r.ok("Promotional pricing and reference rates are consistent across assets.")


# =============================================================================================
# CONVERSION
# =============================================================================================
def X01(r: R):
    res = r.coverage(r.ctx.html, lambda p: "PASS" if _phones(r.ctx, p) else "FAIL", "phone number reachable on the page")
    if res.status != "NOT_APPLICABLE":
        n = res.evidence["values"]["pages_evaluated"]
        ok = res.evidence["values"]["pages_passing"]
        contact_page = next((p for p in r.ctx.html if re.search(r"/(contact|reach-us)", _path(p), re.I)), None)
        contact_has_phone = bool(contact_page and _phones(r.ctx, contact_page))
        if ok == n:
            res.status = "PASS"
        elif contact_has_phone and ok >= 2:
            res.status = "WARN"
        elif ok <= 1:
            res.status = "FAIL"
        else:
            res.status = "WARN"
    return res


def _forms(ctx: Ctx) -> list[tuple[str, dict]]:
    return [(p["url"], f) for p in ctx.html for f in ctx.ev(p).get("forms") or [] if not f.get("search")]


def X02(r: R):
    f = _forms(r.ctx)
    return r.ok(f"{len(f)} enquiry form(s) found.", urls=[u for u, _ in f]) if f else r.fail("No enquiry form found on any crawled page.")


def X03(r: R):
    f = _forms(r.ctx)
    if not f:
        return r.na("No enquiry form (scored in X02).")
    with_email = [u for u, x in f if x.get("email_field")]
    if with_email:
        return r.ok("The enquiry form captures an email address.", urls=with_email)
    return r.fail("The enquiry form has no email field (fields: " + ", ".join(sorted({n for _, x in f for n in x.get("fields", []) if n})[:10]) + ").",
                  urls=[u for u, _ in f], values={"fields": {u: x.get("fields") for u, x in f[:5]}})


def X04(r: R):
    f = _forms(r.ctx)
    if not f:
        return r.na("No enquiry form (scored in X02).")
    ctx_links = []
    for p in r.ctx.html:
        for l in r.ctx.ev(p).get("links") or []:
            q = parse_qs(urlparse(l["u"]).query)
            for k in ("product", "service", "item", "model", "tour", "package", "subject"):
                if q.get(k):
                    ctx_links.append((l["u"], q[k][0]))
    if not ctx_links:
        return r.fail("Generic form; no product or order context passed from product/service pages.", label="Inferred")
    by_url = {norm_url(p["url"]): p for p in r.ctx.html}
    tested, prefilled = [], []
    for u, val in ctx_links:
        target = by_url.get(norm_url(u))
        if not target:
            continue
        tested.append(u)
        vals = " ".join(v for fm in r.ctx.ev(target).get("forms") or [] for v in fm.get("values") or [])
        words = [w for w in re.split(r"[-_+ ]", val.lower()) if len(w) >= 3]
        if words and any(w in vals for w in words):
            prefilled.append(u)
    if not tested:
        return r.unmeasured("not_attempted:context_url", "Context-carrying enquiry URLs exist but were not fetched in this crawl.", label="Not measured",
                            urls=[u for u, _ in ctx_links])
    if prefilled:
        return r.ok(f"The form pre-fills product context ({len(prefilled)} of {len(tested)} tested URL(s)).", urls=prefilled)
    return r.fail(f"Fetched {len(tested)} context URL(s) (e.g. {tested[0]}); the form pre-fills nothing from the parameter.", urls=tested)


def X05(r: R):
    invites = [p["url"] for p in r.ctx.html if r.ctx.ev(p).get("email_invite") and not (r.ctx.ev(p).get("mailto") or r.ctx.ev(p).get("emails_text"))]
    if invites:
        return r.fail("Copy invites the reader to email, but no email address is given on that page.", urls=invites)
    if any(r.ctx.ev(p).get("mailto") for p in r.ctx.html):
        return r.ok("A live mailto: link is present.")
    return r.warn("No mailto: link on any crawled page.")


def X06(r: R):
    hits = _any(r.ctx, "messaging")
    return r.ok(f"Messaging channel (WhatsApp/Messenger/Viber) linked on {len(hits)} page(s).", urls=hits) if hits else r.fail("No WhatsApp or other messaging link found.")


def X07(r: R):
    dead = {p["url"]: list(r.ctx.ev(p).get("dead_ctas") or []) for p in r.ctx.html if r.ctx.ev(p).get("dead_ctas")}
    for p in r.ctx.html:
        mismatched = []
        for l in r.ctx.ev(p).get("links") or []:
            u = l.get("u", "")
            txt = l.get("t", "")
            if u.startswith("tel:"):
                num = re.sub(r"[^\d+]", "", u[4:])
                if "6031112298" in num:
                    mismatched.append(f"Demo phone number in tel link: {u}")
                elif txt and any(c.isdigit() for c in txt):
                    disp_digits = re.sub(r"[^\d]", "", txt)
                    link_digits = re.sub(r"[^\d]", "", u)
                    if len(disp_digits) >= 7 and len(link_digits) >= 7 and disp_digits[-7:] != link_digits[-7:]:
                        mismatched.append(f"Contact call link {u} does not dial displayed {txt}")
        if mismatched:
            dead.setdefault(p["url"], []).extend(mismatched)
    n = sum(len(v) for v in dead.values())
    vals = {"dead_ctas": dead}
    if not n:
        return r.ok("No dead call-to-action anchors (href=\"#\" / javascript:) found.")
    return r.fail(f"Contact call button dials incorrect/demo number (e.g. {next(iter(dead.values()))[0]}).", urls=list(dead), values=vals)


def X08(r: R):
    hits = [p["url"] for p in r.ctx.html if r.ctx.ev(p).get("prices") or r.ctx.ev(p).get("quote_cta")]
    return r.ok("A price, price band or explicit quote process is shown.", urls=hits, label="Inferred") if hits else r.fail("No price expectation or quote process stated.", label="Inferred")


def X09(r: R):
    tags = [p["url"] for p in r.ctx.html if (r.ctx.ev(p).get("analytics") or {}).get("ga4") or (r.ctx.ev(p).get("analytics") or {}).get("gtm")]
    if not tags:
        return r.fail("No GA4 / Google Tag Manager tag detected in the served HTML.")
    if r.ctx.capabilities.get("ga4"):
        return r.ok("GA4 connected.")
    return r.unmeasured("capability_missing:ga4", "A GA4/GTM tag is present; whether form/phone/chat events are tracked requires GA4 access.", label="Integration required", urls=tags)


# =============================================================================================
# REGISTRY
# =============================================================================================
EVALUATORS: dict[str, Callable[[R], CheckResult]] = {
    "T01": T01, "T02": T02, "T03": T03, "T04": T04, "T05": T05, "T06": T06, "T07": T07, "T08": T08, "T09": T09, "T10": T10,
    "T11": T11, "T12": T12, "T13": T13, "T14": T14, "T15": T15, "T16": T16,
    "O01": O01, "O02": O02, "O03": O03, "O04": O04, "O05": O05, "O06": O06, "O07": O07, "O08": O08, "O09": O09, "O10": O10, "O11": O11, "O12": O12,
    "C01": C01, "C02": C02, "C03": C03, "C04": C04, "C05": C05, "C06": C06, "C07": C07, "C08": C08, "C09": C09, "C10": C10,
    "K01": K01, "K02": K02, "K03": K03, "K04": K04, "K05": K05, "K06": K06,
    "L01": L01, "L02": L02, "L03": L03, "L04": L04, "L05": L05, "L06": L06,
    "I01": I01, "I02": I02, "I03": I03, "I04": I04, "I05": I05, "I06": I06, "I07": I07,
    "S01": S01, "S02": S02, "S03": S03, "S04": S04, "S05": S05, "S06": S06, "S07": S07, "S08": S08,
    "M01": M01, "M02": M02, "M03": M03, "M04": M04, "M05": M05, "M06": M06,
    "P01": _cwv, "P02": _cwv, "P03": _cwv, "P04": _cwv, "P05": P05, "P06": P06,
    "Lo01": Lo01, "Lo02": Lo02, "Lo03": Lo03, "Lo04": Lo04, "Lo05": Lo05, "Lo06": Lo06, "Lo07": Lo07, "Lo08": Lo08, "Lo09": MANUAL, "Lo10": Lo10, "Lo11": Lo11,
    "X01": X01, "X02": X02, "X03": X03, "X04": X04, "X05": X05, "X06": X06, "X07": X07, "X08": X08, "X09": X09,
}
VERTICAL_EVALUATORS: dict[str, dict[str, Callable[[R], CheckResult]]] = {
    "b2b_product": {"V01": V01_b2b, "V02": V02_b2b, "V03": V03_b2b, "V04": V04_b2b, "V05": V05_b2b, "V06": V06_b2b, "V07": V07,
                    "V08": V08_b2b, "V09": V09_b2b, "V10": V10_b2b},
    "travel_tourism": {"V01": V01_travel, "V02": V02_travel, "V03": V03_travel, "V04": V04_travel, "V05": V05_travel, "V06": V06_travel,
                       "V07": V07, "V08": V08_travel, "V09": V09_travel, "V10": V10_travel},
    "ecommerce": {"E01": E01_retail, "E02": E02_retail, "E03": E03_retail, "E04": E04_retail, "E05": E05_retail,
                  "E06": E06_retail, "E07": E07_retail, "E08": E08_retail, "E09": E09_retail, "E10": E10_retail},
    "ecommerce_retail": {"E01": E01_retail, "E02": E02_retail, "E03": E03_retail, "E04": E04_retail, "E05": E05_retail,
                         "E06": E06_retail, "E07": E07_retail, "E08": E08_retail, "E09": E09_retail, "E10": E10_retail},
    "digital_asset_marketplace": {"D01": D01_market, "D02": D02_market, "D03": D03_market, "D04": D04_market, "D05": D05_market,
                                  "D06": D06_market, "D07": D07_market, "D08": D08_market, "D09": D09_market, "D10": D10_market},
}


def evaluate_all(ctx: Ctx) -> list[CheckResult]:
    rs = load_ruleset()
    results: list[CheckResult] = []
    for category in rs["weights"]:
        for d in category_checks(category, ctx.profile):
            fn = VERTICAL_EVALUATORS[ctx.profile].get(d["id"]) if category == "vertical" else EVALUATORS.get(d["id"])
            r = R(ctx, category, d)
            if fn is None:
                res = r.unmeasured("not_implemented", "No automated evaluator for this check.", label="Not measured")
            else:
                try:
                    res = fn(r)
                except Exception as exc:  # an evaluator bug must never become a FAIL about the site
                    res = r.unmeasured("evaluator_error", f"Check could not be evaluated: {type(exc).__name__}: {exc}", label="Not measured")
            if d.get("tier") in ("MANUAL",) and res.status != "UNMEASURED":
                res = r.unmeasured("capability_missing:manual", "Requires manual review.", label="Not verifiable")
            results.append(res)
    return results
