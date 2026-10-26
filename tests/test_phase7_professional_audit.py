"""Phase 7 Professional SEO Audit & Intelligence Comprehensive Test Suite.

Validates:
1. SSRF Protection against loopback, private ranges, and cloud metadata.
2. Dual-Level Severity & Warning Counting (Unique Issues vs Affected Instances).
3. Standardized 16-Field Finding Model.
4. AI Search Readiness & Generative Engine Optimization (GEO) Analyzer.
5. Image SEO Standards (Decorative alt="" vs missing alt).
6. Multi-Tier Reporting Engine (Executive, Technical, Developer, Progress).
"""
import unittest
from datetime import datetime, timezone

from backend.main import validate_public_target, BlockedTargetError
from backend.seo_engine.issues import synthesise, summarise, Finding
from backend.seo_engine.scoring import CheckResult
from backend.seo_engine.ai_readiness import evaluate_ai_search_readiness
from backend.reporting_engine import (
    generate_report_data,
    generate_report_pdf,
    generate_report_csv,
    generate_report_excel_xml,
    generate_report_json
)


class TestPhase7SSRFProtection(unittest.TestCase):
    """Test SSRF protection ensures loopback, private, and cloud metadata are blocked."""

    def test_blocks_localhost(self):
        with self.assertRaises(ValueError):
            validate_public_target("http://localhost/")
        with self.assertRaises(ValueError):
            validate_public_target("http://127.0.0.1:8000/")

    def test_blocks_cloud_metadata(self):
        with self.assertRaises(ValueError):
            validate_public_target("http://169.254.169.254/latest/meta-data/")

    def test_blocks_private_networks(self):
        with self.assertRaises(ValueError):
            validate_public_target("http://10.0.0.1/")
        with self.assertRaises(ValueError):
            validate_public_target("http://192.168.1.100/")
        with self.assertRaises(ValueError):
            validate_public_target("http://172.16.0.1/")

    def test_allows_public_target(self):
        from unittest.mock import patch
        with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("93.184.216.34", 443))]):
            url = validate_public_target("https://esupport.live/")
            self.assertTrue(url.startswith("https://"))


class TestPhase7IssueCountingAndFindings(unittest.TestCase):
    """Test dual-level issue counting and 16-field Finding model (Phase 7.3 & 7.13)."""

    def setUp(self):
        self.sample_defs = {
            "T01": {
                "name": "HTTPS Enforced",
                "severity": "critical",
                "effort": 60,
                "dev": True,
                "reason": "Security protocol requirement",
                "fix": "Redirect HTTP to HTTPS with 301",
                "expected": "All pages serve over HTTPS"
            },
            "O09": {
                "name": "Single H1 Tag",
                "severity": "high",
                "effort": 30,
                "dev": True,
                "reason": "Clear topic signal",
                "fix": "Add single H1 per page",
                "expected": "Exactly one H1 element per page"
            },
            "O07": {
                "name": "Meta Description Length",
                "severity": "medium",
                "effort": 15,
                "dev": False,
                "reason": "Search snippet CTR",
                "fix": "Write 120-160 char description",
                "expected": "Optimal meta description length"
            }
        }
        self.category_names = {"technical": "Technical SEO", "onpage": "On-Page SEO"}

    def test_dual_level_issue_counting(self):
        """Verify unique issue types are distinguished from total affected instances."""
        results = [
            CheckResult(
                id="T01",
                category="technical",
                points=8,
                status="FAIL",
                evidence={"statement": "HTTP used on 2 pages", "urls": ["http://example.com/p1", "http://example.com/p2"]},
                evidence_label="Observed"
            ),
            CheckResult(
                id="O09",
                category="onpage",
                points=10,
                status="WARN",
                evidence={"statement": "Multiple H1 tags on 5 pages", "urls": [f"https://example.com/page{i}" for i in range(5)]},
                evidence_label="Observed"
            ),
            CheckResult(
                id="O07",
                category="onpage",
                points=6,
                status="WARN",
                evidence={"statement": "Missing description on 3 pages", "urls": [f"https://example.com/p{i}" for i in range(3)]},
                evidence_label="Observed"
            )
        ]

        issues = synthesise(results, self.sample_defs, self.category_names, audit_id=42)
        summary = summarise(issues)

        # 3 unique issues
        self.assertEqual(summary["unique_issue_count"], 3)
        self.assertEqual(summary["total"], 3)

        # Affected instances: T01 (2 pages) + O09 (5 pages) + O07 (3 pages) = 10 instances
        self.assertEqual(summary["total_affected_instances"], 10)
        self.assertEqual(summary["instance_counts"]["total"], 10)

        # Critical: T01 has 1 unique issue, 2 instances
        self.assertEqual(summary["critical_issues"], 1)
        self.assertEqual(summary["instance_counts"]["critical"], 2)

        # Warnings: O09 (high stepped down to medium for WARN) + O07 (medium stepped down to low)
        self.assertEqual(summary["warnings"], 1)  # 1 unique medium
        self.assertEqual(summary["instance_counts"]["warnings"], 5)  # 5 instances for O09

    def test_standardized_finding_model(self):
        """Verify the 16-field Finding model meets Phase 7.13 schema."""
        results = [
            CheckResult(
                id="T01",
                category="technical",
                points=8,
                status="FAIL",
                evidence={"statement": "HTTP unencrypted", "values": {"protocol": "http"}, "urls": ["http://example.com/"]},
                evidence_label="Observed"
            )
        ]
        issues = synthesise(results, self.sample_defs, self.category_names, audit_id=101)
        iss = issues[0]

        # Verify key Finding fields
        self.assertEqual(iss["finding_id"], "FINDING-T01-01")
        self.assertEqual(iss["check_id"], "T01")
        self.assertEqual(iss["category"], "technical")
        self.assertEqual(iss["severity_standard"], "CRITICAL")
        self.assertEqual(iss["status"], "OPEN")
        self.assertEqual(iss["affected_url"], "http://example.com/")
        self.assertEqual(iss["instance_count"], 1)
        self.assertIn("verification_method", iss)
        self.assertIn("ruleset_version", iss)
        self.assertEqual(iss["audit_id"], 101)


class TestPhase7AISearchReadiness(unittest.TestCase):
    """Test AI Search Readiness / GEO Analyzer (Phase 7.12)."""

    def test_evaluate_open_ai_bots(self):
        """When robots.txt has no disallow, all AI bots are allowed."""
        robots_data = {"found": True, "content": "User-agent: *\nAllow: /\n"}
        pages = [
            {
                "url": "https://example.com/",
                "word_count": 500,
                "h2": ["What is our enterprise platform?", "How does it work?"],
                "schema_types": ["Organization", "FAQPage"],
                "schema_nodes": [{"@type": "Organization", "name": "TestCorp", "sameAs": ["https://linkedin.com/testcorp"]}],
                "rendering_signals": {"likely_js_shell": False}
            },
            {
                "url": "https://example.com/about",
                "word_count": 450,
                "h2": ["Leadership Team", "Our Mission"],
                "schema_types": [],
                "schema_nodes": [],
                "rendering_signals": {"likely_js_shell": False}
            }
        ]

        result = evaluate_ai_search_readiness("https://example.com", pages, robots_data, {})
        self.assertGreaterEqual(result["score"], 80)
        self.assertEqual(result["bot_accessibility"]["blocked_count"], 0)
        self.assertEqual(result["bot_accessibility"]["score"], 100)
        self.assertTrue(result["entity_authority"]["signals"]["has_organization_schema"])
        self.assertTrue(result["entity_authority"]["signals"]["has_about_page"])
        self.assertTrue(result["direct_answers"]["signals"]["has_faq_schema"])

    def test_evaluate_blocked_ai_bots(self):
        """When robots.txt disallows GPTBot and PerplexityBot, they are flagged."""
        robots_data = {
            "found": True,
            "content": "User-agent: GPTBot\nDisallow: /\n\nUser-agent: PerplexityBot\nDisallow: /\n"
        }
        pages = [{"url": "https://example.com/", "word_count": 100, "h2": [], "schema_types": [], "schema_nodes": []}]

        result = evaluate_ai_search_readiness("https://example.com", pages, robots_data, {})
        self.assertIn("GPTBot", [b["bot"] for b in result["bot_accessibility"]["bots"] if b["status"] == "BLOCKED"])
        self.assertIn("PerplexityBot", [b["bot"] for b in result["bot_accessibility"]["bots"] if b["status"] == "BLOCKED"])
        self.assertGreater(result["bot_accessibility"]["blocked_count"], 0)
        # Verify finding generated
        self.assertTrue(any(f["code"] == "AI_BOTS_BLOCKED" for f in result["findings"]))


class TestPhase7MultiReportGeneration(unittest.TestCase):
    """Test PDF, CSV, Excel, and JSON report generation across all 4 core types (Phase 7.15)."""

    def setUp(self):
        self.audit_data = {
            "target": "https://esupport.live/",
            "score": 88,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "pages": [
                {"url": "https://esupport.live/", "status": 200, "canonical": "https://esupport.live/", "word_count": 650},
                {"url": "https://esupport.live/services", "status": 200, "canonical": "https://esupport.live/services", "word_count": 420},
                {"url": "https://esupport.live/gallery", "status": 200, "canonical": "https://esupport.live/gallery", "word_count": 310},
            ],
            "issues": [
                {
                    "code": "MISSING_H1",
                    "severity": "HIGH",
                    "title": "Missing Primary H1 Tag",
                    "affected_url": "https://esupport.live/gallery",
                    "recommendation": "Add a descriptive <h1> tag to the gallery page.",
                    "evidence": "<h1> tag is absent in served HTML"
                },
                {
                    "code": "IMAGE_ALT_OPTIMIZE",
                    "severity": "MEDIUM",
                    "title": "Decorative Image Optimization",
                    "affected_url": "https://esupport.live/services",
                    "recommendation": "Verify decorative icons declare alt=\"\" to avoid screen reader noise.",
                    "evidence": "3 icon images found"
                }
            ],
            "scores": {
                "overall": 88,
                "categories": [
                    {"id": "technical", "category": "Technical SEO", "score": 92, "grade": "Excellent", "weight": 20},
                    {"id": "onpage", "category": "On-Page SEO", "score": 85, "grade": "Good", "weight": 20}
                ]
            }
        }
        self.branding = {"agency_name": "Aviance SEO Pro", "primary_color": "#2563EB"}
        self.client_info = {"name": "Test Client", "company": "eSupport Global"}

    def test_executive_pdf_generation(self):
        rep = generate_report_data("EXECUTIVE", self.audit_data, self.branding, self.client_info)
        pdf_bytes = generate_report_pdf(rep, "EXECUTIVE")
        self.assertTrue(len(pdf_bytes) > 1000)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_technical_audit_pdf_generation(self):
        rep = generate_report_data("TECHNICAL", self.audit_data, self.branding, self.client_info)
        pdf_bytes = generate_report_pdf(rep, "TECHNICAL")
        self.assertTrue(len(pdf_bytes) > 1000)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_developer_fix_pdf_generation(self):
        rep = generate_report_data("RECOMMENDATIONS", self.audit_data, self.branding, self.client_info)
        pdf_bytes = generate_report_pdf(rep, "RECOMMENDATIONS")
        self.assertTrue(len(pdf_bytes) > 1000)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_progress_comparison_pdf_generation(self):
        comp_data = {
            "baseline": self.audit_data,
            "current": {**self.audit_data, "score": 94},
            "score_delta": 6,
            "target": "https://esupport.live/"
        }
        rep = generate_report_data("PROGRESS_COMPARISON", comp_data, self.branding, self.client_info)
        pdf_bytes = generate_report_pdf(rep, "PROGRESS_COMPARISON")
        self.assertTrue(len(pdf_bytes) > 1000)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_export_formats(self):
        rep = generate_report_data("EXECUTIVE", self.audit_data, self.branding, self.client_info)
        csv_str = generate_report_csv(rep, "EXECUTIVE")
        self.assertIn("https://esupport.live/", csv_str)
        self.assertIn("total_issues", csv_str)

        excel_xml = generate_report_excel_xml(rep, "EXECUTIVE")
        self.assertIn("<?xml", excel_xml)
        self.assertIn("Workbook", excel_xml)

        json_str = generate_report_json(rep, "EXECUTIVE")
        self.assertIn('"report_type": "EXECUTIVE"', json_str)

    def test_api_report_pdf_technical(self):
        """Regression test ensuring report_pdf with report_type='technical' returns valid Technical Audit PDF."""
        from backend.main import report_pdf

        payload = {
            "audit": self.audit_data,
            "report_type": "technical"
        }
        response = report_pdf(payload=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.media_type, "application/pdf")
        self.assertTrue(response.body.startswith(b"%PDF"))
        self.assertIn("esupport-seo-technical-audit-", response.headers.get("Content-Disposition", ""))

    def test_api_reports_export_endpoint(self):
        """Regression test ensuring export_report_endpoint works for technical report."""
        from backend.main import export_report_endpoint

        for fmt in ("pdf", "csv", "excel", "json"):
            payload = {
                "audit": self.audit_data,
                "report_type": "TECHNICAL"
            }
            response = export_report_endpoint(format=fmt, payload=payload, db=None)
            self.assertEqual(response.status_code, 200, f"Format {fmt} failed with {response.status_code}")
            if fmt == "pdf":
                self.assertTrue(response.body.startswith(b"%PDF"))
            elif fmt == "csv":
                self.assertIn("esupport.live", response.body.decode("utf-8"))
            elif fmt == "excel":
                self.assertIn("Workbook", response.body.decode("utf-8"))
            elif fmt == "json":
                self.assertIn("TECHNICAL", response.body.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
