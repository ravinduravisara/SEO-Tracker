import os
import unittest
import json
from backend.database import get_db, Base, engine, SessionLocal, Client, Website, Audit, AdminUser
from backend.main import get_dashboard_stats, list_audits, export_report_endpoint
from backend.security import hash_password

class TestPhase11ModernAnalyticsDashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        cls.db = SessionLocal()

        # Ensure an admin user exists
        admin = cls.db.query(AdminUser).filter(AdminUser.email == "test_phase11_admin@esupport.live").first()
        if not admin:
            admin = AdminUser(
                email="test_phase11_admin@esupport.live",
                name="Phase 11 Tester",
                password_hash=hash_password("Secret123!"),
                role="SUPER_ADMIN",
                status="ACTIVE"
            )
            cls.db.add(admin)
            cls.db.commit()
            cls.db.refresh(admin)
        cls.admin = admin

        # Create 2 clients with distinct domains and audits for testing project-scoping
        cls.client_a = Client(name="Alpha Corp", company="Alpha LLC", email="contact@alpha.com")
        cls.client_b = Client(name="Beta Industries", company="Beta Inc", email="info@beta.com")
        cls.db.add_all([cls.client_a, cls.client_b])
        cls.db.commit()
        cls.db.refresh(cls.client_a)
        cls.db.refresh(cls.client_b)

        sample_audit_result = {
            "target": "https://alpha-enterprise.com",
            "score": 84.5,
            "pages_crawled": 5,
            "pages": [{"url": "https://alpha-enterprise.com", "status_code": 200, "score": 85}],
            "scores": {
                "categories": {
                    "indexing": {"score": 90, "weight": 0.25},
                    "content": {"score": 80, "weight": 0.25}
                }
            },
            "status": "COMPLETED"
        }

        cls.audit_a = Audit(
            client_id=cls.client_a.id,
            target_url="https://alpha-enterprise.com",
            score=84.5,
            status="COMPLETED",
            result_json=json.dumps(sample_audit_result)
        )
        cls.audit_b = Audit(
            client_id=cls.client_b.id,
            target_url="https://beta-platform.org",
            score=91.0,
            status="COMPLETED",
            result_json=json.dumps(sample_audit_result)
        )
        cls.db.add_all([cls.audit_a, cls.audit_b])
        cls.db.commit()
        cls.db.refresh(cls.audit_a)
        cls.db.refresh(cls.audit_b)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.db.query(Audit).filter(Audit.id.in_([cls.audit_a.id, cls.audit_b.id])).delete(synchronize_session=False)
            cls.db.query(Client).filter(Client.id.in_([cls.client_a.id, cls.client_b.id])).delete(synchronize_session=False)
            cls.db.query(AdminUser).filter(AdminUser.email == "test_phase11_admin@esupport.live").delete(synchronize_session=False)
            cls.db.commit()
        except Exception:
            cls.db.rollback()
        finally:
            cls.db.close()

    def test_01_dashboard_stats_endpoint(self):
        """Verify get_dashboard_stats returns real system metrics and connected data source flags."""
        data = get_dashboard_stats(db=self.db, current_admin=self.admin)
        self.assertIn("total_clients", data)
        self.assertIn("total_audits", data)
        self.assertIn("avg_score", data)
        self.assertIn("data_sources", data)
        self.assertIn("recent_audits", data)
        self.assertIsInstance(data["recent_audits"], list)

    def test_02_audits_endpoint_project_scoping(self):
        """Verify list_audits supports filtering by client_id and domain for project-scoped analytics."""
        # 1. Query all audits
        all_audits = list_audits(db=self.db, current_admin=self.admin)
        all_ids = [a["id"] for a in all_audits]
        self.assertIn(self.audit_a.id, all_ids)
        self.assertIn(self.audit_b.id, all_ids)

        # 2. Query scoped to client A
        a_audits = list_audits(client_id=self.client_a.id, db=self.db, current_admin=self.admin)
        self.assertTrue(all(a["client_id"] == self.client_a.id for a in a_audits))
        self.assertIn(self.audit_a.id, [a["id"] for a in a_audits])
        self.assertNotIn(self.audit_b.id, [a["id"] for a in a_audits])

        # 3. Query scoped to domain substring
        dom_audits = list_audits(domain="beta-platform", db=self.db, current_admin=self.admin)
        self.assertTrue(all("beta-platform" in a["target_url"] for a in dom_audits))
        self.assertIn(self.audit_b.id, [a["id"] for a in dom_audits])
        self.assertNotIn(self.audit_a.id, [a["id"] for a in dom_audits])

    def test_03_quick_export_api_contracts(self):
        """Verify multi-format quick export endpoints produce correct file payloads."""
        payload = {
            "audit_id": self.audit_a.id,
            "report_type": "executive_seo_report"
        }

        # PDF Export
        res_pdf = export_report_endpoint("pdf", payload, db=self.db, current_admin=self.admin)
        self.assertIn("application/pdf", res_pdf.media_type)
        self.assertTrue(res_pdf.body.startswith(b"%PDF-"))

        # Excel Export
        res_xls = export_report_endpoint("xls", payload, db=self.db, current_admin=self.admin)
        self.assertIn("application/vnd.ms-excel", res_xls.media_type)
        self.assertTrue(res_xls.body.startswith(b"<?xml"))

        # CSV Export
        res_csv = export_report_endpoint("csv", payload, db=self.db, current_admin=self.admin)
        self.assertIn("text/csv", res_csv.media_type)
        self.assertIn(b"Executive SEO Performance Report", res_csv.body)

        # JSON Export
        res_json = export_report_endpoint("json", payload, db=self.db, current_admin=self.admin)
        self.assertIn("application/json", res_json.media_type)
        parsed = json.loads(res_json.body.decode("utf-8"))
        self.assertIn("score", parsed)

    def test_04_frontend_html_modern_dashboard_structure(self):
        """Verify frontend/index.html contains required UI controls for Phase 11."""
        path = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
        self.assertTrue(os.path.exists(path))
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()

        # SEMrush/Ahrefs Project Selector
        self.assertIn('id="globalProjectSelector"', html)
        self.assertIn('id="globalProjectActiveBadge"', html)

        # Theme Toggle Button
        self.assertIn('id="themeToggleBtn"', html)
        self.assertIn('onclick="app.toggleTheme()"', html)

        # Quick Export Hub
        self.assertIn('id="quickExportDropdown"', html)
        self.assertIn("triggerQuickExport('pdf')", html)
        self.assertIn("triggerQuickExport('xls')", html)

        # Live Scan Progress Dock
        self.assertIn('id="globalScanProgressDock"', html)
        self.assertIn('id="globalScanProgressBarFill"', html)
        self.assertIn('id="globalScanTelemetry"', html)

        # Project Scope Banner on Dashboard
        self.assertIn('id="dashProjectScopeBanner"', html)
        self.assertIn('id="dashScopeDomain"', html)

        # Searchable and Sortable Tables
        self.assertIn('id="auditSearchInput"', html)
        self.assertIn('id="clientSearchInput"', html)
        self.assertIn("app.sortTable('auditsTable'", html)
        self.assertIn("app.sortTable('clientsTable'", html)
        self.assertIn("app.sortTable('reportsTable'", html)

    def test_05_frontend_css_modern_analytics_system(self):
        """Verify frontend/style.css defines light/dark themes and enterprise UI styling."""
        path = os.path.join(os.path.dirname(__file__), "..", "frontend", "style.css")
        self.assertTrue(os.path.exists(path))
        with open(path, "r", encoding="utf-8") as f:
            css = f.read()

        # Dark theme selector
        self.assertIn('[data-theme="dark"]', css)
        self.assertIn('--bg-main: #0B0F19;', css)
        self.assertIn('--bg-card: #111827;', css)

        # Enterprise SEMrush / Ahrefs UI components
        self.assertIn('.project-selector-wrapper', css)
        self.assertIn('.global-scan-dock', css)
        self.assertIn('.quick-export-dropdown', css)
        self.assertIn('.table-toolbar', css)
        self.assertIn('th.sortable', css)
        self.assertIn('.skeleton-line', css)
        self.assertIn('.empty-state-card', css)

    def test_06_frontend_app_js_methods_and_zero_fabrication(self):
        """Verify frontend/app.js implements required methods and respects zero fabrication."""
        path = os.path.join(os.path.dirname(__file__), "..", "frontend", "app.js")
        self.assertTrue(os.path.exists(path))
        with open(path, "r", encoding="utf-8") as f:
            js = f.read()

        # Theme methods
        self.assertIn("initTheme()", js)
        self.assertIn("toggleTheme()", js)

        # Project Scoping methods
        self.assertIn("onGlobalProjectChange(", js)
        self.assertIn("updateProjectScopeUI()", js)
        self.assertIn("clearProjectScope()", js)

        # Quick Export & Table Sorting
        self.assertIn("triggerQuickExport(", js)
        self.assertIn("sortTable(", js)
        self.assertIn("filterAudits()", js)

        # Zero Fabrication in Score Trend Chart (no fake 63 fallback)
        self.assertNotIn("trends[0].score !== undefined ? Math.round(trends[0].score) : 63;", js)
        self.assertIn("Baseline Audit Recorded", js)
        self.assertIn("No Audit History Recorded", js)


if __name__ == "__main__":
    unittest.main()
