"""
Data models and contracts for the Website Technology Detector module.
"""

from __future__ import annotations
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class ScanRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048, description="Target website URL to scan")


class EvidenceItem(BaseModel):
    source: str = Field(..., description="Evidence source, e.g., 'HTML Meta Generator', 'HTTP Response Header'")
    observed_fact: str = Field(..., description="Sanitized, observed snippet or header fact")
    inference: str = Field(..., description="Technical inference drawn from this fact")
    confidence: str = Field(..., description="'Strong Evidence' or 'Possible'")


class TechnologyFinding(BaseModel):
    id: str
    name: str
    category: str
    category_id: int
    detection_status: str = Field(..., description="'Strong Evidence', 'Possible', 'Not Detected', 'Not Measured', 'Inconclusive'")
    confidence: str = Field(..., description="'Strong Evidence', 'Possible', 'Not Detected', 'Not Measured', 'Inconclusive'")
    version: Optional[str] = None
    evidence: List[EvidenceItem] = Field(default_factory=list)
    description: str
    explanation: str
    limitations: str
    is_reliably_detectable: bool = True


class SecurityHeaderInfo(BaseModel):
    name: str
    present: bool
    value: Optional[str] = None


class ScanResponse(BaseModel):
    scan_id: str
    submitted_url: str
    final_url: str
    http_status: int
    is_https: bool
    scanned_at: str
    primary_classification: str
    primary_summary: str
    primary_category: str
    custom_website_assessment: str
    detected_technologies: List[TechnologyFinding]
    all_catalog_results: Optional[List[TechnologyFinding]] = None
    total_detected_count: int
    catalog_total_count: int = 96
    security_headers: List[SecurityHeaderInfo]
    scan_limitations: List[str]
    is_inconclusive: bool
    inconclusive_reasons: List[str]


class HistoryItem(BaseModel):
    scan_id: str
    submitted_url: str
    final_url: str
    primary_classification: str
    detected_count: int
    top_technologies: List[str]
    scanned_at: str
    http_status: int


class ExportRequest(BaseModel):
    scan_id: str
    export_format: str = Field("json", pattern="^(json|csv)$")
