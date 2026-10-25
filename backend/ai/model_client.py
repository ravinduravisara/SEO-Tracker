"""
Production Model Client Interface for Gemma 4 & Hybrid AI Providers.

Supports:
- Hosted Gemma 4 API (Bearer token authentication, cloud endpoints)
- Google Gemini API (official REST / Google GenAI protocol)
- Zero-downtime deterministic fallback when external AI is unavailable
- Exponential backoff with jitter and bounded retries
- Token usage tracking, budget caps, and in-memory response caching
- Strict model status classification
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
from pydantic import BaseModel, Field

logger = logging.getLogger("aviance.ai.model_client")

# -----------------------------------------------------------------------------
# MODEL STATUS ENUM / CONSTANTS
# -----------------------------------------------------------------------------
MODEL_AVAILABLE = "MODEL_AVAILABLE"
MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
MODEL_AUTHENTICATION_FAILED = "MODEL_AUTHENTICATION_FAILED"
MODEL_RATE_LIMITED = "MODEL_RATE_LIMITED"
MODEL_RESPONSE_INVALID = "MODEL_RESPONSE_INVALID"
MODEL_RESPONSE_VERIFIED = "MODEL_RESPONSE_VERIFIED"


class AIUsageMetrics(BaseModel):
    requests_today: int = 0
    tokens_input_today: int = 0
    tokens_output_today: int = 0
    estimated_cost_usd: float = 0.0
    last_request_timestamp: Optional[float] = None
    last_error: Optional[str] = None
    last_status: str = MODEL_AVAILABLE


class AIResponse(BaseModel):
    ok: bool
    status: str
    text: str
    model: str
    provider: str
    cached: bool = False
    tokens_input: int = 0
    tokens_output: int = 0
    latency_ms: float = 0.0
    error: Optional[str] = None


class GemmaModelClient:
    """
    Thread-safe, production-resilient client for Gemma 4 and hybrid AI providers.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._cache: Dict[str, Tuple[float, AIResponse]] = {}
        self._cache_ttl = 3600.0  # 1 hour
        self._metrics = AIUsageMetrics()
        self._reload_config()

    def _reload_config(self):
        """Read configuration from environment with graceful fallbacks."""
        self.provider = os.getenv("AI_PROVIDER", "auto").strip().lower()
        self.model_id = os.getenv(
            "AI_MODEL_ID",
            os.getenv("OLLAMA_MODEL", "gemma4:31b")
        ).strip()
        
        # Check all possible API key environment variable aliases
        self.api_key = (
            os.getenv("AI_API_KEY", "")
            or os.getenv("GEMMA_API_KEY", "")
            or os.getenv("GEMINI_API_KEY", "")
            or os.getenv("GOOGLE_API_KEY", "")
            or os.getenv("OLLAMA_API_KEY", "")
        ).strip()

        self.endpoint = os.getenv(
            "AI_ENDPOINT",
            os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
        ).strip()

        self.timeout = float(os.getenv("AI_API_TIMEOUT", os.getenv("OLLAMA_TIMEOUT", "30")))
        self.insight_timeout = float(os.getenv("AI_INSIGHT_TIMEOUT", os.getenv("OLLAMA_INSIGHT_TIMEOUT", "90")))
        self.max_retries = int(os.getenv("AI_MAX_RETRIES", "3"))
        self.rag_enabled = os.getenv("AI_RAG_ENABLED", "true").strip().lower() in ("1", "true", "yes")
        self.validation_enabled = os.getenv("AI_VALIDATION_ENABLED", "true").strip().lower() in ("1", "true", "yes")
        self.fallback_enabled = os.getenv("AI_FALLBACK_ENABLED", "true").strip().lower() in ("1", "true", "yes")
        self.max_input_tokens = int(os.getenv("AI_MAX_INPUT_TOKENS", "8192"))
        self.max_output_tokens = int(os.getenv("AI_MAX_OUTPUT_TOKENS", "2048"))
        self.max_requests_per_audit = int(os.getenv("AI_MAX_REQUESTS_PER_AUDIT", "5"))
        self.knowledge_version = os.getenv("AI_KNOWLEDGE_VERSION", "1.0.0").strip()

    def get_effective_provider(self) -> str:
        """Determines the active AI provider based on configuration."""
        if self.provider in ("google", "gemini"):
            return "gemini"
        if self.provider in ("gemma", "gemma4", "hosted", "ollama", "ollama_cloud"):
            return "gemma4"
        
        # Auto-detection
        if "generativelanguage.googleapis.com" in self.endpoint:
            return "gemini"
        if self.api_key and ("AIza" in self.api_key or "gemini" in self.model_id.lower()):
            return "gemini"
        return "gemma4"

    def check_health(self) -> Dict[str, Any]:
        """
        Non-destructive health check testing model reachability and authentication.
        """
        self._reload_config()
        provider = self.get_effective_provider()
        start_t = time.time()

        if not self.endpoint and not self.api_key:
            return {
                "status": MODEL_UNAVAILABLE,
                "available": False,
                "provider": provider,
                "model": self.model_id,
                "latency_ms": 0.0,
                "message": "AI endpoint and API key not configured. Deterministic fallback active.",
                "fallback_ready": True
            }

        try:
            if provider == "gemini":
                # Check Gemini models endpoint
                url = f"https://generativelanguage.googleapis.com/v1beta/models?key={self.api_key}"
                r = requests.get(url, timeout=5.0)
                latency = round((time.time() - start_t) * 1000, 2)
                if r.status_code == 200:
                    return {
                        "status": MODEL_AVAILABLE,
                        "available": True,
                        "provider": provider,
                        "model": self.model_id,
                        "latency_ms": latency,
                        "fallback_ready": True
                    }
                elif r.status_code in (401, 403):
                    return {
                        "status": MODEL_AUTHENTICATION_FAILED,
                        "available": False,
                        "provider": provider,
                        "model": self.model_id,
                        "latency_ms": latency,
                        "error": f"Invalid Gemini API key (HTTP {r.status_code})",
                        "fallback_ready": True
                    }
                elif r.status_code == 429:
                    return {
                        "status": MODEL_RATE_LIMITED,
                        "available": False,
                        "provider": provider,
                        "model": self.model_id,
                        "latency_ms": latency,
                        "error": "Gemini API rate limit reached",
                        "fallback_ready": True
                    }

            # Default: Gemma 4 hosted / Ollama endpoint check
            base = self.endpoint.rsplit("/api/", 1)[0].rstrip("/")
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            
            check_url = f"{base}/api/tags" if "/api/" in self.endpoint else self.endpoint
            r = requests.get(check_url, headers=headers, timeout=5.0)
            latency = round((time.time() - start_t) * 1000, 2)

            if r.status_code == 200:
                models = [str(x.get("name", "")).lower() for x in (r.json().get("models") or [])] if r.headers.get("content-type", "").startswith("application/json") else []
                return {
                    "status": MODEL_AVAILABLE,
                    "available": True,
                    "provider": provider,
                    "model": self.model_id,
                    "installed_models": models[:10],
                    "latency_ms": latency,
                    "fallback_ready": True
                }
            elif r.status_code in (401, 403):
                return {
                    "status": MODEL_AUTHENTICATION_FAILED,
                    "available": False,
                    "provider": provider,
                    "model": self.model_id,
                    "latency_ms": latency,
                    "error": f"Invalid AI API credentials (HTTP {r.status_code})",
                    "fallback_ready": True
                }
            elif r.status_code == 429:
                return {
                    "status": MODEL_RATE_LIMITED,
                    "available": False,
                    "provider": provider,
                    "model": self.model_id,
                    "latency_ms": latency,
                    "error": "AI provider rate limit reached",
                    "fallback_ready": True
                }
            elif r.status_code == 404 and self.api_key:
                # Cloud endpoints that only accept /api/generate
                return {
                    "status": MODEL_AVAILABLE,
                    "available": True,
                    "provider": provider,
                    "model": self.model_id,
                    "latency_ms": latency,
                    "fallback_ready": True
                }
            else:
                return {
                    "status": MODEL_UNAVAILABLE,
                    "available": False,
                    "provider": provider,
                    "model": self.model_id,
                    "latency_ms": latency,
                    "error": f"HTTP {r.status_code}: {r.text[:150]}",
                    "fallback_ready": True
                }

        except Exception as exc:
            return {
                "status": MODEL_UNAVAILABLE,
                "available": False,
                "provider": provider,
                "model": self.model_id,
                "latency_ms": round((time.time() - start_t) * 1000, 2),
                "error": str(exc),
                "fallback_ready": True
            }

    def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.2,
        json_mode: bool = False,
        use_cache: bool = True
    ) -> AIResponse:
        """
        Executes bounded, resilient AI inference with exponential backoff and caching.
        """
        self._reload_config()
        provider = self.get_effective_provider()

        # Approximate token count for budgeting
        approx_tokens_in = max(1, len(prompt) // 4)
        if approx_tokens_in > self.max_input_tokens:
            prompt = prompt[: self.max_input_tokens * 4]

        # Cache lookup
        cache_key = hashlib.sha256(f"{provider}:{self.model_id}:{temperature}:{prompt}".encode("utf-8")).hexdigest()
        now = time.time()
        if use_cache:
            with self._lock:
                if cache_key in self._cache:
                    ts, cached_resp = self._cache[cache_key]
                    if now - ts < self._cache_ttl:
                        cached_resp.cached = True
                        return cached_resp

        # Retry loop with exponential backoff and jitter
        last_error = ""
        attempt = 0
        while attempt <= self.max_retries:
            attempt += 1
            t_start = time.time()
            try:
                if provider == "gemini":
                    resp = self._invoke_gemini(prompt, system_instruction, temperature, json_mode)
                else:
                    resp = self._invoke_gemma4(prompt, system_instruction, temperature, json_mode)

                latency = round((time.time() - t_start) * 1000, 2)
                resp.latency_ms = latency
                resp.tokens_input = approx_tokens_in
                resp.tokens_output = max(1, len(resp.text) // 4)

                # Update metrics
                with self._lock:
                    self._metrics.requests_today += 1
                    self._metrics.tokens_input_today += resp.tokens_input
                    self._metrics.tokens_output_today += resp.tokens_output
                    self._metrics.last_request_timestamp = now
                    self._metrics.last_status = resp.status
                    if use_cache and resp.ok:
                        self._cache[cache_key] = (now, resp)

                return resp

            except requests.exceptions.HTTPError as http_err:
                status_code = getattr(http_err.response, "status_code", 0)
                if status_code in (401, 403):
                    # Do not retry bad credentials
                    last_error = f"Authentication failed (HTTP {status_code})"
                    with self._lock:
                        self._metrics.last_error = last_error
                        self._metrics.last_status = MODEL_AUTHENTICATION_FAILED
                    return AIResponse(
                        ok=False,
                        status=MODEL_AUTHENTICATION_FAILED,
                        text="",
                        model=self.model_id,
                        provider=provider,
                        error=last_error
                    )
                elif status_code == 429:
                    last_error = "Rate limit encountered"
                    with self._lock:
                        self._metrics.last_status = MODEL_RATE_LIMITED
                else:
                    last_error = str(http_err)

            except Exception as exc:
                last_error = str(exc)

            if attempt <= self.max_retries:
                # Exponential backoff with jitter: 0.5s, 1.2s, 2.5s...
                sleep_time = min(5.0, (0.5 * (2 ** (attempt - 1))) + random.uniform(0.1, 0.4))
                logger.warning(f"AI call attempt {attempt} failed ({last_error}). Retrying in {sleep_time:.2f}s...")
                time.sleep(sleep_time)

        with self._lock:
            self._metrics.last_error = last_error
            self._metrics.last_status = MODEL_UNAVAILABLE

        return AIResponse(
            ok=False,
            status=MODEL_UNAVAILABLE,
            text="",
            model=self.model_id,
            provider=provider,
            error=last_error
        )

    def _invoke_gemma4(
        self,
        prompt: str,
        system_instruction: Optional[str],
        temperature: float,
        json_mode: bool
    ) -> AIResponse:
        """Invokes Gemma 4 via standard hosted HTTP endpoint."""
        full_prompt = f"{system_instruction}\n\n{prompt}" if system_instruction else prompt
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: Dict[str, Any] = {
            "model": self.model_id,
            "prompt": full_prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": self.max_output_tokens
            }
        }
        if json_mode:
            payload["format"] = "json"

        r = requests.post(self.endpoint, json=payload, headers=headers, timeout=self.insight_timeout)
        r.raise_for_status()
        raw = r.json()
        text = raw.get("response") or raw.get("content") or ""
        return AIResponse(
            ok=True,
            status=MODEL_AVAILABLE,
            text=text.strip(),
            model=self.model_id,
            provider="gemma4"
        )

    def _invoke_gemini(
        self,
        prompt: str,
        system_instruction: Optional[str],
        temperature: float,
        json_mode: bool
    ) -> AIResponse:
        """Invokes Google Gemini REST API."""
        model_name = self.model_id if "gemini" in self.model_id.lower() else "gemini-1.5-flash"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={self.api_key}"
        
        contents = []
        if system_instruction:
            contents.append({"role": "user", "parts": [{"text": f"SYSTEM INSTRUCTION: {system_instruction}"}]})
            contents.append({"role": "model", "parts": [{"text": "Understood. I will strictly obey all system instructions and ground my analysis in the verified evidence."}]})
        
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        body: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": self.max_output_tokens
            }
        }
        if json_mode:
            body["generationConfig"]["responseMimeType"] = "application/json"

        r = requests.post(url, json=body, timeout=self.insight_timeout)
        r.raise_for_status()
        data = r.json()
        candidates = data.get("candidates") or []
        text = ""
        if candidates:
            parts = (candidates[0].get("content") or {}).get("parts") or []
            if parts:
                text = parts[0].get("text", "")

        return AIResponse(
            ok=True,
            status=MODEL_AVAILABLE,
            text=text.strip(),
            model=model_name,
            provider="gemini"
        )

    def get_metrics(self) -> Dict[str, Any]:
        with self._lock:
            return self._metrics.dict()


# Global client singleton
model_client = GemmaModelClient()

