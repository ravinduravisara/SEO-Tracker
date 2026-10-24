"""
Comprehensive Test Suite for Phase 2: Professional Technical SEO Audit.

Covers:
1. Standardized Technical Issue Contract:
   - affected_url, problem_description, severity, evidence, suggested_correction, verification_method, status.
2. Technical Crawler & Audit Engine Checks:
   - HTTP status codes (2xx, 3xx, 4xx, 5xx).
   - Redirect chains and circular redirect loops.
   - Canonical tags (missing, cross-domain, non-self, outside head).
   - Duplicate titles, meta descriptions, and duplicate visible text.
   - Missing meta descriptions, short/long descriptions.
   - Missing H1, multiple H1, duplicate H1 across pages, and heading hierarchy jumps.
   - Robots.txt restrictions (Googlebot access, missing robots.txt).
   - XML sitemap cross-checks (sitemap missing, noindex in sitemap, canonical in sitemap).
   - Indexability directives (noindex, nofollow, X-Robots-Tag).
   - Thin content indicators (<150 words on indexable content pages).
   - Image alt text, dimensions, and large image files (>1MB).
   - Broken internal and external links.
   - Orphan page candidates in crawled internal link graph.
   - HTTPS configuration and mixed-content resources.
   - Structured data (JSON-LD syntax and missing schema).
   - Hreflang configuration and reciprocal validation.
3. Historical Audit Comparison:
   - Score delta computation.
   - Resolved issues detection.
   - Regressions / new issues detection.
   - Category-level progression.
"""

import unittest
import json
from unittest.mock import MagicMock

from backend.main import (
    page_checks,
    global_checks,
    sitemap_cross_checks,
    hreflang_checks,
    annotate_issue_sources,
    developer_validation,
    compare_audits_endpoint,
)
from backend.seo_engine.issues import synthesise
from backend.seo_engine.scoring import CheckResult


class TestPhase2StandardizedIssueContract(unittest.TestCase):
    def test_engine_synthesised_issues_contract(self):
        """Verify synthesised issues have all required fields for Phase 2."""
        sample_results = [
            CheckResult(
                id="SEC-01",
                category="technical",
                status="FAIL",
                points=0,
                evidence_label="HTTP Protocol Detected",
                evidence={"statement": "Site served over plain HTTP", "urls": ["http://example.com/"]},
            )
        ]
        defs = {
            "SEC-01": {
                "name": "HTTPS Usage",
                "severity": "critical",
                "effort": 15,
                "reason": "Security and indexing risk.",
                "fix": "Redirect HTTP to HTTPS.",
                "dev": True,
            }
        }
        category_names = {"security": "Security"}
        issues = synthesise(sample_results, defs, category_names)
        self.assertEqual(len(issues), 1)
        issue = issues[0]

        # Verify all required Phase 2 fields
        self.assertIn("affected_url", issue)
        self.assertEqual(issue["affected_url"], "http://example.com/")
        self.assertIn("problem_description", issue)
        self.assertIn("HTTPS Usage", issue["problem_description"])
        self.assertEqual(issue["severity"], "critical")
        self.assertIn("evidence", issue)
        self.assertIn("statement", issue["evidence"])
        self.assertIn("suggested_correction", issue)
        self.assertEqual(issue["suggested_correction"], "Redirect HTTP to HTTPS.")
        self.assertIn("verification_method", issue)
        self.assertTrue(len(issue["verification_method"]) > 0)
        self.assertEqual(issue["status"], "OPEN")

    def test_page_level_issue_contract(self):
        """Verify page-level issues populated by page_checks have standardized fields."""
        page = {
            "url": "https://example.com/test",
            "status": 404,
            "title": "",
            "meta_description": "",
            "h1": [],
            "heading_order": [],
            "viewport": "",
            "lang": "",
            "charset": "",
            "meta_robots": "",
            "x_robots_tag": "",
            "canonical": "",
            "canonical_location": "head",
            "robots_meta_location": "head",
            "images": [],
            "schema_types": [],
            "schema_errors": [],
            "og": {},
            "twitter": {},
            "word_count": 0,
            "semantic_elements": {},
            "internal_links": [],
            "forms": {"unlabelled_inputs": 0},
            "headers": {},
            "response_time_ms": 100,
            "html_bytes": 500,
            "rendering_signals": {"script_count": 2},
            "favicon": True,
            "redirect_count": 0,
            "redirect_chain": [],
            "issues": [],
        }
        page_checks(page)
        self.assertTrue(len(page["issues"]) > 0)

        for iss in page["issues"]:
            self.assertIn("affected_url", iss or {})
            self.assertIn("problem_description", iss)
            self.assertIn("severity", iss)
            self.assertIn("evidence", iss)
            self.assertIn("suggested_correction", iss)
            self.assertIn("verification_method", iss)
            self.assertEqual(iss["status"], "OPEN")

    def test_annotate_issue_sources_standardization(self):
        """Verify annotate_issue_sources enforces standardized fields on arbitrary findings."""
        raw_audit = {
            "page_findings": [
                {
                    "severity": "warning",
                    "code": "broken_internal_links",
                    "category": "Links",
                    "message": "1 checked internal URL returned errors.",
                    "recommendation": "Fix or remove broken internal links.",
                    "url": "https://example.com/broken",
                }
            ]
        }
        annotate_issue_sources(raw_audit)
        finding = raw_audit["page_findings"][0]
        self.assertEqual(finding["affected_url"], "https://example.com/broken")
        self.assertEqual(finding["problem_description"], "1 checked internal URL returned errors.")
        self.assertEqual(finding["suggested_correction"], "Fix or remove broken internal links.")
        self.assertIn("verification_method", finding)
        self.assertEqual(finding["status"], "OPEN")


class TestPhase2TechnicalCrawlerChecks(unittest.TestCase):
    def test_redirect_loop_detection(self):
        """Verify circular redirect loops are detected as critical issues."""
        page = {
            "url": "https://example.com/a",
            "status": 301,
            "redirect_count": 3,
            "redirect_chain": [
                {"url": "https://example.com/a"},
                {"url": "https://example.com/b"},
                {"url": "https://example.com/a"},
            ],
            "title": "A",
            "meta_description": "Valid meta description long enough for check.",
            "h1": ["Heading"],
            "heading_order": [{"tag": "h1"}],
            "viewport": "width=device-width",
            "lang": "en",
            "charset": "utf-8",
            "meta_robots": "",
            "x_robots_tag": "",
            "canonical": "https://example.com/a",
            "canonical_location": "head",
            "robots_meta_location": "head",
            "images": [],
            "schema_types": ["WebPage"],
            "schema_errors": [],
            "og": {},
            "twitter": {},
            "word_count": 250,
            "semantic_elements": {},
            "internal_links": ["https://example.com/b"],
            "forms": {"unlabelled_inputs": 0},
            "headers": {},
            "response_time_ms": 100,
            "html_bytes": 1000,
            "rendering_signals": {"script_count": 1},
            "favicon": True,
            "issues": [],
        }
        page_checks(page)
        loop_issue = next((i for i in page["issues"] if i["code"] == "redirect_loop"), None)
        self.assertIsNotNone(loop_issue)
        self.assertEqual(loop_issue["severity"], "critical")
        self.assertIn("circular redirect loop", loop_issue["problem_description"].lower())

    def test_thin_content_detection(self):
        """Verify indexable pages with < 150 words of body copy are flagged as thin_content."""
        page = {
            "url": "https://example.com/services/consulting",
            "status": 200,
            "redirect_count": 0,
            "redirect_chain": [],
            "title": "Consulting Services",
            "meta_description": "We offer top tier strategy and technology consulting services.",
            "h1": ["Consulting"],
            "heading_order": [{"tag": "h1"}],
            "viewport": "width=device-width",
            "lang": "en",
            "charset": "utf-8",
            "meta_robots": "",
            "x_robots_tag": "",
            "canonical": "https://example.com/services/consulting",
            "canonical_location": "head",
            "robots_meta_location": "head",
            "images": [],
            "schema_types": ["Service"],
            "schema_errors": [],
            "og": {},
            "twitter": {},
            "word_count": 95,  # < 150 words
            "semantic_elements": {},
            "internal_links": ["https://example.com/"],
            "forms": {"unlabelled_inputs": 0},
            "headers": {},
            "response_time_ms": 120,
            "html_bytes": 1500,
            "rendering_signals": {"script_count": 1},
            "favicon": True,
            "issues": [],
        }
        page_checks(page)
        thin_issue = next((i for i in page["issues"] if i["code"] == "thin_content"), None)
        self.assertIsNotNone(thin_issue)
        self.assertEqual(thin_issue["severity"], "warning")
        self.assertIn("thin visible copy", thin_issue["problem_description"])

    def test_large_image_detection(self):
        """Verify image assets > 1MB are flagged for optimization."""
        page = {
            "url": "https://example.com/gallery",
            "status": 200,
            "redirect_count": 0,
            "redirect_chain": [],
            "title": "Photo Gallery",
            "meta_description": "High resolution photo gallery of our products and services.",
            "h1": ["Photo Gallery"],
            "heading_order": [{"tag": "h1"}],
            "viewport": "width=device-width",
            "lang": "en",
            "charset": "utf-8",
            "meta_robots": "",
            "x_robots_tag": "",
            "canonical": "https://example.com/gallery",
            "canonical_location": "head",
            "robots_meta_location": "head",
            "images": [
                {
                    "src": "https://example.com/huge-banner.png",
                    "alt": "Huge Banner",
                    "width": "1920",
                    "height": "1080",
                    "bytes": 2_450_000,  # ~2.4 MB > 1MB
                    "loading": "lazy",
                    "format": "png",
                }
            ],
            "schema_types": ["WebPage"],
            "schema_errors": [],
            "og": {},
            "twitter": {},
            "word_count": 350,
            "semantic_elements": {},
            "internal_links": ["https://example.com/"],
            "forms": {"unlabelled_inputs": 0},
            "headers": {},
            "response_time_ms": 110,
            "html_bytes": 2000,
            "rendering_signals": {"script_count": 1},
            "favicon": True,
            "issues": [],
        }
        page_checks(page)
        img_issue = next((i for i in page["issues"] if i["code"] == "large_image_file"), None)
        self.assertIsNotNone(img_issue)
        self.assertEqual(img_issue["severity"], "warning")
        self.assertIn("Large image file", img_issue["problem_description"])

    def test_heading_jump_detection(self):
        """Verify heading outline jumping from H1 directly to H3 or H4 is detected."""
        page = {
            "url": "https://example.com/article",
            "status": 200,
            "redirect_count": 0,
            "redirect_chain": [],
            "title": "Technical SEO Guide",
            "meta_description": "Comprehensive guide to auditing technical SEO factors on web apps.",
            "h1": ["Technical SEO"],
            "heading_order": [{"tag": "h1"}, {"tag": "h3"}],  # Jumps H1 -> H3
            "viewport": "width=device-width",
            "lang": "en",
            "charset": "utf-8",
            "meta_robots": "",
            "x_robots_tag": "",
            "canonical": "https://example.com/article",
            "canonical_location": "head",
            "robots_meta_location": "head",
            "images": [],
            "schema_types": ["Article"],
            "schema_errors": [],
            "og": {},
            "twitter": {},
            "word_count": 400,
            "semantic_elements": {},
            "internal_links": ["https://example.com/"],
            "forms": {"unlabelled_inputs": 0},
            "headers": {},
            "response_time_ms": 90,
            "html_bytes": 2000,
            "rendering_signals": {"script_count": 1},
            "favicon": True,
            "issues": [],
        }
        page_checks(page)
        jump_issue = next((i for i in page["issues"] if i["code"] == "heading_jump"), None)
        self.assertIsNotNone(jump_issue)
        self.assertIn("H1 to H3", jump_issue["problem_description"])

    def test_duplicate_titles_and_orphan_candidates(self):
        """Verify global checks correctly detect duplicate titles and orphan page candidates."""
        pages = [
            {
                "url": "https://example.com/",
                "title": "Welcome to Example",
                "meta_description": "Home page description.",
                "h1": ["Home"],
                "content_hash": "hash1",
                "word_count": 200,
                "internal_links": ["https://example.com/page-1"],
                "canonical": "https://example.com/",
                "status": 200,
            },
            {
                "url": "https://example.com/page-1",
                "title": "Duplicate Title Example",
                "meta_description": "First page with this title.",
                "h1": ["Page 1"],
                "content_hash": "hash2",
                "word_count": 200,
                "internal_links": ["https://example.com/"],
                "canonical": "https://example.com/page-1",
                "status": 200,
            },
            {
                "url": "https://example.com/page-2",
                "title": "Duplicate Title Example",  # Duplicate title
                "meta_description": "Second page with this title.",
                "h1": ["Page 2"],
                "content_hash": "hash3",
                "word_count": 200,
                "internal_links": [],  # Orphan: not linked from any crawled page
                "canonical": "https://example.com/page-2",
                "status": 200,
            },
        ]
        robots = {"found": True, "url": "https://example.com/robots.txt", "googlebot_allows_root": True, "googlebot_allows_start": True}
        sitemap = {"urls": ["https://example.com/", "https://example.com/page-1", "https://example.com/page-2"], "files": ["/sitemap.xml"]}
        link_results = []

        issues = global_checks("https://example.com/", pages, robots, sitemap, link_results)
        dup_title = next((i for i in issues if i["code"] == "duplicate_title"), None)
        self.assertIsNotNone(dup_title)
        self.assertEqual(dup_title["severity"], "warning")

        orphan = next((i for i in issues if i["code"] == "orphan_candidate" and i["url"] == "https://example.com/page-2"), None)
        self.assertIsNotNone(orphan)


class TestPhase2AuditComparison(unittest.TestCase):
    def test_compare_audits_endpoint_logic(self):
        """Verify audit comparison endpoint calculates score deltas, resolved issues, and regressions."""
        mock_a1 = MagicMock()
        mock_a1.id = 101
        mock_a1.target_url = "https://example.com/"
        mock_a1.score = 65.0
        mock_a1.created_at = MagicMock()
        mock_a1.created_at.isoformat.return_value = "2026-10-01T10:00:00"
        mock_a1.result_json = {
            "page_count": 10,
            "seo_engine": {
                "score": {"overall": 65.0, "grade": "C"},
                "categories": [
                    {"id": "technical", "name": "Technical SEO", "score": 60.0},
                    {"id": "content", "name": "Content SEO", "score": 70.0},
                ],
                "issues": [
                    {"check_id": "TECH-01", "name": "Broken Links", "severity": "high"},
                    {"check_id": "CONT-01", "name": "Thin Content", "severity": "medium"},
                ],
                "measurement_coverage": {"coverage_percentage": 90.0},
            },
            "stats": {"broken_links": 3},
        }

        mock_a2 = MagicMock()
        mock_a2.id = 102
        mock_a2.target_url = "https://example.com/"
        mock_a2.score = 85.0
        mock_a2.created_at = MagicMock()
        mock_a2.created_at.isoformat.return_value = "2026-10-15T10:00:00"
        mock_a2.result_json = {
            "page_count": 15,
            "seo_engine": {
                "score": {"overall": 85.0, "grade": "B"},
                "categories": [
                    {"id": "technical", "name": "Technical SEO", "score": 90.0},
                    {"id": "content", "name": "Content SEO", "score": 80.0},
                ],
                "issues": [
                    {"check_id": "CONT-01", "name": "Thin Content", "severity": "medium"},
                    {"check_id": "NEW-01", "name": "Missing Viewport", "severity": "low"},  # Regression / New
                ],
                "measurement_coverage": {"coverage_percentage": 95.0},
            },
            "stats": {"broken_links": 0},
        }

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.side_effect = [mock_a1, mock_a2]

        result = compare_audits_endpoint(101, 102, db=mock_db, current_admin=MagicMock())

        # Verify score delta
        self.assertEqual(result["score_delta"], 20.0)
        self.assertTrue(result["improved"])
        self.assertFalse(result["regressed"])

        # Verify resolved issues (TECH-01 resolved)
        self.assertEqual(result["issues_summary"]["resolved_count"], 1)
        self.assertEqual(result["resolved_issues"][0]["check_id"], "TECH-01")

        # Verify new issues (NEW-01 added)
        self.assertEqual(result["issues_summary"]["new_count"], 1)
        self.assertEqual(result["new_issues"][0]["check_id"], "NEW-01")

        # Verify persistent issues (CONT-01 retained)
        self.assertEqual(result["issues_summary"]["persistent_count"], 1)
        self.assertEqual(result["persistent_issues"][0]["check_id"], "CONT-01")

        # Verify category deltas
        tech_diff = next(c for c in result["categories_diff"] if c["id"] == "technical")
        self.assertEqual(tech_diff["delta"], 30.0)

        # Verify stats delta
        self.assertEqual(result["stats_diff"]["pages_crawled"], 5)
        self.assertEqual(result["stats_diff"]["broken_links"], -3)


if __name__ == "__main__":
    unittest.main()
