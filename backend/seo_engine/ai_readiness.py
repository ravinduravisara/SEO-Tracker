"""AI Search Readiness & Generative Engine Optimization (GEO) Analyzer (Phase 7.12).

Evaluates website readiness for AI-powered search engines, conversational agents,
and generative search experiences (Google AI Overviews, Perplexity AI, ChatGPT Search, Gemini).
Analyzes bot permissions, factual entity clarity, direct answer capability, and source transparency.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser


AI_BOTS = [
    {"name": "GPTBot", "owner": "OpenAI", "purpose": "ChatGPT Web Search & Training"},
    {"name": "ChatGPT-User", "owner": "OpenAI", "purpose": "Direct User Browsing in ChatGPT"},
    {"name": "Google-Extended", "owner": "Google", "purpose": "Google Gemini & AI Overviews"},
    {"name": "PerplexityBot", "owner": "Perplexity AI", "purpose": "Perplexity AI Search & Citations"},
    {"name": "ClaudeBot", "owner": "Anthropic", "purpose": "Claude AI Search & Citations"},
    {"name": "anthropic-ai", "owner": "Anthropic", "purpose": "Anthropic Model Evaluation"},
    {"name": "CCBot", "owner": "Common Crawl", "purpose": "Open Training Dataset Foundation"},
]


def evaluate_ai_search_readiness(
    target_url: str,
    pages: list[dict[str, Any]],
    robots_data: dict[str, Any],
    sitemap_data: dict[str, Any]
) -> dict[str, Any]:
    """Computes evidence-grounded AI search readiness score and findings."""
    root_url = f"{urlparse(target_url).scheme}://{urlparse(target_url).netloc}"
    robots_content = robots_data.get("content", "")
    robots_found = bool(robots_data.get("found"))
    
    # 1. AI Crawler Accessibility
    bot_status: list[dict[str, Any]] = []
    blocked_bots = []
    allowed_bots = []
    
    if robots_found and robots_content:
        rp = RobotFileParser()
        rp.parse(robots_content.splitlines())
        
        for bot in AI_BOTS:
            bot_name = bot["name"]
            # Check explicit robot rule
            is_disallowed = False
            # Check pattern in robots content directly for fine-grained clarity
            bot_pattern = re.search(
                rf"(?im)^\s*User-agent:\s*{re.escape(bot_name)}\s*\n(?:^\s*(?:Disallow|Allow):[^\n]*\n)*^\s*Disallow:\s*(/.*)\s*$",
                robots_content
            )
            if bot_pattern:
                disallow_path = bot_pattern.group(1).strip()
                if disallow_path == "/" or disallow_path.startswith("/*"):
                    is_disallowed = True
            elif not rp.can_fetch(bot_name, root_url + "/"):
                is_disallowed = True
                
            status_label = "BLOCKED" if is_disallowed else "ALLOWED"
            if is_disallowed:
                blocked_bots.append(bot_name)
            else:
                allowed_bots.append(bot_name)
                
            bot_status.append({
                "bot": bot_name,
                "owner": bot["owner"],
                "purpose": bot["purpose"],
                "status": status_label,
                "disallow_rule": bot_pattern.group(0).strip() if bot_pattern else None
            })
    else:
        for bot in AI_BOTS:
            allowed_bots.append(bot["name"])
            bot_status.append({
                "bot": bot["name"],
                "owner": bot["owner"],
                "purpose": bot["purpose"],
                "status": "ALLOWED (DEFAULT)",
                "disallow_rule": None
            })
            
    bot_score = round((len(allowed_bots) / max(1, len(AI_BOTS))) * 100)
    
    # 2. Entity & Authority Clarity (Schema, Organization, About Page)
    entity_signals = {
        "has_organization_schema": False,
        "has_person_schema": False,
        "has_about_page": False,
        "has_contact_page": False,
        "has_social_sameas": False,
    }
    
    for p in pages:
        path = urlparse(p.get("url", "")).path.lower()
        if any(x in path for x in ("/about", "/about-us", "/company", "/team", "/who-we-are")):
            entity_signals["has_about_page"] = True
        if any(x in path for x in ("/contact", "/contact-us", "/get-in-touch", "/reach-us")):
            entity_signals["has_contact_page"] = True
            
        for node in p.get("schema_nodes", []):
            if isinstance(node, dict):
                node_type = str(node.get("@type", "")).lower()
                if "organization" in node_type or "localbusiness" in node_type or "corporation" in node_type:
                    entity_signals["has_organization_schema"] = True
                    if node.get("sameAs"):
                        entity_signals["has_social_sameas"] = True
                if "person" in node_type or "author" in node_type:
                    entity_signals["has_person_schema"] = True
                    
    entity_points = sum([
        30 if entity_signals["has_organization_schema"] else 0,
        25 if entity_signals["has_about_page"] else 0,
        20 if entity_signals["has_contact_page"] else 0,
        15 if entity_signals["has_social_sameas"] else 0,
        10 if entity_signals["has_person_schema"] else 0,
    ])
    entity_score = min(100, entity_points)
    
    # 3. Direct Answers & FAQ Readiness
    faq_signals = {
        "has_faq_schema": any("FAQPage" in p.get("schema_types", []) for p in pages),
        "faq_terms_count": 0,
        "question_headings_count": 0,
    }
    
    for p in pages:
        # Check headings for question forms (what, how, why, when, who, can, does)
        headings = (p.get("h2") or []) + (p.get("h3") or [])
        for h in headings:
            if re.search(r"^(what|how|why|when|where|who|which|can|does|is|are|should)\b|\?$", h.strip(), re.I):
                faq_signals["question_headings_count"] += 1
                
    faq_score = 0
    if faq_signals["has_faq_schema"]:
        faq_score += 50
    if faq_signals["question_headings_count"] >= 3:
        faq_score += 50
    elif faq_signals["question_headings_count"] >= 1:
        faq_score += 25
    faq_score = min(100, faq_score)
    
    # 4. Content Structure & Extractability
    structured_content_pages = sum(
        1 for p in pages 
        if p.get("word_count", 0) >= 300 
        and len(p.get("h2", [])) >= 2 
        and not p.get("rendering_signals", {}).get("likely_js_shell")
    )
    extractability_score = round((structured_content_pages / max(1, len(pages))) * 100)
    
    # Overall GEO Readiness Score
    geo_score = round(
        (bot_score * 0.30) +
        (entity_score * 0.25) +
        (faq_score * 0.25) +
        (extractability_score * 0.20)
    )
    
    # Actionable Findings
    geo_findings = []
    if blocked_bots:
        geo_findings.append({
            "code": "AI_BOTS_BLOCKED",
            "category": "AI Search Readiness",
            "severity": "HIGH",
            "title": f"Robots.txt blocks {len(blocked_bots)} AI search bot(s)",
            "message": f"Bots blocked: {', '.join(blocked_bots)}. This prevents search agents from indexing, synthesizing, and citing this domain.",
            "recommendation": "Review robots.txt disallow rules. Allow GPTBot and PerplexityBot if you want AI engines to cite your brand.",
            "impact": "Domain cannot appear in AI search syntheses or citations."
        })
    else:
        geo_findings.append({
            "code": "AI_BOTS_PERMITTED",
            "category": "AI Search Readiness",
            "severity": "NOTICE",
            "title": "AI Search crawlers permitted",
            "message": "Major AI crawlers (GPTBot, PerplexityBot, ClaudeBot, Google-Extended) can access public content.",
            "recommendation": "Maintain open crawlability for high-value public informational pages.",
            "impact": "Positive: Allows generative search models to discover and reference website content."
        })
        
    if not entity_signals["has_organization_schema"]:
        geo_findings.append({
            "code": "MISSING_ENTITY_SCHEMA",
            "category": "AI Search Readiness",
            "severity": "MEDIUM",
            "title": "Missing Organization Knowledge Graph Schema",
            "message": "No structured Organization JSON-LD was detected on the site.",
            "recommendation": "Publish Organization schema with official name, url, logo, and sameAs social profile links to establish entity identity in AI knowledge bases.",
            "impact": "AI models may confuse or fail to disambiguate the brand entity."
        })
        
    if not faq_signals["has_faq_schema"] and faq_signals["question_headings_count"] < 2:
        geo_findings.append({
            "code": "NO_DIRECT_ANSWER_FORMAT",
            "category": "AI Search Readiness",
            "severity": "LOW",
            "title": "Low direct question-and-answer structure",
            "message": "Few question headings or FAQ structured data found across crawled pages.",
            "recommendation": "Format common customer inquiries as clear H2 questions followed by immediate direct answers (40-60 words), then annotate with FAQPage schema.",
            "impact": "Low probability of being selected as a snippet source for conversational search."
        })

    return {
        "score": geo_score,
        "grade": "EXCELLENT" if geo_score >= 85 else "GOOD" if geo_score >= 70 else "NEEDS_IMPROVEMENT" if geo_score >= 50 else "POOR",
        "bot_accessibility": {
            "score": bot_score,
            "allowed_count": len(allowed_bots),
            "blocked_count": len(blocked_bots),
            "bots": bot_status
        },
        "entity_authority": {
            "score": entity_score,
            "signals": entity_signals
        },
        "direct_answers": {
            "score": faq_score,
            "signals": faq_signals
        },
        "content_extractability": {
            "score": extractability_score,
            "structured_pages": structured_content_pages,
            "total_pages": len(pages)
        },
        "findings": geo_findings,
    }

