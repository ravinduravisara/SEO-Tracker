# Gemma 4 & Google GenAI API Configuration Guide

## 1. Overview
The SEO Tracker AI integration connects directly to production-grade hosted Gemma 4 or Google Gemini models via secure REST endpoints. It supports standard Bearer token authorization, environment configuration, bounded retries, and token budgets.

---

## 2. Supported Providers & Models

| Provider Mode | Environment Variable `AI_PROVIDER` | Default Model ID `AI_MODEL_ID` | Authentication |
| :--- | :--- | :--- | :--- |
| **Hosted Gemma 4** | `hosted_gemma` or `gemma4` | `gemma4:31b` | Bearer Token via `AI_API_KEY` or `OLLAMA_API_KEY` |
| **Google GenAI / Gemini**| `gemini` | `gemini-2.5-flash` | API Key via `AI_API_KEY` or `GEMINI_API_KEY` |
| **Auto-Detect** | `auto` (Default) | Automatically resolves based on key format and model ID | Header Detection |
| **Deterministic Fallback**| N/A | Deterministic Engine | None (Zero external dependencies) |

---

## 3. Environment Variables Configuration

Add the following variables to your `.env` file or Render Environment Settings:

```bash
# Model Provider Configuration
AI_PROVIDER=auto
AI_MODEL_ID=gemma4:31b
AI_API_KEY=your_production_api_key_here

# Custom Endpoint (Optional for hosted private instances)
AI_API_ENDPOINT=https://your-hosted-gemma-gateway.com/api/generate

# Network & Latency Budgets
AI_TIMEOUT_SECONDS=45
AI_MAX_RETRIES=3

# Token & Cost Management
AI_MAX_INPUT_TOKENS=6000
AI_MAX_OUTPUT_TOKENS=2048

# Feature Flags
AI_RAG_ENABLED=true
AI_VALIDATION_ENABLED=true
AI_FALLBACK_ENABLED=true
```

---

## 4. API Key Rotation Procedure

1. **Generate New Key**: Obtain the rotated API key from your hosted model provider or Google Cloud Console.
2. **Update Render Environment**:
   - In Render Dashboard -> Navigate to your Web Service -> **Environment**.
   - Update `AI_API_KEY` with the new credential.
   - Click **Save Changes**. Render will automatically trigger a zero-downtime rolling restart.
3. **Verify Health**:
   - Query the health endpoint: `GET /api/admin/ai/status`
   - Confirm status reports `MODEL_AVAILABLE`.

---

## 5. Status Diagnostics

The system continuously tracks runtime status:
* `MODEL_AVAILABLE`: Model is answering and within latency threshold.
* `MODEL_RATE_LIMITED`: HTTP 429 received; exponential backoff active.
* `MODEL_AUTHENTICATION_FAILED`: HTTP 401/403 received; retries aborted to prevent lockouts.
* `MODEL_UNAVAILABLE`: Network timeout or connection refusal; deterministic fallback active.

