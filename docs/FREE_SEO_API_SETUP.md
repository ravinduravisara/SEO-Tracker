# Free SEO API Setup Guide

This guide explains how to obtain, configure, and verify all supported free SEO APIs in **SEO Tracker / Aviance SEO Pro Max**.

---

## 1. Supported Free Providers Overview

| Provider | Purpose | Metric Scope | API Cost | Setup Time |
| :--- | :--- | :--- | :--- | :--- |
| **Google PageSpeed Insights** | Lighthouse lab audits & performance scores | Mobile & Desktop | Free (25,000 req/day) | 2 mins |
| **Google Chrome UX Report (CrUX)** | Real-user Core Web Vitals (p75, 28-day rolling) | LCP, INP, CLS, FCP, TTFB | Free with Google Cloud key | 2 mins |
| **Google Search Console** | Verified search performance & rankings | Clicks, Impressions, CTR, Avg Position | Free (Service Account) | 5 mins |
| **Google Analytics 4** | Real website traffic & user engagement | Sessions, Users, Engagement Rate | Free (Data API v1beta) | 5 mins |
| **Bing Webmaster Tools** | Bing search performance & crawl statistics | Clicks, Impressions, Crawl Stats | Free (API Key) | 3 mins |
| **Ahrefs Free Domain Rating** | Third-party domain authority (0-100 scale) | Domain Rating (DR) & Ahrefs Rank | Free (API v3 token) | 3 mins |
| **Open PageRank** | Common Crawl link graph authority (0-10 scale) | Open PageRank decimal & global rank | Free (DomCop key) | 2 mins |

---

## 2. Google PageSpeed Insights & CrUX

### Obtaining an API Key
1. Visit the [Google Cloud Console Credentials Page](https://console.cloud.google.com/apis/credentials).
2. Create a new Google Cloud project (e.g. `SEO-Tracker-Telemetry`).
3. Enable the **PageSpeed Insights API** and **Chrome UX Report API** in the API Library.
4. Click **Create Credentials** > **API Key**.
5. (Optional but recommended) Restrict the API key to `PageSpeed Insights API` and `Chrome UX Report API`.

### Environment Configuration
Add to `.env` or Render environment settings:
```bash
PAGESPEED_API_KEY="AIzaSyYourGeneratedApiKeyHere"
PAGESPEED_TIMEOUT=90
```

> [!NOTE]
> If `PAGESPEED_API_KEY` is omitted, the application uses Google's public anonymous quota. A dedicated key is recommended for production deployment to prevent 429 rate limiting.

---

## 3. Bing Webmaster Tools API

### Obtaining an API Key
1. Log in to [Bing Webmaster Tools](https://www.bing.com/webmasters) with your Microsoft account.
2. Ensure your target website is verified in Bing Webmaster Tools.
3. Click the gear icon (**Settings**) in the top right.
4. Navigate to **API Access** > **API Key**.
5. Click **Generate API Key** and copy the string.

### Environment Configuration
```bash
BING_API_KEY="your_32_character_bing_api_key_here"
```

---

## 4. Ahrefs Free Domain Rating API (v3)

### Obtaining an API Key
1. Go to [Ahrefs Developer Portal](https://ahrefs.com/api).
2. Sign in to your Ahrefs account (Ahrefs Webmaster Tools accounts have free API access).
3. Generate an API v3 Token with `site-explorer:domain-rating:read` permission.
4. Copy the bearer token.

### Environment Configuration
```bash
AHREFS_API_KEY="ahrefs_api_v3_bearer_token"
```

### Attribution & Limitations
- **Mandatory Attribution**: All Ahrefs measurements display `Domain Rating by Ahrefs`.
- **Limitation**: The free DR endpoint provides domain authority and global rank. It does not provide granular backlink lists. When full link tables are requested without a paid provider, the application cleanly displays `BACKLINK DATA PROVIDER REQUIRED`.

---

## 5. Open PageRank (DomCop)

### Obtaining an API Key
1. Register for a free account at [Open PageRank](https://www.domcop.com/openpagerank/).
2. Copy your free API Key from the dashboard.

### Environment Configuration
```bash
OPENPAGERANK_API_KEY="your_domcop_openpagerank_key"
```

---

## 6. Testing Connections Locally

To verify all provider connections, run the automated integration test suite:
```bash
./.venv/bin/python -m unittest tests/test_phase8_free_seo_apis.py
```
Or check connection statuses directly through the web UI under **Google & Performance > ⚙️ API Connections**.
