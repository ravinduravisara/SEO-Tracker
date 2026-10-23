"""
Admin-Scoped Scan History Manager
Maintains recent scan records per administrator without modifying existing SEO tables.
Thread-safe with JSON file persistence backup.
"""

from __future__ import annotations
import json
import logging
import threading
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

from .models import ScanResponse, HistoryItem

logger = logging.getLogger("tech_detector_history")

MAX_HISTORY_PER_ADMIN = 50
STORAGE_FILE = Path(__file__).resolve().parents[2] / "uploads" / "tech_detector_history.json"


class TechScanHistoryManager:
    """Thread-safe manager for tracking recent technology detection scans per admin."""

    def __init__(self, storage_path: Path = STORAGE_FILE):
        self.storage_path = storage_path
        self._lock = threading.Lock()
        # admin_id -> deque of ScanResponse dicts
        self._history: Dict[int, deque] = {}
        # scan_id -> ScanResponse dict
        self._scans_by_id: Dict[str, dict] = {}
        self._load()

    def _load(self):
        with self._lock:
            if not self.storage_path.exists():
                return
            try:
                data = json.loads(self.storage_path.read_text(encoding="utf-8"))
                for admin_str, scans in data.items():
                    admin_id = int(admin_str)
                    d = deque(maxlen=MAX_HISTORY_PER_ADMIN)
                    for s in scans:
                        d.append(s)
                        if "scan_id" in s:
                            self._scans_by_id[s["scan_id"]] = s
                    self._history[admin_id] = d
            except Exception as e:
                logger.warning("Could not load tech detector scan history: %s", e)

    def _persist(self):
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            serializable = {
                str(admin_id): list(scans)
                for admin_id, scans in self._history.items()
            }
            self.storage_path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error("Could not persist tech detector scan history: %s", e)

    def record_scan(self, admin_id: int, scan: ScanResponse):
        """Record a completed real scan for the given administrator."""
        scan_dict = scan.model_dump() if hasattr(scan, "model_dump") else scan.dict()
        with self._lock:
            if admin_id not in self._history:
                self._history[admin_id] = deque(maxlen=MAX_HISTORY_PER_ADMIN)
            self._history[admin_id].appendleft(scan_dict)
            self._scans_by_id[scan.scan_id] = scan_dict
            self._persist()

    def get_admin_history(self, admin_id: int) -> List[HistoryItem]:
        """Return summary list of recent scans for this administrator."""
        with self._lock:
            scans = self._history.get(admin_id, deque())
            items = []
            for s in scans:
                top_techs = [
                    t["name"] for t in s.get("detected_technologies", [])
                    if t.get("detection_status") in ("Strong Evidence", "Possible")
                ][:4]
                items.append(HistoryItem(
                    scan_id=s.get("scan_id", ""),
                    submitted_url=s.get("submitted_url", ""),
                    final_url=s.get("final_url", ""),
                    primary_classification=s.get("primary_classification", ""),
                    detected_count=s.get("total_detected_count", 0),
                    top_technologies=top_techs,
                    scanned_at=s.get("scanned_at", ""),
                    http_status=s.get("http_status", 200)
                ))
            return items

    def get_scan_by_id(self, scan_id: str) -> Optional[dict]:
        """Fetch raw scan payload by unique scan_id."""
        with self._lock:
            return self._scans_by_id.get(scan_id)


# Global singleton instance
history_manager = TechScanHistoryManager()
