"""
FastAPI Router for Website Technology Detector
Protected by server-side RBAC admin dependencies.
"""

from __future__ import annotations
import csv
import io
import json
import logging
from typing import List, Dict, Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..security import AdminUser, record_activity
from ..rbac import require_permission

from .models import ScanRequest, ScanResponse, HistoryItem, ExportRequest, TechnologyFinding
from .scanner import SafeTechScanner, validate_and_normalize_url
from .detector import TechnologyDetector
from .signatures import get_all_catalog_entries
from .history import history_manager

logger = logging.getLogger("tech_detector_router")

router = APIRouter(
    prefix="/api/admin/technology-detector",
    tags=["Website Technology Detector"]
)

# Reusable detector and scanner
_scanner = SafeTechScanner()
_detector = TechnologyDetector(scanner=_scanner)


@router.post("/scan", response_model=ScanResponse)
def scan_website(
    req: ScanRequest,
    current_admin: AdminUser = Depends(require_permission("tech_detector.scan")),
    db: Session = Depends(get_db)
):
    """
    Perform a real, non-invasive technology detection scan on a public website.
    Enforces SSRF prevention, timeouts, redirect limits, and returns evidence-based findings.
    """
    raw_url = req.url.strip()
    if not raw_url:
        raise HTTPException(status_code=400, detail="A website URL is required.")

    # 1. SSRF and destination validation
    try:
        validated_url = validate_and_normalize_url(raw_url)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    # 2. Safely fetch website content
    try:
        payload = _scanner.fetch(validated_url)
    except ValueError as ve:
        # Blocked private address or unsafe redirect hop
        raise HTTPException(status_code=400, detail=f"Target URL is not permitted: {ve}")
    except RuntimeError as re:
        raise HTTPException(status_code=504, detail=f"Scan failed: {re}")
    except Exception as exc:
        logger.error("Unexpected scanner error on %s: %s", raw_url, exc)
        raise HTTPException(status_code=500, detail="An error occurred while inspecting the target website.")

    # 3. Execute technology detection engine
    try:
        response = _detector.detect(payload)
    except Exception as exc:
        logger.error("Detection engine error on %s: %s", raw_url, exc)
        raise HTTPException(status_code=500, detail="An error occurred during technology classification.")

    # 4. Record history scoped to current administrator
    try:
        history_manager.record_scan(current_admin.id, response)
    except Exception as exc:
        logger.warning("Failed to record scan history: %s", exc)

    # 5. Record activity in audit trail
    try:
        record_activity(
            db,
            "TECH_DETECTOR_SCAN",
            f"Scanned {validated_url}",
            f"Classified: {response.primary_classification} ({response.total_detected_count} technologies)",
            user=current_admin
        )
    except Exception as exc:
        logger.warning("Failed to record activity log: %s", exc)

    return response


@router.get("/history", response_model=List[HistoryItem])
def get_recent_history(
    current_admin: AdminUser = Depends(require_permission("tech_detector.view"))
):
    """
    Retrieve real recent technology scans performed by the authenticated administrator.
    """
    return history_manager.get_admin_history(current_admin.id)


@router.get("/scan/{scan_id}", response_model=ScanResponse)
def get_scan_details(
    scan_id: str,
    current_admin: AdminUser = Depends(require_permission("tech_detector.view"))
):
    """
    Retrieve full details and evidence for a past scan by scan_id.
    """
    scan = history_manager.get_scan_by_id(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan result not found.")
    return scan


@router.get("/catalog")
def get_technology_catalog(
    current_admin: AdminUser = Depends(require_permission("tech_detector.view"))
):
    """
    Return all 96 cataloged technology signatures organized by category.
    """
    entries = get_all_catalog_entries()
    return {
        "total_count": len(entries),
        "catalog": [
            {
                "id": e.id,
                "name": e.name,
                "category_id": e.category_id,
                "category_name": e.category_name,
                "description": e.description,
                "limitations": e.limitations,
                "is_reliably_detectable": e.is_reliably_detectable
            }
            for e in entries
        ]
    }


@router.post("/export")
def export_scan_results(
    req: ExportRequest,
    current_admin: AdminUser = Depends(require_permission("tech_detector.view"))
):
    """
    Export real technology scan results and evidence as JSON or CSV.
    """
    scan = history_manager.get_scan_by_id(req.scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan record not found for export.")

    host = urlparse(scan.get("submitted_url", "site")).hostname or "website"
    safe_host = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in host)

    if req.export_format == "json":
        data_bytes = json.dumps(scan, ensure_ascii=False, indent=2).encode("utf-8")
        filename = f"technology-detector-{safe_host}-{scan.get('scan_id', '')[:8]}.json"
        return Response(
            content=data_bytes,
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    # CSV Export
    csv_out = io.StringIO(newline="")
    csv_out.write("\ufeff")  # BOM for Excel UTF-8 compatibility
    writer = csv.writer(csv_out)
    writer.writerow([
        "Technology Name",
        "Category",
        "Detection Status",
        "Confidence",
        "Version",
        "Evidence Count",
        "Primary Evidence Source",
        "Observed Fact",
        "Inference",
        "Limitations"
    ])

    for tech in scan.get("detected_technologies", []):
        evidence_list = tech.get("evidence", [])
        if evidence_list:
            for ev in evidence_list:
                writer.writerow([
                    tech.get("name", ""),
                    tech.get("category", ""),
                    tech.get("detection_status", ""),
                    tech.get("confidence", ""),
                    tech.get("version", "") or "N/A",
                    len(evidence_list),
                    ev.get("source", ""),
                    ev.get("observed_fact", ""),
                    ev.get("inference", ""),
                    tech.get("limitations", "")
                ])
        else:
            writer.writerow([
                tech.get("name", ""),
                tech.get("category", ""),
                tech.get("detection_status", ""),
                tech.get("confidence", ""),
                tech.get("version", "") or "N/A",
                0,
                "None",
                "None",
                tech.get("explanation", ""),
                tech.get("limitations", "")
            ])

    csv_bytes = csv_out.getvalue().encode("utf-8")
    filename = f"technology-detector-{safe_host}-{scan.get('scan_id', '')[:8]}.csv"
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
