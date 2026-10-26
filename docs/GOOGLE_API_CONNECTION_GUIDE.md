# Google Search Console & GA4 Connection Guide

This guide details the complete configuration process for integrating **Google Search Console** and **Google Analytics 4 Data API** with **SEO Tracker / Aviance SEO Pro Max**.

---

## 1. Authentication Architecture

The application uses an authorized **Google Cloud Service Account** to communicate with both Search Console and GA4:
- **Search Console API Scope**: `https://www.googleapis.com/auth/webmasters.readonly`
- **Google Analytics 4 Scope**: `https://www.googleapis.com/auth/analytics.readonly`

This server-to-server connection requires no end-user redirects and enables scheduled telemetry collection, real-time dashboards, and client reporting.

---

## 2. Setting Up the Google Service Account

### Step 1: Create a Google Cloud Project
1. Go to [Google Cloud Console](https://console.cloud.google.com/).
2. Select or create a project (e.g., `SEO-Tracker-Integration`).
3. Enable the following APIs in **APIs & Services > Library**:
   - **Google Search Console API**
   - **Google Analytics Data API** (v1beta)
   - **PageSpeed Insights API** (Optional)

### Step 2: Create a Service Account
1. In Google Cloud Console, navigate to **IAM & Admin > Service Accounts**.
2. Click **Create Service Account**.
3. Name the account (e.g., `seo-tracker-reader`).
4. Click **Create and Continue**. (No IAM project roles are required; permissions are granted directly on individual web properties).
5. Click **Done**.
6. Note the **Service Account Email** (e.g., `seo-tracker-reader@seo-tracker-integration.iam.gserviceaccount.com`).

### Step 3: Generate the JSON Key
1. Click on the created service account.
2. Select the **Keys** tab > **Add Key** > **Create new key**.
3. Select **JSON** and download the key file.
4. Keep this file private and never commit it to Git.

---

## 3. Configuring the Application

### Option A: Via Environment Variable (Recommended for Render)
Paste the full JSON content into `GSC_SERVICE_ACCOUNT_JSON` in Render's Environment Variables:
```bash
GSC_SERVICE_ACCOUNT_JSON='{"type": "service_account", "project_id": "...", ...}'
```

### Option B: Via Local Key File (Development)
Save the JSON file locally and configure its path in `.env`:
```bash
GSC_SERVICE_ACCOUNT_FILE="./keys/google_service_account.json"
```

---

## 4. Authorizing Web Properties

### Authorizing Google Search Console
1. Open [Google Search Console](https://search.google.com/search-console).
2. Select the target property (e.g., `https://esupport.live/` or `sc-domain:esupport.live`).
3. Go to **Settings** > **Users and permissions**.
4. Click **Add user**.
5. Enter the **Service Account Email**.
6. Set permission to **Restricted** or **Full** (Read-only access is used by the app).
7. Save.

### Authorizing Google Analytics 4
1. Open [Google Analytics](https://analytics.google.com/).
2. Navigate to **Admin** (gear icon in lower left).
3. Under the **Property** column, click **Property Access Management**.
4. Click the blue **+** button in the top right > **Add users**.
5. Enter the **Service Account Email**.
6. Assign the **Viewer** role.
7. Note the **Property ID** shown under **Property Settings > Property Details** (e.g., `123456789`).

---

## 5. Linking Properties to Client Websites

In the SEO Tracker application:
1. Navigate to **Google & Performance** or click **Clients > [Target Website]**.
2. Open **Configure Google Connections**.
3. Set the **Search Console Property** (e.g. `sc-domain:esupport.live` or `https://esupport.live/`).
4. Set the **GA4 Property ID** (numeric ID).
5. Click **Save & Test Connection**.
6. The ribbon will immediately display `✓ Connected` upon successful authorization.

---

## 6. Multi-Tenant Security & Tenant Isolation

- **Client Isolation**: Client accounts are strictly sandboxed. The application enforces database-level authorization checks on all `/api/google/*` routes to prevent cross-client data leakage.
- **Credential Protection**: Private keys and service account tokens are never returned to frontend JavaScript and are never exposed in audit logs.
- **Accurate Metric Labeling**: Search Console average position is clearly labeled as aggregated query impressions over time, not an exact live rank. GA4 sessions are kept distinct from Search Console clicks.

