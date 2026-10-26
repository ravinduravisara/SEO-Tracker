# Bing Webmaster Tools API Setup Guide

This guide describes how to configure the **Bing Webmaster Tools JSON API** for verified crawl statistics and search performance telemetry in **SEO Tracker / Aviance SEO Pro Max**.

---

## 1. Overview & Capabilities

Bing Webmaster Tools provides official search telemetry from Microsoft Bing:
- **Crawl Statistics**: Daily pages crawled by Bingbot, crawl error counts, HTTP status distribution (2xx, 3xx, 4xx, 5xx), and DNS failure rates.
- **Search Queries**: Organic search queries driving impressions and clicks on Bing, with average click and impression positions.
- **Indexation Health**: Real-time indexation diagnostics.

> [!IMPORTANT]
> Bing rankings and impressions are from Microsoft Bing and are strictly labeled as **BING SEARCH PERFORMANCE**. They are never combined with Google rankings without explicit search engine attribution.

---

## 2. Obtaining an API Key

1. Sign in to [Bing Webmaster Tools](https://www.bing.com/webmasters) using a Microsoft, Google, or Facebook account.
2. If your site is not yet added, add and verify ownership of your site (e.g. `https://esupport.live/`). Verification can be completed via DNS CNAME/TXT record, XML file, or one-click import from Google Search Console.
3. Once verified, click the **Settings** gear in the top right navigation bar.
4. Under **API Access**, select **API Key**.
5. Click **Generate API Key**.
6. Copy the resulting key string.

---

## 3. Configuring the Application

### Option A: Environment Variable (Server-Wide)
Add to your `.env` file or Render Environment Variables:
```bash
BING_API_KEY="your_32_character_bing_api_key_here"
```

### Option B: Via Web UI
1. Navigate to **Google & Performance** or the Administration portal.
2. Click **⚙️ API Connections**.
3. Under **Bing Webmaster Tools REST API**, paste your key.
4. Click **Save API Keys**.

---

## 4. Endpoints & REST Architecture

The application communicates exclusively with the modern Microsoft REST API:
- **Base Endpoint**: `https://ssl.bing.com/webmaster/api.svc/json`
- **Crawl Stats**: `GET /GetCrawlStats?siteUrl={siteUrl}&apikey={apiKey}`
- **Query Stats**: `GET /GetQueryStats?siteUrl={siteUrl}&apikey={apiKey}`

Deprecated SOAP and XML-RPC interfaces are completely avoided.

---

## 5. Error & Status Mapping

| Status Code / State | Display Status | UI Indicator | Action Required |
| :--- | :--- | :--- | :--- |
| `HTTP 200` with data | `CONNECTED` | `✓ Connected` | Telemetry active and rendered. |
| `HTTP 401 / 403` | `UNAUTHORIZED` | `⚠️ Unauthorized` | Verify API key and verify site ownership in Bing portal. |
| Empty `d` list | `NO DATA` | `No Telemetry` | Site has not accumulated recent Bing search impressions. |
| Network / Timeout | `UNAVAILABLE` | `⚠️ Unavailable` | Cached data will be displayed if within 24h TTL. |

