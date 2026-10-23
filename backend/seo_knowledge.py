"""SEO knowledge base: one source of truth for audit thresholds, client explanations and citations.

Every rule cites the primary documentation it is based on (Google Search Central, web.dev,
MDN, W3C, ogp.me). Where Google publishes no fixed number (for example title length), the
threshold is marked ``basis: "convention"`` so reports never present it as a Google rule.
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Primary sources
# ---------------------------------------------------------------------------
SOURCES: dict[str, dict[str, str]] = {
    "title_link": {"name": "Google Search Central - Influencing title links", "url": "https://developers.google.com/search/docs/appearance/title-link"},
    "snippet": {"name": "Google Search Central - Control your snippets", "url": "https://developers.google.com/search/docs/appearance/snippet"},
    "starter_guide": {"name": "Google Search Central - SEO Starter Guide", "url": "https://developers.google.com/search/docs/fundamentals/seo-starter-guide"},
    "helpful_content": {"name": "Google Search Central - Creating helpful, reliable, people-first content", "url": "https://developers.google.com/search/docs/fundamentals/creating-helpful-content"},
    "canonical": {"name": "Google Search Central - Consolidate duplicate URLs", "url": "https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls"},
    "robots_meta": {"name": "Google Search Central - Robots meta tag and X-Robots-Tag", "url": "https://developers.google.com/search/docs/crawling-indexing/robots-meta-tag"},
    "block_indexing": {"name": "Google Search Central - Block indexing with noindex", "url": "https://developers.google.com/search/docs/crawling-indexing/block-indexing"},
    "robots_txt": {"name": "Google Search Central - Introduction to robots.txt", "url": "https://developers.google.com/search/docs/crawling-indexing/robots/intro"},
    "sitemaps": {"name": "Google Search Central - Sitemaps overview", "url": "https://developers.google.com/search/docs/crawling-indexing/sitemaps/overview"},
    "redirects": {"name": "Google Search Central - Redirects and Google Search", "url": "https://developers.google.com/search/docs/crawling-indexing/301-redirects"},
    "http_errors": {"name": "Google Search Central - HTTP status codes, network and DNS errors", "url": "https://developers.google.com/search/docs/crawling-indexing/http-network-errors"},
    "links": {"name": "Google Search Central - Link best practices", "url": "https://developers.google.com/search/docs/crawling-indexing/links-crawlable"},
    "url_structure": {"name": "Google Search Central - URL structure best practices", "url": "https://developers.google.com/search/docs/crawling-indexing/url-structure"},
    "images": {"name": "Google Search Central - Google Images SEO best practices", "url": "https://developers.google.com/search/docs/appearance/google-images"},
    "structured_data": {"name": "Google Search Central - Introduction to structured data", "url": "https://developers.google.com/search/docs/appearance/structured-data/intro-structured-data"},
    "sd_policies": {"name": "Google Search Central - General structured data guidelines", "url": "https://developers.google.com/search/docs/appearance/structured-data/sd-policies"},
    "mobile_first": {"name": "Google Search Central - Mobile-first indexing best practices", "url": "https://developers.google.com/search/docs/crawling-indexing/mobile/mobile-sites-mobile-first-indexing"},
    "page_experience": {"name": "Google Search Central - Understanding page experience", "url": "https://developers.google.com/search/docs/appearance/page-experience"},
    "cwv_search": {"name": "Google Search Central - Core Web Vitals and Google Search", "url": "https://developers.google.com/search/docs/appearance/core-web-vitals"},
    "web_vitals": {"name": "web.dev - Web Vitals (thresholds)", "url": "https://web.dev/articles/vitals"},
    "lcp": {"name": "web.dev - Largest Contentful Paint", "url": "https://web.dev/articles/lcp"},
    "inp": {"name": "web.dev - Interaction to Next Paint", "url": "https://web.dev/articles/inp"},
    "cls": {"name": "web.dev - Cumulative Layout Shift", "url": "https://web.dev/articles/cls"},
    "fcp": {"name": "web.dev - First Contentful Paint", "url": "https://web.dev/articles/fcp"},
    "ttfb": {"name": "web.dev - Time to First Byte", "url": "https://web.dev/articles/ttfb"},
    "optimize_cls": {"name": "web.dev - Optimize Cumulative Layout Shift", "url": "https://web.dev/articles/optimize-cls"},
    "lazy_loading": {"name": "web.dev - Browser-level image lazy loading", "url": "https://web.dev/articles/browser-level-image-lazy-loading"},
    "mixed_content": {"name": "web.dev - What is mixed content?", "url": "https://web.dev/articles/what-is-mixed-content"},
    "javascript_seo": {"name": "Google Search Central - JavaScript SEO basics", "url": "https://developers.google.com/search/docs/crawling-indexing/javascript/javascript-seo-basics"},
    "hreflang": {"name": "Google Search Central - Localized versions of your page", "url": "https://developers.google.com/search/docs/specialty/international/localized-versions"},
    "favicon": {"name": "Google Search Central - Define a favicon for search results", "url": "https://developers.google.com/search/docs/appearance/favicon-in-search"},
    "https": {"name": "Google Search Central - HTTPS and page experience", "url": "https://developers.google.com/search/docs/appearance/page-experience"},
    "hsts": {"name": "MDN - Strict-Transport-Security", "url": "https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Strict-Transport-Security"},
    "csp": {"name": "MDN - Content-Security-Policy", "url": "https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Content-Security-Policy"},
    "nosniff": {"name": "MDN - X-Content-Type-Options", "url": "https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/X-Content-Type-Options"},
    "lang": {"name": "MDN - lang global attribute", "url": "https://developer.mozilla.org/en-US/docs/Web/HTML/Global_attributes/lang"},
    "charset": {"name": "MDN - <meta charset>", "url": "https://developer.mozilla.org/en-US/docs/Web/HTML/Element/meta#charset"},
    "main_landmark": {"name": "MDN - <main> element", "url": "https://developer.mozilla.org/en-US/docs/Web/HTML/Element/main"},
    "form_labels": {"name": "W3C WAI - Labeling form controls", "url": "https://www.w3.org/WAI/tutorials/forms/labels/"},
    "open_graph": {"name": "The Open Graph protocol", "url": "https://ogp.me/"},
    "twitter_cards": {"name": "X Developer - About Cards", "url": "https://developer.x.com/en/docs/x-for-websites/cards/overview/abouts-cards"},
    "search_console": {"name": "Google Search Console API - Search Analytics", "url": "https://developers.google.com/webmaster-tools/v1/searchanalytics/query"},
    "pagespeed_api": {"name": "PageSpeed Insights API", "url": "https://developers.google.com/speed/docs/insights/v5/about"},
    "crux": {"name": "Chrome UX Report (CrUX)", "url": "https://developer.chrome.com/docs/crux"},
    "spam_policies": {"name": "Google Search Central - Spam policies (link spam)", "url": "https://developers.google.com/search/docs/essentials/spam-policies"},
}

# ---------------------------------------------------------------------------
# Thresholds used by the crawler checks. basis = "google" (published by Google/web.dev)
# or "convention" (widely used practice; Google publishes no fixed number).
# ---------------------------------------------------------------------------
THRESHOLDS: dict[str, dict[str, Any]] = {
    "title_short_chars": {"value": 30, "basis": "convention", "source": "title_link",
                          "note": "Google sets no minimum; very short titles rarely describe the page well."},
    "title_long_chars": {"value": 60, "basis": "convention", "source": "title_link",
                         "note": "Google sets no maximum; desktop results truncate by pixel width (~600px, roughly 50-60 characters)."},
    "meta_description_short_chars": {"value": 70, "basis": "convention", "source": "snippet",
                                     "note": "Google sets no length limit; snippets are truncated to fit the device width."},
    "meta_description_long_chars": {"value": 160, "basis": "convention", "source": "snippet",
                                    "note": "Google sets no length limit; around 150-160 characters usually displays without truncation on desktop."},
    "ttfb_good_ms": {"value": 800, "basis": "google", "source": "ttfb", "note": "web.dev: TTFB of 0.8 seconds or less is good."},
    "ttfb_poor_ms": {"value": 1800, "basis": "google", "source": "ttfb", "note": "web.dev: TTFB above 1.8 seconds is poor."},
    "url_long_chars": {"value": 180, "basis": "convention", "source": "url_structure",
                       "note": "Google recommends simple, readable URLs but sets no length limit."},
    "redirect_chain_hops": {"value": 2, "basis": "google", "source": "redirects",
                            "note": "Googlebot follows up to 10 hops, but chains slow crawling and users; redirect directly to the final URL."},
}

# Core Web Vitals thresholds at the 75th percentile (web.dev/articles/vitals).
CWV_THRESHOLDS: dict[str, dict[str, Any]] = {
    "LCP": {"good": 2500, "poor": 4000, "unit": "ms", "source": "lcp", "label": "Largest Contentful Paint", "core": True},
    "INP": {"good": 200, "poor": 500, "unit": "ms", "source": "inp", "label": "Interaction to Next Paint", "core": True},
    "CLS": {"good": 0.1, "poor": 0.25, "unit": "", "source": "cls", "label": "Cumulative Layout Shift", "core": True},
    "FCP": {"good": 1800, "poor": 3000, "unit": "ms", "source": "fcp", "label": "First Contentful Paint", "core": False},
    "TTFB": {"good": 800, "poor": 1800, "unit": "ms", "source": "ttfb", "label": "Time to First Byte", "core": False},
}


def threshold(name: str) -> Any:
    return THRESHOLDS[name]["value"]


def rate_cwv(metric: str, value: float | None) -> str:
    """Rate a metric value as good / needs-improvement / poor using web.dev thresholds."""
    t = CWV_THRESHOLDS.get(metric)
    if t is None or value is None:
        return "unknown"
    if value <= t["good"]:
        return "good"
    if value <= t["poor"]:
        return "needs-improvement"
    return "poor"


# ---------------------------------------------------------------------------
# Rules keyed by audit issue code.
# title / why / action are client-friendly; source keys point into SOURCES.
# ---------------------------------------------------------------------------
RULES: dict[str, dict[str, Any]] = {
    # Crawl / status
    "fetch_error": {"title": "Page Could Not Be Fetched", "why": "If Googlebot cannot fetch a page it cannot index it; persistent DNS, TLS or server errors reduce crawling.", "action": "Check DNS, TLS certificate and server availability, then re-test the URL.", "sources": ["http_errors"]},
    "server_error": {"title": "Server Error (5xx)", "why": "Google slows crawling when a site returns 5xx errors, and URLs that keep failing are dropped from the index.", "action": "Fix the server or application error so the URL returns HTTP 200 (or a deliberate redirect/404).", "sources": ["http_errors"]},
    "client_error": {"title": "Broken Page (4xx)", "why": "Google does not index URLs that return 4xx; links pointing to them waste users' clicks and crawl activity.", "action": "Restore the page, 301-redirect it to the closest relevant page, or remove links to it.", "sources": ["http_errors"]},
    "broken_page": {"title": "Broken Page (404 Error)", "why": "404 pages are not indexed and frustrate visitors who follow links to them.", "action": "Restore the content or 301-redirect the URL to the most relevant live page.", "sources": ["http_errors", "redirects"]},
    "crawl_worker_error": {"title": "Page Failed During Crawl", "why": "A URL that intermittently fails can also fail for Googlebot.", "action": "Re-test the URL and check server logs for timeouts or errors.", "sources": ["http_errors"]},
    "redirected_page": {"title": "Internal URL Redirects", "why": "Linking to redirecting URLs adds an extra request for users and crawlers.", "action": "Update internal links to point straight to the final URL.", "sources": ["redirects"]},
    "redirect_chain": {"title": "Redirect Chain", "why": "Google recommends redirecting directly to the final destination; chains slow down users and crawling.", "action": "Replace multi-hop redirects with a single 301 to the final URL.", "sources": ["redirects"]},
    "meta_refresh": {"title": "Meta Refresh Redirect", "why": "Google recommends server-side 301/308 redirects; meta refresh is a weaker signal and a poorer user experience.", "action": "Replace the meta refresh with a server-side 301 redirect.", "sources": ["redirects"]},
    "offsite_redirect": {"title": "Redirect to Another Domain", "why": "Unintended cross-domain redirects send users and ranking signals away from your site.", "action": "Confirm the redirect is intentional; otherwise point it to the correct page on your domain.", "sources": ["redirects"]},
    "not_https": {"title": "Page Not Served Over HTTPS", "why": "HTTPS is part of Google's page experience guidance and browsers mark HTTP pages as 'Not secure'.", "action": "Serve every page over HTTPS and 301-redirect HTTP to HTTPS.", "sources": ["https"]},
    # Title / meta
    "missing_title": {"title": "Missing Page Title", "why": "The <title> element is the main source Google uses to generate the title link in search results.", "action": "Add a unique, descriptive title to every page, with the main topic first and the brand last.", "sources": ["title_link"]},
    "short_title": {"title": "Very Short Page Title", "why": "Google may rewrite titles that are too short to describe the page.", "action": "Write a descriptive title that clearly states the page topic. Google sets no minimum length; 30+ characters is a common guide.", "sources": ["title_link"], "threshold": "title_short_chars"},
    "long_title": {"title": "Long Page Title", "why": "Google sets no length limit, but titles longer than about 600px (roughly 50-60 characters) are truncated in results.", "action": "Keep titles concise, with the most important words first.", "sources": ["title_link"], "threshold": "title_long_chars"},
    "duplicate_title": {"title": "Duplicate Page Titles", "why": "Google recommends a unique title for each page so results are distinguishable.", "action": "Give each page a unique title that reflects its specific content.", "sources": ["title_link"]},
    "missing_meta_description": {"title": "Missing Meta Description", "why": "Google may use the meta description for the search snippet; without it, Google picks text from the page.", "action": "Write a unique, accurate summary of each page. Google sets no length limit; about 150-160 characters usually displays fully.", "sources": ["snippet"]},
    "short_meta_description": {"title": "Short Meta Description", "why": "A very short description may not explain why a searcher should click.", "action": "Expand the description with specific, useful details about the page.", "sources": ["snippet"], "threshold": "meta_description_short_chars"},
    "long_meta_description": {"title": "Long Meta Description", "why": "Snippets are truncated to fit the device width, so long descriptions are cut off.", "action": "Put the key message in the first ~150 characters.", "sources": ["snippet"], "threshold": "meta_description_long_chars"},
    "duplicate_meta_description": {"title": "Duplicate Meta Descriptions", "why": "Google recommends unique descriptions per page; identical ones are less helpful in results.", "action": "Write page-specific descriptions, at least for the most important pages.", "sources": ["snippet"]},
    # Headings / content
    "missing_h1": {"title": "Missing Main Heading (H1)", "why": "Headings help users and Google understand the page's main topic.", "action": "Add a clear main heading describing the page topic.", "sources": ["starter_guide"]},
    "multiple_h1": {"title": "Multiple H1 Headings", "why": "Multiple H1s are valid HTML and Google handles them; just keep the main topic obvious.", "action": "Optional: review the heading outline so the primary topic stands out.", "sources": ["starter_guide"]},
    "heading_jump": {"title": "Heading Levels Skipped", "why": "A logical heading outline helps accessibility and readability.", "action": "Use headings in order (H1, then H2, then H3) without skipping levels.", "sources": ["starter_guide"]},
    "thin_article": {"title": "Thin Article Content", "why": "Google rewards helpful, people-first content; there is no minimum word count, but the page must fully answer the user's need.", "action": "Make sure the page fully answers the visitor's question. Do not add filler just to raise the word count.", "sources": ["helpful_content"]},
    "very_low_visible_text": {"title": "Very Little Visible Text", "why": "If the main content is not in the HTML or rendered page, Google has little to understand or rank.", "action": "Check the rendered page; make sure the main content is present in the HTML or rendered DOM.", "sources": ["helpful_content", "javascript_seo"]},
    "duplicate_content": {"title": "Duplicate Content", "why": "Google picks one canonical URL from a set of duplicates; the others are usually not shown.", "action": "Consolidate duplicates with 301 redirects or rel=canonical to the preferred URL.", "sources": ["canonical"]},
    # Indexing / canonical
    "noindex": {"title": "Page Set to noindex", "why": "noindex tells Google to drop the page from search results.", "action": "Remove noindex if this page should appear in Google.", "sources": ["block_indexing", "robots_meta"]},
    "nofollow_directive": {"title": "Page-Level nofollow", "why": "A page-level nofollow tells Google not to follow any links on the page.", "action": "Remove the nofollow directive unless it is intentional.", "sources": ["robots_meta"]},
    "robots_meta_outside_head": {"title": "Robots Meta Tag Outside <head>", "why": "Robots meta tags belong in the <head>; placing them in the <body> makes processing unreliable.", "action": "Move the robots meta tag into the <head>.", "sources": ["robots_meta"]},
    "missing_canonical": {"title": "Missing Canonical Tag", "why": "rel=canonical tells Google which URL to show when duplicates or parameter variants exist.", "action": "Add a self-referencing rel=canonical to each indexable page.", "sources": ["canonical"]},
    "cross_domain_canonical": {"title": "Canonical Points to Another Domain", "why": "Google may index the other domain's URL instead of yours.", "action": "Confirm the cross-domain canonical is intentional.", "sources": ["canonical"]},
    "non_self_canonical": {"title": "Canonical Points to a Different URL", "why": "Google may treat this page as a duplicate and show the canonical target instead.", "action": "Confirm the canonical target is the version you want indexed.", "sources": ["canonical"]},
    "canonical_outside_head": {"title": "Canonical Tag Outside <head>", "why": "Google ignores rel=canonical found in the <body>.", "action": "Move the canonical link element into the <head>.", "sources": ["canonical"]},
    "robots_blocked": {"title": "Blocked by robots.txt", "why": "robots.txt controls crawling, not indexing; blocked URLs can still be indexed without content.", "action": "Unblock pages that should rank, and use noindex (not robots.txt) for pages that should not be indexed.", "sources": ["robots_txt", "block_indexing"]},
    "robots_missing": {"title": "robots.txt Not Found", "why": "robots.txt is optional, but it is the standard place to manage crawling and reference sitemaps.", "action": "Add a robots.txt at the site root that references your XML sitemap.", "sources": ["robots_txt"]},
    "global_block": {"title": "robots.txt Blocks the Whole Site", "why": "A site-wide Disallow stops Google crawling every page.", "action": "Remove 'Disallow: /' for Googlebot unless the site must stay hidden.", "sources": ["robots_txt"]},
    "start_blocked": {"title": "Homepage Blocked by robots.txt", "why": "Google cannot crawl the start page, so it cannot read its content or follow its links.", "action": "Allow crawling of the homepage in robots.txt.", "sources": ["robots_txt"]},
    "sitemap_missing": {"title": "XML Sitemap Not Found", "why": "Sitemaps help Google discover URLs, especially on large or new sites.", "action": "Publish an XML sitemap, reference it in robots.txt, and submit it in Search Console.", "sources": ["sitemaps"]},
    "not_in_sitemap": {"title": "Indexable Page Missing From Sitemap", "why": "Google recommends listing the canonical URLs you want indexed in the sitemap.", "action": "Add the indexable canonical URLs to the XML sitemap.", "sources": ["sitemaps"]},
    "noindex_in_sitemap": {"title": "noindex Page Listed in Sitemap", "why": "Sitemaps should list only URLs you want indexed; listing noindex URLs sends mixed signals.", "action": "Remove noindex URLs from the sitemap, or remove the noindex.", "sources": ["sitemaps", "block_indexing"]},
    "canonical_not_in_sitemap": {"title": "Canonical URL Missing From Sitemap", "why": "Sitemaps act as a canonicalization signal; they should contain the canonical URLs.", "action": "List the canonical version of each page in the sitemap.", "sources": ["sitemaps", "canonical"]},
    "sitemap_lastmod_format": {"title": "Invalid Sitemap lastmod Date", "why": "Google uses lastmod only when it is in W3C Datetime format and consistently accurate.", "action": "Use W3C Datetime (for example 2026-10-07 or 2026-10-07T10:00:00+05:30), and update it only when content really changes.", "sources": ["sitemaps"]},
    "canonical_to_error": {"title": "Canonical Points to an Error Page", "why": "A canonical that targets a 4xx/5xx URL is an invalid signal, so Google will ignore it.", "action": "Point the canonical to a live (200) URL.", "sources": ["canonical"]},
    "https_page_http_canonical": {"title": "HTTPS Page With HTTP Canonical", "why": "Google prefers HTTPS URLs as canonical; pointing to HTTP sends conflicting signals.", "action": "Use the HTTPS URL in rel=canonical.", "sources": ["canonical", "https"]},
    "duplicate_h1": {"title": "Duplicate H1 Headings Across Pages", "why": "The same main heading on many pages makes it harder to tell the pages apart.", "action": "Give each page a heading that describes its specific content.", "sources": ["starter_guide"]},
    "duplicate_hreflang": {"title": "Duplicate hreflang Values", "why": "Each language/region code should map to exactly one URL.", "action": "Remove conflicting hreflang entries.", "sources": ["hreflang"]},
    "hreflang_nonreciprocal": {"title": "hreflang Missing Return Links", "why": "Google ignores hreflang pairs unless each page links back to the other.", "action": "Add reciprocal hreflang annotations on every language version.", "sources": ["hreflang"]},
    "orphan_candidate": {"title": "Possible Orphan Page", "why": "Pages with no internal links pointing to them are hard for users and Google to discover.", "action": "Link to the page from relevant pages or navigation.", "sources": ["links"]},
    # Mobile / HTML
    "missing_viewport": {"title": "Missing Mobile Viewport Tag", "why": "Google uses mobile-first indexing; pages without a viewport tag render poorly on phones.", "action": "Add <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">.", "sources": ["mobile_first"]},
    "missing_lang": {"title": "Missing HTML Language", "why": "The lang attribute helps browsers and assistive technology handle the content correctly.", "action": "Set the document language, for example <html lang=\"en\">.", "sources": ["lang"]},
    "invalid_lang": {"title": "Invalid Language Code", "why": "Invalid language tags are ignored by browsers and assistive technology.", "action": "Use a valid BCP 47 tag such as en, en-US or si-LK.", "sources": ["lang"]},
    "missing_charset": {"title": "Missing Character Encoding", "why": "Without a declared charset, text can be displayed incorrectly.", "action": "Add <meta charset=\"utf-8\"> as early as possible in the <head>.", "sources": ["charset"]},
    "missing_main": {"title": "No <main> Landmark", "why": "Semantic landmarks improve accessibility and document structure.", "action": "Wrap the primary content in a <main> element.", "sources": ["main_landmark"]},
    "unlabelled_form_controls": {"title": "Form Fields Without Labels", "why": "Unlabelled form fields are not accessible to screen-reader users.", "action": "Associate every form control with a visible <label>.", "sources": ["form_labels"]},
    # Links
    "broken_link": {"title": "Broken Links", "why": "Broken links waste visitors' clicks and crawl activity.", "action": "Fix the link target, redirect it, or remove the link.", "sources": ["links", "http_errors"]},
    "broken_internal_links": {"title": "Broken Internal Links", "why": "Broken internal links stop users and Google from reaching your content.", "action": "Update or remove links that point to 4xx/5xx URLs.", "sources": ["links"]},
    "no_internal_links": {"title": "No Internal Links", "why": "Google discovers pages through links; pages without links are hard to find.", "action": "Add descriptive contextual links to related important pages.", "sources": ["links"]},
    "empty_anchor_text": {"title": "Links With Empty Anchor Text", "why": "Google uses anchor text to understand the linked page.", "action": "Give links descriptive text (or alt text for image links).", "sources": ["links"]},
    "generic_anchor_text": {"title": "Generic Anchor Text", "why": "Google recommends descriptive anchor text over phrases like 'click here'.", "action": "Rewrite link text to describe the destination page.", "sources": ["links"]},
    "broken_resource": {"title": "Broken Resources", "why": "Missing CSS, JS or images can break rendering for users and Google.", "action": "Fix or remove references to resources that return errors.", "sources": ["javascript_seo"]},
    # Images
    "missing_alt": {"title": "Images Missing ALT Text", "why": "Google uses alt text to understand images, and it is essential for accessibility.", "action": "Add short, descriptive alt text to meaningful images; use alt=\"\" for decorative ones.", "sources": ["images"]},
    "missing_image_dimensions": {"title": "Images Without Width/Height", "why": "Images without dimensions cause layout shifts, which hurt CLS (a Core Web Vital).", "action": "Set width and height attributes (or a CSS aspect-ratio) on images.", "sources": ["optimize_cls"]},
    "lazy_loading": {"title": "Below-the-Fold Images Not Lazy-Loaded", "why": "Lazy-loading offscreen images reduces initial page weight.", "action": "Add loading=\"lazy\" to below-the-fold images, but never to the LCP/hero image.", "sources": ["lazy_loading"]},
    "legacy_image_formats": {"title": "Legacy Image Formats", "why": "WebP and AVIF are usually much smaller than JPEG/PNG at similar quality, and Google supports both.", "action": "Serve WebP or AVIF where possible.", "sources": ["images"]},
    # Structured data / social
    "no_structured_data": {"title": "No Structured Data", "why": "Structured data helps Google understand the page and can enable rich results.", "action": "Add JSON-LD that matches the visible content (Organization, LocalBusiness, Product, Article and so on).", "sources": ["structured_data", "sd_policies"]},
    "malformed_jsonld": {"title": "Invalid Structured Data", "why": "Google cannot use JSON-LD that fails to parse.", "action": "Fix the JSON syntax and validate it with Google's Rich Results Test.", "sources": ["structured_data"]},
    "incomplete_open_graph": {"title": "Incomplete Open Graph Tags", "why": "Social platforms use og:title and og:description for link previews (not a Google ranking factor).", "action": "Add og:title, og:description, og:image and og:url.", "sources": ["open_graph"]},
    "missing_og_image": {"title": "Missing Social Share Image", "why": "Without og:image, shared links show no or a random preview image.", "action": "Add an og:image (1200x630 px works on most platforms).", "sources": ["open_graph"]},
    "og_url_mismatch": {"title": "og:url Differs From Page URL", "why": "Inconsistent og:url can split social share counts.", "action": "Set og:url to the canonical URL.", "sources": ["open_graph"]},
    "missing_twitter_card": {"title": "Missing X/Twitter Card", "why": "X/Twitter uses twitter:card to choose the link preview layout.", "action": "Add <meta name=\"twitter:card\" content=\"summary_large_image\">.", "sources": ["twitter_cards"]},
    # Performance (crawler measurements, not field data)
    "slow_response": {"title": "Slow Server Response", "why": "web.dev rates server response (TTFB) above 1.8 seconds as poor; it delays every other metric, including LCP.", "action": "Add server and page caching, a CDN, and optimize slow database or application work.", "sources": ["ttfb"], "threshold": "ttfb_poor_ms"},
    "moderate_response": {"title": "Server Response Could Be Faster", "why": "web.dev rates TTFB above 0.8 seconds as needing improvement. This was measured by the crawler, not by real users.", "action": "Profile server response time and enable caching.", "sources": ["ttfb"], "threshold": "ttfb_good_ms"},
    "large_html": {"title": "Very Large HTML", "why": "Large HTML slows download and parsing, especially on mobile.", "action": "Remove inline bloat, duplicated markup and unused embedded data.", "sources": ["page_experience"]},
    "very_high_script_count": {"title": "Too Many Scripts", "why": "Heavy JavaScript delays rendering and interactivity (INP).", "action": "Remove unused scripts, and defer or async the non-critical ones.", "sources": ["inp", "javascript_seo"]},
    "high_script_count": {"title": "Many Scripts", "why": "Many scripts can slow rendering and interactivity.", "action": "Audit the scripts and defer non-critical ones.", "sources": ["inp"]},
    "js_heavy_page": {"title": "JavaScript-Dependent Content", "why": "Google can render JavaScript, but content and links missing from the HTML depend on rendering succeeding.", "action": "Use server-side rendering or pre-rendering for important content and links.", "sources": ["javascript_seo"]},
    "transport_fallback": {"title": "Alternate Host/Protocol Needed", "why": "Inconsistent host or protocol variants can create duplicates.", "action": "301-redirect all variants (http/https, www/non-www) to one preferred origin.", "sources": ["canonical", "redirects"]},
    # Security headers (engineering signals, not ranking factors)
    "mixed_content_resource": {"title": "Mixed Content", "why": "Browsers block or warn about HTTP resources on HTTPS pages.", "action": "Load every resource over HTTPS.", "sources": ["mixed_content"]},
    "missing_hsts": {"title": "HSTS Header Missing", "why": "HSTS forces browsers to use HTTPS. It is a security measure, not a Google ranking factor.", "action": "Add Strict-Transport-Security once HTTPS works site-wide.", "sources": ["hsts"]},
    "missing_csp": {"title": "Content-Security-Policy Missing", "why": "CSP reduces XSS risk. It is a security measure, not a Google ranking factor.", "action": "Add a Content-Security-Policy suited to the site.", "sources": ["csp"]},
    "missing_x_content_type_options": {"title": "X-Content-Type-Options Missing", "why": "nosniff prevents MIME-type confusion attacks. It is a security measure, not a ranking factor.", "action": "Add X-Content-Type-Options: nosniff.", "sources": ["nosniff"]},
    # URLs / international / appearance
    "long_url": {"title": "Long URL", "why": "Google recommends simple, readable URLs.", "action": "Use short, descriptive URL paths.", "sources": ["url_structure"], "threshold": "url_long_chars"},
    "uppercase_path": {"title": "Uppercase Letters in URL", "why": "URLs are case-sensitive, so mixed case can create duplicate URLs.", "action": "Use lowercase URLs and 301-redirect uppercase variants.", "sources": ["url_structure"]},
    "tracking_params": {"title": "Tracking Parameters in URLs", "why": "Parameters create duplicate URLs that Google must consolidate.", "action": "Keep tracking parameters out of internal links and sitemaps, and canonicalize to the clean URL.", "sources": ["url_structure", "canonical"]},
    "missing_favicon": {"title": "Missing Favicon", "why": "Google shows the favicon next to your result in mobile search.", "action": "Add a favicon of at least 48x48 px, referenced with <link rel=\"icon\">.", "sources": ["favicon"]},
    # Core Web Vitals (real field data from CrUX via PageSpeed Insights)
    "cwv_lcp_poor": {"title": "Slow Largest Contentful Paint (real users)", "why": "LCP above 4.0 s at the 75th percentile is rated poor by Google; it is a Core Web Vital used in page experience.", "action": "Optimize the hero image or text block: preload it, compress it, use a CDN, and reduce render-blocking CSS/JS and server time.", "sources": ["lcp", "cwv_search"]},
    "cwv_lcp_needs_improvement": {"title": "LCP Needs Improvement (real users)", "why": "LCP between 2.5 s and 4.0 s is rated 'needs improvement' by Google.", "action": "Prioritise the LCP element (fetchpriority=\"high\"), compress images and cut server response time.", "sources": ["lcp"]},
    "cwv_inp_poor": {"title": "Slow Interaction to Next Paint (real users)", "why": "INP above 500 ms is rated poor: the page feels unresponsive to clicks and taps.", "action": "Break up long JavaScript tasks, reduce third-party scripts and avoid heavy work in event handlers.", "sources": ["inp", "cwv_search"]},
    "cwv_inp_needs_improvement": {"title": "INP Needs Improvement (real users)", "why": "INP between 200 ms and 500 ms is rated 'needs improvement' by Google.", "action": "Profile interactions in Chrome DevTools and defer non-critical JavaScript.", "sources": ["inp"]},
    "cwv_cls_poor": {"title": "Layout Shifts (real users)", "why": "CLS above 0.25 is rated poor: content jumps while the page loads.", "action": "Set image and video dimensions, reserve space for ads and embeds, and avoid inserting content above existing content.", "sources": ["cls", "optimize_cls"]},
    "cwv_cls_needs_improvement": {"title": "CLS Needs Improvement (real users)", "why": "CLS between 0.1 and 0.25 is rated 'needs improvement' by Google.", "action": "Find the shifting elements with PageSpeed Insights and reserve their space.", "sources": ["cls"]},
    "cwv_ttfb_poor": {"title": "Slow Server Response (real users)", "why": "Real-user TTFB above 1.8 s is rated poor by web.dev and delays LCP.", "action": "Use caching or a CDN and optimize backend processing.", "sources": ["ttfb"]},
    "lighthouse_seo_low": {"title": "Lighthouse SEO Checks Failing", "why": "Google's Lighthouse found basic SEO problems on this page.", "action": "Open PageSpeed Insights and fix the failed SEO audits it lists.", "sources": ["pagespeed_api"]},
}


def source_entries(keys: list[str]) -> list[dict[str, str]]:
    return [SOURCES[k] for k in keys if k in SOURCES]


def get_rule(code: str) -> dict[str, Any] | None:
    rule = RULES.get((code or "").strip().lower())
    if not rule:
        return None
    out = dict(rule)
    out["source_links"] = source_entries(rule.get("sources", []))
    if rule.get("threshold") in THRESHOLDS:
        t = THRESHOLDS[rule["threshold"]]
        out["threshold_info"] = {"value": t["value"], "basis": t["basis"], "note": t["note"]}
    return out


def enrich_issue(issue: dict[str, Any]) -> dict[str, Any]:
    """Attach knowledge-base guidance and citations to an audit issue (in place)."""
    rule = get_rule(issue.get("code", ""))
    if not rule:
        return issue
    links = rule["source_links"]
    issue.setdefault("kb_title", rule["title"])
    issue.setdefault("kb_why", rule["why"])
    issue.setdefault("kb_action", rule["action"])
    if links:
        issue.setdefault("reference", links[0]["url"])
        issue.setdefault("reference_name", links[0]["name"])
        issue.setdefault("references", links)
    if rule.get("threshold_info"):
        issue.setdefault("threshold_basis", rule["threshold_info"]["basis"])
        issue.setdefault("threshold_note", rule["threshold_info"]["note"])
    return issue


def knowledge_base_export() -> dict[str, Any]:
    """Serializable view of the knowledge base for the /api/seo-knowledge endpoint."""
    return {
        "rules": {code: get_rule(code) for code in sorted(RULES)},
        "thresholds": THRESHOLDS,
        "core_web_vitals": CWV_THRESHOLDS,
        "sources": SOURCES,
        "policy": "Thresholds marked basis=google come from Google Search Central or web.dev. basis=convention means Google publishes no fixed number and the value is a widely used guideline.",
    }
