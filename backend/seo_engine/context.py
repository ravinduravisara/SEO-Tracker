"""Site-level evidence context shared by all check evaluators.

Built once per audit from the crawler result plus probes. Pure derivations only (no network).
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional
from urllib.parse import urlparse

STOP = {
    "the", "and", "for", "with", "that", "this", "from", "your", "you", "are", "was", "were", "our", "their", "into", "have",
    "has", "had", "about", "will", "can", "www", "com", "https", "http", "home", "page", "pages", "news", "read", "more", "what",
    "when", "where", "which", "while", "who", "how", "why", "all", "any", "not", "but", "get", "use", "new", "one", "two", "also",
    "only", "than", "then", "them", "they", "its", "out", "over", "under", "after", "before", "these", "those", "there", "here",
    "best", "top", "welcome", "official", "website", "site", "online", "index", "html", "php", "aspx", "default", "pvt", "ltd",
    "limited", "private", "company", "inc", "llc", "plc", "co",
}
GENERIC_H1 = {"welcome", "home", "homepage", "products", "our products", "services", "our services", "about", "about us",
              "contact", "contact us", "untitled", "page", "hello", "hi", "main", "blog", "news", "shop", "gallery"}
UTILITY_RE = re.compile(r"/(about|about-us|who-we-are|contact|contact-us|privacy|privacy-policy|terms|terms-and-conditions|"
                        r"terms-of-service|cookie|cookies|legal|disclaimer|login|register|account|my-account|cart|basket|checkout|"
                        r"wishlist|faq|faqs|search|sitemap|careers?|jobs|thank-you|thanks|team|gallery|news|blog|tag|author|feed|"
                        r"refund|returns|shipping)(/|$)", re.I)
ARTICLE_RE = re.compile(r"/(blog|news|articles?|posts?)/[^/]+", re.I)
LOCAL_TYPES = ("localbusiness", "store", "restaurant", "medicalbusiness", "professionalservice", "dentist", "hotel",
               "lodgingbusiness", "travelagency", "autorepair", "autodealer", "beautysalon", "legalservice", "homeandconstructionbusiness",
               "foodestablishment", "healthandbeautybusiness", "realestateagent", "electrician", "plumber", "hvacbusiness",
               "generalcontractor", "touristinformationcenter", "sportsactivitylocation", "financialservice", "insuranceagency")
ORG_TYPES = ("organization", "corporation") + LOCAL_TYPES
COUNTRY_BY_TLD = {"lk": ("LK", "Sri Lanka"), "in": ("IN", "India"), "uk": ("GB", "United Kingdom"), "au": ("AU", "Australia"),
                  "sg": ("SG", "Singapore"), "ae": ("AE", "United Arab Emirates"), "my": ("MY", "Malaysia"), "nz": ("NZ", "New Zealand"),
                  "ca": ("CA", "Canada"), "pk": ("PK", "Pakistan"), "bd": ("BD", "Bangladesh"), "mv": ("MV", "Maldives")}
COUNTRY_NAMES = {"sri lanka": "LK", "india": "IN", "united kingdom": "GB", "australia": "AU", "singapore": "SG", "maldives": "MV",
                 "united arab emirates": "AE", "malaysia": "MY", "new zealand": "NZ", "canada": "CA", "pakistan": "PK",
                 "bangladesh": "BD", "united states": "US", "usa": "US", "uk": "GB"}
TITLE_SPLIT = re.compile(r"\s+[|\-–—:·•]\s+")


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9'’-]*[a-z0-9]|[a-z0-9]", (text or "").lower())


def sig_terms(text: str) -> list[str]:
    return [t for t in tokens(text) if len(t) >= 3 and t not in STOP and not t.isdigit()]


def stem_in(term: str, words: list[str]) -> bool:
    stem = term[: max(4, len(term) - 2)]
    return any(w.startswith(stem) or term.startswith(w[: max(4, len(w) - 2)]) for w in words if len(w) >= 3)


def norm_url(u: str) -> str:
    p = urlparse(u or "")
    host = (p.hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    path = (p.path or "/").rstrip("/") or "/"
    return f"{host}{path}" + (f"?{p.query}" if p.query else "")


def parse_date(value: str) -> Optional[date]:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(value or ""))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


@dataclass
class Ctx:
    audit: dict[str, Any]
    pages_all: list[dict[str, Any]]
    html: list[dict[str, Any]]
    home: Optional[dict[str, Any]]
    commercial: list[dict[str, Any]]
    articles: list[dict[str, Any]]
    robots: dict[str, Any]
    sitemap: dict[str, Any]
    sitemap_set: set[str]
    sitemap_complete: bool
    probes: Optional[dict[str, Any]]
    sitemap_sample: Optional[dict[str, Any]]
    render: Optional[dict[str, Any]]
    real_data: dict[str, Any]
    capabilities: dict[str, Any]
    profile: str
    audit_date: date
    apex: str
    brand: str
    brand_tokens: set[str]
    site_vocab: list[str]
    market_code: Optional[str]
    market_names: list[str]
    city_names: list[str]
    is_local_business: bool
    inbound: Counter
    link_status: dict[str, int]
    js_site: bool
    small_site: bool
    notes: list[str] = field(default_factory=list)

    def ev(self, p: dict[str, Any]) -> dict[str, Any]:
        return p.get("ev") or {}

    def target_terms(self, p: dict[str, Any]) -> list[str]:
        path = urlparse(p.get("url", "")).path.strip("/")
        seg = path.split("/")[-1] if path else ""
        seg = re.sub(r"\.(html?|php|aspx?)$", "", seg, flags=re.I)
        terms = [t for t in sig_terms(re.sub(r"[-_.+]", " ", seg)) if t not in self.brand_tokens]
        return terms[:6] or self.site_vocab[:5]


def schema_nodes_of(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for p in pages:
        for n in p.get("schema_nodes") or []:
            if isinstance(n, dict):
                out.append(n)
    return out


def node_types(n: dict[str, Any]) -> list[str]:
    t = n.get("@type")
    if isinstance(t, list):
        return [str(x).lower() for x in t]
    return [str(t).lower()] if t else []


def build_context(audit: dict[str, Any], probes: Optional[dict], sitemap_full: Optional[dict], robots_full: Optional[dict],
                  sitemap_sample: Optional[dict], render: Optional[dict], capabilities: dict[str, Any], profile: Optional[str]) -> Ctx:
    pages_all = [p for p in audit.get("pages") or [] if isinstance(p, dict)]
    html = [p for p in pages_all if not p.get("non_html") and not p.get("error") and 200 <= int(p.get("status") or 0) < 400]
    target = audit.get("target") or (html[0]["url"] if html else "")
    tp = urlparse(target)
    apex = (tp.hostname or "").lower()
    apex = apex[4:] if apex.startswith("www.") else apex
    home = next((p for p in html if urlparse(p.get("url", "")).path in ("", "/")), html[0] if html else None)
    articles = [p for p in html if p is not home and (ARTICLE_RE.search(urlparse(p.get("url", "")).path) or str((p.get("og") or {}).get("og:type", "")).lower() == "article")]
    commercial = [p for p in html if p is home or (p not in articles and not UTILITY_RE.search(urlparse(p.get("url", "")).path))]
    if not commercial:
        commercial = list(html)

    site = audit.get("site") or {}
    robots = dict(robots_full or {})
    if not robots:
        robots = dict(site.get("robots") or {})
    sitemap = dict(sitemap_full or {})
    if not sitemap:
        sm = site.get("sitemap") or {}
        sitemap = {"files": sm.get("files", []), "urls": sm.get("urls_sample", []), "lastmod": sm.get("lastmod_sample", {}),
                   "detected": sm.get("detected", ""), "truncated": int(sm.get("url_count") or 0) > len(sm.get("urls_sample") or [])}
    sitemap_set = {norm_url(u) for u in sitemap.get("urls") or []}
    sitemap_complete = bool(sitemap_set) and not sitemap.get("truncated")

    # Brand: og:site_name, schema organisation name, or the title segment repeated across pages.
    cands: Counter = Counter()
    for p in html:
        sn = str((p.get("og") or {}).get("og:site_name") or "").strip()
        if sn:
            cands[sn.lower()] += 3
        segs = [s.strip() for s in TITLE_SPLIT.split(p.get("title") or "") if s.strip()]
        if len(segs) > 1:
            cands[segs[-1].lower()] += 1
            cands[segs[0].lower()] += 0.5
    for n in schema_nodes_of(html):
        if any(t in ORG_TYPES for t in node_types(n)) and isinstance(n.get("name"), str):
            cands[n["name"].strip().lower()] += 2
    brand = cands.most_common(1)[0][0] if cands and cands.most_common(1)[0][1] >= 2 else (apex.split(".")[0] if apex else "")
    brand_tokens = set(sig_terms(brand)) | {apex.split(".")[0]} if apex else set(sig_terms(brand))

    vocab: Counter = Counter()
    for p in html:
        heads = " ".join([p.get("title") or ""] + list(p.get("h1") or []) + list(p.get("h2") or [])[:6])
        for t in set(sig_terms(heads)):
            if t not in brand_tokens:
                vocab[t] += 1
    site_vocab = [t for t, _ in vocab.most_common(8)]

    # Market: schema address, og:locale, ccTLD, address text.
    market_code = None
    market_names: list[str] = []
    city_names: list[str] = []
    for n in schema_nodes_of(html):
        addr = n.get("address") if isinstance(n.get("address"), dict) else (n if "addresslocality" in json.dumps(n).lower() else None)
        if isinstance(addr, dict):
            for k in ("addressLocality", "addressRegion"):
                v = addr.get(k)
                if isinstance(v, str) and v.strip() and v.strip().lower() not in city_names:
                    city_names.append(v.strip().lower())
            c = addr.get("addressCountry")
            c = c.get("name") if isinstance(c, dict) else c
            if isinstance(c, str) and c.strip():
                code = c.strip().upper() if len(c.strip()) == 2 else COUNTRY_NAMES.get(c.strip().lower())
                market_code = market_code or code
    if not market_code:
        for p in html:
            loc = str((p.get("og") or {}).get("og:locale") or "")
            m = re.match(r"[a-z]{2}[_-]([A-Z]{2})$", loc)
            if m and m.group(1) not in ("US",):
                market_code = m.group(1)
                break
    tld = apex.rsplit(".", 1)[-1] if "." in apex else ""
    if not market_code and tld in COUNTRY_BY_TLD:
        market_code = COUNTRY_BY_TLD[tld][0]
    if not market_code:
        addr_text = " ".join((p.get("ev") or {}).get("address_text", "") for p in html).lower()
        for name, code in COUNTRY_NAMES.items():
            if len(name) > 3 and name in addr_text:
                market_code = code
                break
    if market_code:
        market_names = [n for n, c in COUNTRY_NAMES.items() if c == market_code and len(n) > 3]
    has_address = any((p.get("ev") or {}).get("address_text") or (p.get("ev") or {}).get("schema_address") for p in html)
    has_local_schema = any(any(t in LOCAL_TYPES for t in node_types(n)) for n in schema_nodes_of(html))
    is_local = bool(has_address or has_local_schema or tld in COUNTRY_BY_TLD)

    inbound: Counter = Counter()
    for p in html:
        src = norm_url(p.get("url", ""))
        for u in set(norm_url(x) for x in p.get("internal_links") or []):
            if u != src:
                inbound[u] += 1
    link_status = {norm_url(x.get("url", "")): int(x.get("status") or 0) for x in audit.get("link_checks") or []}
    js_pages = [p for p in html if (p.get("rendering_signals") or {}).get("likely_js_shell") and not p.get("rendered")]
    js_site = bool(html) and len(js_pages) / len(html) >= 0.5

    return Ctx(
        audit=audit, pages_all=pages_all, html=html, home=home, commercial=commercial, articles=articles, robots=robots,
        sitemap=sitemap, sitemap_set=sitemap_set, sitemap_complete=sitemap_complete, probes=probes, sitemap_sample=sitemap_sample,
        render=render, real_data=audit.get("real_data") or {}, capabilities=capabilities, profile=profile or "b2b_product",
        audit_date=(parse_date(audit.get("created_at", "")) or date.today()), apex=apex, brand=brand, brand_tokens=brand_tokens,
        site_vocab=site_vocab, market_code=market_code, market_names=market_names, city_names=city_names, is_local_business=is_local,
        inbound=inbound, link_status=link_status, js_site=js_site, small_site=len(html) <= 1,
    )


def detect_profile(audit: dict[str, Any]) -> tuple[str, str]:
    """Vertical slot: b2b_product, travel_tourism, ecommerce_retail, or digital_asset_marketplace."""
    pages = [p for p in audit.get("pages") or [] if isinstance(p, dict) and not p.get("error")]
    travel = shop = digital = 0
    for p in pages:
        path = urlparse(p.get("url", "")).path.lower()
        ev = p.get("ev") or {}
        types = " ".join(str(t).lower() for t in p.get("schema_types") or [])
        heads = " ".join([p.get("title") or ""] + list(p.get("h1") or [])).lower()
        if re.search(r"/(tours?|packages?|safari|excursions?|itinerar|day-trips?|holidays?)(/|-|$)", path) or "touristtrip" in types or "travelagency" in types:
            travel += 2
        if re.search(r"\b(tours?|safari|holiday packages?|travel|itinerary|excursion)\b", heads):
            travel += 1
        cs = p.get("commerce_signals") or {}
        if cs.get("add_to_cart") or cs.get("platform") in ("shopify", "woocommerce", "magento") or ("product" in types and cs.get("has_price_schema")) or re.search(r"/(cart|checkout|shop|product-category|products)(/|$)", path):
            shop += 2
        if ev.get("cart"):
            shop += 1
        if re.search(r"\b(after effects|mogrt|premiere pro|templates|motion graphics|video editing assets|royalty-free music)\b", heads + " " + path):
            digital += 2
    if digital >= 4 and digital >= shop:
        return "digital_asset_marketplace", f"digital asset signals={digital} (templates, MOGRTs, motion graphics)"
    if shop >= 3 and shop >= travel:
        return "ecommerce", f"shop signals={shop} (cart / platform / priced Product markup)"
    if travel >= 3:
        return "travel_tourism", f"travel signals={travel} (tour/package URLs, travel headings, TouristTrip markup)"
    return "b2b_product", f"default profile (travel signals={travel}, shop signals={shop})"
