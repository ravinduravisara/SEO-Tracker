# Aviance SEO Pro Max v10.4.0 - Legend Universal Edition

Universal live-site SEO crawler for publicly reachable HTTP/HTTPS websites, with conservative transport fallbacks, weighted scorecards, evidence-bound automatic recommendations, keyword/topic intelligence, hashtag suggestions and report exports. Enter a site URL, run a full A-Z crawl, inspect real fetched evidence, view scores and automatic recommendations, and download PDF/CSV/JSON/report-pack exports.

## Universal crawl
- Starts from the supplied URL
- Discovers internal URLs from HTML links and XML sitemaps, including nested sitemap indexes
- Normalizes fragments and common tracking parameters while preserving meaningful query URLs in `allquery` mode
- Supports optional `www`/non-`www` equivalence and subdomain crawling
- Respects robots.txt by default
- Bounded concurrency, timeouts, retries and Retry-After handling
- Optional system-Chrome/Playwright rendering for JavaScript-heavy pages and the start page
- Does not bypass login walls, CAPTCHA or access controls
- Reports crawl failures explicitly instead of inventing data

## Real-data boundaries
The tool measures data it actually fetches: HTML, headers, metadata, headings, links, images, JSON-LD, robots.txt, sitemaps, response timing, resource status and related technical signals. Search volume, rankings, backlink indexes, traffic, Search Console metrics, GA4 metrics and field Core Web Vitals require their corresponding external data integrations.

## Windows
```powershell
cd "E:\e suppourt\aviance-tool-v800"
.\run.ps1
```
Use `INSTALL_RENDERER.ps1` when you want the Playwright Chromium fallback; the crawler also attempts installed Google Chrome automatically.

## v10.1 highlights
- Universal fetch fallback: after a transport-level failure, tries conservative www/non-www and HTTP/HTTPS variants before declaring fetch failure. Valid HTTP responses are never hidden by fallback logic.
- Internal all-site crawl safety ceiling: 25,000 URLs by default; the UI does not expose a maximum-pages field.
- Overall score is normalized across category weights and includes a bounded severity penalty.
- Every finding carries a source/evidence class where applicable.
- Page rows are clickable for a fresh one-page re-check.
- Automatic recommendations work without Ollama; Ollama is optional enrichment.
- One-click All PDF Reports + full Report Pack ZIP.

## Accuracy boundaries
Aviance does not bypass authentication, CAPTCHA, paywalls, robots rules, WAF challenges or access controls. A target can still be reported as unreachable or partially crawlable when the server blocks automated access. The tool reports the limitation instead of fabricating data.

## Current SEO knowledge references
Google Search Central documentation: https://developers.google.com/search/docs/essentials
Google spam policies: https://developers.google.com/search/docs/essentials/spam-policies
Google canonicalization: https://developers.google.com/search/docs/crawling-indexing/canonicalization
Google structured data: https://developers.google.com/search/docs/appearance/structured-data/
Schema.org documentation: https://schema.org/docs/documents.html


## v10.3.0 report download upgrade

The Reports Center and Recommendations tab now include **Download ALL Recommendations PDF**. This is a single consolidated PDF containing:
- every automatic grouped recommendation;
- the developer action plan with evidence, fixes, validation and affected URLs;
- quick wins; and
- recommendation-bearing findings from the current audit.

This avoids browser multi-download restrictions and gives developers one PDF handover file.


## v10.3.0 crawl-scope correction
External URLs are never crawled when external link checking is enabled; they are status-checked only. Same-site matching is strict and symmetric, including optional true subdomains. Query URL crawling is bounded to 50 variants per path.

## v10.4.0 production hardening
- **SSRF protection**: every audit target and discovered link is resolved and checked before fetching; requests to loopback, private, link-local and cloud-metadata addresses (including `169.254.169.254`) are refused, and redirects are re-validated on every hop instead of being followed blindly. Applies to the HTTP fetch path and the optional Playwright-rendered path alike.
- **Security headers** on every response: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, and a `Content-Security-Policy` scoped to same-origin. `Strict-Transport-Security` is added automatically when `APP_ENV=production`.
- **CORS** is now environment-driven via `CORS_ORIGINS` (comma-separated). It stays same-origin-only (no CORS middleware at all) until you explicitly set it, so a same-host deployment needs no change.
- **Rate limiting**: the crawl/report endpoints are limited per client IP (`RATE_LIMIT_PER_MINUTE`, default 20/min) to reduce abuse and hosting-cost risk on a public deployment. In-memory and single-process — a multi-instance deployment needs a shared store instead.
- **Upload hardening**: the source-ZIP analyzer now caps per-file and total decompressed bytes and the number of entries scanned, so a decompression-bomb archive can no longer exhaust memory.
- **Error handling & logging**: unexpected errors are logged server-side with full detail and return a generic message to the client instead of leaking internals; requests are logged with method, path, client, status and duration.
- **New Client View**: audit results now default to a client-safe tab showing the overall score and a Good / Needs Improvement / Poor rating per category, with an **Improve My SEO — Chat on WhatsApp** button that opens a prefilled WhatsApp chat (site + score). Raw codes, evidence and developer fixes stay on the existing Overview/Issues/Developer tabs for internal use.

**Not yet in this codebase** (raised in project discussion, intentionally out of scope for this pass — each needs product/infra decisions before implementation): persistent storage (MySQL/any database), user accounts, authentication, RBAC (Admin/Manager/Staff/Customer), multi-tenant customer/website records, billing/invoicing, a WhatsApp Business API integration (the current CTA is a plain `wa.me` link, no API/credentials needed), monitoring/scheduling, and competitor/backlink tracking. The tool remains a stateless, single-run crawler: nothing is persisted between audits today.
