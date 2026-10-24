"""Unit tests for Phase 8: Keyword Rank Tracking & SERP Monitoring."""
import io
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from backend import rank_tracker, integrations
from backend.database import SessionLocal, TrackedKeyword, RankingObservation, RankingAlert, AdminUser
from backend.main import (
    rankings_overview_endpoint,
    rankings_list_keywords_endpoint,
    rankings_add_keywords_endpoint,
    rankings_keyword_history_endpoint,
    rankings_update_keyword_endpoint,
    rankings_delete_keyword_endpoint,
    rankings_check_keyword_endpoint,
    rankings_check_all_endpoint,
    rankings_list_alerts_endpoint,
    rankings_mark_alert_read_endpoint,
    rankings_export_csv_endpoint,
    rankings_export_excel_endpoint,
    rankings_export_pdf_endpoint,
    AddTrackedKeywordsRequest,
    UpdateTrackedKeywordRequest,
)


class TestPhase8RankTracking(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin_user = AdminUser(
            id=1,
            email="admin@esupport.live",
            role="super_admin",
            status="active"
        )
        cls.db = SessionLocal()

    @classmethod
    def tearDownClass(cls):
        # Cleanup test keywords
        try:
            cls.db.query(TrackedKeyword).filter(TrackedKeyword.target_domain == "testdomain8.com").delete()
            cls.db.commit()
        except Exception:
            cls.db.rollback()
        finally:
            cls.db.close()

    def test_visibility_scoring(self):
        """Tests SERP visibility index calculation using organic CTR decay curve."""
        self.assertEqual(rank_tracker.calculate_visibility_score([]), 0.0)
        # Position 1 gives 32% SOV
        self.assertEqual(rank_tracker.calculate_visibility_score([1]), 32.0)
        # Position 1 and Position 2 average
        self.assertEqual(rank_tracker.calculate_visibility_score([1, 2]), 25.0)
        # Unranked gives 0
        self.assertEqual(rank_tracker.calculate_visibility_score([None, None]), 0.0)

    def test_add_and_crud_tracked_keywords(self):
        """Tests adding, updating, and querying tracked keywords."""
        keywords = ["seo audit software", "backlink analyzer tool"]
        created = rank_tracker.add_tracked_keywords(
            db=self.db,
            keywords=keywords,
            target_domain="testdomain8.com",
            device="desktop",
            competitor_domains=["comp-a.com", "comp-b.com"],
            tags="core,saas",
            check_frequency="daily"
        )
        self.assertEqual(len(created), 2)
        kw1 = created[0]
        self.assertEqual(kw1.target_domain, "testdomain8.com")
        self.assertEqual(kw1.device, "desktop")
        self.assertIn("comp-a.com", kw1.competitor_domains)

        # Deduplication test: re-adding should update rather than duplicate
        created2 = rank_tracker.add_tracked_keywords(
            db=self.db,
            keywords=["seo audit software"],
            target_domain="testdomain8.com",
            tags="core,updated"
        )
        self.assertEqual(len(created2), 1)
        self.assertEqual(created2[0].id, kw1.id)
        self.assertEqual(created2[0].tags, "core,updated")

    def test_check_keyword_ranking_and_alerts(self):
        """Tests SERP ranking position parsing, competitor extraction, and alert generation."""
        # Create a test keyword
        tks = rank_tracker.add_tracked_keywords(
            db=self.db,
            keywords=["best ranking tool"],
            target_domain="testdomain8.com",
            competitor_domains=["comp-a.com"]
        )
        tk = tks[0]
        # Simulate prior position at rank 15
        tk.current_position = 15
        self.db.commit()

        # Mock Google live SERP result where testdomain8.com is at rank 3, and comp-a.com is at rank 7
        mock_serp = {
            "ok": True,
            "keyword": "best ranking tool",
            "device": "desktop",
            "source": "Mock Google SERP API",
            "serp_features": ["featured_snippet", "people_also_ask"],
            "items": [
                {"rank_group": 1, "domain": "leader.com", "url": "https://leader.com/rank"},
                {"rank_group": 2, "domain": "second.org", "url": "https://second.org/rank"},
                {"rank_group": 3, "domain": "testdomain8.com", "url": "https://testdomain8.com/tool"},
                {"rank_group": 7, "domain": "comp-a.com", "url": "https://comp-a.com/features"},
            ]
        }

        with patch.object(integrations, "google_live_serp", return_value=mock_serp):
            res = rank_tracker.check_keyword_ranking(self.db, tk.id)

            self.assertTrue(res["ok"])
            self.assertEqual(res["current_position"], 3)
            self.assertEqual(res["previous_position"], 15)
            # 15 - 3 = +12 improvement
            self.assertEqual(res["position_change"], 12)
            self.assertEqual(res["best_position"], 3)
            self.assertEqual(res["ranked_url"], "https://testdomain8.com/tool")
            self.assertEqual(res["competitor_positions"].get("comp-a.com"), 7)

            # Verify observation was saved
            obs = self.db.query(RankingObservation).filter(
                RankingObservation.tracked_keyword_id == tk.id
            ).order_by(RankingObservation.collected_at.desc()).first()
            self.assertIsNotNone(obs)
            self.assertEqual(obs.position, 3)

            # Verify alert generation (entered Top 3 from #15)
            alerts = self.db.query(RankingAlert).filter(
                RankingAlert.tracked_keyword_id == tk.id
            ).all()
            self.assertGreaterEqual(len(alerts), 1)
            self.assertTrue(any(a.alert_type in ("ENTERED_TOP_3", "ENTERED_TOP_10", "MAJOR_GAIN") for a in alerts))

    def test_rankings_overview_aggregation(self):
        """Tests overview analytics, distribution buckets, winners & losers, and competitor benchmarks."""
        overview = rank_tracker.get_rankings_overview(self.db, target_domain="testdomain8.com")
        self.assertTrue(overview["ok"])
        self.assertEqual(overview["target_domain"], "testdomain8.com")
        self.assertGreaterEqual(overview["total_keywords"], 1)
        self.assertIn("distribution", overview)
        self.assertIn("top_3", overview["distribution"])
        self.assertIn("top_10", overview["distribution"])
        self.assertIn("winners", overview)
        self.assertIn("losers", overview)
        self.assertIn("disclaimer", overview)
        self.assertIn("Google Search Console average position", overview["disclaimer"])

    def test_keyword_history(self):
        """Tests retrieval of historical observations and trajectory."""
        tk = self.db.query(TrackedKeyword).filter(TrackedKeyword.target_domain == "testdomain8.com").first()
        self.assertIsNotNone(tk)
        hist = rank_tracker.get_keyword_history(self.db, tk.id, days=30)
        self.assertTrue(hist["ok"])
        self.assertEqual(hist["tracked_keyword_id"], tk.id)
        self.assertIsInstance(hist["timeline"], list)

    def test_exporters(self):
        """Tests CSV, Excel XML, and vector ReportLab PDF exporters."""
        overview_data = {
            "target_domain": "testdomain8.com",
            "total_keywords": 2,
            "average_position": 4.5,
            "visibility_score": 28.5,
            "distribution": {"top_3": 1, "top_10": 2, "top_20": 2, "top_50": 2, "top_100": 2, "unranked": 0},
            "disclaimer": "Live SERP data disclaimer.",
            "keywords": [
                {
                    "keyword": "seo audit software",
                    "target_domain": "testdomain8.com",
                    "device": "desktop",
                    "location_name": "United States",
                    "current_position": 3,
                    "previous_position": 15,
                    "position_change": 12,
                    "best_position": 3,
                    "latest_url": "https://testdomain8.com/tool",
                    "search_volume": 1200,
                    "keyword_difficulty": 45.0
                }
            ]
        }

        # 1. CSV
        csv_text = rank_tracker.generate_rankings_csv(overview_data)
        self.assertIn("KEYWORD RANK TRACKING REPORT", csv_text)
        self.assertIn("testdomain8.com", csv_text)
        self.assertIn("seo audit software", csv_text)

        # 2. Excel XML
        xml_text = rank_tracker.generate_rankings_excel_xml(overview_data)
        self.assertTrue(xml_text.startswith("<?xml version=\"1.0\" encoding=\"UTF-8\"?>"))
        self.assertIn("<Worksheet ss:Name=\"Overview\">", xml_text)
        self.assertIn("<Worksheet ss:Name=\"Keywords\">", xml_text)
        self.assertIn("seo audit software", xml_text)

        # 3. Vector ReportLab PDF
        pdf_bytes = rank_tracker.generate_rankings_pdf(overview_data)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertGreater(len(pdf_bytes), 2000)

    def test_api_endpoints(self):
        """Tests FastAPI endpoints in backend/main.py for rank tracking."""
        # 1. GET /api/rankings/overview
        ov = rankings_overview_endpoint(
            target_domain="testdomain8.com",
            website_id=None,
            device=None,
            db=self.db,
            current_admin=self.admin_user
        )
        self.assertTrue(ov["ok"])

        # 2. GET /api/rankings/keywords
        kws = rankings_list_keywords_endpoint(
            target_domain="testdomain8.com",
            website_id=None,
            tag=None,
            db=self.db,
            current_admin=self.admin_user
        )
        self.assertIsInstance(kws, list)
        self.assertGreaterEqual(len(kws), 1)
        test_kw = kws[0]

        # 3. PUT /api/rankings/keywords/{id}
        update_req = UpdateTrackedKeywordRequest(tags="updated-tag", check_frequency="weekly")
        up_res = rankings_update_keyword_endpoint(
            keyword_id=test_kw["id"],
            req=update_req,
            db=self.db,
            current_admin=self.admin_user
        )
        self.assertEqual(up_res["status"], "success")

        # 4. GET /api/rankings/alerts
        alerts = rankings_list_alerts_endpoint(
            target_domain="testdomain8.com",
            unread_only=False,
            db=self.db,
            current_admin=self.admin_user
        )
        self.assertIsInstance(alerts, list)

        # 5. Export Endpoints
        sample_payload = {"overview": {"target_domain": "testdomain8.com", "total_keywords": 1, "keywords": []}}

        csv_resp = rankings_export_csv_endpoint(payload=sample_payload, current_admin=self.admin_user)
        self.assertEqual(csv_resp.media_type, "text/csv")
        self.assertIn(".csv\"", csv_resp.headers["Content-Disposition"])

        excel_resp = rankings_export_excel_endpoint(payload=sample_payload, current_admin=self.admin_user)
        self.assertEqual(excel_resp.media_type, "application/vnd.ms-excel")
        self.assertIn(".xls\"", excel_resp.headers["Content-Disposition"])

        pdf_resp = rankings_export_pdf_endpoint(payload=sample_payload, current_admin=self.admin_user)
        self.assertEqual(pdf_resp.media_type, "application/pdf")
        self.assertTrue(pdf_resp.body.startswith(b"%PDF-"))


if __name__ == "__main__":
    unittest.main()

