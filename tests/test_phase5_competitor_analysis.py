"""Unit tests for Phase 5: Competitor Analysis & Market Intelligence."""
import io
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from backend import competitor_engine, integrations
from backend.database import SessionLocal, Audit, CompetitorComparison, AdminUser
from backend.main import (
    competitor_discover_endpoint,
    competitor_analyze_endpoint,
    competitor_comparisons_list_endpoint,
    competitor_comparison_save_endpoint,
    competitor_comparison_detail_endpoint,
    competitor_comparison_delete_endpoint,
    competitor_export_csv_endpoint,
    competitor_export_excel_endpoint,
    competitor_export_pdf_endpoint,
    CompetitorAnalyzeRequest,
    CompetitorSaveRequest,
)


class TestPhase5CompetitorAnalysis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin_user = AdminUser(
            id=1,
            email="admin@esupport.live",
            role="super_admin",
            status="active"
        )

    def test_bare_domain_normalizer(self):
        """Tests that bare_domain normalizes all shapes of URLs, protocols, and hosts."""
        self.assertEqual(competitor_engine.bare_domain("https://www.example.com/path?arg=1"), "example.com")
        self.assertEqual(competitor_engine.bare_domain("http://esupport.live/"), "esupport.live")
        self.assertEqual(competitor_engine.bare_domain("WWW.TOPTIER.COM:8080/"), "toptier.com")
        self.assertEqual(competitor_engine.bare_domain("subdomain.example.org/about"), "subdomain.example.org")
        self.assertEqual(competitor_engine.bare_domain(""), "")

    def test_discover_competitors_platform_fallback(self):
        """When DataForSEO is unconfigured, discovery returns platform audited websites or benchmarks."""
        res = competitor_engine.discover_competitors("esupport.live", limit=10)
        self.assertTrue(res["ok"])
        self.assertEqual(res["target_domain"], "esupport.live")
        self.assertIsInstance(res["competitors"], list)
        self.assertGreater(len(res["competitors"]), 0)
        # Verify target domain is never returned as its own competitor
        for c in res["competitors"]:
            self.assertNotEqual(c["domain"], "esupport.live")
            self.assertIn("competitor_relevance", c)
            self.assertIn("source", c)

    def test_discover_competitors_dataforseo_mock(self):
        """When DataForSEO is active, discovery processes live SERP competitor items."""
        mock_dfs = {
            "ok": True,
            "target": "example.com",
            "competitors": [
                {
                    "domain": "competitor1.com",
                    "shared_keywords": 45,
                    "organic_keywords_count": 210,
                    "estimated_traffic": 5400.0,
                    "avg_position": 14.2
                },
                {
                    "domain": "competitor2.com",
                    "shared_keywords": 28,
                    "organic_keywords_count": 150,
                    "estimated_traffic": 3200.0,
                    "avg_position": 18.5
                }
            ]
        }
        with patch.object(integrations, "dataforseo_configured", return_value=True):
            with patch.object(integrations, "competitors_domain", return_value=mock_dfs):
                res = competitor_engine.discover_competitors("example.com", limit=5)
                self.assertTrue(res["ok"])
                self.assertEqual(res["provider"], "DataForSEO Labs")
                self.assertEqual(len(res["competitors"]), 2)
                self.assertEqual(res["competitors"][0]["domain"], "competitor1.com")
                self.assertEqual(res["competitors"][0]["shared_keywords"], 45)

    def test_analyze_competitors_structure_and_scoreboard(self):
        """Full competitor analysis returns scoreboard, keyword gap matrix, content opportunities, and provenance."""
        res = competitor_engine.analyze_competitors(
            target_domain="esupport.live",
            competitor_domains=["toptier.com", "example.com"],
            location_code=2840,
            language_code="en"
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["target_domain"], "esupport.live")
        self.assertIn("toptier.com", res["competitor_domains"])

        # Scoreboard checks
        scoreboard = res["scoreboard"]
        self.assertEqual(len(scoreboard), 3)
        domains_in_score = [s["domain"] for s in scoreboard]
        self.assertIn("esupport.live", domains_in_score)
        self.assertIn("toptier.com", domains_in_score)
        self.assertIn("example.com", domains_in_score)

        # Target flag check
        target_entry = next(s for s in scoreboard if s["domain"] == "esupport.live")
        self.assertTrue(target_entry["is_target"])
        comp_entry = next(s for s in scoreboard if s["domain"] == "toptier.com")
        self.assertFalse(comp_entry["is_target"])

        # Scoreboard metrics integrity
        for s in scoreboard:
            self.assertIn("seo_score", s)
            self.assertIn("organic_keywords_count", s)
            self.assertIn("traffic_data_state", s)

        # Keyword Gap checks
        kg = res["keyword_gap"]
        self.assertIn("total_keywords", kg)
        self.assertIn("shared_count", kg)
        self.assertIn("missing_count", kg)
        self.assertIn("weak_count", kg)
        self.assertIn("strong_count", kg)
        self.assertIn("intent_distribution", kg)
        self.assertIsInstance(kg["keywords"], list)

        # Content Opportunities checks
        opps = res["content_opportunities"]
        self.assertIsInstance(opps, list)
        for o in opps:
            self.assertIn("topic", o)
            self.assertIn("intent", o)
            self.assertIn("opportunity_score", o)
            self.assertIn("suggested_action", o)

        # Provenance & Privacy Guarantee
        prov = res["provenance"]
        self.assertIn("estimates_notice", prov)
        self.assertIn("privacy_notice", prov)
        self.assertIn("Google Search Console", prov["privacy_notice"])

    def test_keyword_gap_classification_logic(self):
        """Verifies that keyword gap categorizes shared, missing, weak, and strong appropriately."""
        # Simulated DataForSEO ranked keywords for target and competitor
        target_kws_mock = {
            "ok": True,
            "target": "target.com",
            "total_count": 3,
            "keywords": [
                {"keyword": "shared query", "position": 5, "search_volume": 1200, "keyword_difficulty": 30, "cpc": 1.5, "intent": "Informational"},
                {"keyword": "weak query", "position": 18, "search_volume": 800, "keyword_difficulty": 45, "cpc": 2.1, "intent": "Commercial"},
                {"keyword": "strong query", "position": 2, "search_volume": 2500, "keyword_difficulty": 20, "cpc": 3.0, "intent": "Transactional"},
            ]
        }
        comp_kws_mock = {
            "ok": True,
            "target": "comp.com",
            "total_count": 3,
            "keywords": [
                {"keyword": "shared query", "position": 5, "search_volume": 1200, "keyword_difficulty": 30, "cpc": 1.5, "intent": "Informational"},
                {"keyword": "weak query", "position": 3, "search_volume": 800, "keyword_difficulty": 45, "cpc": 2.1, "intent": "Commercial"},
                {"keyword": "missing query", "position": 4, "search_volume": 3100, "keyword_difficulty": 50, "cpc": 4.2, "intent": "Transactional"},
            ]
        }

        def mock_ranked(target, limit, location_code, language_code):
            if "target" in target:
                return target_kws_mock
            return comp_kws_mock

        with patch.object(integrations, "dataforseo_configured", return_value=True):
            with patch.object(integrations, "ranked_keywords", side_effect=mock_ranked):
                res = competitor_engine.analyze_competitors("target.com", ["comp.com"])
                kg = res["keyword_gap"]
                kw_map = {k["keyword"]: k for k in kg["keywords"]}

                # 'shared query': both rank at pos 5
                self.assertEqual(kw_map["shared query"]["gap_type"], "shared")
                # 'weak query': target at pos 18, comp at pos 3 (comp is better)
                self.assertEqual(kw_map["weak query"]["gap_type"], "weak")
                # 'missing query': target has no rank, comp at pos 4
                self.assertEqual(kw_map["missing query"]["gap_type"], "missing")
                # 'strong query': target at pos 2, comp has no rank
                self.assertEqual(kw_map["strong query"]["gap_type"], "strong")

    def test_saved_comparison_crud(self):
        """Tests saving, listing, fetching, and deleting competitor comparison sets."""
        # 1. Save
        saved = competitor_engine.save_comparison(
            name="Q4 Benchmarking",
            target_domain="esupport.live",
            competitor_domains=["toptier.com", "example.com"],
            client_id=None,
            location_code=2840,
            language_code="en",
            analysis_data={"status": "ok", "test_id": 999}
        )
        self.assertIn("id", saved)
        comp_id = saved["id"]

        # 2. List
        all_comps = competitor_engine.list_comparisons("esupport.live")
        self.assertTrue(any(c["id"] == comp_id for c in all_comps))

        # 3. Get Detail
        detail = competitor_engine.get_comparison(comp_id)
        self.assertIsNotNone(detail)
        self.assertEqual(detail["name"], "Q4 Benchmarking")
        self.assertEqual(detail["target_domain"], "esupport.live")
        self.assertIn("toptier.com", detail["competitor_domains"])
        self.assertEqual(detail["data"]["test_id"], 999)

        # 4. Delete
        del_success = competitor_engine.delete_comparison(comp_id)
        self.assertTrue(del_success)
        post_del = competitor_engine.get_comparison(comp_id)
        self.assertIsNone(post_del)

    def test_competitor_exports_csv(self):
        """CSV export contains scoreboard, keyword gap headers, content opportunities, and disclaimers."""
        analysis = competitor_engine.analyze_competitors("esupport.live", ["toptier.com"])
        csv_text = competitor_engine.generate_competitor_csv(analysis)
        self.assertIn("eSupport SEO Platform - Competitor Intelligence Report", csv_text)
        self.assertIn("--- DOMAIN SCOREBOARD COMPARISON ---", csv_text)
        self.assertIn("--- KEYWORD GAP MATRIX ---", csv_text)
        self.assertIn("--- CONTENT GAP OPPORTUNITIES ---", csv_text)
        self.assertIn("esupport.live", csv_text)
        self.assertIn("toptier.com", csv_text)

    def test_competitor_exports_excel_xml(self):
        """Excel XML export produces valid SpreadsheetML with all required worksheets."""
        analysis = competitor_engine.analyze_competitors("esupport.live", ["toptier.com"])
        xml_text = competitor_engine.generate_competitor_excel_xml(analysis)
        self.assertIn('<?xml version="1.0" encoding="UTF-8"?>', xml_text)
        self.assertIn('ss:Name="Scoreboard"', xml_text)
        self.assertIn('ss:Name="Keyword Gap"', xml_text)
        self.assertIn('ss:Name="Content Opportunities"', xml_text)
        self.assertIn('ss:Name="Backlink Gap"', xml_text)
        self.assertIn("</Workbook>", xml_text)

    def test_competitor_exports_pdf(self):
        """ReportLab PDF export produces valid PDF binary bytes with ReportLab header and footer."""
        analysis = competitor_engine.analyze_competitors("esupport.live", ["toptier.com"])
        pdf_bytes = competitor_engine.generate_competitor_pdf(analysis)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertGreater(len(pdf_bytes), 1000)

    def test_api_endpoints_direct_call(self):
        """Tests the FastAPI route handlers for Phase 5 directly with model instances."""
        # Discover
        disco_res = competitor_discover_endpoint(
            target="esupport.live",
            country=2840,
            language="en",
            limit=5,
            current_admin=self.admin_user
        )
        self.assertTrue(disco_res["ok"])

        # Analyze
        analyze_req = CompetitorAnalyzeRequest(
            target_domain="esupport.live",
            competitor_domains=["toptier.com"],
            country=2840,
            language="en"
        )
        analyze_res = competitor_analyze_endpoint(req=analyze_req, current_admin=self.admin_user)
        self.assertTrue(analyze_res["ok"])
        self.assertEqual(analyze_res["target_domain"], "esupport.live")

        # Save & List & Delete
        save_req = CompetitorSaveRequest(
            name="API Test Set",
            target_domain="esupport.live",
            competitor_domains=["toptier.com"],
            client_id=None,
            country=2840,
            language="en",
            data={"status": "verified"}
        )
        save_res = competitor_comparison_save_endpoint(req=save_req, current_admin=self.admin_user)
        self.assertEqual(save_res["status"], "success")
        comp_id = save_res["comparison"]["id"]

        list_res = competitor_comparisons_list_endpoint(
            target="esupport.live",
            client_id=None,
            current_admin=self.admin_user
        )
        self.assertTrue(any(c["id"] == comp_id for c in list_res))

        detail_res = competitor_comparison_detail_endpoint(
            comparison_id=comp_id,
            current_admin=self.admin_user
        )
        self.assertEqual(detail_res["name"], "API Test Set")

        del_res = competitor_comparison_delete_endpoint(
            comparison_id=comp_id,
            current_admin=self.admin_user
        )
        self.assertEqual(del_res["status"], "success")

        # CSV Export endpoint
        csv_resp = competitor_export_csv_endpoint(req=analyze_req, current_admin=self.admin_user)
        self.assertEqual(csv_resp.media_type, "text/csv")

        # Excel Export endpoint
        excel_resp = competitor_export_excel_endpoint(req=analyze_req, current_admin=self.admin_user)
        self.assertEqual(excel_resp.media_type, "application/vnd.ms-excel")

        # PDF Export endpoint
        pdf_resp = competitor_export_pdf_endpoint(req=analyze_req, current_admin=self.admin_user)
        self.assertEqual(pdf_resp.media_type, "application/pdf")
        self.assertTrue(pdf_resp.body.startswith(b"%PDF-"))


if __name__ == "__main__":
    unittest.main()

