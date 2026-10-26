# Ahrefs Free Domain Rating API Setup Guide

This guide details how to configure the **Ahrefs Free Domain Rating API (v3)** and Ahrefs Webmaster Tools within **SEO Tracker / Aviance SEO Pro Max**.

---

## 1. Metric Definition & Authority Context

**Domain Rating (DR)** is a proprietary third-party metric developed by Ahrefs that calculates the relative strength of a website's backlink profile on a logarithmic scale from 0 to 100:
- It is based on the quantity and quality of unique linking root domains in Ahrefs' web index.
- **Critical Distinction**: Domain Rating is **not a Google ranking factor** and must never be represented to clients as a search engine score.
- **Distinction from Open PageRank**: Open PageRank is calculated from the open Common Crawl graph on a 0-10 scale. Ahrefs DR uses Ahrefs' proprietary index on a 0-100 scale. Both metrics are displayed separately with clear source labeling.

---

## 2. Mandatory Provider Attribution

In accordance with Ahrefs developer guidelines and terms of service, all representations of Domain Rating within dashboards, public web links, and exported PDF reports must include the explicit attribution:
> **Domain Rating by Ahrefs**

The application automatically embeds this attribution into all visual badges, tables, and ReportLab PDF documents.

---

## 3. Obtaining an API v3 Token

1. Sign in to the [Ahrefs Developer Console](https://ahrefs.com/api).
2. Users with an active **Ahrefs Webmaster Tools (AWT)** account for verified websites have access to the free API v3 endpoints.
3. In the Developer Portal, create an API v3 App or Token.
4. Set permissions to include `site-explorer:domain-rating:read`.
5. Copy the generated API Bearer Token.

---

## 4. Configuring the Token

### Option A: Environment Variable (Server-Wide)
Add to your `.env` file or Render environment settings:
```bash
AHREFS_API_KEY="your_ahrefs_api_v3_bearer_token"
```

### Option B: Via Web UI
1. Navigate to **Google & Performance** or the Administration portal.
2. Click **⚙️ API Connections**.
3. Under **Ahrefs Free Domain Rating API (v3)**, paste your token.
4. Click **Save API Keys**.

---

## 5. Free API Boundaries & Backlink Explorer Fallback

The free Ahrefs Domain Rating endpoint provides:
- Target Domain Rating (`domain_rating`, 0.0 - 100.0)
- Global Ahrefs Rank (`ahrefs_top`)

It does **not** include:
- Complete lists of referring domains
- Granular live backlinks
- Competitor search traffic estimates

When a user requests full backlink row tables without a paid DataForSEO Backlinks subscription, the application strictly adheres to the **Zero Fabrication Rule** and displays:
```
BACKLINK DATA PROVIDER REQUIRED
Connect DataForSEO or an enterprise backlink provider to view live backlink records.
Verified on-site internal link equity calculations are displayed below.
```
