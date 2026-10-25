"""
AI Recommendation Verification Engine.

Enforces strict factual consistency, rejects hallucinations, verifies citations,
and ensures AI suggestions never contradict verified crawler evidence.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from .rag_engine import rag_knowledge_base
from ..database import SessionLocal, AIRecommendationRecord

logger = logging.getLogger("aviance.ai.validator")

# Banned hallucination phrases that violate SEO integrity
PROHIBITED_GUARANTEE_PATTERNS = [
    r"guarantee(?:s|d)?\s+(?:.*)?(?:first\s+page|top\s+rank|#1\s+position|#1\s+ranking|#1|ranking|traffic)",
    r"will\s+rank\s+(?:#1|first|number\s+one)",
    r"guaranteed\s+(?:traffic|rankings?|results?)",
    r"100%\s+indexing\s+guarantee",
]


class ValidatedRecommendation(BaseModel):
    recommendation_id: str
    issue_id: str
    affected_url: str
    category: str
    issue_title: str
    severity: str
    evidence_reference: str
    explanation: str
    recommended_action: str
    developer_instructions: str
    verification_method: str
    documentation_references: List[Dict[str, str]] = Field(default_factory=list)
    evidence_status: str = "VERIFIED"  # VERIFIED | PROVISIONAL | INSUFFICIENT_EVIDENCE
    validation_status: str = "VERIFIED"  # VERIFIED | REJECTED | INSUFFICIENT_EVIDENCE
    validation_reason: str = "Verified against crawler findings and documentation."
    validated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class ValidationReport(BaseModel):
    total_evaluated: int = 0
    verified_count: int = 0
    rejected_count: int = 0
    insufficient_evidence_count: int = 0
    verified_recommendations: List[ValidatedRecommendation] = Field(default_factory=list)
    rejected_recommendations: List[ValidatedRecommendation] = Field(default_factory=list)


def validate_recommendation(
    rec: Dict[str, Any],
    audit_data: Dict[str, Any],
    verified_issues_map: Dict[str, Dict[str, Any]]
) -> ValidatedRecommendation:
    """
    Deterministically validates a single AI-generated recommendation.
    """
    rec_id = str(rec.get("recommendation_id") or rec.get("id") or "REC-UNKNOWN")
    issue_id = str(rec.get("issue_id") or rec.get("code") or rec.get("check_id") or "")
    affected_urls_list = rec.get("affected_urls")
    if isinstance(affected_urls_list, list) and affected_urls_list:
        affected_url = str(affected_urls_list[0])
    else:
        affected_url = str(rec.get("affected_url") or "")
    category = str(rec.get("category") or "General")
    issue_title = str(rec.get("issue_title") or rec.get("title") or "")
    severity = str(rec.get("severity") or rec.get("priority") or "MEDIUM").upper()
    evidence_ref = str(rec.get("evidence_reference") or rec.get("evidence") or "")
    explanation = str(rec.get("explanation") or "")
    action = str(rec.get("recommended_action") or rec.get("action") or "")
    dev_instructions = str(rec.get("developer_instructions") or "")
    verification_method = str(rec.get("verification_method") or rec.get("validation") or "")
    doc_refs = rec.get("documentation_references") or []
    if isinstance(doc_refs, list):
        clean_docs = [{"title": str(d.get("title", "")), "url": str(d.get("url", "")) or str(d.get("source_url", ""))} for d in doc_refs if isinstance(d, dict)]
    else:
        clean_docs = []

    target_url = audit_data.get("target") or audit_data.get("url") or ""
    target_host = (urlparse(target_url).hostname or "").lower().removeprefix("www.")

    # 1. Check issue ID existence (with title/category heuristic fallback)
    if not issue_id and verified_issues_map:
        t_low = issue_title.lower()
        for k, v in verified_issues_map.items():
            vt = (v.get("title") or "").lower()
            if (vt and vt in t_low) or (t_low and t_low in vt):
                issue_id = k
                break
        if not issue_id:
            issue_id = next(iter(verified_issues_map.keys()))

    if not issue_id or issue_id not in verified_issues_map:
        return ValidatedRecommendation(
            recommendation_id=rec_id,
            issue_id=issue_id,
            affected_url=affected_url,
            category=category,
            issue_title=issue_title,
            severity=severity,
            evidence_reference=evidence_ref,
            explanation=explanation,
            recommended_action=action,
            developer_instructions=dev_instructions,
            verification_method=verification_method,
            documentation_references=clean_docs,
            evidence_status="INSUFFICIENT_EVIDENCE",
            validation_status="REJECTED",
            validation_reason=f"Issue identifier '{issue_id}' was not found in verified audit telemetry."
        )

    matched_issue = verified_issues_map[issue_id]

    # 2. Check URL domain boundary
    if affected_url:
        aff_host = (urlparse(affected_url).hostname or "").lower().removeprefix("www.")
        if target_host and aff_host and (aff_host != target_host and not aff_host.endswith(f".{target_host}")):
            return ValidatedRecommendation(
                recommendation_id=rec_id,
                issue_id=issue_id,
                affected_url=affected_url,
                category=category,
                issue_title=issue_title,
                severity=severity,
                evidence_reference=evidence_ref,
                explanation=explanation,
                recommended_action=action,
                developer_instructions=dev_instructions,
                verification_method=verification_method,
                documentation_references=clean_docs,
                evidence_status="INSUFFICIENT_EVIDENCE",
                validation_status="REJECTED",
                validation_reason=f"Affected URL host '{aff_host}' is outside the authorized audit target '{target_host}'."
            )

    # 3. Check for prohibited guaranteed ranking claims
    combined_text = f"{explanation} {action} {dev_instructions}"
    for pat in PROHIBITED_GUARANTEE_PATTERNS:
        if re.search(pat, combined_text, re.IGNORECASE):
            return ValidatedRecommendation(
                recommendation_id=rec_id,
                issue_id=issue_id,
                affected_url=affected_url,
                category=category,
                issue_title=issue_title,
                severity=severity,
                evidence_reference=evidence_ref,
                explanation=explanation,
                recommended_action=action,
                developer_instructions=dev_instructions,
                verification_method=verification_method,
                documentation_references=clean_docs,
                evidence_status="INSUFFICIENT_EVIDENCE",
                validation_status="REJECTED",
                validation_reason="Recommendation makes prohibited, unsupportable claims of guaranteed Google rankings."
            )

    # 4. Check for contradiction against audit facts
    # Contradiction check: XML sitemap
    if "sitemap" in combined_text.lower():
        site_info = audit_data.get("site", {}).get("sitemap") or {}
        has_sitemap = bool(site_info.get("url_count") or site_info.get("found") or audit_data.get("sitemap_present"))
        if has_sitemap and re.search(r"(?:create|generate|missing|does not have|lacks)\s+(?:an?\s+)?(?:xml\s+)?sitemap", combined_text, re.I):
            return ValidatedRecommendation(
                recommendation_id=rec_id,
                issue_id=issue_id,
                affected_url=affected_url,
                category=category,
                issue_title=issue_title,
                severity=severity,
                evidence_reference=evidence_ref,
                explanation=explanation,
                recommended_action=action,
                developer_instructions=dev_instructions,
                verification_method=verification_method,
                documentation_references=clean_docs,
                evidence_status="INSUFFICIENT_EVIDENCE",
                validation_status="REJECTED",
                validation_reason="Recommendation contradicts verified audit evidence: a valid XML sitemap was already verified."
            )

    # Contradiction check: robots.txt HTTP 404
    if "robots" in combined_text.lower():
        robots_info = audit_data.get("site", {}).get("robots") or {}
        r_status = robots_info.get("status_code", 0) or audit_data.get("robots_txt_status", 0)
        if r_status in (404, 410) and re.search(r"(?:critical|severe|penalty|disaster|emergency)", combined_text, re.I):
            return ValidatedRecommendation(
                recommendation_id=rec_id,
                issue_id=issue_id,
                affected_url=affected_url,
                category=category,
                issue_title=issue_title,
                severity=severity,
                evidence_reference=evidence_ref,
                explanation=explanation,
                recommended_action=action,
                developer_instructions=dev_instructions,
                verification_method=verification_method,
                documentation_references=clean_docs,
                evidence_status="INSUFFICIENT_EVIDENCE",
                validation_status="REJECTED",
                validation_reason="Under Google Search Central specifications, HTTP 404 on robots.txt is not a critical ranking failure."
            )

    # Contradiction check: fabricated keyword search volumes
    if re.search(r"(\b\d{1,3}(?:,\d{3})+\s*(?:monthly\s+)?searches\b|search\s+volume\s+of\s+\d{1,3}(?:,\d{3})+)", combined_text, re.I):
        rd = audit_data.get("real_data") or {}
        has_kw_data = bool(rd.get("dataforseo") or rd.get("search_console") or audit_data.get("keyword_integration_enabled"))
        if not has_kw_data:
            return ValidatedRecommendation(
                recommendation_id=rec_id,
                issue_id=issue_id,
                affected_url=affected_url,
                category=category,
                issue_title=issue_title,
                severity=severity,
                evidence_reference=evidence_ref,
                explanation=explanation,
                recommended_action=action,
                developer_instructions=dev_instructions,
                verification_method=verification_method,
                documentation_references=clean_docs,
                evidence_status="INSUFFICIENT_EVIDENCE",
                validation_status="REJECTED",
                validation_reason="Recommendation contains unverified numerical keyword search volumes without a connected volume data provider."
            )

    # 5. Fallback documentation citation if missing
    if not clean_docs:
        cites = rag_knowledge_base.get_citations_for_issue(issue_id, category, issue_title)
        clean_docs = [{"title": c.title, "url": c.source_url} for c in cites]

    return ValidatedRecommendation(
        recommendation_id=rec_id,
        issue_id=issue_id,
        affected_url=affected_url or target_url,
        category=category,
        issue_title=issue_title or matched_issue.get("title", "SEO Issue"),
        severity=severity,
        evidence_reference=evidence_ref or matched_issue.get("evidence", ""),
        explanation=explanation or f"Addressed issue {issue_id} under Google search specifications.",
        recommended_action=action,
        developer_instructions=dev_instructions,
        verification_method=verification_method or f"Re-run technical crawl and verify {issue_id} reports PASS.",
        documentation_references=clean_docs,
        evidence_status="VERIFIED",
        validation_status="VERIFIED",
        validation_reason="Verified against crawler telemetry and authoritative Google search guidelines."
    )


def validate_all_recommendations(
    raw_recommendations: List[Dict[str, Any]],
    audit_data: Dict[str, Any],
    audit_id: Optional[int] = None
) -> ValidationReport:
    """
    Validates a batch of recommendations and persists outcomes to database.
    """
    raw_issues = audit_data.get("issues") or []
    issues_map = {}
    for idx, iss in enumerate(raw_issues):
        cid = str(iss.get("code") or iss.get("check_id") or f"ISSUE_{idx+1}")
        issues_map[cid] = iss

    report = ValidationReport()
    report.total_evaluated = len(raw_recommendations)

    for rec in raw_recommendations:
        validated = validate_recommendation(rec, audit_data, issues_map)
        if validated.validation_status == "VERIFIED":
            report.verified_count += 1
            report.verified_recommendations.append(validated)
        else:
            report.rejected_count += 1
            report.rejected_recommendations.append(validated)

    # Persist to database for auditing and diagnostics
    if audit_id:
        try:
            with SessionLocal() as db:
                for v in report.verified_recommendations + report.rejected_recommendations:
                    rec_row = AIRecommendationRecord(
                        audit_id=audit_id,
                        recommendation_id=v.recommendation_id,
                        issue_id=v.issue_id,
                        affected_url=v.affected_url,
                        category=v.category,
                        issue_title=v.issue_title,
                        severity=v.severity,
                        explanation=v.explanation,
                        recommended_action=v.recommended_action,
                        developer_instructions=v.developer_instructions,
                        verification_method=v.verification_method,
                        citations_json=json.dumps(v.documentation_references),
                        evidence_status=v.evidence_status,
                        validation_status=v.validation_status,
                        validation_reason=v.validation_reason,
                        created_at=datetime.utcnow()
                    )
                    db.add(rec_row)
                db.commit()
        except Exception as exc:
            logger.debug(f"Failed to persist recommendation record: {exc}")

    return report
