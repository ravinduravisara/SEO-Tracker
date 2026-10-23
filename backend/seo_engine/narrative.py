"""AI narrative layer (spec N.1 rule 2 / N.2): prose only. It may never emit, alter or round a number.

Output is validated: non-string values are rejected, and any text containing a digit or matching the
fabrication patterns is discarded, so the deterministic payload stays the only source of numbers.
"""
from __future__ import annotations

import json
import re
from typing import Any

import requests

from .gate import fabrication_hits


def clean_prose(value: Any) -> str | None:
    if not isinstance(value, str):
        return None  # spec: reject numeric (or structured) fields from the narrative layer
    text = value.strip()
    if len(text.split()) < 5 or re.search(r"\d", text) or re.search(r"[<\[{]", text):
        return None
    if fabrication_hits([text]):
        return None
    return text[:600]


def category_explanations(payload: dict[str, Any], ollama_url: str, model: str, timeout: float) -> dict[str, Any]:
    """Ask the local Ollama model for plain-language explanations of each scored category."""
    lines = []
    checks = {c["id"]: c for c in payload["checks"]}
    ids = []
    for cat in payload["categories"]:
        if cat["score"] is None:
            continue
        ids.append(cat["id"])
        gaps = [checks[i]["name"] for i in cat["check_ids"] if checks[i]["status"] in ("FAIL", "WARN")][:4]
        good = cat["strengths"][:3]
        lines.append(f"[{cat['id']}] {cat['name']}: good = {', '.join(good) or 'nothing yet'}; needs work = {', '.join(gaps) or 'nothing'}")
    if not ids:
        return {"enabled": False, "error": "No scored categories.", "data": {}}
    example = ", ".join(f'"{i}": "<two simple sentences>"' for i in ids)
    prompt = ("You are an SEO consultant writing for a small-business owner with no technical knowledge.\n"
              f"Website: {payload['audit'].get('target_url')}\n\nAudit findings:\n" + "\n".join(lines) + "\n\n"
              "For EACH category id in square brackets write two simple sentences: what is good, and the most important fix. "
              "Do not use any numbers, percentages, scores, rankings, traffic or speed figures. Do not invent facts.\n"
              "Answer with ONLY this JSON:\n{" + example + "}")
    try:
        base = ollama_url.rsplit("/api/", 1)[0].rstrip("/")
        tags = requests.get(base + "/api/tags", timeout=2)
        names = [str(x.get("name", "")) for x in (tags.json().get("models") or [])] if tags.ok else []
        if not any(n == model or n.startswith(model + ":") for n in names):
            return {"enabled": False, "model": model, "error": f"Ollama model '{model}' is not available.", "data": {}}
        r = requests.post(ollama_url, json={"model": model, "prompt": prompt, "stream": False, "format": "json", "keep_alive": "30m",
                                            "options": {"temperature": 0.2, "num_predict": 700}}, timeout=timeout)
        r.raise_for_status()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", (r.json().get("response") or "").strip(), flags=re.I | re.S)
        data = json.loads(raw)
        out = {k: t for k, v in data.items() if k in ids and (t := clean_prose(v))}
        return {"enabled": True, "model": model, "data": out, "rejected": sorted(set(ids) - set(out))}
    except (requests.RequestException, ValueError) as exc:
        return {"enabled": False, "model": model, "error": str(exc), "data": {}}
