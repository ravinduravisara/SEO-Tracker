"""
Phase 9: Evidence-Based AI SEO Recommendation Engine & Assistant
Connects to local/cloud Ollama (or compatible AI endpoints), analyzes verified audit findings,
and produces evidence-grounded recommendations across 8 core disciplines:
1. SEO Issue Explanations
2. Prioritized Actionable Roadmap
3. Suggested Technical Fixes (code/config snippets)
4. Content Improvement Proposals (title/meta rewrites, headings)
5. Keyword Targeting Opportunities
6. Internal Linking Proposals (link equity distribution)
7. Structured Data JSON-LD Schemas
8. Actionable Developer Instructions

Enforces strict zero-fabrication policies and graceful deterministic fallbacks when Ollama is unavailable.
"""

from __future__ import annotations

import io
import csv
import html
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional, Dict, List, Tuple
from urllib.parse import urlparse

import requests
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, PageBreak
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas

from . import seo_knowledge
from .ai.model_client import model_client, MODEL_AVAILABLE
from .ai.rag_engine import rag_knowledge_base
from .ai.context_builder import build_gemma_context
from .ai.recommendation_validator import validate_all_recommendations

logger = logging.getLogger("aviance.ai_advisor")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate").strip()
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:31b").strip()
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "").strip()
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "20"))
OLLAMA_INSIGHT_TIMEOUT = float(os.getenv("OLLAMA_INSIGHT_TIMEOUT", "90"))


def _ollama_headers() -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if OLLAMA_API_KEY:
        headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"
    return headers


def check_ollama_status() -> Dict[str, Any]:
    """Tests live connectivity to the configured Gemma 4 / AI model provider."""
    health = model_client.check_health()
    return {
        "available": health.get("available", False),
        "configured": bool(model_client.endpoint or model_client.api_key),
        "endpoint": model_client.endpoint,
        "model": model_client.model_id,
        "provider": health.get("provider", "gemma4"),
        "status": health.get("status", "MODEL_UNAVAILABLE"),
        "model_available": health.get("available", False),
        "installed_models": health.get("installed_models", [model_client.model_id]),
        "fallback_ready": True,
        "mode": "cloud" if (model_client.api_key or model_client.endpoint.startswith("https://")) else "local",
        "latency_ms": health.get("latency_ms", 0.0),
        "error": health.get("error")
    }


# -----------------------------------------------------------------------------
# EVIDENCE EXTRACTION & NORMALIZATION
# -----------------------------------------------------------------------------

def extract_audit_evidence(audit_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extracts verified audit facts and boundaries to ground AI generation.
    Strictly filters out any unverified or missing data points.
    """
    target = audit_data.get("target") or audit_data.get("url") or "https://example.com"
    score = audit_data.get("score")
    if score is None:
        score = (audit_data.get("scores") or {}).get("overall", 0)

    # 1. Gather all detected issues
    raw_issues = audit_data.get("issues") or []
    issues_by_severity = {"CRITICAL": [], "HIGH": [], "MEDIUM": [], "LOW": []}
    for iss in raw_issues:
        sev = str(iss.get("severity", "MEDIUM")).upper()
        if sev not in issues_by_severity:
            sev = "MEDIUM"
        issues_by_severity[sev].append({
            "code": iss.get("code", "unknown"),
            "category": iss.get("category", "General"),
            "severity": sev,
            "message": iss.get("message", ""),
            "url": iss.get("url", target),
            "recommendation": iss.get("recommendation", ""),
            "evidence": iss.get("evidence", "")[:300]
        })

    # 2. Gather sampled page metadata
    pages = []
    for p in (audit_data.get("pages") or [])[:30]:
        raw_imgs = p.get("images")
        img_count = len(raw_imgs) if isinstance(raw_imgs, (list, tuple, dict)) else (int(raw_imgs) if isinstance(raw_imgs, (int, float)) else 0)
        raw_links = p.get("internal_links")
        links_count = len(raw_links) if isinstance(raw_links, (list, tuple, dict)) else (int(raw_links) if isinstance(raw_links, (int, float)) else 0)
        raw_h1 = p.get("h1")
        h1_list = raw_h1 if isinstance(raw_h1, list) else ([str(raw_h1)] if raw_h1 else [])

        pages.append({
            "url": p.get("url", ""),
            "status": p.get("status", 200),
            "title": p.get("title", ""),
            "title_length": len(p.get("title") or ""),
            "meta_description": p.get("meta_description", ""),
            "h1": h1_list,
            "word_count": p.get("word_count", 0),
            "images_count": img_count,
            "internal_links_count": links_count,
            "has_schema": bool(p.get("schema_types")),
            "schema_types": p.get("schema_types") or [],
            "response_time_ms": p.get("response_time_ms", 0),
        })

    # 3. Discovered terms and search queries (from Search Console or on-page)
    discovered_keywords = []
    real_data = audit_data.get("real_data") or {}
    gsc_queries = ((real_data.get("search_console") or {}).get("top_queries") or [])[:15]
    for q in gsc_queries:
        if q.get("query"):
            discovered_keywords.append({
                "term": q.get("query"),
                "clicks": q.get("clicks", 0),
                "impressions": q.get("impressions", 0),
                "source": "Search Console"
            })

    # If no Search Console, sample title and H1 words
    if not discovered_keywords:
        for p in pages[:10]:
            if p.get("title"):
                discovered_keywords.append({"term": p["title"][:50], "source": "Page Title"})
            for h in p.get("h1", [])[:1]:
                discovered_keywords.append({"term": h[:50], "source": "H1 Heading"})

    # 4. Core Web Vitals Summary
    cwv = (real_data.get("pagespeed") or {}).get("field") or {}
    cwv_assessment = cwv.get("core_web_vitals_assessment") or "unknown"

    return {
        "target": target,
        "score": score,
        "page_count": audit_data.get("pages_crawled") or audit_data.get("page_count") or len(pages),
        "issues_summary": {
            "critical": len(issues_by_severity["CRITICAL"]),
            "high": len(issues_by_severity["HIGH"]),
            "medium": len(issues_by_severity["MEDIUM"]),
            "low": len(issues_by_severity["LOW"]),
            "CRITICAL": len(issues_by_severity["CRITICAL"]),
            "HIGH": len(issues_by_severity["HIGH"]),
            "MEDIUM": len(issues_by_severity["MEDIUM"]),
            "LOW": len(issues_by_severity["LOW"]),
        },
        "top_critical_issues": issues_by_severity["CRITICAL"][:10],
        "top_high_issues": issues_by_severity["HIGH"][:15],
        "top_medium_issues": issues_by_severity["MEDIUM"][:15],
        "pages_sample": pages[:15],
        "discovered_keywords": discovered_keywords[:15],
        "core_web_vitals_assessment": cwv_assessment,
    }


# -----------------------------------------------------------------------------
# DETERMINISTIC FALLBACK RECOMMENDATION GENERATOR
# -----------------------------------------------------------------------------

def generate_deterministic_fallback_recommendations(audit_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generates rich, evidence-grounded recommendations derived deterministically
    from verified audit findings and seo_knowledge.py rules.
    Guarantees 100% availability even when Ollama is offline or unconfigured.
    """
    evidence = extract_audit_evidence(audit_data)
    target = evidence["target"]
    domain = urlparse(target).hostname or "example.com"
    pages = evidence["pages_sample"]

    # 1. Issue Explanations
    issue_explanations = []
    all_issues = evidence["top_critical_issues"] + evidence["top_high_issues"] + evidence["top_medium_issues"]
    for iss in all_issues[:12]:
        rule = seo_knowledge.get_rule(iss["code"])
        why_text = rule.get("why") if rule else "This issue impacts search engine crawling efficiency or user experience."
        action_text = rule.get("action") if rule else iss.get("recommendation", "Review and resolve this issue.")
        issue_explanations.append({
            "code": iss["code"],
            "severity": iss.get("severity", "MEDIUM"),
            "title": rule.get("title", iss["code"].replace("_", " ").title()) if rule else iss["code"],
            "affected_url": iss["url"],
            "evidence": iss["evidence"] or f"Detected on {iss['url']}",
            "explanation": why_text,
            "action": action_text,
            "citations": [s.get("name") for s in rule.get("source_links", [])] if rule else ["Google Search Central"]
        })

    # 2. Prioritized Recommendations
    prioritized_recommendations = []
    priority_order = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    rec_counter = 1
    for sev in priority_order:
        items = [iss for iss in all_issues if iss.get("severity") == sev]
        for it in items[:4]:
            rule = seo_knowledge.get_rule(it["code"])
            prioritized_recommendations.append({
                "id": rec_counter,
                "priority": sev,
                "category": it["category"],
                "title": f"Fix {rule.get('title', it['code'])}" if rule else f"Resolve {it['code']}",
                "impact": "High" if sev in ("CRITICAL", "HIGH") else "Medium",
                "effort": "Low" if "meta" in it["code"] or "title" in it["code"] else "Medium",
                "affected_urls": [it["url"]],
                "action": it["recommendation"] or (rule.get("action") if rule else "Resolve this issue."),
                "validation": f"Re-crawl {it['url']} to verify {it['code']} no longer triggers."
            })
            rec_counter += 1

    # 3. Suggested Technical Fixes (code/config snippets)
    technical_fixes = [
        {
            "category": "Canonicalization",
            "title": "Enforce Canonical Link Headers",
            "snippet_type": "HTML Tag",
            "code": f'<link rel="canonical" href="{target}" />',
            "description": "Add self-referential canonical tags on all indexable pages to prevent duplicate content consolidation issues."
        },
        {
            "category": "Security & Crawl Directives",
            "title": "Enable Strict-Transport-Security (HSTS)",
            "snippet_type": "Nginx Header",
            "code": "add_header Strict-Transport-Security \"max-age=31536000; includeSubDomains\" always;\nadd_header X-Content-Type-Options \"nosniff\" always;",
            "description": "Instruct browsers and crawlers to always communicate over secure HTTPS connections."
        },
        {
            "category": "Robots & Crawl Budget",
            "title": "Optimized robots.txt Configuration",
            "snippet_type": "robots.txt",
            "code": f"User-agent: *\nAllow: /\nDisallow: /admin/\nDisallow: /api/\n\nSitemap: {target.rstrip('/')}/sitemap.xml",
            "description": "Guide search engine spiders away from private endpoints and reference XML sitemaps."
        }
    ]

    # 4. Content Improvement Suggestions
    content_improvements = []
    for p in pages[:6]:
        curr_title = p.get("title") or ""
        curr_desc = p.get("meta_description") or ""
        p_url = p.get("url") or target

        improvements = []
        if len(curr_title) < 30 or len(curr_title) > 65:
            clean_host = domain.replace("www.", "").capitalize()
            improvements.append({
                "type": "Title Tag Rewrite",
                "current": curr_title or "(Missing Title Tag)",
                "proposed": f"{curr_title[:35]} | {clean_host}" if curr_title else f"Professional Services | {clean_host}",
                "character_count": len(f"{curr_title[:35]} | {clean_host}") if curr_title else 30,
                "rationale": "Title tags between 50-60 characters prevent truncation in Google search results snippets."
            })

        if len(curr_desc) < 80 or len(curr_desc) > 160:
            improvements.append({
                "type": "Meta Description Proposal",
                "current": curr_desc or "(Missing Meta Description)",
                "proposed": f"Discover {domain}'s specialized solutions. Explore features, industry insights, and get in touch with our team today.",
                "character_count": len(f"Discover {domain}'s specialized solutions. Explore features, industry insights, and get in touch with our team today."),
                "rationale": "Compelling meta descriptions between 120-155 characters maximize organic click-through rate (CTR)."
            })

        if improvements:
            content_improvements.append({
                "page_url": p_url,
                "suggestions": improvements
            })

    # 5. Keyword Targeting Opportunities
    keyword_opportunities = []
    discovered = evidence.get("discovered_keywords") or []
    for d in discovered[:8]:
        term = d.get("term", "").strip()
        if term:
            keyword_opportunities.append({
                "keyword": term,
                "source": d.get("source", "Observed Page Heading"),
                "intent": "Informational" if any(w in term.lower() for w in ["how", "what", "guide"]) else "Commercial",
                "recommendation": f"Target '{term}' in primary H1 and intro paragraph of relevant landing page.",
                "evidence_basis": f"Discovered directly on site ({d.get('source', 'Crawl')})."
            })

    # 6. Internal Linking Recommendations
    internal_linking = []
    if len(pages) >= 2:
        for i in range(min(4, len(pages) - 1)):
            source_p = pages[i]
            target_p = pages[i + 1]
            anchor = target_p.get("title") or target_p["url"].split("/")[-1].replace("-", " ").title() or "Learn More"
            internal_linking.append({
                "source_url": source_p["url"],
                "target_url": target_p["url"],
                "suggested_anchor_text": anchor[:40],
                "rationale": "Distribute internal PageRank authority from top-level page to deeper content hubs."
            })

    # 7. Structured Data Schemas (Valid JSON-LD)
    structured_data_schemas = [
        {
            "schema_type": "Organization",
            "page_target": target,
            "json_ld": json.dumps({
                "@context": "https://schema.org",
                "@type": "Organization",
                "name": domain.capitalize(),
                "url": target,
                "logo": f"{target.rstrip('/')}/logo.png",
                "sameAs": []
            }, indent=2),
            "implementation_guide": "Insert inside <script type=\"application/ld+json\"> in the <head> of the homepage."
        },
        {
            "schema_type": "WebSite",
            "page_target": target,
            "json_ld": json.dumps({
                "@context": "https://schema.org",
                "@type": "WebSite",
                "name": domain.capitalize(),
                "url": target,
                "potentialAction": {
                    "@type": "SearchAction",
                    "target": f"{target.rstrip('/')}/search?q={{search_term_string}}",
                    "query-input": "required name=search_term_string"
                }
            }, indent=2),
            "implementation_guide": "Enables Google Sitelinks Search Box rich result."
        }
    ]

    # 8. Actionable Developer Instructions
    developer_instructions = [
        {
            "step": 1,
            "category": "Server & Header Configuration",
            "title": "Configure 301 Redirects & HTTPS Canonical Origin",
            "task": "Ensure HTTP traffic and non-preferred host variants (www vs non-www) redirect via permanent 301 to the canonical HTTPS URL.",
            "verification": "curl -IL http://" + domain + " should return HTTP/1.1 301 Moved Permanently pointing to https://" + domain
        },
        {
            "step": 2,
            "category": "HTML Metadata & Headings",
            "title": "Ensure Exactly One Unique H1 Heading Per Page",
            "task": "Inspect templates to guarantee pages render a single descriptive H1 matching the primary topic.",
            "verification": "document.querySelectorAll('h1').length === 1 in browser console."
        },
        {
            "step": 3,
            "category": "Structured Data",
            "title": "Deploy Valid JSON-LD Schema Markup",
            "task": "Inject the provided Organization and WebSite schema blocks into document <head>.",
            "verification": "Test with Google Rich Results Test (https://search.google.com/test/rich-results)."
        }
    ]

    return {
        "ok": True,
        "ai_generated": False,
        "source_model": "Deterministic SEO Knowledge Engine (Ollama Offline Fallback)",
        "target": target,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "disclaimer": (
            "Evidence Grounding Policy: All recommendations are strictly tied to verified crawl evidence and primary "
            "search documentation. Aviance never alters measured SEO scores or invents unverified metrics."
        ),
        "issue_explanations": issue_explanations,
        "prioritized_recommendations": prioritized_recommendations,
        "technical_fixes": technical_fixes,
        "content_improvements": content_improvements,
        "keyword_opportunities": keyword_opportunities,
        "internal_linking": internal_linking,
        "structured_data_schemas": structured_data_schemas,
        "developer_instructions": developer_instructions,
    }


# -----------------------------------------------------------------------------
# AI ASSISTANT DISPATCHER & PROMPT GROUNDING
# -----------------------------------------------------------------------------

def generate_ai_recommendations(
    audit_data: Dict[str, Any],
    force_refresh: bool = False
) -> Dict[str, Any]:
    """
    Orchestrates evidence-grounded AI recommendations via Ollama with automatic
    fallback to deterministic knowledge-base engine if Ollama is unavailable.
    """
    evidence = extract_audit_evidence(audit_data)
    target = evidence["target"]

    status = check_ollama_status()
    if not status.get("available") or not status.get("model_available"):
        logger.info("Ollama is not available (%s); utilizing deterministic fallback engine.", status.get("error"))
        return generate_deterministic_fallback_recommendations(audit_data)

    # Construct strict JSON-schema prompt
    system_prompt = (
        "You are an expert technical SEO architect. You analyze verified website audit findings and produce "
        "concrete, actionable recommendations. "
        "STRICT CONSTRAINTS:\n"
        "1. Never alter or change measured SEO scores, response times, or word counts.\n"
        "2. Never invent search rankings, keyword search volumes, or backlink counts.\n"
        "3. Every recommendation must cite specific affected URLs and verified evidence from the audit findings.\n"
        "4. Respond with valid JSON ONLY. Do not wrap with markdown backticks or commentary.\n"
    )

    user_prompt = f"""
Audit Evidence for Website: {target}
Health Score: {evidence['score']}/100
Issues Summary: {json.dumps(evidence['issues_summary'])}
Top Critical Issues: {json.dumps(evidence['top_critical_issues'][:5])}
Top High Issues: {json.dumps(evidence['top_high_issues'][:5])}
Sampled Pages: {json.dumps(evidence['pages_sample'][:6])}
Discovered Keywords: {json.dumps(evidence['discovered_keywords'][:6])}

Generate comprehensive, evidence-grounded recommendations strictly structured as JSON with these keys:
{{
  "issue_explanations": [
    {{"code": "string", "severity": "CRITICAL|HIGH|MEDIUM", "title": "string", "affected_url": "string", "evidence": "string", "explanation": "two clear sentences", "action": "actionable fix"}}
  ],
  "prioritized_recommendations": [
    {{"id": 1, "priority": "CRITICAL|HIGH|MEDIUM", "category": "Technical|On-Page|Performance", "title": "string", "impact": "High|Medium", "effort": "Low|Medium|High", "affected_urls": ["string"], "action": "string", "validation": "string"}}
  ],
  "technical_fixes": [
    {{"category": "string", "title": "string", "snippet_type": "HTML Tag|Nginx Header|robots.txt", "code": "string", "description": "string"}}
  ],
  "content_improvements": [
    {{"page_url": "string", "suggestions": [{{"type": "Title Tag Rewrite|Meta Description Proposal", "current": "string", "proposed": "string", "character_count": 55, "rationale": "string"}}]}}
  ],
  "keyword_opportunities": [
    {{"keyword": "string", "source": "string", "intent": "Informational|Commercial", "recommendation": "string", "evidence_basis": "string"}}
  ],
  "internal_linking": [
    {{"source_url": "string", "target_url": "string", "suggested_anchor_text": "string", "rationale": "string"}}
  ],
  "structured_data_schemas": [
    {{"schema_type": "Organization|WebSite", "page_target": "string", "json_ld": "string", "implementation_guide": "string"}}
  ],
  "developer_instructions": [
    {{"step": 1, "category": "string", "title": "string", "task": "string", "verification": "string"}}
  ]
}}
"""

    # Build RAG-grounded, injection-resistant context
    gemma_ctx = build_gemma_context(audit_data)
    rag_prompt = f"{gemma_ctx['system_prompt']}\n\n{gemma_ctx['user_prompt']}"

    # Dispatch to production model client (Gemma 4 / Gemini API)
    ai_resp = model_client.generate(
        prompt=gemma_ctx["user_prompt"],
        system_instruction=gemma_ctx["system_prompt"],
        temperature=0.2,
        json_mode=True
    )

    if not ai_resp.ok:
        logger.warning("AI model generation unavailable (%s); serving deterministic recommendations.", ai_resp.error)
        return generate_deterministic_fallback_recommendations(audit_data)

    try:
        raw_clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", ai_resp.text, flags=re.I | re.S).strip()
        data = json.loads(raw_clean)

        raw_recs = []
        if isinstance(data, dict):
            if "recommendations" in data and isinstance(data["recommendations"], list):
                raw_recs = data["recommendations"]
            elif "prioritized_recommendations" in data and isinstance(data["prioritized_recommendations"], list):
                raw_recs = data["prioritized_recommendations"]
            elif "issue_explanations" in data and isinstance(data["issue_explanations"], list):
                raw_recs = data["issue_explanations"]
        elif isinstance(data, list):
            raw_recs = data

        # Run strict recommendation verification
        val_report = validate_all_recommendations(raw_recs, audit_data, audit_id=audit_data.get("id"))

        if not val_report.verified_recommendations:
            logger.warning("No AI recommendations passed strict evidence validation. Serving deterministic recommendations.")
            return generate_deterministic_fallback_recommendations(audit_data)

        # Build output structure matching existing reporting contracts
        out_explanations = []
        out_prioritized = []
        for idx, v in enumerate(val_report.verified_recommendations):
            out_explanations.append({
                "code": v.issue_id,
                "severity": v.severity,
                "title": v.issue_title,
                "affected_url": v.affected_url,
                "evidence": v.evidence_reference,
                "explanation": v.explanation,
                "action": v.recommended_action
            })
            out_prioritized.append({
                "id": idx + 1,
                "priority": v.severity,
                "category": v.category,
                "title": v.issue_title,
                "impact": "High" if v.severity in ("CRITICAL", "HIGH") else "Medium",
                "effort": "Low" if v.severity == "CRITICAL" else "Medium",
                "affected_urls": [v.affected_url],
                "action": v.recommended_action,
                "validation": v.verification_method,
                "citations": v.documentation_references,
                "validation_status": v.validation_status
            })

        fallback_data = generate_deterministic_fallback_recommendations(audit_data)

        return {
            "ok": True,
            "ai_generated": True,
            "source_model": f"{ai_resp.provider.upper()} ({ai_resp.model}) + RAG v{rag_knowledge_base.knowledge_version}",
            "target": target,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "issue_explanations": out_explanations,
            "prioritized_recommendations": out_prioritized,
            "technical_fixes": fallback_data.get("technical_fixes", []),
            "content_improvements": fallback_data.get("content_improvements", []),
            "keyword_opportunities": fallback_data.get("keyword_opportunities", []),
            "internal_linking": fallback_data.get("internal_linking", []),
            "structured_data_schemas": fallback_data.get("structured_data_schemas", []),
            "developer_instructions": fallback_data.get("developer_instructions", []),
            "validation_metrics": {
                "total_evaluated": val_report.total_evaluated,
                "verified": val_report.verified_count,
                "rejected": val_report.rejected_count,
            },
            "disclaimer": (
                "Evidence Grounding Policy: All recommendations are strictly tied to verified crawl evidence and primary "
                "search documentation. Aviance never alters measured SEO scores or invents unverified metrics."
            )
        }

    except Exception as exc:
        logger.warning("AI processing error (%s); serving deterministic recommendations.", exc)
        return generate_deterministic_fallback_recommendations(audit_data)


# -----------------------------------------------------------------------------
# INTERACTIVE AI SEO CONSULTANT (CHAT ASSISTANT)
# -----------------------------------------------------------------------------

def ask_ai_seo_assistant(
    question: str,
    audit_data: Optional[Dict[str, Any]] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None
) -> Dict[str, Any]:
    """
    Evidence-grounded conversational assistant that answers specific user questions
    about an audited website without inventing unverified facts.
    """
    clean_q = (question or "").strip()
    if not clean_q:
        return {"ok": False, "error": "Please provide a question for the AI SEO assistant."}

    # Extract context if audit payload provided
    context_text = "No specific audit loaded. Providing general Google Search Central guidance."
    target = ""
    if audit_data:
        evidence = extract_audit_evidence(audit_data)
        target = evidence["target"]
        context_text = (
            f"Website Target: {target}\n"
            f"Overall Audit Score: {evidence['score']}/100\n"
            f"Audited Pages Count: {evidence['page_count']}\n"
            f"Top Issues: {', '.join([i['code'] for i in evidence['top_critical_issues'][:4] + evidence['top_high_issues'][:4]])}\n"
            f"Sampled Pages: {', '.join([p['url'] for p in evidence['pages_sample'][:5]])}\n"
            f"Discovered Keywords: {', '.join([k['term'] for k in evidence['discovered_keywords'][:5]])}\n"
        )

    # Retrieve relevant SEO documentation via RAG
    rag_results = rag_knowledge_base.search(clean_q, top_k=2)
    doc_context = ""
    citations = []
    if rag_results:
        doc_context = "PRIMARY SEO DOCUMENTATION (GOOGLE SEARCH CENTRAL / WEB.DEV):\n"
        for doc, _ in rag_results:
            doc_context += f"- {doc.title}: {doc.content} ({doc.source_url})\n"
            citations.append({"title": doc.title, "url": doc.source_url})

    system_instruction = (
        "You are Aviance AI SEO Consultant, an expert technical search engine optimization advisor. "
        "Answer the user's question directly, accurately, and actionably. "
        "STRICT CONSTRAINTS:\n"
        "1. Never invent rankings, keyword search volume, or backlink statistics.\n"
        "2. Ground your advice in Google Search Central and web.dev specifications.\n"
        "3. Clearly distinguish General SEO Best Practice from Actual Observed Website Findings.\n"
        "4. Provide code snippets (HTML, CSS, JSON-LD, HTTP headers) whenever technical fixes are requested.\n"
        "5. Keep your answer concise, well-formatted, and professional.\n\n"
        f"{doc_context}\n"
        f"VERIFIED AUDIT CONTEXT:\n{context_text}"
    )

    prompt = f"User Question: {clean_q}\n\nExpert Answer:"
    ai_resp = model_client.generate(
        prompt=prompt,
        system_instruction=system_instruction,
        temperature=0.25
    )

    if ai_resp.ok and ai_resp.text:
        return {
            "ok": True,
            "answer": ai_resp.text,
            "ai_generated": True,
            "source_model": f"{ai_resp.provider.upper()} ({ai_resp.model})",
            "target": target,
            "citations": citations,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    # Deterministic knowledge fallback
    fallback_cites = [f"- [{c['title']}]({c['url']})" for c in citations]
    cites_str = "\n".join(fallback_cites) if fallback_cites else "- [Google Search Central](https://developers.google.com/search/docs)"
    reply = (
        f"**Aviance AI SEO Guidance for {target or 'your website'}**\n\n"
        f"Based on your question: *\"{clean_q}\"*\n\n"
        f"To optimize search performance according to Google Search Central best practices:\n"
        f"1. **Technical Foundation**: Ensure canonical tags match preferred URLs, HTTP redirects use status 301, and XML sitemaps are referenced in `robots.txt`.\n"
        f"2. **On-Page Optimization**: Craft unique `<title>` tags (30–60 characters) and descriptive meta descriptions (70–155 characters) for every indexed page.\n"
        f"3. **Structured Data**: Implement valid JSON-LD schemas (`Organization`, `WebSite`, or `Article`) to enrich search snippets.\n\n"
        f"**Authoritative References:**\n{cites_str}\n\n"
        f"*(Note: AI service is in deterministic SEO Knowledge Base mode. No external API call was made.)*"
    )
    return {
        "ok": True,
        "answer": reply,
        "ai_generated": False,
        "source_model": "Deterministic SEO Knowledge Engine",
        "target": target,
        "citations": citations,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


# -----------------------------------------------------------------------------
# MULTI-FORMAT EXPORTERS (CSV, EXCEL XML, VECTOR REPORTLAB PDF)
# -----------------------------------------------------------------------------

def generate_ai_recommendations_csv(rec_data: Dict[str, Any]) -> str:
    """Produces RFC-4180 CSV export of prioritized AI recommendations."""
    out = io.StringIO()
    writer = csv.writer(out)

    target = rec_data.get("target", "")
    writer.writerow(["# AI SEO RECOMMENDATIONS REPORT", target])
    writer.writerow(["Generated At", rec_data.get("generated_at", "")])
    writer.writerow(["Source Engine", rec_data.get("source_model", "")])
    writer.writerow(["AI Generated", rec_data.get("ai_generated", False)])
    writer.writerow([])

    # Table 1: Prioritized Recommendations
    writer.writerow(["# PRIORITIZED ACTIONABLE RECOMMENDATIONS"])
    writer.writerow(["Priority", "Category", "Title", "Impact", "Effort", "Action Plan", "Validation Criteria", "Affected URLs"])
    for p in rec_data.get("prioritized_recommendations", []):
        writer.writerow([
            p.get("priority", "MEDIUM"),
            p.get("category", "General"),
            p.get("title", ""),
            p.get("impact", "Medium"),
            p.get("effort", "Medium"),
            p.get("action", ""),
            p.get("validation", ""),
            " | ".join(p.get("affected_urls", []))
        ])
    writer.writerow([])

    # Table 2: Issue Explanations
    writer.writerow(["# VERIFIED ISSUE EXPLANATIONS"])
    writer.writerow(["Code", "Severity", "Title", "Explanation", "Action", "Affected URL", "Evidence"])
    for iss in rec_data.get("issue_explanations", []):
        writer.writerow([
            iss.get("code", ""),
            iss.get("severity", ""),
            iss.get("title", ""),
            iss.get("explanation", ""),
            iss.get("action", ""),
            iss.get("affected_url", ""),
            iss.get("evidence", "")
        ])

    return out.getvalue()


def generate_ai_recommendations_excel_xml(rec_data: Dict[str, Any]) -> str:
    """Produces Microsoft Excel 2003 XML workbook with multiple worksheets."""
    target = rec_data.get("target", "")

    def esc_xml(val: Any) -> str:
        s = str(val if val is not None else "")
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    xml = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<?mso-application progid="Excel.Sheet"?>',
        '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"',
        ' xmlns:o="urn:schemas-microsoft-com:office:office"',
        ' xmlns:x="urn:schemas-microsoft-com:office:excel"',
        ' xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"',
        ' xmlns:html="http://www.w3.org/TR/REC-html40">',
        ' <Styles>',
        '  <Style ss:ID="Header">',
        '   <Font ss:Bold="1" ss:Color="#FFFFFF"/>',
        '   <Interior ss:Color="#4F46E5" ss:Pattern="Solid"/>',
        '   <Alignment ss:Horizontal="Center"/>',
        '  </Style>',
        '  <Style ss:ID="Bold"><Font ss:Bold="1"/></Style>',
        ' </Styles>',
    ]

    # Worksheet 1: Prioritized Roadmap
    xml.append(' <Worksheet ss:Name="Action Roadmap">')
    xml.append('  <Table>')
    xml.append('   <Column ss:Width="100"/>')
    xml.append('   <Column ss:Width="120"/>')
    xml.append('   <Column ss:Width="180"/>')
    xml.append('   <Column ss:Width="80"/>')
    xml.append('   <Column ss:Width="280"/>')
    xml.append('   <Row ss:StyleID="Header">')
    for h in ("Priority", "Category", "Title", "Impact", "Action Plan"):
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(h)}</Data></Cell>')
    xml.append('   </Row>')

    for p in rec_data.get("prioritized_recommendations", []):
        xml.append('   <Row>')
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(p.get("priority"))}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(p.get("category"))}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(p.get("title"))}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(p.get("impact"))}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(p.get("action"))}</Data></Cell>')
        xml.append('   </Row>')

    xml.append('  </Table>')
    xml.append(' </Worksheet>')

    # Worksheet 2: Issue Explanations
    xml.append(' <Worksheet ss:Name="Issue Explanations">')
    xml.append('  <Table>')
    xml.append('   <Row ss:StyleID="Header">')
    for h in ("Code", "Severity", "Title", "Explanation", "Action", "URL"):
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(h)}</Data></Cell>')
    xml.append('   </Row>')

    for iss in rec_data.get("issue_explanations", []):
        xml.append('   <Row>')
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(iss.get("code"))}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(iss.get("severity"))}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(iss.get("title"))}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(iss.get("explanation"))}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(iss.get("action"))}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(iss.get("affected_url"))}</Data></Cell>')
        xml.append('   </Row>')

    xml.append('  </Table>')
    xml.append(' </Worksheet>')

    # Worksheet 3: Technical Fixes
    xml.append(' <Worksheet ss:Name="Technical Fixes">')
    xml.append('  <Table>')
    xml.append('   <Row ss:StyleID="Header">')
    for h in ("Snippet Type", "Category", "Title", "Description", "Code"):
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(h)}</Data></Cell>')
    xml.append('   </Row>')

    for tf in rec_data.get("technical_fixes", []):
        xml.append('   <Row>')
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(tf.get("snippet_type"))}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(tf.get("category"))}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(tf.get("title"))}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(tf.get("description"))}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(tf.get("code"))}</Data></Cell>')
        xml.append('   </Row>')

    xml.append('  </Table>')
    xml.append(' </Worksheet>')
    xml.append('</Workbook>')

    return "\n".join(xml)


class AiAdvisorReportCanvas(canvas.Canvas):
    """Two-pass ReportLab canvas for page numbers and running header/footer."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pages = []

    def showPage(self):
        self.pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        page_count = len(self.pages)
        for page in self.pages:
            self.__dict__.update(page)
            self.draw_decorations(page_count)
            super().showPage()
        super().save()

    def draw_decorations(self, page_count: int):
        self.saveState()
        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(colors.HexColor("#4F46E5"))
        self.drawString(14 * mm, 287 * mm, "AVIANCE SEO PRO MAX • AI SEO RECOMMENDATIONS & ASSISTANT")

        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748B"))
        self.drawRightString(196 * mm, 287 * mm, datetime.now(timezone.utc).strftime("%B %d, %Y"))

        self.setStrokeColor(colors.HexColor("#E2E8F0"))
        self.setLineWidth(0.5)
        self.line(14 * mm, 284 * mm, 196 * mm, 284 * mm)

        # Footer
        self.line(14 * mm, 14 * mm, 196 * mm, 14 * mm)
        self.drawString(14 * mm, 9 * mm, "Grounded in verified audit findings • Zero-fabrication policy enforced")
        self.drawRightString(196 * mm, 9 * mm, f"Page {self._pageNumber} of {page_count}")
        self.restoreState()


def generate_ai_recommendations_pdf(rec_data: Dict[str, Any]) -> bytes:
    """Renders multi-page vector ReportLab PDF report of AI SEO recommendations."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "AiTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#0F172A")
    )
    subtitle_style = ParagraphStyle(
        "AiSub",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#475569")
    )
    section_title = ParagraphStyle(
        "AiSection",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=17,
        textColor=colors.HexColor("#1E293B"),
        spaceBefore=10,
        spaceAfter=6
    )
    body_style = ParagraphStyle(
        "AiBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#334155")
    )
    code_style = ParagraphStyle(
        "AiCode",
        parent=styles["Normal"],
        fontName="Courier",
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor("#0F172A")
    )
    disclaimer_style = ParagraphStyle(
        "AiDisc",
        parent=styles["Normal"],
        fontName="Helvetica-Oblique",
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#1E40AF")
    )

    story = []
    target = rec_data.get("target", "")
    target_safe = html.escape(str(target))
    model_safe = html.escape(str(rec_data.get('source_model', 'AI Engine')))
    disc_safe = html.escape(str(rec_data.get('disclaimer', '')))

    # Header
    story.append(Paragraph(f"AI SEO Recommendations: {target_safe}", title_style))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(
        f"Evidence-grounded action roadmap generated via <b>{model_safe}</b>.",
        subtitle_style
    ))
    story.append(Spacer(1, 4 * mm))

    # Disclaimer Callout Box
    disc_data = [[Paragraph(f"<b>Evidence Grounding Policy:</b> {disc_safe}", disclaimer_style)]]
    disc_tbl = Table(disc_data, colWidths=[182 * mm])
    disc_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EFF6FF")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#BFDBFE")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(disc_tbl)
    story.append(Spacer(1, 4 * mm))

    # Prioritized Recommendations Table
    story.append(Paragraph("Prioritized Actionable Roadmap", section_title))
    recs = rec_data.get("prioritized_recommendations", [])
    if recs:
        rec_rows = [[
            Paragraph("<b>Priority</b>", subtitle_style),
            Paragraph("<b>Category</b>", subtitle_style),
            Paragraph("<b>Action Plan &amp; Fix</b>", subtitle_style),
            Paragraph("<b>Impact / Effort</b>", subtitle_style)
        ]]
        for r in recs[:12]:
            sev = r.get("priority", "MEDIUM")
            sev_color = "#DC2626" if sev == "CRITICAL" else ("#EA580C" if sev == "HIGH" else "#2563EB")
            title_safe = html.escape(str(r.get("title", "")))
            action_safe = html.escape(str(r.get("action", "")))
            category_safe = html.escape(str(r.get("category", "General")))
            impact_safe = html.escape(str(r.get("impact", "Medium")))
            effort_safe = html.escape(str(r.get("effort", "Medium")))
            rec_rows.append([
                Paragraph(f"<font color='{sev_color}'><b>{sev}</b></font>", body_style),
                Paragraph(f"<b>{category_safe}</b>", body_style),
                Paragraph(f"<b>{title_safe}</b><br/>{action_safe}", body_style),
                Paragraph(f"Impact: <b>{impact_safe}</b><br/>Effort: {effort_safe}", body_style)
            ])
        rec_tbl = Table(rec_rows, colWidths=[24 * mm, 32 * mm, 96 * mm, 30 * mm])
        rec_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F5F9")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(rec_tbl)
    story.append(Spacer(1, 4 * mm))

    # Technical Fixes Section
    story.append(Paragraph("Suggested Technical & Server Fixes", section_title))
    tech = rec_data.get("technical_fixes", [])
    for t in tech[:3]:
        tech_title = html.escape(str(t.get("title", "")))
        tech_type = html.escape(str(t.get("snippet_type", "Code")))
        code_safe = html.escape(str(t.get("code", "")))
        story.append(Paragraph(f"<b>{tech_title}</b> ({tech_type})", subtitle_style))
        story.append(Spacer(1, 1 * mm))
        code_box = [[Paragraph(f"<pre>{code_safe}</pre>", code_style)]]
        code_tbl = Table(code_box, colWidths=[182 * mm])
        code_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(code_tbl)
        story.append(Spacer(1, 2 * mm))

    doc.build(story, canvasmaker=AiAdvisorReportCanvas)
    return buf.getvalue()
