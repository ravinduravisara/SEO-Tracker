# Render Free Production Deployment Guide (Phase 8)

This guide documents the production deployment architecture for **SEO Tracker / Aviance SEO Pro Max** on **Render Free**.

---

## 1. Hosting Architecture & Render Free Constraints

| Constraint | Value | Mitigation Strategy in Application |
| :--- | :--- | :--- |
| **Memory Limit** | 512 MB RAM | Bounded worker pools (`ThreadPoolExecutor(max_workers=6)`), streaming PDF generation via `io.BytesIO`, no large local LLMs or embeddings in memory. |
| **CPU Sharing** | Shared vCPU | Respectful non-blocking asynchronous network requests with exponential backoff and timeouts. |
| **Inactivity Sleep** | Spins down after 15m idle | Health probe keeps application ready; rapid warm-up (<2s); lightweight FastAPI initialization. |
| **Ephemeral Filesystem** | Files wiped on redeploy | All critical state (clients, audits, public reports, branding, connection status) stored in MongoDB Atlas via `DATABASE_URL`. |

---

## 2. Environment Variables Configuration

Set these variables in the **Render Dashboard > Environment** tab:

### Core Application & Security
```bash
APP_ENV="production"
PORT="8000"
CORS_ORIGINS="https://esupport.live,https://www.esupport.live"
DATABASE_URL="mongodb+srv://<USER>:<PASSWORD>@cluster0.wvoxrnq.mongodb.net/seo_platform?retryWrites=true&w=majority"
PUBLIC_REPORT_BASE_URL="https://esupport.live"
RATE_LIMIT_PER_MINUTE="30"
```

### AI Intelligence (Gemma 4 API + RAG)
```bash
AI_PROVIDER="auto"
AI_MODEL_ID="gemma4:31b"
AI_API_KEY="your_hosted_gemma4_api_key"
AI_RAG_ENABLED="true"
AI_VALIDATION_ENABLED="true"
AI_FALLBACK_ENABLED="true"
```

### Free External SEO APIs (Phase 8)
```bash
# Google PageSpeed Insights & CrUX
PAGESPEED_API_KEY="AIzaSyYourGoogleApiKey"
PAGESPEED_TIMEOUT="90"

# Google Search Console & GA4 Data API (Paste Service Account JSON string)
GSC_SERVICE_ACCOUNT_JSON='{"type":"service_account","project_id":"...","private_key":"...","client_email":"..."}'

# Bing Webmaster Tools REST API
BING_API_KEY="your_bing_webmaster_key"

# Ahrefs Free Domain Rating API (v3)
AHREFS_API_KEY="your_ahrefs_api_v3_token"

# Open PageRank (DomCop)
OPENPAGERANK_API_KEY="your_domcop_key"

# Integration Caching (Hours)
INTEGRATION_CACHE_HOURS="24"
```

---

## 3. Deployment Steps

1. **Push Changes to GitHub**:
   Ensure `main` is updated and all automated regression tests pass:
   ```bash
   ./.venv/bin/python -m unittest discover tests
   ```

2. **Trigger Render Build**:
   Render is configured to automatically build and deploy from the `main` branch:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`

3. **Verify Deployment Health**:
   Execute HTTP health probe:
   ```bash
   curl -s https://<your-render-app>.onrender.com/api/health
   ```
   Expected response:
   ```json
   {
     "status": "healthy",
     "app": "Aviance SEO Pro Max",
     "version": "10.4.0",
     "database": "mongodb"
   }
   ```

---

## 4. Rollback Procedure

If any deployment issue arises:
1. In Render Dashboard, click **Deploys**.
2. Locate the previous successful deploy.
3. Click **Rollback to this deploy**.
4. The database remains completely safe because no destructive migrations were executed.
