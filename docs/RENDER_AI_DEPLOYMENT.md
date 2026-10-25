# Render Production Deployment & Security Guide

## 1. Overview
This guide provides exact, step-by-step instructions for deploying the Gemma 4 AI Intelligence and RAG Knowledge System on Render without breaking existing infrastructure, databases, or client workspaces.

---

## 2. Security Hardening (Database Credentials)

### 2.1 Critical Action Completed
* Hardcoded MongoDB connection strings have been completely removed from `render.yaml` and `scripts/migrate_to_mongo.py`.
* In `render.yaml`, `DATABASE_URL` is marked with `sync: false`, enforcing private environment injection in Render's dashboard.
* Application logs use `mask_connection_string()` to prevent credential exposure in log streams.

### 2.2 Rotating the Compromised Credential in MongoDB Atlas
1. Log in to [MongoDB Atlas Console](https://cloud.mongodb.com/).
2. Navigate to **Database Access** -> Select user `seoesupport_db_user`.
3. Click **Edit** -> **Edit Password** -> Generate a secure new password.
4. Update the connection string in your Render Environment Settings (under `DATABASE_URL`).
5. Terminate all active database sessions in MongoDB Atlas **Network Access** if needed.

---

## 3. Render Web Service Configuration

In Render Dashboard -> **Environment Variables**:

| Variable Key | Recommended Production Value | Required? | Purpose |
| :--- | :--- | :--- | :--- |
| `APP_ENV` | `production` | Yes | Enforces production security headers and logging |
| `DATABASE_URL` | `mongodb+srv://user:pass@cluster.../seo_platform?retryWrites=true&w=majority` | Yes | MongoDB Atlas connection string |
| `CORS_ORIGINS` | `https://esupport.live,https://www.esupport.live` | Yes | Restricts browser cross-origin requests |
| `AI_PROVIDER` | `auto` | Yes | Resolves hosted Gemma 4 or Gemini API based on key |
| `AI_MODEL_ID` | `gemma4:31b` | Yes | Target model identifier |
| `AI_API_KEY` | `[PRIVATE SECRET]` | Yes | API authentication key |
| `AI_TIMEOUT_SECONDS` | `45` | No (default: 45) | Maximum latency before serving fallback |
| `AI_RAG_ENABLED` | `true` | Yes | Enables dynamic BM25 knowledge retrieval |
| `AI_VALIDATION_ENABLED` | `true` | Yes | Enables post-generation recommendation verifier |
| `AI_FALLBACK_ENABLED` | `true` | Yes | Enables deterministic knowledge-base fallback |

---

## 4. Database Syncing & Migration Command

If migrating or restoring historical audits from local SQLite to MongoDB Atlas:
```bash
# Run migration script with secure environment injection
DATABASE_URL="mongodb+srv://<USER>:<PASSWORD>@cluster0.wvoxrnq.mongodb.net/seo_platform?retryWrites=true&w=majority" \
python scripts/migrate_to_mongo.py
```
This migrates all 35 audits, 4 clients, 4 websites, 16 public reports, and 17 leads into MongoDB Atlas.

---

## 5. Post-Deployment Verification Checklist

1. **API Health**: Query `GET /api/health` -> verify status is `ok`.
2. **AI Model Client**: Query `GET /api/admin/ai/status` -> verify status is `MODEL_AVAILABLE`.
3. **RAG Knowledge Base**: Query `GET /api/admin/ai/knowledge` -> verify 13 documents indexed.
4. **Dashboard Telemetry**: Load dashboard -> verify total audits, average score, and recent audits list render smoothly.

