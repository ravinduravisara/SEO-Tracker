"""Unit tests for Phase 6: Backlink Analytics & Link Intelligence."""
import io
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from backend import backlink_engine, integrations
from backend.database import SessionLocal, Audit, BacklinkSnapshot, AdminUser
from backend.main import (
    backlink_overview_endpoint,
    backlink_referring_domains_endpoint,
    backlink_anchors_endpoint,
    backlink_internal_equity_endpoint,
    backlink_gap_endpoint,
    backlink_snapshots_list_endpoint,
    backlink_snapshot_save_endpoint,
    backlink_snapshot_detail_endpoint,
    backlink_snapshot_delete_endpoint,
    backlink_export_csv_endpoint,
    backlink_export_excel_endpoint,
    backlink_export_pdf_endpoint,
    BacklinkGapRequest,
    BacklinkSnapshotSaveRequest,
)


class TestPhase6BacklinkAnalytics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin_user = AdminUser(
            id=1,
            email="admin@esupport.live",
            role="super_admin",
            status="active"
        )

    def test_bare_domain_normalizer(self):
        """Tests domain normalization across various formats."""
        self.assertEqual(backlink_engine.bare_domain("https://www.example.com/blog/seo"), "example.com")
        self.assertEqual(backlink_engine.bare_domain("http://esupport.live/"), "esupport.live")
        self.assertEqual(backlink_engine.bare_domain("WWW.SHWOAH.COM:8080/"), "shwoah.com")
        self.assertEqual(backlink_engine.bare_domain(""), "")

    def test_anchor_classification(self):
        """Tests that anchor texts are correctly categorized into SEO classifications."""
        # Naked URL
        cat, color = backlink_engine.classify_anchor("https://esupport.live/contact", "esupport.live")
        self.assertEqual(cat, "Naked URL")

        # Generic
        cat, color = backlink_engine.classify_anchor("click here", "esupport.live")
        self.assertEqual(cat, "Generic")
        cat, color = backlink_engine.classify_anchor("read more", "esupport.live")
        self.assertEqual(cat, "Generic")

        # Branded
        cat, color = backlink_engine.classify_anchor("eSupport SEO Services", "esupport.live")
        self.assertEqual(cat, "Branded")

        # Exact Match with target keyword
        cat, color = backlink_engine.classify_anchor("technical seo audit", "esupport.live", ["technical seo audit", "best seo"])
        self.assertEqual(cat, "Exact Match")

        # Partial Match
        cat, color = backlink_engine.classify_anchor("professional technical seo audit firm", "esupport.live", ["technical seo audit"])
        self.assertEqual(cat, "Partial Match")

    def test_internal_equity_pagerank_calculation(self):
        """Tests iterative PageRank internal equity modeling and orphan page detection."""
        sample_pages = [
            {
                "url": "https://example.com/",
                "title": "Home",
                "status": 200,
                "depth": 1,
                "internal_links": [
                    {"url": "https://example.com/about", "text": "About Us"},
                    {"url": "https://example.com/services", "text": "Our Services"},
                    {"url": "https://example.com/contact", "text": "Contact Us"}
                ]
            },
            {
                "url": "https://example.com/services",
                "title": "Services",
                "status": 200,
                "depth": 2,
                "internal_links": [
                    {"url": "https://example.com/about", "text": "About"},
                    {"url": "https://example.com/", "text": "Home"}
                ]
            },
            {
                "url": "https://example.com/about",
                "title": "About",
                "status": 200,
                "depth": 2,
                "internal_links": [
                    {"url": "https://example.com/contact", "text": "Contact"}
                ]
            },
            {
                "url": "https://example.com/contact",
                "title": "Contact",
                "status": 200,
                "depth": 3,
                "internal_links": [
                    {"url": "https://example.com/", "text": "Home"}
                ]
            },
            {
                "url": "https://example.com/orphan-article",
                "title": "Unlinked Article",
                "status": 200,
                "depth": 4,
                "internal_links": [
                    {"url": "https://example.com/", "text": "Home"}
                ]
            }
        ]

        res = backlink_engine.calculate_internal_equity(sample_pages)

        self.assertGreater(res["platform_authority_index"], 0.0)
        self.assertEqual(res["internal_pages_evaluated"], 5)
        self.assertIn("PageRank", res["methodology"])

        # Verify orphan page detection
        orphans = res["orphan_pages"]
        orphan_urls = [o["url"] for o in orphans]
        self.assertIn("https://example.com/orphan-article", orphan_urls)

        # Verify equity scores are on 0-100 scale
        for p in res["top_equity_pages"]:
            self.assertGreaterEqual(p["internal_equity_score"], 0.0)
            self.assertLessEqual(p["internal_equity_score"], 100.0)

        # Home page linked by all should have highest equity
        home = next(p for p in res["top_equity_pages"] if p["url"] == "https://example.com/")
        self.assertGreater(home["internal_equity_score"], 40.0)

    def test_toxicity_radar_evaluation(self):
        """Tests link toxicity and suspicious pattern detection."""
        # Scenario 1: Clean profile
        clean_tox = backlink_engine.evaluate_toxicity_radar(
            total_backlinks=500,
            referring_domains=50,
            spam_score=5.0,
            referring_domain_items=[{"domain": "techcrunch.com"}, {"domain": "bbc.com"}],
            anchor_items=[{"category": "Branded", "backlinks": 300}, {"category": "Naked URL", "backlinks": 200}]
        )
        self.assertEqual(clean_tox["risk_level"], "LOW")
        self.assertEqual(clean_tox["flags_count"], 0)

        # Scenario 2: Sitewide spam & low trust TLDs
        dirty_tox = backlink_engine.evaluate_toxicity_radar(
            total_backlinks=50000,
            referring_domains=20,
            spam_score=45.0,
            referring_domain_items=[{"domain": "spam1.xyz"}, {"domain": "spam2.top"}, {"domain": "spam3.click"}],
            anchor_items=[{"category": "Exact Match", "backlinks": 40000}]
        )
        self.assertIn(dirty_tox["risk_level"], ["MODERATE", "HIGH"])
        self.assertGreater(dirty_tox["flags_count"], 1)

    def test_get_backlink_profile_fallback_integrity(self):
        """Ensures that without DataForSEO, the engine never invents fake external backlinks."""
        with patch.object(integrations, "dataforseo_configured", return_value=False), \
             patch.object(integrations, "openpagerank_configured", return_value=False):
            profile = backlink_engine.get_backlink_profile("esupport.live")
            self.assertTrue(profile["ok"])
            self.assertEqual(profile["target_domain"], "esupport.live")
            self.assertFalse(profile["has_external_provider"])
            self.assertIn("require a connected provider", profile["data_provider_note"])
            # External backlink counts should be None, not fabricated numbers
            self.assertIsNone(profile["overview"]["total_backlinks"])
            self.assertIsNone(profile["overview"]["referring_domains"])
            # Platform Authority Index is calculated from internal crawl evidence
            self.assertIn("platform_authority_index", profile)

    def test_backlink_gap_analysis(self):
        """Tests competitor backlink gap discovery."""
        mock_target_refs = {"items": [{"domain": "common-directory.com"}]}
        mock_comp1_refs = {"items": [{"domain": "common-directory.com"}, {"domain": "industry-leader.org", "rank": 75, "backlinks": 4}]}
        mock_comp2_refs = {"items": [{"domain": "industry-leader.org", "rank": 75, "backlinks": 6}, {"domain": "tech-blog.io", "rank": 60, "backlinks": 2}]}

        def mock_fetch(dom, limit=150):
            if dom == "mybrand.com":
                return mock_target_refs
            elif dom == "rival1.com":
                return mock_comp1_refs
            else:
                return mock_comp2_refs

        with patch.object(integrations, "backlinks_referring_domains", side_effect=mock_fetch):
            gap_res = backlink_engine.analyze_backlink_gap("mybrand.com", ["rival1.com", "rival2.com"])
            self.assertTrue(gap_res["ok"])
            gaps = gap_res["gaps"]
            self.assertGreater(len(gaps), 0)

            # industry-leader.org links to BOTH competitors, should be rank 1
            top_gap = gaps[0]
            self.assertEqual(top_gap["referring_domain"], "industry-leader.org")
            self.assertEqual(top_gap["competitors_count"], 2)

    def test_backlink_snapshot_crud(self):
        """Tests saving, listing, getting, and deleting backlink snapshots."""
        db = SessionLocal()
        try:
            profile_sample = {
                "target_domain": "test-snapshot-dom.com",
                "overview": {"total_backlinks": 1200, "referring_domains": 110, "dofollow_backlinks": 950},
                "domain_authority": {"score": 45.0, "provider": "DataForSEO Domain Rank"},
                "platform_authority_index": {"score": 68.5},
                "toxicity_radar": {"risk_level": "LOW"}
            }

            # 1. Save
            snap = backlink_engine.save_backlink_snapshot(db, "test-snapshot-dom.com", profile_sample)
            self.assertIsNotNone(snap.id)
            snap_id = snap.id

            # 2. List
            snapshots = backlink_engine.list_backlink_snapshots(db, "test-snapshot-dom.com")
            self.assertGreaterEqual(len(snapshots), 1)
            self.assertEqual(snapshots[0]["target_domain"], "test-snapshot-dom.com")

            # 3. Get Detail
            detail = backlink_engine.get_backlink_snapshot(db, snap_id)
            self.assertIsNotNone(detail)
            self.assertEqual(detail["target_domain"], "test-snapshot-dom.com")
            self.assertEqual(detail["data"]["overview"]["total_backlinks"], 1200)

            # 4. Delete
            deleted = backlink_engine.delete_backlink_snapshot(db, snap_id)
            self.assertTrue(deleted)
            self.assertIsNone(backlink_engine.get_backlink_snapshot(db, snap_id))
        finally:
            db.close()

    def test_backlink_exporters(self):
        """Tests CSV, Excel XML, and ReportLab PDF exporters."""
        profile = {
            "target_domain": "esupport.live",
            "timestamp": "2026-10-24T12:00:00Z",
            "data_provider_note": "Internal engine & DataForSEO index",
            "overview": {
                "total_backlinks": 520,
                "referring_domains": 45,
                "dofollow_backlinks": 400,
                "dofollow_percentage": 76.9
            },
            "domain_authority": {"score": 52.0, "provider": "DataForSEO Domain Rank"},
            "platform_authority_index": {
                "score": 64.2,
                "methodology": "PageRank d=0.85 simulation"
            },
            "toxicity_radar": {
                "risk_level": "LOW",
                "risk_score": 10,
                "backlinks_per_domain_ratio": 11.5,
                "flags": []
            },
            "referring_domains": [
                {"domain": "techhub.com", "rank": 65, "backlinks": 12, "dofollow": 10, "nofollow": 2, "first_seen": "2026-01-10"}
            ],
            "anchor_profile": [
                {"anchor": "eSupport Live", "category": "Branded", "backlinks": 25, "referring_domains": 10, "dofollow": 25}
            ],
            "internal_equity": {
                "top_equity_pages": [
                    {"url": "https://esupport.live/", "internal_equity_score": 85.0, "inbound_internal_links": 24, "outbound_internal_links": 8, "depth": 1, "is_orphan": False}
                ]
            }
        }

        # CSV Export
        csv_out = backlink_engine.generate_backlink_csv(profile)
        self.assertIn("BACKLINK ANALYTICS INTELLIGENCE REPORT", csv_out)
        self.assertIn("esupport.live", csv_out)
        self.assertIn("techhub.com", csv_out)

        # Excel XML Export
        xml_out = backlink_engine.generate_backlink_excel_xml(profile)
        self.assertIn('<?xml version="1.0" encoding="UTF-8"?>', xml_out)
        self.assertIn("Referring Domains", xml_out)
        self.assertIn("Internal Link Equity", xml_out)

        # ReportLab PDF Export
        pdf_bytes = backlink_engine.generate_backlink_pdf(profile)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertGreater(len(pdf_bytes), 2000)

    def test_backlink_api_endpoints(self):
        """Tests Backlink Analytics FastAPI endpoint handlers."""
        db = SessionLocal()
        try:
            # 1. Overview Endpoint
            ov = backlink_overview_endpoint(target="esupport.live", refresh=False, db=db, current_admin=self.admin_user)
            self.assertTrue(ov["ok"])
            self.assertEqual(ov["target_domain"], "esupport.live")

            # 2. Referring Domains Endpoint
            refs = backlink_referring_domains_endpoint(target="esupport.live", filter_type="all", search="", limit=50, offset=0, db=db, current_admin=self.admin_user)
            self.assertTrue(refs["ok"])
            self.assertIsInstance(refs["items"], list)

            # 3. Anchors Endpoint
            anc = backlink_anchors_endpoint(target="esupport.live", limit=20, db=db, current_admin=self.admin_user)
            self.assertTrue(anc["ok"])
            self.assertIsInstance(anc["items"], list)

            # 4. Internal Equity Endpoint
            eq = backlink_internal_equity_endpoint(target="esupport.live", db=db, current_admin=self.admin_user)
            self.assertTrue(eq["ok"])
            self.assertIn("platform_authority_index", eq)

            # 5. Gap Endpoint
            gap = backlink_gap_endpoint(
                BacklinkGapRequest(target_domain="esupport.live", competitor_domains=["shwoah.com"]),
                db=db,
                current_admin=self.admin_user
            )
            self.assertTrue(gap["ok"])

            # 6. Snapshots List
            snaps = backlink_snapshots_list_endpoint(target="esupport.live", db=db, current_admin=self.admin_user)
            self.assertIsInstance(snaps, list)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
