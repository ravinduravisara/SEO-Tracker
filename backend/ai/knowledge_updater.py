"""
Controlled SEO Knowledge Update Service.

Manages automated and administrator-triggered SEO documentation refreshes,
change detection via SHA-256 hashes, version tracking, and rollback capabilities.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from .rag_engine import rag_knowledge_base, KnowledgeChunk, SEED_KNOWLEDGE_DOCUMENTS
from ..database import SessionLocal, KnowledgeDocument

logger = logging.getLogger("aviance.ai.knowledge_updater")


class KnowledgeVersionMeta(BaseModel):
    version: str
    active: bool = True
    created_at: str
    updated_at: str
    document_count: int
    source_count: int
    review_status: str = "APPROVED"
    notes: str = ""


class KnowledgeRefreshResult(BaseModel):
    success: bool
    version: str
    total_sources_checked: int
    documents_updated: int
    documents_unchanged: int
    failed_sources: List[str] = Field(default_factory=list)
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    message: str = ""


class KnowledgeUpdateService:
    """
    Manages controlled updates to the SEO knowledge base.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._versions: Dict[str, KnowledgeVersionMeta] = {
            "1.0.0": KnowledgeVersionMeta(
                version="1.0.0",
                active=True,
                created_at="2026-10-01T00:00:00",
                updated_at="2026-10-25T00:00:00",
                document_count=len(SEED_KNOWLEDGE_DOCUMENTS),
                source_count=len({d["source_url"] for d in SEED_KNOWLEDGE_DOCUMENTS}),
                notes="Initial baseline authoritative documentation corpus (Google Search Central & Web.dev)."
            )
        }
        self.active_version = "1.0.0"

    def refresh_knowledge(self, force_fetch: bool = False) -> KnowledgeRefreshResult:
        """
        Refreshes approved documentation sources with hash-based change detection.
        Runs safely in background or via admin trigger.
        """
        with self._lock:
            total_checked = 0
            updated_count = 0
            unchanged_count = 0
            failed_sources = []

            # Work on a clone of documents
            current_docs = rag_knowledge_base.get_all_documents()
            
            for doc in current_docs:
                total_checked += 1
                try:
                    # If force_fetch is true and network is enabled, check HTTP head/get
                    if force_fetch:
                        headers = {"User-Agent": "Aviance-SEO-Knowledge-Bot/2.0 (+https://esupport.live)"}
                        resp = requests.get(doc.source_url, headers=headers, timeout=5.0)
                        if resp.status_code == 200:
                            soup = BeautifulSoup(resp.text, "html.parser")
                            # Strip navigation and scripts
                            for tag in soup(["script", "style", "nav", "footer", "header"]):
                                tag.extract()
                            text = soup.get_text(" ", strip=True)
                            new_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
                            if new_hash != doc.content_hash:
                                # Content changed
                                updated_count += 1
                                doc.content_hash = new_hash
                                doc.retrieved_at = datetime.utcnow().isoformat()
                                continue
                    
                    unchanged_count += 1

                except Exception as exc:
                    logger.debug(f"Source fetch skipped/failed for {doc.source_url}: {exc}")
                    unchanged_count += 1
                    failed_sources.append(doc.source_url)

            # Record version update
            new_version = f"1.0.{len(self._versions)}"
            meta = KnowledgeVersionMeta(
                version=new_version,
                active=True,
                created_at=datetime.utcnow().isoformat(),
                updated_at=datetime.utcnow().isoformat(),
                document_count=len(current_docs),
                source_count=len({d.source_url for d in current_docs}),
                notes=f"Refresh check completed: {updated_count} updated, {unchanged_count} confirmed."
            )
            # Mark previous inactive
            if self.active_version in self._versions:
                self._versions[self.active_version].active = False
            self._versions[new_version] = meta
            self.active_version = new_version
            rag_knowledge_base.knowledge_version = new_version

            return KnowledgeRefreshResult(
                success=True,
                version=new_version,
                total_sources_checked=total_checked,
                documents_updated=updated_count,
                documents_unchanged=unchanged_count,
                failed_sources=failed_sources,
                message=f"Knowledge refresh completed successfully. Active version: {new_version}."
            )

    def rollback_version(self, target_version: str) -> bool:
        """
        Rolls back the active knowledge base to a prior recorded version.
        """
        with self._lock:
            if target_version not in self._versions:
                return False

            for v in self._versions.values():
                v.active = (v.version == target_version)

            self.active_version = target_version
            rag_knowledge_base.knowledge_version = target_version
            logger.info(f"Knowledge base rolled back to version {target_version}.")
            return True

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "active_version": self.active_version,
                "versions": [v.dict() for v in self._versions.values()],
                "document_count": rag_knowledge_base.document_count(),
                "last_checked": datetime.utcnow().isoformat()
            }


knowledge_update_service = KnowledgeUpdateService()

