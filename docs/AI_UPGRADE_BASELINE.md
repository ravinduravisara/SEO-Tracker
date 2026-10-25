# Production Baseline & AI Upgrade Architecture Report

**Project:** SEO Tracker / Aviance SEO Pro Max  
**Date:** October 25, 2026  
**Git Baseline Commit:** `8155351e69bab5841f0b25a73c55dd3235655cf3`  
**Development Branch:** `feat/gemma4-rag-intelligence`  
**Hosting Environment:** Render Web Service (`aviance-seo-backend`)  
**Backend Framework:** Python 3.15 + FastAPI + Uvicorn  
**Database Engines:** SQLite (`seo_platform.db` local/persistent) / MongoDB Atlas (`IS_MONGO` native ODM)  

---

## 1. Security & Credential Isolation (Task 0.1)

### Status of Exposed Credentials
* **Finding:** `render.yaml` previously contained a plain-text MongoDB Atlas connection string with embedded username and password. `scripts/migrate_to_mongo.py` also contained a duplicate connection string.
* **Remediation Applied:**
  1. `render.yaml` updated: `DATABASE_URL` and `CORS_ORIGINS` configured with `sync: false`. No connection strings remain in version control.
  2. `scripts/migrate_to_mongo.py` updated: Reads `DATABASE_URL` or `MONGO_URI` strictly from environment variables.
  3. `backend/database.py` updated: Added `mask_connection_string()` ensuring any URI diagnostics or logs mask passwords (`mongodb+srv://user:****@host`).
  4. `.env.example` updated with complete configuration flags and no secrets.

### Credential Rotation Procedure (Action Required by Administrator)
1. **Rotate MongoDB Password in Atlas:**
   * Log into MongoDB Atlas Dashboard.
   * Navigate to **Database Access** -> **Database Users**.
   * Edit user `seoesupport_db_user` and click **Edit Password**.
   * Generate a new cryptographically secure password (at least 24 characters).
   * Save changes.
2. **Update Render Environment Variable:**
   * Go to Render Dashboard -> `aviance-seo-backend` -> **Environment**.
   * Update `DATABASE_URL` to the new connection string with the rotated password.
   * Trigger **Manual Deploy** -> **Clear build cache & deploy**.
3. **Optional Git History Scrubbing:**
   * If the repository is public or shared outside trusted team members, use `git-filter-repo` or BFG Repo-Cleaner to purge historical commits containing the old credential:
     ```bash
     bfg --replace-text passwords.txt
     git reflog expire --expire=now --all && git gc --prune=now --aggressive
     ```

---

## 2. Active Application Structure & Components

```
SEO-Tracker/
├── backend/
│   ├── main.py                  # FastAPI server, core audit endpoints, rate limiting, CORS
│   ├── database.py              # Dual SQLite/MongoDB ORM/ODM, session management
│   ├── security.py              # Password hashing, JWT/token auth, admin RBAC
│   ├── ai_advisor.py            # AI advisory routines, category summaries, prompt handling
│   ├── seo_knowledge.py         # Deterministic SEO rules, thresholds, and primary source citations
│   ├── integrations.py          # PageSpeed (CrUX), Search Console, DataForSEO, OpenPageRank
│   ├── keyword_engine.py        # Keyword research, search intent, clustering, export engine
│   ├── competitor_engine.py     # Competitor domain comparison & visibility analysis
│   ├── backlink_engine.py       # Backlink analytics, toxicity scoring, anchor text distribution
│   ├── rank_tracker.py          # Position tracking, SERP features, volatility monitoring
│   └── seo_engine/              # Deterministic check execution and scoring engine
├── frontend/
│   ├── index.html               # Main dashboard UI
│   ├── report.html              # Client-facing interactive report
│   ├── seo-check.html           # Public lightweight SEO checker
│   ├── app.js                   # Client portal logic, KPI charts, report viewers
│   └── css/                     # Styling and layout
├── render.yaml                  # Render Infrastructure-as-Code blueprint
└── tests/                       # Automated test suite (176 tests)
```

---

## 3. Active AI Integration Baseline

| Parameter | Current Value / Baseline |
| :--- | :--- |
| **Active Model** | `gemma4:31b` (Gemma 4 family) |
| **Configured Provider** | Hosted Gemma 4 API with Bearer token authentication |
| **API Endpoint** | Configurable via `AI_ENDPOINT` / `OLLAMA_URL` |
| **Authentication** | Server-side Bearer token / API key |
| **Deterministic Fallback** | Comprehensive deterministic rule-based advice when AI endpoint is unreachable |
| **Zero-Fabrication Guard** | Strict rule that measured scores, rankings, and traffic numbers are never modified by AI |

---

## 4. Current Test Suite Status
* **Ran:** `python -m unittest discover tests`
* **Test Count:** 176 tests
* **Result:** 100% Passed (`OK` in 1.813s)
* **Categories Tested:**
  * Phase 1: Security & Accuracy
  * Phase 2: Technical SEO Crawling
  * Phase 3: Domain Overview
  * Phase 4: Keyword Research
  * Phase 5: Competitor Analysis
  * Phase 6: SEO Accuracy Verification & Backlink Analytics
  * Phase 7: Google Integrations (CrUX, GSC)
  * Phase 8: Rank Tracking
  * Phase 9: AI SEO Advisory & Evidence Extraction
  * Phase 10: Professional Client Reports
  * Phase 11: Modern Analytics Dashboard

---

## 5. Render Deployment Baseline
* **Service Name:** `aviance-seo-backend`
* **Type:** Web Service (`free` plan compatible)
* **Runtime:** Python
* **Build Command:** `pip install -r requirements.txt`
* **Start Command:** `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
* **Key Environment Variables:**
  * `APP_ENV=production`
  * `DATABASE_URL` (Private, `sync: false`)
  * `CORS_ORIGINS` (Private, `sync: false`)
  * `AI_PROVIDER=auto`
  * `AI_MODEL_ID=gemma4:31b`
  * `AI_API_KEY` (Private, `sync: false`)
  * `AI_RAG_ENABLED=true`
  * `AI_VALIDATION_ENABLED=true`
  * `AI_FALLBACK_ENABLED=true`

