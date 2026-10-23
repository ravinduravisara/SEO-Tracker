# Aviance SEO Pro Max v10.1 — A–Z Coverage Matrix

This is a practical implementation checklist. A check means the tool can inspect a live signal; it does not mean Google uses that signal as a direct ranking factor.

| Area | Coverage |
|---|---|
| A — Accessibility/HTML | lang, charset, semantic landmarks, form-label signals |
| B — Broken URLs | checked internal/external links, HTTP errors, redirect targets |
| C — Canonicalization | rel=canonical, cross-host and non-self checks |
| D — Duplicates | duplicate titles, meta descriptions, exact visible-content hashes |
| E — External links | discovery and optional status checks |
| F — Favicon/Search appearance | favicon signal, Open Graph/Twitter |
| G — Graph/structured data | JSON-LD extraction, type inventory, parser errors |
| H — Headings | H1–H4 inventory and hierarchy-jump detection |
| I — Indexability | meta robots, X-Robots-Tag, robots-aware crawling |
| J — JavaScript rendering | script counts and low-text/JS-shell heuristics; no browser execution |
| K — Keyword/topic signals | observed terms/phrases, placement signals, page mapping, heuristic intent; not ranking/volume data |
| L — Links | internal graph, anchor text signals, orphan candidates |
| M — Meta | title + meta-description presence/length guidance |
| N — Navigation | internal links, discovery depth, orphan candidates |
| O — Open Graph | og:title, og:description, og:image |
| P — Performance proxies | response time, HTML bytes, script count, cache/compression headers, resource checks |
| Q — Quality signals | visible text count, article-like thin content heuristic |
| R — Robots | robots.txt fetch, allow/disallow check, sitemap references |
| S — Sitemaps | sitemap.xml + index recursion, URL reconciliation, lastmod samples |
| T — Technical headers | HSTS, CSP, X-Content-Type-Options |
| U — URL hygiene | HTTPS, URL length, uppercase paths, tracking parameters |
| V — Viewport/mobile | responsive viewport signal |
| W — Web/schema | schema type inventory and malformed JSON-LD detection |
| X — eXperience signals | image dimensions/lazy loading, script load signals, semantic structure |
| Y — Your source | ZIP-based source-code SEO scan |
| Z — Zero-history privacy mode | no audit-history page and no local SQLite audit persistence |

## Accuracy boundaries

The crawler measures real HTTP responses and fetched HTML. It does not invent traffic, backlinks, rankings, search volume, Search Console data, or Core Web Vitals.

Browser rendering and field Core Web Vitals should be added through browser instrumentation or a trusted field-data source when those measurements are required.


## v10.1 accuracy improvements
- Sitemap URLs are merged into the crawl queue correctly even when the link queue becomes empty at the same moment a sitemap job completes.
- Transport-level failures can trigger conservative hostname/protocol fallbacks before a fetch is classified as failed.
- Page rows can be re-checked individually after a site audit.
- Every issue can be traced to an evidence source class.
- Overall score normalization is based on the declared category weights plus a bounded severity penalty.
