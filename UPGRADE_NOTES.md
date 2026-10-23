# Aviance SEO Pro Max v9.1.0 — Universal Crawl Upgrade

## Main fixes
- Universal arbitrary-site crawl from user-supplied HTTP/HTTPS URL
- Full-site discovery from HTML links + XML sitemaps + nested sitemap indexes
- `www`/non-`www` normalization and optional subdomain crawling
- Safe query-URL handling with optional all-query mode
- 20,000-page internal safety ceiling (not shown as a UI input)
- Bounded concurrent crawl workers, timeouts, retries and Retry-After handling
- Explicit crawl diagnostics and data-coverage/confidence telemetry
- Start-page browser rendering in `auto` and `rendered` modes, not only child pages
- System Google Chrome fallback plus optional Playwright Chromium
- Accurate renderer availability reporting
- Robots-aware crawl: an explicitly disallowed start URL is not fetched during the audit
- Canonical query serialization fixed with URL encoding
- H1 absence downgraded to a warning; multiple H1s remain informational
- PDF, JSON, CSV and report-pack exports preserved
- No audit history page/database

## Real-data boundary
The crawler reports only evidence it actually observes from live HTTP/HTML or browser-rendered DOM. It does not invent search volume, rankings, backlinks, traffic, Search Console, GA4 or field Core Web Vitals.

## Browser rendering on Windows
The application first attempts the installed Google Chrome channel. If unavailable, it attempts Playwright Chromium. Run `INSTALL_RENDERER.ps1` to install a bundled browser if you want that fallback.

## Validation performed
- Python compile check passed
- Local multi-page site crawl passed
- Nested sitemap discovery passed
- Page scoring passed
- Automatic recommendations passed
- PDF exports passed for all report types
- CSV exports passed for pages/issues/developer/automatic/keywords/hashtags/categories
- Report bundle ZIP passed
- Frontend version/control strings passed
