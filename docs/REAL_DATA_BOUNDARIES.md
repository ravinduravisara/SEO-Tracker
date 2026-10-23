# Real Data Boundaries — v10.5

## Measured directly by the crawler
- HTTP status and redirect chain
- Response time and fetched body size
- HTML metadata and headings
- Canonical and robots directives present in the fetched response
- Internal/external links discovered in the fetched HTML
- Image attributes and referenced resources
- JSON-LD syntax/types present in the fetched HTML
- Open Graph/Twitter metadata
- robots.txt and XML sitemap files that the crawler can fetch
- Page-to-page crawl depth and discovered-link graph
- Optional browser-rendered DOM when Playwright/Chromium is installed

## Measured by connected providers (see REAL_DATA_SETUP.md)
| Data | Provider | Free? |
|---|---|---|
| Field Core Web Vitals (LCP, INP, CLS, FCP, TTFB, 75th percentile, 28 days) | Google PageSpeed Insights API → Chrome UX Report | Free |
| Lighthouse performance / SEO / accessibility / best-practices scores | Google PageSpeed Insights API | Free |
| Clicks, impressions, CTR, average position, top queries/pages | Google Search Console API | Free |
| Search volume, CPC, competition, keyword difficulty, search intent | DataForSEO Labs | Paid |
| Google organic ranking positions | DataForSEO Labs | Paid |
| Backlinks, referring domains, domain rank, spam score | DataForSEO Backlinks API | Paid (subscription) |

When a provider is not configured or fails, the report says so (`data_provenance.integration_errors`). It never fills the gap with an invented value.

## Still not available
- Organic traffic / conversions (Google Analytics is not connected)

## Interpretation
- The overall score and the category percentages are **estimates**: internal weighted heuristics over crawled signals. They are labelled "estimate" in the API (`scores.score_type`), the dashboard and the client report.
- Issue guidance and thresholds come from `backend/seo_knowledge.py`. Each rule cites Google Search Central, web.dev, MDN or W3C. Thresholds where Google publishes no number (title / meta description length, URL length) are marked `basis: convention`.
