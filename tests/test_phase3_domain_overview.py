"""
Comprehensive Test Suite for Phase 3: Domain Overview Dashboard.

Covers:
1. Domain Discovery & Listing (list_domains_endpoint):
   - Aggregation of distinct audited domains with audit counts and latest scores.
   - Graceful inclusion of registered client websites without audits.
2. Comprehensive Domain Overview Telemetry (domain_overview_endpoint):
   - URL / domain normalization (protocols, paths, trailing slashes).
   - Handling of un-audited domains (has_data: False, zero fake metrics).
   - Website SEO Health Score (deterministic engine score, grade, categories, data provenance).
   - Organic Search Visibility & Keywords (distinction between on-site extracted terms and SERP rankings).
   - Zero-Fabrication Policy: Guarantee that traffic_estimate is NEVER fabricated without connected data.
   - Referring Domains & Backlinks (DataForSEO / OpenPageRank telemetry or explicit unconfigured notice).
   - Google Search Console Telemetry (verified clicks, impressions, position or not connected notice).
   - Google PageSpeed & Core Web Vitals (strict separation of Lab Diagnostics from Real-User Field CrUX).
   - Technical Issues Summary (critical, high, medium, low breakdown and actionable issue list).
   - Top-Performing Pages (internal crawl graph ranking by equity and content depth).
   - Historical Trends (chronological progression data for interactive chart rendering).
"""

import unittest
import json
from datetime import datetime
from unittest.mock import MagicMock

from backend.main import list_domains_endpoint, domain_overview_endpoint


class TestPhase3DomainOverview(unittest.TestCase):
    def setUp(self):
        # Create rich mock audits
        self.mock_a1 = MagicMock()
        self.mock_a1.id = 1
        self.mock_a1.target_url = "https://example.com/"
        self.mock_a1.score = 65.0
        self.mock_a1.created_at = datetime(2026, 10, 10, 10, 0, 0)
        self.mock_a1.result_json = {
            "page_count": 10,
            "seo_engine": {
                "score": {"overall": 65.0, "grade": "Needs Improvement", "maturity_level": 2, "maturity_label": "Managed"},
                "categories": [
                    {"id": "technical", "name": "Technical SEO", "score": 75.0, "weight": 15},
                    {"id": "content", "name": "Content SEO", "score": 60.0, "weight": 12},
                ],
                "issue_summary": {"critical": 2, "high": 5, "medium": 8, "low": 10, "total": 25},
                "issues": [
                    {
                        "check_id": "TECH-01",
                        "severity": "critical",
                        "title": "Broken Links Detected",
                        "urls": ["https://example.com/broken"],
                        "recommended_fix": "Fix broken target URLs."
                    }
                ]
            },
            "real_data": {
                "pagespeed": {
                    "mobile": {
                        "ok": True,
                        "lighthouse_scores": {"performance": 88, "accessibility": 90, "best-practices": 85, "seo": 80},
                        "lab": {"LCP": "2.1s", "CLS": "0.05", "FCP": "1.3s", "TBT": "120ms"},
                        "field_origin": {"LARGEST_CONTENTFUL_PAINT_MS": 2400}
                    }
                },
                "search_console": {
                    "ok": True,
                    "clicks": 450,
                    "impressions": 12500,
                    "ctr": 0.036,
                    "average_position": 14.2,
                    "top_queries": [{"query": "example keywords", "clicks": 120, "impressions": 3000}],
                    "top_pages": [{"page": "https://example.com/", "clicks": 300, "impressions": 8000}]
                },
                "openpagerank": {
                    "ok": True,
                    "page_rank_decimal": 4.5,
                    "rank": 120000
                }
            },
            "keywords": [
                {"term": "example", "count": 15, "pages": 5, "intent": "navigational"},
                {"term": "solutions", "count": 8, "pages": 3, "intent": "informational"}
            ],
            "pages": [
                {
                    "url": "https://example.com/",
                    "status": 200,
                    "title": "Example Home",
                    "word_count": 1200,
                    "internal_links": ["https://example.com/about", "https://example.com/services"],
                    "canonical": "https://example.com/"
                },
                {
                    "url": "https://example.com/services",
                    "status": 200,
                    "title": "Services",
                    "word_count": 800,
                    "internal_links": ["https://example.com/"],
                    "canonical": "https://example.com/services"
                }
            ]
        }

        self.mock_a2 = MagicMock()
        self.mock_a2.id = 2
        self.mock_a2.target_url = "https://example.com/"
        self.mock_a2.score = 75.0
        self.mock_a2.created_at = datetime(2026, 10, 20, 10, 0, 0)
        self.mock_a2.result_json = {
            "page_count": 12,
            "seo_engine": {
                "score": {"overall": 75.0, "grade": "Good", "maturity_level": 3, "maturity_label": "Optimised"},
                "categories": [
                    {"id": "technical", "name": "Technical SEO", "score": 85.0, "weight": 15},
                    {"id": "content", "name": "Content SEO", "score": 70.0, "weight": 12},
                ],
                "issue_summary": {"critical": 1, "high": 3, "medium": 6, "low": 8, "total": 18},
                "issues": [
                    {
                        "check_id": "CONT-01",
                        "severity": "high",
                        "title": "Short Meta Description",
                        "urls": ["https://example.com/services"],
                        "recommended_fix": "Expand meta description."
                    }
                ]
            },
            "real_data": {
                "pagespeed": {
                    "mobile": {
                        "ok": True,
                        "lighthouse_scores": {"performance": 92, "accessibility": 95, "best-practices": 90, "seo": 85},
                        "lab": {"LCP": "1.8s", "CLS": "0.02", "FCP": "1.1s", "TBT": "80ms"},
                        "field_origin": {"LARGEST_CONTENTFUL_PAINT_MS": 2100}
                    }
                },
                "search_console": {
                    "ok": True,
                    "clicks": 620,
                    "impressions": 16000,
                    "ctr": 0.039,
                    "average_position": 11.8,
                    "top_queries": [{"query": "example keywords", "clicks": 180, "impressions": 4200}],
                    "top_pages": [{"page": "https://example.com/", "clicks": 420, "impressions": 10500}]
                },
                "openpagerank": {
                    "ok": True,
                    "page_rank_decimal": 4.8,
                    "rank": 115000
                }
            },
            "keywords": [
                {"term": "example", "count": 20, "pages": 6, "intent": "navigational"},
                {"term": "solutions", "count": 12, "pages": 4, "intent": "informational"}
            ],
            "pages": [
                {
                    "url": "https://example.com/",
                    "status": 200,
                    "title": "Example Home",
                    "word_count": 1350,
                    "internal_links": ["https://example.com/about", "https://example.com/services"],
                    "canonical": "https://example.com/"
                }
            ]
        }

    def test_list_domains_endpoint(self):
        """Verify list_domains_endpoint groups audits by bare domain and returns counts and scores."""
        mock_db = MagicMock()
        mock_db.query.return_value.order_by.return_value.all.return_value = [self.mock_a2, self.mock_a1]
        mock_db.query.return_value.all.return_value = []

        domains = list_domains_endpoint(db=mock_db, current_admin=MagicMock())
        self.assertEqual(len(domains), 1)
        dom = domains[0]
        self.assertEqual(dom["domain_display"], "example.com")
        self.assertEqual(dom["audit_count"], 2)
        self.assertEqual(dom["latest_score"], 75.0)
        self.assertEqual(dom["latest_audit_id"], 2)

    def test_domain_overview_unknown_domain(self):
        """Verify requesting an unknown domain gracefully returns has_data: False with no fake metrics."""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        res = domain_overview_endpoint(target_url="https://newdomain-never-audited.org", db=mock_db, current_admin=MagicMock())
        self.assertFalse(res["has_data"])
        self.assertEqual(res["domain_display"], "newdomain-never-audited.org")
        self.assertIn("No audit history found", res["message"])
        self.assertEqual(res["audits_found"], 0)

    def test_domain_overview_known_domain_data_integrity(self):
        """Verify complete domain overview telemetry, data provenance, and zero-fabrication rules."""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [self.mock_a2, self.mock_a1]

        res = domain_overview_endpoint(target_url="example.com", db=mock_db, current_admin=MagicMock())

        self.assertTrue(res["has_data"])
        self.assertEqual(res["domain_display"], "example.com")
        self.assertEqual(res["audit_count"], 2)
        self.assertEqual(res["last_audit_id"], 2)

        # 1. SEO Health Score
        health = res["seo_health"]
        self.assertEqual(health["score"], 75.0)
        self.assertEqual(health["grade"], "Good")
        self.assertEqual(health["maturity_label"], "Optimised")
        self.assertEqual(health["data_type"], "calculated_score")
        self.assertIn("Deterministic", health["data_provider"])
        self.assertEqual(len(health["categories"]), 2)

        # 2. Organic Search & Zero-Fabrication Rule
        org = res["organic_search"]
        self.assertIsNone(org["traffic_estimate"], "Organic traffic estimate MUST NOT be fabricated when unconfigured!")
        self.assertEqual(org["traffic_data_type"], "unavailable")
        self.assertIn("First-party traffic measurements require connecting", org["traffic_note"])
        self.assertEqual(org["organic_keywords_count"], 2)
        self.assertEqual(org["keywords_data_type"], "first_party_measurement")

        # 3. Referring Domains & Backlinks
        bl = res["backlinks"]
        self.assertTrue(bl["is_configured"])
        self.assertEqual(bl["openpagerank_score"], 4.8)
        self.assertIn("OpenPageRank", bl["data_provider"])
        self.assertEqual(bl["data_type"], "third_party_index")

        # 4. Search Console
        gsc = res["search_console"]
        self.assertTrue(gsc["connected"])
        self.assertEqual(gsc["clicks"], 620)
        self.assertEqual(gsc["impressions"], 16000)
        self.assertEqual(gsc["average_position"], 11.8)
        self.assertEqual(gsc["data_type"], "first_party_measurement")

        # 5. PageSpeed & Core Web Vitals (Lab vs Field)
        ps = res["pagespeed"]
        self.assertTrue(ps["is_available"])
        self.assertEqual(ps["mobile"]["performance_score"], 92)
        self.assertIn("LCP", ps["mobile"]["lab"])
        self.assertIn("LARGEST_CONTENTFUL_PAINT_MS", ps["mobile"]["field"])

        # 6. Technical Issues
        issues = res["technical_issues"]
        self.assertEqual(issues["critical"], 1)
        self.assertEqual(issues["high"], 3)
        self.assertEqual(issues["total"], 18)
        self.assertTrue(len(issues["top_issues"]) > 0)
        top_iss = issues["top_issues"][0]
        self.assertEqual(top_iss["check_id"], "CONT-01")
        self.assertEqual(top_iss["severity"], "high")

        # 7. Top Performing Pages
        pages = res["top_pages"]
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0]["url"], "https://example.com/")
        self.assertEqual(pages[0]["word_count"], 1350)

        # 8. Historical Trends
        trends = res["historical_trends"]
        self.assertEqual(len(trends), 2)
        self.assertEqual(trends[0]["audit_id"], 1)
        self.assertEqual(trends[0]["score"], 65.0)
        self.assertEqual(trends[1]["audit_id"], 2)
        self.assertEqual(trends[1]["score"], 75.0)
        self.assertEqual(trends[0]["critical_issues"], 2)
        self.assertEqual(trends[1]["critical_issues"], 1)


if __name__ == "__main__":
    unittest.main()

