# Aviance SEO A–Z Guide v10.1

This guide separates directly measurable website implementation signals from metrics that require external search, analytics, backlink, or browser/field data.

## A — Accessibility & HTML semantics
Language, viewport, form labels, semantic landmarks, headings, image ALT, and meaningful link text.

## B — Bot access & robots.txt
robots.txt availability, sitemap references, crawler access, disallow/allow signals, and blocked URLs.

## C — Canonicalization
Canonical presence, location, normalized target, protocol/host consistency, redirect interaction, and duplicate URL signals. A canonical hint is not an absolute command.

## D — Duplicate content & metadata
Duplicate titles/descriptions and exact duplicate fetched visible text. Similar content needs contextual review rather than automatic deletion.

## E — Experience & performance signals
Crawler-measured response time, HTML size, script count, resource timing, cache-control signals and image delivery attributes. These are not field Core Web Vitals.

## F — Files, feeds & favicons
robots, XML sitemaps, favicon, linked feeds/resources and HTTP content types.

## G — Google Search readiness
Implementation checks mapped to Search Essentials and search appearance documentation. Search Console data is only shown when connected.

## H — Head metadata
Title, meta description, robots, viewport, charset, canonical, hreflang, Open Graph and Twitter/X metadata.

## I — Indexability
Indexability matrix using HTTP status, meta robots, X-Robots-Tag, robots.txt, sitemap membership and canonical signals.

## J — JavaScript rendering
Raw HTML analysis plus optional browser-rendered DOM audit for pages that appear JavaScript-heavy. A browser audit can reveal content and links missing from raw HTML.

## K — Keyword & topic signals
Observed terms and phrases extracted from fetched content, intent heuristics, placement signals, page counts and topic overlap. These are not keyword-volume or ranking metrics.

## L — Links & internal architecture
Internal link graph, external links, broken targets, anchor-text signals, crawl depth, pagination links and orphan candidates.

## M — Media & images
ALT, dimensions, loading attributes, srcset, format and live resource status.

## N — Navigation & discoverability
Link-driven discovery, sitemap-driven discovery, crawl depth and pages with no inbound internal links.

## O — Open Graph & social
og:title, og:description, og:image, og:url, Twitter/X card signals and social sharing readiness.

## P — URL patterns
HTTPS, host normalization, path case, length, fragments, tracking parameters and query-parameter behavior.

## Q — Quality/content signals
Visible text, article-like page signals, duplicates, thin/low-text warnings and semantic content coverage. No arbitrary word-count target is treated as a ranking rule.

## R — Redirects & resilience
Redirect chains, final URL, offsite redirects, 429/5xx retry behavior, response errors and bounded timeouts.

## S — Structured data
JSON-LD parsing, detected schema types and syntax errors. Validate implementation with structured-data testing and confirm it matches visible content.

## T — Technical SEO
Crawlability, status, indexability, canonicals, sitemap/robots, HTML, links, resources, rendering and security signals in one audit.

## U — URL hygiene
Stable normalization, tracking-parameter handling, case consistency, duplicate query permutations and crawl-safe URL policies.

## V — Validation & verification
Every recommendation contains evidence and a validation step that can be checked with a fresh crawl.

## W — Web/security signals
HTTPS, HSTS, CSP, X-Content-Type-Options and mixed-content resource references. These are engineering signals, not direct ranking guarantees.

## X — XML sitemaps
Discover sitemap URLs from robots.txt and conventional root paths, traverse sitemap indexes, record lastmod samples, and compare sitemap membership with crawled pages.

## Y — Yield/actionability
Automatic recommendations group repeated issues into P0/P1/P2 actions and include evidence, affected URLs, action, developer fix and validation. Optional Ollama adds evidence-bound natural-language enrichment.

## Z — Zero fabrication
Never invent rankings, traffic, backlinks, domain authority, Search Console values, search volume, keyword difficulty, or field Core Web Vitals.

## Official references
- Google Search Essentials: https://developers.google.com/search/docs/essentials
- Canonicalization: https://developers.google.com/search/docs/crawling-indexing/canonicalization
- Search appearance: https://developers.google.com/search/docs/appearance
- Structured data: https://developers.google.com/search/docs/appearance/structured-data/intro-structured-data
- Robots specification: https://developers.google.com/crawling/docs/robots-txt/robots-txt-spec


## Practical workflow
1. Enter the canonical public starting URL.
2. Run **Test Live Site** to capture HTTP status, redirects, robots and sitemap availability before the full crawl.
3. Run **Full A-Z Audit** with link/resource checks as needed.
4. Review the **Overall Score**, category scores, data coverage and issue source categories.
5. Open **Recommendations** and **Developer** for evidence, affected URLs, fixes and validation.
6. Review **Keywords**, **Hashtags** and **Pages** for content planning; treat these as observed-content signals, not search-volume/rank data.
7. Re-check individual URLs after fixes with the one-page audit.
8. Download the full PDF or complete report pack for handoff.

## What can make a site only partially crawlable
Aviance intentionally does not bypass authentication, CAPTCHA, paywalls, WAF challenges, robots restrictions, TLS failures, or other access controls. JavaScript-heavy sites may require the optional Playwright renderer. Very large sites can take longer and are subject to an internal safety ceiling to protect the local machine. When data is unavailable, the report records the limitation instead of inventing a value.

## Current official guidance used by this edition
- Google Search Essentials: https://developers.google.com/search/docs/essentials
- Google crawling and indexing: https://developers.google.com/search/docs/crawling-indexing
- Google canonicalization: https://developers.google.com/search/docs/crawling-indexing/canonicalization
- Google structured data: https://developers.google.com/search/docs/appearance/structured-data/
- Google spam policies: https://developers.google.com/search/docs/essentials/spam-policies
- Schema.org documentation: https://schema.org/docs/documents.html
