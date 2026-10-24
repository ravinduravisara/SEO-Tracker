"""Unit tests for Phase 7: Google Search Console, Analytics 4 & Performance."""
import io
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from backend import google_service, integrations
from backend.database import SessionLocal, Website, Client, AdminUser
from backend.main import (
    google_websites_list,
    google_connections_endpoint,
    google_settings_endpoint,
    google_performance_endpoint,
    google_export_csv_endpoint,
    google_export_excel_endpoint,
    google_export_pdf_endpoint,
    GoogleSettingsRequest,
)


class TestPhase7GoogleIntegrations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin_user = AdminUser(
            id=1,
            email="admin@esupport.live",
            role="super_admin",
            status="active"
        )
        cls.db = SessionLocal()
        # Create a test client and website
        test_client = cls.db.query(Client).filter(Client.email == "phase7test@example.com").first()
        if not test_client:
            test_client = Client(
                name="Phase 7 Test Client",
                company="Phase 7 Corp",
                email="phase7test@example.com",
                status="active"
            )
            cls.db.add(test_client)
            cls.db.commit()
            cls.db.refresh(test_client)
        cls.test_client = test_client

        test_website = cls.db.query(Website).filter(Website.url == "https://phase7corp.com").first()
        if not test_website:
            test_website = Website(
                client_id=test_client.id,
                url="https://phase7corp.com",
                name="Phase 7 Corp",
                gsc_property="sc-domain:phase7corp.com",
                ga4_property_id="99887766",
                status="ACTIVE"
            )
            cls.db.add(test_website)
            cls.db.commit()
            cls.db.refresh(test_website)
        cls.test_website = test_website

    @classmethod
    def tearDownClass(cls):
        try:
            if hasattr(cls, "test_website") and cls.test_website:
                cls.db.delete(cls.test_website)
            if hasattr(cls, "test_client") and cls.test_client:
                cls.db.delete(cls.test_client)
            cls.db.commit()
        except Exception:
            cls.db.rollback()
        finally:
            cls.db.close()

    def test_connection_status_not_configured(self):
        """Tests connection status when Google service account is not configured."""
        website = Website(
            id=999,
            url="https://unconfigured-client.com",
            name="Unconfigured Site",
            gsc_property="",
            ga4_property_id=""
        )
        with patch.object(integrations, "gsc_configured", return_value=False), \
             patch.object(integrations, "pagespeed_configured", return_value=False), \
             patch.object(integrations, "local_lighthouse_available", return_value=False):
            status = google_service.check_google_connections(website)
            self.assertEqual(status["search_console"]["status"], "NOT_CONFIGURED")
            self.assertEqual(status["google_analytics_4"]["status"], "NOT_CONFIGURED")
            self.assertFalse(status["search_console"]["is_connected"])
            self.assertFalse(status["google_analytics_4"]["is_connected"])

    def test_connection_status_connected(self):
        """Tests connection status when GSC and GA4 are successfully authorized."""
        website = Website(
            id=998,
            url="https://authorized-client.com",
            name="Authorized Site",
            gsc_property="sc-domain:authorized-client.com",
            ga4_property_id="12345678"
        )
        with patch.object(integrations, "gsc_configured", return_value=True), \
             patch.object(integrations, "gsc_match_property", return_value="sc-domain:authorized-client.com"), \
             patch.object(integrations, "ga4", return_value={"ok": True, "property_id": "12345678"}):
            status = google_service.check_google_connections(website)
            self.assertEqual(status["search_console"]["status"], "CONNECTED")
            self.assertEqual(status["google_analytics_4"]["status"], "CONNECTED")
            self.assertTrue(status["search_console"]["is_connected"])
            self.assertTrue(status["google_analytics_4"]["is_connected"])

    def test_get_client_performance_report(self):
        """Tests aggregation of GSC, GA4, CrUX field data and Lighthouse lab data."""
        mock_gsc = {
            "ok": True,
            "property": "sc-domain:phase7corp.com",
            "totals": {"clicks": 1420, "impressions": 28400, "ctr": 5.0, "position": 12.3},
            "top_queries": [{"query": "phase 7 software", "clicks": 250, "impressions": 1200, "ctr": 20.8, "position": 2.1}],
            "top_pages": [{"page": "https://phase7corp.com/features", "clicks": 320, "impressions": 3000, "ctr": 10.7, "position": 4.5}],
            "devices": [{"device": "DESKTOP", "clicks": 900, "impressions": 18000, "ctr": 5.0, "position": 11.2}],
            "countries": [{"country": "USA", "clicks": 1100, "impressions": 20000, "ctr": 5.5, "position": 10.1}],
            "dates": [{"date": "2026-10-20", "clicks": 50, "impressions": 1000, "ctr": 5.0, "position": 12.0}]
        }
        mock_ga4 = {
            "ok": True,
            "property_id": "99887766",
            "totals": {
                "sessions": 3450, "total_users": 2800, "active_users": 2100, "new_users": 1900,
                "engagement_rate": 64.5, "average_session_duration": 142.0, "bounce_rate": 35.5
            },
            "channels": [{"channel": "Organic Search", "sessions": 2100, "users": 1800}],
            "top_pages": [{"page_path": "/", "page_views": 4500, "sessions": 2200}],
            "countries": [{"country": "United States", "sessions": 2500}]
        }
        mock_psi_mobile = {
            "field": {
                "core_web_vitals_assessment": "passed",
                "scope": "origin",
                "metrics": {
                    "largest_contentful_paint": {"value": 1850, "category": "FAST"},
                    "cumulative_layout_shift": {"value": 0.02, "category": "FAST"}
                }
            },
            "categories": {"performance": 88, "accessibility": 95, "best_practices": 92, "seo": 100},
            "lab": {"largest_contentful_paint_ms": 1920}
        }
        mock_psi_desktop = {
            "field": {
                "core_web_vitals_assessment": "passed",
                "scope": "origin",
                "metrics": {
                    "largest_contentful_paint": {"value": 950, "category": "FAST"},
                    "cumulative_layout_shift": {"value": 0.01, "category": "FAST"}
                }
            },
            "categories": {"performance": 96, "accessibility": 98, "best_practices": 95, "seo": 100},
            "lab": {"largest_contentful_paint_ms": 820}
        }

        with patch.object(integrations, "search_console", return_value=mock_gsc), \
             patch.object(integrations, "ga4", return_value=mock_ga4), \
             patch.object(integrations, "pagespeed", side_effect=[mock_psi_mobile, mock_psi_desktop]):
            report = google_service.get_client_performance_report(self.test_website, days=28, db=self.db)

            self.assertTrue(report["ok"])
            self.assertEqual(report["target_domain"], "phase7corp.com")
            self.assertIn("disclaimer", report)
            self.assertIn("aggregated searcher impressions", report["disclaimer"])
            self.assertIn("75th percentile", report["disclaimer"])

            # Verify Search Console
            self.assertTrue(report["search_console"]["is_connected"])
            self.assertEqual(report["search_console"]["totals"]["clicks"], 1420)
            self.assertEqual(len(report["search_console"]["top_queries"]), 1)

            # Verify GA4
            self.assertTrue(report["google_analytics_4"]["is_connected"])
            self.assertEqual(report["google_analytics_4"]["totals"]["sessions"], 3450)
            self.assertEqual(report["google_analytics_4"]["channels"][0]["channel"], "Organic Search")

            # Verify Core Web Vitals Field vs Lab Separation
            cwv = report["core_web_vitals_field"]
            self.assertEqual(cwv["assessment"], "passed")
            self.assertTrue(cwv["has_real_user_data"])
            self.assertIn("largest_contentful_paint", cwv["mobile"])

            lab = report["lighthouse_lab"]
            self.assertEqual(lab["mobile_score"], 88)
            self.assertEqual(lab["desktop_score"], 96)

    def test_exporters(self):
        """Tests CSV, Excel XML, and vector ReportLab PDF exporters."""
        report = {
            "target_domain": "phase7corp.com",
            "website_url": "https://phase7corp.com",
            "report_date": "2026-10-24T12:00:00Z",
            "days": 28,
            "disclaimer": "Search Console average position represents aggregated impressions. Field data represents p75.",
            "search_console": {
                "is_connected": True,
                "totals": {"clicks": 1200, "impressions": 24000, "ctr": 5.0, "position": 11.5},
                "top_queries": [{"query": "phase 7 seo", "clicks": 150, "impressions": 800, "ctr": 18.7, "position": 3.2}],
                "top_pages": [{"page": "https://phase7corp.com/", "clicks": 500, "impressions": 10000, "ctr": 5.0, "position": 8.1}],
                "devices": [{"device": "MOBILE", "clicks": 800, "impressions": 16000, "ctr": 5.0, "position": 10.0}],
                "countries": [{"country": "USA", "clicks": 900, "impressions": 18000, "ctr": 5.0, "position": 9.5}],
                "dates": [{"date": "2026-10-24", "clicks": 45, "impressions": 900, "ctr": 5.0, "position": 11.0}]
            },
            "google_analytics_4": {
                "is_connected": True,
                "property_id": "99887766",
                "totals": {
                    "sessions": 3000, "total_users": 2500, "active_users": 1800, "new_users": 1600,
                    "engagement_rate": 62.0, "average_session_duration": 130.0, "bounce_rate": 38.0
                },
                "channels": [{"channel": "Direct", "sessions": 1200, "users": 1000}],
                "top_pages": [{"page_path": "/", "page_views": 3500, "sessions": 1500}],
                "countries": [{"country": "United States", "sessions": 2200}]
            },
            "core_web_vitals_field": {
                "assessment": "passed",
                "has_real_user_data": True,
                "mobile": {"largest_contentful_paint": {"value": 1800, "category": "FAST"}},
                "desktop": {"largest_contentful_paint": {"value": 900, "category": "FAST"}}
            },
            "lighthouse_lab": {
                "mobile_score": 85,
                "desktop_score": 95,
                "categories_mobile": {"performance": 85, "accessibility": 92}
            }
        }

        # 1. CSV
        csv_text = google_service.generate_performance_csv(report)
        self.assertIn("GOOGLE SEARCH CONSOLE & ANALYTICS PERFORMANCE REPORT", csv_text)
        self.assertIn("phase7corp.com", csv_text)
        self.assertIn("phase 7 seo", csv_text)

        # 2. Excel XML
        xml_text = google_service.generate_performance_excel_xml(report)
        self.assertTrue(xml_text.startswith("<?xml version=\"1.0\" encoding=\"UTF-8\"?>"))
        self.assertIn("<Worksheet ss:Name=\"Overview\">", xml_text)
        self.assertIn("phase 7 seo", xml_text)

        # 3. Vector ReportLab PDF
        pdf_bytes = google_service.generate_performance_pdf(report)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertGreater(len(pdf_bytes), 2000)

    def test_ga4_integration_mock(self):
        """Tests the GA4 Data API v1beta wrapper with mocked response."""
        mock_totals_resp = MagicMock()
        mock_totals_resp.status_code = 200
        mock_totals_resp.json.return_value = {
            "rows": [{
                "metricValues": [
                    {"value": "1500"},  # sessions
                    {"value": "1200"},  # totalUsers
                    {"value": "900"},   # activeUsers
                    {"value": "850"},   # newUsers
                    {"value": "0.654"}, # engagementRate
                    {"value": "125.4"}, # userEngagementDuration
                    {"value": "0.346"}, # bounceRate
                ]
            }]
        }

        mock_channels_resp = MagicMock()
        mock_channels_resp.status_code = 200
        mock_channels_resp.json.return_value = {
            "rows": [{
                "dimensionValues": [{"value": "Organic Search"}],
                "metricValues": [{"value": "1000"}, {"value": "800"}]
            }]
        }

        with patch.object(integrations, "gsc_configured", return_value=True), \
             patch.object(integrations, "_gsc_token", return_value="mock-token-xyz"), \
             patch("requests.post", side_effect=[mock_totals_resp, mock_channels_resp, mock_channels_resp, mock_channels_resp]):
            res = integrations.ga4("https://phase7corp.com", property_id="12345678", days=14)
            self.assertTrue(res["ok"])
            self.assertEqual(res["totals"]["sessions"], 1500)
            self.assertEqual(res["totals"]["engagement_rate"], 65.4)
            self.assertEqual(res["totals"]["bounce_rate"], 34.6)
            self.assertEqual(len(res["channels"]), 1)
            self.assertEqual(res["channels"][0]["channel"], "Organic Search")

    def test_main_endpoints(self):
        """Tests REST API endpoints in backend/main.py."""
        # 1. GET /api/google/websites
        sites = google_websites_list(db=self.db, current_admin=self.admin_user)
        self.assertIsInstance(sites, list)
        self.assertTrue(any(s["url"] == "https://phase7corp.com" for s in sites))

        # 2. GET /api/google/connections/{website_id}
        with patch.object(google_service, "check_google_connections", return_value={"website_id": self.test_website.id, "ok": True}):
            conn_res = google_connections_endpoint(website_id=self.test_website.id, db=self.db, current_admin=self.admin_user)
            self.assertEqual(conn_res["website_id"], self.test_website.id)

        # 3. POST /api/google/settings/{website_id}
        req = GoogleSettingsRequest(gsc_property="sc-domain:updated-test.com", ga4_property_id="55443322")
        with patch.object(google_service, "check_google_connections", return_value={"ok": True}):
            sett_res = google_settings_endpoint(website_id=self.test_website.id, req=req, db=self.db, current_admin=self.admin_user)
            self.assertTrue(sett_res["ok"])
            self.db.refresh(self.test_website)
            self.assertEqual(self.test_website.gsc_property, "sc-domain:updated-test.com")
            self.assertEqual(self.test_website.ga4_property_id, "55443322")

        # 4. GET /api/google/performance/{website_id}
        with patch.object(google_service, "get_client_performance_report", return_value={"ok": True, "target_domain": "updated-test.com"}):
            perf_res = google_performance_endpoint(website_id=self.test_website.id, days=28, db=self.db, current_admin=self.admin_user)
            self.assertTrue(perf_res["ok"])

        # 5. Export Endpoints
        sample_report = {
            "target_domain": "updated-test.com",
            "report_date": "2026-10-24T12:00:00Z",
            "days": 28,
            "disclaimer": "Test disclaimer",
            "search_console": {"totals": {}, "top_queries": [], "top_pages": []},
            "google_analytics_4": {"totals": {}, "channels": [], "top_pages": []},
            "core_web_vitals_field": {},
            "lighthouse_lab": {}
        }

        # CSV Export
        csv_resp = google_export_csv_endpoint(payload={"report": sample_report}, current_admin=self.admin_user)
        self.assertEqual(csv_resp.media_type, "text/csv")
        self.assertIn("filename=\"google_performance_updated-test.com_", csv_resp.headers["Content-Disposition"])

        # Excel Export
        excel_resp = google_export_excel_endpoint(payload={"report": sample_report}, current_admin=self.admin_user)
        self.assertEqual(excel_resp.media_type, "application/vnd.ms-excel")
        self.assertIn(".xls\"", excel_resp.headers["Content-Disposition"])

        # PDF Export
        pdf_resp = google_export_pdf_endpoint(payload={"report": sample_report}, current_admin=self.admin_user)
        self.assertEqual(pdf_resp.media_type, "application/pdf")
        self.assertIn(".pdf\"", pdf_resp.headers["Content-Disposition"])
        self.assertTrue(pdf_resp.body.startswith(b"%PDF-"))


if __name__ == "__main__":
    unittest.main()
