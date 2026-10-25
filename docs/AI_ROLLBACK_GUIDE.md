# AI Upgrade Safe Rollback & Failure Recovery Guide

## 1. Overview
The hybrid AI system is architected to guarantee zero-downtime, continuous availability, and safe fallback under all failure scenarios. If external AI endpoints experience latency spikes, rate limits, or outages, the platform gracefully switches to deterministic evaluation without interrupting user workflows.

---

## 2. Automatic Runtime Failover Mechanisms

### 2.1 Provider Outage / Network Timeout
* If the remote Gemma 4 or Gemini API fails to respond within `AI_TIMEOUT_SECONDS` (default: 45s), the client times out.
* The system logs a warning, switches status to `MODEL_UNAVAILABLE`, and automatically serves deterministic recommendations generated from verified audit signals.
* Client-facing HTTP responses return `200 OK` with `"ai_generated": false` and `"source_model": "Deterministic SEO Knowledge Engine"`.

### 2.2 Rate Limiting (HTTP 429)
* Exponential backoff with random jitter retries the request up to 3 times ($0.5\text{s}, 1.2\text{s}, 2.5\text{s}$).
* If all retries fail, status changes to `MODEL_RATE_LIMITED` and deterministic fallback advice is served.

### 2.3 Authentication / Key Failure (HTTP 401 / 403)
* Retries are immediately terminated to avoid account lockout.
* Status changes to `MODEL_AUTHENTICATION_FAILED`.
* An administrative alert is recorded and fallback recommendations are delivered.

---

## 3. Manual Feature Flag Rollback (Instant Disablement)

If you need to instantly disable all external AI calls and force 100% local deterministic operation:

In Render Dashboard -> **Environment Variables**:
```bash
# Disable external AI and enforce local knowledge-base fallback
AI_RAG_ENABLED=false
AI_FALLBACK_ENABLED=true
AI_PROVIDER=deterministic
```
Click **Save Changes**. The server will immediately serve purely local, deterministic recommendations with zero external API calls.

---

## 4. Git Branch Rollback (Code Reversion)

If a code-level reversion is necessary:
```bash
# 1. Inspect current branch
git checkout feat/gemma4-rag-intelligence

# 2. Check git log for the baseline commit prior to AI changes
git log -n 5 --oneline

# 3. If needed, switch back to main
git checkout main

# 4. Verify all tests pass
./.venv/bin/python -m unittest discover tests
```
The codebase preserves strict backward compatibility with all historical database schemas, report formats, and REST APIs.

