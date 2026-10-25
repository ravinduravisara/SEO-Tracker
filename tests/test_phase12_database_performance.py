"""Test Suite: Phase 12 Database, Performance, Provenance & Background Processing.

Covers:
1. Unified Project CRUD operations and relational indexing
2. Page-level findings persistence and filtering
3. Report export tracking with cryptographic provenance
4. Persistent background job lifecycle (Queue -> Running -> Progress -> Completed)
5. Background job cancellation via cancellation events
6. Background job retry policy (max retries and status transition to FAILED)
7. Server restart recovery for orphaned running/queued jobs
8. Safe non-destructive database migrations (init_db idempotency)
9. Data provenance SHA-256 integrity verification
10. Relational integrity across Projects, Websites, and Audits
"""
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from backend.database import (
    AdminUser,
    Audit,
    BackgroundJob,
    Client,
    PageFinding,
    Project,
    ReportExport,
    SessionLocal,
    Website,
    init_db,
)
from backend.job_service import (
    PersistentJobManager,
    clear_cancel_event,
    generate_provenance,
    get_cancel_event,
)
from backend.main import (
    ProjectCreateRequest,
    ProjectUpdateRequest,
    create_project_endpoint,
    delete_project_endpoint,
    get_project_endpoint,
    list_audit_findings_endpoint,
    list_background_jobs_endpoint,
    list_projects_endpoint,
    list_report_exports_endpoint,
    update_project_endpoint,
)


class TestPhase12DatabasePerformance(unittest.TestCase):

    def setUp(self):
        init_db()
        self.db = SessionLocal()
        self.admin = AdminUser(
            email="phase12.admin@example.com",
            name="Phase 12 Admin",
            role="SUPER_ADMIN",
            status="ACTIVE",
            password_hash="test-hash"
        )
        # Create a test client
        self.client = Client(name="Acme Corp", company="Acme Industries", email="seo@acme.com")
        self.db.add(self.client)
        self.db.commit()
        self.db.refresh(self.client)

    def tearDown(self):
        try:
            self.db.query(PageFinding).delete()
            self.db.query(ReportExport).delete()
            self.db.query(BackgroundJob).delete()
            self.db.query(Audit).delete()
            self.db.query(Website).delete()
            self.db.query(Project).delete()
            self.db.query(Client).filter(Client.id == self.client.id).delete()
            self.db.commit()
        finally:
            self.db.close()

    # 1. Unified Project CRUD operations
    def test_project_crud_persistence(self):
        # Create
        req = ProjectCreateRequest(
            name="Q4 Enterprise SEO Project",
            description="Complete site audit and keyword tracking",
            client_id=self.client.id,
            target_domains=["acme.com", "shop.acme.com"]
        )
        res = create_project_endpoint(req=req, db=self.db, current_admin=self.admin)
        self.assertEqual(res["status"], "success")
        proj_id = res["project_id"]

        # Read
        proj = get_project_endpoint(project_id=proj_id, db=self.db, current_admin=self.admin)
        self.assertEqual(proj["name"], "Q4 Enterprise SEO Project")
        self.assertEqual(proj["client_id"], self.client.id)
        self.assertIn("acme.com", proj["target_domains"])

        # Update
        upd_req = ProjectUpdateRequest(name="Q4 Enterprise SEO Project (Updated)", status="ACTIVE")
        upd_res = update_project_endpoint(project_id=proj_id, req=upd_req, db=self.db, current_admin=self.admin)
        self.assertEqual(upd_res["name"], "Q4 Enterprise SEO Project (Updated)")

        # List
        projects = list_projects_endpoint(client_id=self.client.id, db=self.db, current_admin=self.admin)
        self.assertTrue(any(p["id"] == proj_id for p in projects))

        # Delete
        del_res = delete_project_endpoint(project_id=proj_id, db=self.db, current_admin=self.admin)
        self.assertEqual(del_res["status"], "success")

    # 2. Page-level findings persistence and filtering
    def test_page_findings_persistence(self):
        audit = Audit(
            target_url="https://acme.com",
            result_json="{}",
            score=82.0,
            status="COMPLETED"
        )
        self.db.add(audit)
        self.db.commit()
        self.db.refresh(audit)

        f1 = PageFinding(
            audit_id=audit.id,
            url="https://acme.com/products",
            check_id="T04",
            category="technical",
            severity="critical",
            problem_description="Broken canonical link destination (HTTP 404)",
            suggested_correction="Update canonical URL to resolve to valid product index."
        )
        f2 = PageFinding(
            audit_id=audit.id,
            url="https://acme.com/about",
            check_id="O09",
            category="on_page",
            severity="medium",
            problem_description="Multiple H1 tags in semantic layout",
            suggested_correction="Consider consolidating section titles."
        )
        self.db.add_all([f1, f2])
        self.db.commit()

        # Query all
        all_findings = list_audit_findings_endpoint(audit_id=audit.id, db=self.db)
        self.assertEqual(len(all_findings), 2)

        # Filter by severity
        crit = list_audit_findings_endpoint(audit_id=audit.id, severity="critical", db=self.db)
        self.assertEqual(len(crit), 1)
        self.assertEqual(crit[0]["check_id"], "T04")

    # 3. Report export tracking with cryptographic provenance
    def test_report_export_persistence_and_provenance(self):
        prov = generate_provenance("REPORT_EXPORT", "https://acme.com", raw_payload={"type": "EXECUTIVE", "format": "PDF"})
        self.assertIn("sha256_hash", prov)
        self.assertEqual(len(prov["sha256_hash"]), 64)  # Valid SHA-256

        export = ReportExport(
            client_id=self.client.id,
            report_type="EXECUTIVE",
            format="PDF",
            filename="executive_report_acme_2026.pdf",
            file_size_bytes=245000,
            provenance_json=json.dumps(prov)
        )
        self.db.add(export)
        self.db.commit()

        exports = list_report_exports_endpoint(client_id=self.client.id, db=self.db)
        self.assertTrue(len(exports) >= 1)
        exp_item = exports[0]
        self.assertEqual(exp_item["format"], "PDF")
        self.assertEqual(exp_item["provenance"]["sha256_hash"], prov["sha256_hash"])

    # 4. Persistent background job lifecycle
    def test_persistent_background_job_lifecycle(self):
        job = PersistentJobManager.enqueue_job("AUDIT", "https://acme.com", client_id=self.client.id, db=self.db)
        self.assertEqual(job.status, "QUEUED")

        started = PersistentJobManager.start_job(job.id, db=self.db)
        self.assertEqual(started.status, "RUNNING")
        self.assertIsNotNone(started.started_at)

        updated = PersistentJobManager.update_progress(job.id, progress_pct=50.0, phase="crawling", db=self.db)
        self.assertEqual(updated.progress_pct, 50.0)

        completed = PersistentJobManager.complete_job(job.id, result_summary={"pages": 25, "score": 90}, db=self.db)
        self.assertEqual(completed.status, "COMPLETED")
        self.assertEqual(completed.progress_pct, 100.0)

        jobs_list = list_background_jobs_endpoint(status="COMPLETED", db=self.db)
        self.assertTrue(any(j["id"] == job.id for j in jobs_list))

    # 5. Background job cancellation via cancellation events
    def test_background_job_cancellation(self):
        job = PersistentJobManager.enqueue_job("AUDIT", "https://acme.com", db=self.db)
        evt = get_cancel_event(job.id)
        self.assertFalse(evt.is_set())

        # Cancel job
        ok = PersistentJobManager.cancel_job(job.id, db=self.db)
        self.assertTrue(ok)
        self.assertTrue(evt.is_set())

        refreshed = self.db.query(BackgroundJob).filter(BackgroundJob.id == job.id).first()
        self.assertEqual(refreshed.status, "CANCELLED")

    # 6. Background job retry policy
    def test_background_job_retry_policy(self):
        job = PersistentJobManager.enqueue_job("AUDIT", "https://acme.com", max_retries=2, db=self.db)

        # Fail attempt 1 -> should re-queue
        PersistentJobManager.fail_job(job.id, "Connection timeout", db=self.db)
        j1 = self.db.query(BackgroundJob).filter(BackgroundJob.id == job.id).first()
        self.assertEqual(j1.status, "QUEUED")
        self.assertEqual(j1.retry_count, 1)

        # Fail attempt 2 -> should re-queue
        PersistentJobManager.fail_job(job.id, "Connection timeout", db=self.db)
        j2 = self.db.query(BackgroundJob).filter(BackgroundJob.id == job.id).first()
        self.assertEqual(j2.status, "QUEUED")
        self.assertEqual(j2.retry_count, 2)

        # Fail attempt 3 (exceeds max_retries 2) -> should mark as FAILED
        PersistentJobManager.fail_job(job.id, "Permanent connection failure", db=self.db)
        j3 = self.db.query(BackgroundJob).filter(BackgroundJob.id == job.id).first()
        self.assertEqual(j3.status, "FAILED")
        self.assertIn("Permanent connection failure", j3.error_message)

    # 7. Server restart recovery for orphaned running/queued jobs
    def test_server_restart_orphaned_job_recovery(self):
        # Simulate a job that was RUNNING when server crashed
        crashed_job = BackgroundJob(
            id="crashed-job-123",
            job_type="AUDIT",
            target_url="https://acme.com",
            status="RUNNING",
            retry_count=0,
            max_retries=2,
            created_at=datetime.now(timezone.utc)
        )
        self.db.add(crashed_job)
        self.db.commit()

        # Run recovery
        recovered_count = PersistentJobManager.recover_orphaned_jobs(db=self.db)
        self.assertGreaterEqual(recovered_count, 1)

        refreshed = self.db.query(BackgroundJob).filter(BackgroundJob.id == "crashed-job-123").first()
        self.assertEqual(refreshed.status, "QUEUED")
        self.assertIn("restart", refreshed.error_message.lower())

    # 8. Safe non-destructive database migrations
    def test_init_db_safe_migrations(self):
        # Multiple calls to init_db() must run safely and idempotently
        init_db()
        init_db()
        # Verify client still exists and is accessible
        c = self.db.query(Client).filter(Client.id == self.client.id).first()
        self.assertIsNotNone(c)
        self.assertEqual(c.name, "Acme Corp")

    # 9. Data provenance SHA-256 integrity verification
    def test_data_provenance_cryptographic_verification(self):
        payload = {"domain": "acme.com", "score": 85, "pages": 12}
        prov1 = generate_provenance("LIVE_CRAWL", "https://acme.com", raw_payload=payload)
        prov2 = generate_provenance("LIVE_CRAWL", "https://acme.com", raw_payload=payload)
        self.assertEqual(prov1["sha256_hash"], prov2["sha256_hash"])

        # Tampered payload produces different hash
        tampered_payload = {"domain": "acme.com", "score": 99, "pages": 12}
        prov_tampered = generate_provenance("LIVE_CRAWL", "https://acme.com", raw_payload=tampered_payload)
        self.assertNotEqual(prov1["sha256_hash"], prov_tampered["sha256_hash"])

    # 10. Relational integrity across Projects, Websites, and Audits
    def test_project_and_website_relational_linkage(self):
        proj = Project(name="Acme Global", client_id=self.client.id)
        self.db.add(proj)
        self.db.commit()
        self.db.refresh(proj)

        site = Website(client_id=self.client.id, project_id=proj.id, url="https://acme.com", name="Main Site")
        self.db.add(site)
        self.db.commit()
        self.db.refresh(site)

        audit = Audit(
            client_id=self.client.id,
            website_id=site.id,
            project_id=proj.id,
            target_url=site.url,
            result_json="{}",
            score=88.0,
            status="COMPLETED"
        )
        self.db.add(audit)
        self.db.commit()
        self.db.refresh(audit)

        # Relational check
        self.assertEqual(site.project.id, proj.id)
        self.assertEqual(audit.project.id, proj.id)
        self.assertEqual(audit.website.id, site.id)


if __name__ == "__main__":
    unittest.main()

