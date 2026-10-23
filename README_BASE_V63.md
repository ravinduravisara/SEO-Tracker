# Aviance SEO Pro Max - v6.3.0

A local SEO engineering workbench for live, authorized websites. It performs bounded concurrent HTTP/HTML crawling and produces developer-focused audit data without storing audit history.

## v6.3.0 highlights

- Concurrent page crawling (default 8 workers) with live page-speed telemetry.
- Crawls internal-link discoveries and XML-sitemap URLs up to an internal 5,000-page safety ceiling; the UI does not expose a maximum-page field.
- Live Site Preflight checks HTTP status, redirects, response time, robots.txt and sitemap endpoints before the full audit.
- External link checks are optional, bounded, HEAD-first with GET fallback and do not block the core crawl forever.
- Resource checks are concurrent and sampled.
- Cancellation no longer waits for outstanding link/resource futures.
- Local Ollama AI is optional and evidence-bound; the core rule-based audit completes independently.
- Report Center downloads Full PDF, raw JSON, developer CSV and a portable ZIP report pack.
- No History page and no audit-history database.

## A-Z live audit coverage

Technical crawling, HTTP status and redirects, robots.txt, XML sitemaps, sitemap/indexability reconciliation, indexability directives, canonicals, titles, meta descriptions, headings, duplicate metadata, duplicate visible text, internal links, external links, broken targets, orphan candidates, anchor-text signals, image ALT and delivery attributes, JSON-LD/schema parsing, Open Graph, Twitter metadata, hreflang reciprocity, URL hygiene, favicon, semantic HTML, form labels, security headers, response timing, HTML size, cache/compression signals, JavaScript-heavy heuristics, sampled resources, topic-frequency signals, and source-ZIP implementation checks.

## Real-data boundary

Aviance reports only what it can fetch or derive from the supplied live URL/source archive. It does not fabricate Google rankings, backlink indexes, traffic, Search Console data or field Core Web Vitals. Browser-rendered JavaScript and real-user performance metrics need browser/field instrumentation.

## Windows installation

From the extracted `aviance_pro` directory:

```powershell
cd "E:\e suppourt\aviance-tool\aviance_pro"
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\run.ps1
```

Then open `http://127.0.0.1:8000`. The launcher uses the project virtual environment, so a global `python` command is not required after the venv is created.

## Workflow

1. Enter the live URL.
2. Click **Test Live Site**.
3. Review the HTTP/robots/sitemap diagnostics.
4. Run **Full SEO Audit**.
5. Watch concurrent crawl, link and resource progress in real time.
6. Use the **Report Center** to download PDF/JSON/CSV or the complete report ZIP.
7. Send the developer plan and evidence to the implementation team, then re-run the audit after fixes.

## Optional Ollama

Install Ollama separately and pull the model named in `.env`. The UI reports whether the service and selected model are available. AI output is evidence-bound and the core audit remains rule-based.

## Built-in validation

The delivered v6.3 crawler was smoke-tested against a local 62-page synthetic site with an XML sitemap, robots.txt, 62 link/resource checks and concurrent crawling. The test completed in about 5.3 seconds in the development environment, and the PDF + report-pack endpoints both returned successfully.
