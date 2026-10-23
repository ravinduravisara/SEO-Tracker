# Real Data Setup

The tool can pull real SEO data from three providers. Put the keys in a `.env` file in the project folder (next to `requirements.txt`; copy `.env.example` to get started), then restart with `run.ps1`.

---

## 1. Google PageSpeed Insights: Core Web Vitals + Lighthouse (FREE)

You must have a key. Without one, Google's shared quota is almost always used up (HTTP 429).

1. Go to https://console.cloud.google.com/ and create a project (or pick an existing one).
2. Open **APIs & Services → Library**, search for **PageSpeed Insights API**, and click **Enable**.
3. Open **APIs & Services → Credentials → Create credentials → API key**.
4. Optional: restrict the key to "PageSpeed Insights API".
5. Add it to `.env`:
   ```
   PAGESPEED_API_KEY=AIza...
   ```

Free quota: 25,000 requests per day. Each audit uses 2 (mobile + desktop).

## 2. Google Search Console: clicks, impressions, CTR, positions (FREE)

This works only for sites whose Search Console property you (or your client) can access.

1. In the same Google Cloud project, open **APIs & Services → Library**, find **Google Search Console API**, and click **Enable**.
2. Open **IAM & Admin → Service Accounts → Create service account**. Any name works, for example `seo-tool`.
3. Open the service account, go to **Keys → Add key → Create new key → JSON**, and save the downloaded file in the project folder, for example `gsc-key.json`. **Do not commit it to git.**
4. Copy the service account email (`seo-tool@your-project.iam.gserviceaccount.com`).
5. For **each website**: open https://search.google.com/search-console, then **Settings → Users and permissions → Add user**. Paste the email and choose the **Restricted** permission.
6. Add to `.env`:
   ```
   GSC_SERVICE_ACCOUNT_FILE=gsc-key.json
   ```
   On Vercel or Docker, put the whole JSON content in `GSC_SERVICE_ACCOUNT_JSON` instead.

The tool finds the matching property automatically. It prefers the `sc-domain:example.com` property, then a URL-prefix property for the same host. It uses the last 28 days of final data, which ends 3 days ago because Search Console data lags.

## 3. Open PageRank: Off-Page / Backlinks score (FREE)

1. Register at https://www.domcop.com/openpagerank/ and copy your API key.
2. Add it to `.env`:
   ```
   OPENPAGERANK_API_KEY=xxxxxxxx
   ```

The Off-Page percentage is Open PageRank × 10. Open PageRank is a 0-10 link-authority score computed from the Common Crawl link graph. Without a key, Off-Page shows "Not Measured" and is left out of the overall score.

## 4. Ollama: plain-language explanations (FREE, local)

1. Ollama is already installed. Download the model once:
   ```
   ollama pull gemma3
   ```
2. With Ollama running, admin audits with "Ollama AI Recommendations" ticked, and all public `/seo-check` scans (`PUBLIC_SCAN_AI=1`), get a short explanation per category written for business owners.

Ollama only rewrites the measured check results into simple words. It never sets or changes a percentage. If Ollama is not running, the cards show the factual check summary instead.

## How the 8 category percentages are calculated

Each category is a list of concrete checks, for example "8 of 8 pages use HTTPS" or "Core Web Vitals: 2 of 3 rated good". The percentage is the weighted share of checks passed. Anything that could not be measured is left out instead of guessed. Customers can open "See what was checked" on every card. The overall score is the weighted average of the measured categories:

| Category | Weight |
|---|---|
| Technical | 25 |
| On-Page | 20 |
| Content | 15 |
| Keyword & Search Intent | 10 |
| Internal Linking | 10 |
| Off-Page | 10 |
| Local | 5 |
| E-commerce | 5 |

Local SEO and E-commerce show "Not Applicable" when the site has no local-business or shop signals.

## 5. DataForSEO: search volume, keyword difficulty, rankings, backlinks (PAID, optional, not needed)

1. Sign up at https://dataforseo.com/ (pay-as-you-go; the minimum top-up is about $50).
2. Copy your **API login** and **API password** from https://app.dataforseo.com/api-access. These are not your website login.
3. Backlinks need the **Backlinks API** subscription, enabled separately in the dashboard. Without it, the other DataForSEO data still works and backlinks show the API error.
4. Add to `.env`:
   ```
   DATAFORSEO_LOGIN=you@example.com
   DATAFORSEO_PASSWORD=xxxxxxxx
   DATAFORSEO_LOCATION_CODE=2144   # Sri Lanka. 2840 = US, 2826 = UK, 2036 = Australia
   DATAFORSEO_LANGUAGE_CODE=en
   ```

DataForSEO costs money, so it is **off by default**. Tick **"DataForSEO (paid)"** in the audit options to use it for an audit. Each audit makes about 4 calls (ranked keywords, keyword overview, backlink summary, referring domains). The cost is shown in the Real Data tab. Identical calls are cached for `INTEGRATION_CACHE_HOURS` (default 24).

---

## Check it works

- Admin API: `GET /api/integrations/status` shows which providers are configured and the service account email.
- Run an audit, then open the **Real Data** tab. Errors (wrong key, property not shared, no credit) are shown there word for word.
- Single lookups (admin only):
  - `POST /api/integrations/pagespeed` `{"url": "...", "strategy": "mobile"}`
  - `POST /api/integrations/search-console` `{"url": "...", "days": 28}`
  - `POST /api/integrations/keywords` `{"keywords": ["..."], "location_code": 2144}`
  - `POST /api/integrations/rankings` `{"url": "..."}`
  - `POST /api/integrations/backlinks` `{"url": "..."}`
- Knowledge base: `GET /api/seo-knowledge` returns every rule, threshold and source link.

Public lead-gen scans (`/seo-check`) never call these providers, so private Search Console data and paid credits are never exposed to anonymous visitors.
