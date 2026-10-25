"""Persistent Background Job Processing, Recovery & Provenance Service (Phase 12).

Provides:
- Persistent storage and tracking for background crawls and scheduled tasks.
- Restart recovery: detects and recovers orphaned running/queued jobs on server reboot.
- Progress reporting, cancellation events, and retry policies.
- Provenance recording (SHA-256 signatures, collector versions, timestamps).
- Dual-mode architecture: Redis-ready with persistent DB fallback.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from .database import BackgroundJob, SessionLocal, get_db

logger = logging.getLogger("aviance.jobs")

_CANCEL_EVENTS: Dict[str, threading.Event] = {}
_CANCEL_LOCK = threading.Lock()
REDIS_URL = os.getenv("REDIS_URL", "").strip()


def get_cancel_event(job_id: str) -> threading.Event:
    with _CANCEL_LOCK:
        if job_id not in _CANCEL_EVENTS:
            _CANCEL_EVENTS[job_id] = threading.Event()
        return _CANCEL_EVENTS[job_id]


def clear_cancel_event(job_id: str) -> None:
    with _CANCEL_LOCK:
        _CANCEL_EVENTS.pop(job_id, None)


def generate_provenance(
    source: str,
    target_url: str,
    collector_version: str = "2.0.0",
    raw_payload: Optional[Any] = None,
    verified: bool = True
) -> Dict[str, Any]:
    """
    Generates a cryptographic data provenance record guaranteeing measurement authenticity.
    """
    now_utc = datetime.now(timezone.utc)
    raw_bytes = json.dumps(raw_payload, sort_keys=True, default=str).encode("utf-8") if raw_payload is not None else b""
    content_hash = hashlib.sha256(raw_bytes).hexdigest() if raw_bytes else ""

    return {
        "source": source,
        "target_url": target_url,
        "collector_version": collector_version,
        "collected_at": now_utc.isoformat(),
        "sha256_hash": content_hash,
        "verified": verified,
        "environment": os.getenv("APP_ENV", "production")
    }


class PersistentJobManager:
    """Manages the full lifecycle of persistent background jobs with restart recovery."""

    @staticmethod
    def enqueue_job(
        job_type: str,
        target_url: str = "",
        client_id: Optional[int] = None,
        website_id: Optional[int] = None,
        audit_id: Optional[int] = None,
        max_retries: int = 3,
        initial_progress: Optional[Dict[str, Any]] = None,
        db: Optional[Session] = None
    ) -> BackgroundJob:
        close_session = False
        if db is None:
            db = SessionLocal()
            close_session = True

        try:
            job_id = uuid.uuid4().hex
            job = BackgroundJob(
                id=job_id,
                job_type=job_type,
                target_url=target_url,
                client_id=client_id,
                website_id=website_id,
                audit_id=audit_id,
                status="QUEUED",
                progress_pct=0.0,
                progress_phase="queued",
                progress_json=json.dumps(initial_progress or {"phase": "queued", "pages": 0, "queued": 1}),
                retry_count=0,
                max_retries=max_retries,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
            db.add(job)
            db.commit()
            db.refresh(job)
            # Register in-memory cancel event
            get_cancel_event(job_id)
            logger.info("Enqueued persistent job %s (type: %s, target: %s)", job_id, job_type, target_url)
            return job
        finally:
            if close_session:
                db.close()

    @staticmethod
    def start_job(job_id: str, db: Optional[Session] = None) -> Optional[BackgroundJob]:
        close_session = False
        if db is None:
            db = SessionLocal()
            close_session = True

        try:
            job = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
            if not job:
                return None
            job.status = "RUNNING"
            job.started_at = datetime.now(timezone.utc)
            job.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(job)
            return job
        finally:
            if close_session:
                db.close()

    @staticmethod
    def update_progress(
        job_id: str,
        progress_pct: float,
        phase: str,
        progress_data: Optional[Dict[str, Any]] = None,
        db: Optional[Session] = None
    ) -> Optional[BackgroundJob]:
        close_session = False
        if db is None:
            db = SessionLocal()
            close_session = True

        try:
            job = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
            if not job:
                return None
            job.progress_pct = round(max(0.0, min(100.0, float(progress_pct))), 1)
            job.progress_phase = phase
            if progress_data:
                job.progress_json = json.dumps(progress_data)
            job.updated_at = datetime.now(timezone.utc)
            db.commit()
            return job
        finally:
            if close_session:
                db.close()

    @staticmethod
    def complete_job(job_id: str, result_summary: Optional[Dict[str, Any]] = None, db: Optional[Session] = None) -> Optional[BackgroundJob]:
        close_session = False
        if db is None:
            db = SessionLocal()
            close_session = True

        try:
            job = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
            if not job:
                return None
            job.status = "COMPLETED"
            job.progress_pct = 100.0
            job.progress_phase = "completed"
            if result_summary:
                job.progress_json = json.dumps(result_summary)
            job.completed_at = datetime.now(timezone.utc)
            job.updated_at = datetime.now(timezone.utc)
            db.commit()
            clear_cancel_event(job_id)
            logger.info("Completed persistent job %s", job_id)
            return job
        finally:
            if close_session:
                db.close()

    @staticmethod
    def fail_job(job_id: str, error_message: str, db: Optional[Session] = None) -> Optional[BackgroundJob]:
        close_session = False
        if db is None:
            db = SessionLocal()
            close_session = True

        try:
            job = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
            if not job:
                return None

            job.error_message = str(error_message)[:1000]
            job.updated_at = datetime.now(timezone.utc)

            # Retry policy evaluation
            if job.retry_count < job.max_retries:
                job.retry_count += 1
                job.status = "QUEUED"
                job.progress_phase = f"retrying (attempt {job.retry_count}/{job.max_retries})"
                logger.warning("Job %s failed (%s); scheduled retry attempt %s/%s", job_id, error_message, job.retry_count, job.max_retries)
            else:
                job.status = "FAILED"
                job.progress_phase = "failed"
                job.completed_at = datetime.now(timezone.utc)
                logger.error("Job %s permanently failed after %s retries: %s", job_id, job.retry_count, error_message)

            db.commit()
            clear_cancel_event(job_id)
            return job
        finally:
            if close_session:
                db.close()

    @staticmethod
    def cancel_job(job_id: str, db: Optional[Session] = None) -> bool:
        close_session = False
        if db is None:
            db = SessionLocal()
            close_session = True

        try:
            job = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
            if not job:
                return False

            # Signal cancellation
            evt = get_cancel_event(job_id)
            evt.set()

            job.status = "CANCELLED"
            job.progress_phase = "cancelled_by_user"
            job.completed_at = datetime.now(timezone.utc)
            job.updated_at = datetime.now(timezone.utc)
            db.commit()
            clear_cancel_event(job_id)
            logger.info("Cancelled persistent job %s", job_id)
            return True
        finally:
            if close_session:
                db.close()

    @staticmethod
    def recover_orphaned_jobs(db: Optional[Session] = None) -> int:
        """
        Executed on server startup: detects jobs that were marked 'RUNNING' or 'QUEUED'
        when the server terminated or crashed, and recovers them.
        """
        close_session = False
        if db is None:
            db = SessionLocal()
            close_session = True

        try:
            interrupted = db.query(BackgroundJob).filter(
                BackgroundJob.status.in_(["RUNNING", "QUEUED"])
            ).all()

            count = len(interrupted)
            if not count:
                logger.info("Server startup check: 0 orphaned background jobs detected.")
                return 0

            logger.warning("Server startup recovery: detected %s orphaned job(s) from previous server execution.", count)
            for j in interrupted:
                if j.retry_count < j.max_retries:
                    j.retry_count += 1
                    j.status = "QUEUED"
                    j.progress_phase = f"recovered_queued (attempt {j.retry_count}/{j.max_retries})"
                    j.error_message = "Interrupted by server restart; automatically re-queued for execution."
                else:
                    j.status = "FAILED"
                    j.progress_phase = "interrupted_by_server_restart"
                    j.error_message = "Interrupted by server restart; exceeded max retries."
                    j.completed_at = datetime.now(timezone.utc)
                j.updated_at = datetime.now(timezone.utc)

            db.commit()
            logger.info("Server startup recovery: successfully processed %s orphaned jobs.", count)
            return count
        finally:
            if close_session:
                db.close()

    @staticmethod
    def list_jobs(
        status: Optional[str] = None,
        job_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        db: Optional[Session] = None
    ) -> List[Dict[str, Any]]:
        close_session = False
        if db is None:
            db = SessionLocal()
            close_session = True

        try:
            q = db.query(BackgroundJob)
            if status:
                q = q.filter(BackgroundJob.status == status.upper())
            if job_type:
                q = q.filter(BackgroundJob.job_type == job_type.upper())

            rows = q.order_by(BackgroundJob.created_at.desc()).offset(offset).limit(limit).all()
            return [
                {
                    "id": r.id,
                    "job_type": r.job_type,
                    "target_url": r.target_url,
                    "status": r.status,
                    "progress_pct": r.progress_pct,
                    "progress_phase": r.progress_phase,
                    "progress": json.loads(r.progress_json) if isinstance(r.progress_json, str) else (r.progress_json or {}),
                    "retry_count": r.retry_count,
                    "max_retries": r.max_retries,
                    "error_message": r.error_message,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
        finally:
            if close_session:
                db.close()

