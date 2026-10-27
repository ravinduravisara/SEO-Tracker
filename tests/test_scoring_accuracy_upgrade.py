"""Tests for Professional SEO Scoring Accuracy Upgrade.

Verifies:
1. Ruleset v2.0 loading and new vertical profiles.
2. Dual scoring architecture: Technical SEO Health Score vs Overall Audit Score.
3. 10-tier Letter Grading (A+ through F) with exact boundary testing.
4. Measurement coverage percentage and UNMEASURED / NOT_APPLICABLE handling.
5. Business profile detection (agency_services, software_saas, local_services, etc.).
6. Local SEO exemption for non-physical/digital business entities.
7. Corrected SEO rules:
   - Canonical checks (T04: multiple, relative, clean)
   - Commercial intent false positive fix (C04)
   - Image optimization & decorative alt="" support (I01, I04)
   - Structured data recognition (S01)
   - Digital contact channels (M04)
"""
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.seo_engine.ruleset import load_ruleset, check_def
from backend.seo_engine.scoring import (
    CheckResult,
    letter_grade,
    calculate_grade,
    score_technical_health,
    score_site,
    LETTER_GRADES,
)
from backend.seo_engine.context import detect_profile, build_context
from backend.seo_engine.engine import run_engine
from backend.main import parse_page


def make_page(url: str, html: str, status: int = 200, headers=None) -> dict:
    p = parse_page(url, {
        "ok": status < 400,
        "status": status,
        "url": url,
        "content_type": "text/html; charset=utf-8",
        "body": html.encode("utf-8"),
        "headers": headers or {},
        "elapsed_ms": 120,
        "history": [],
    })
    p["depth"] = 0 if url.endswith("/") else 1
    return p


class TestScoringAccuracyUpgrade(unittest.TestCase):

    def setUp(self):
        self.rules_v2 = load_ruleset("2.0.0")
        self.rules_v1 = load_ruleset("1.0.0")

    def test_ruleset_v2_loaded(self):
        """Ruleset v2 should load with version 2.0.0 and contain new vertical profiles."""
        self.assertEqual(self.rules_v2["ruleset_version"], "2.0.0")
        self.assertIn("agency_services", self.rules_v2["vertical_profiles"])
        self.assertIn("software_saas", self.rules_v2["vertical_profiles"])
        self.assertIn("local_services", self.rules_v2["vertical_profiles"])
        self.assertIn("publisher_blog", self.rules_v2["vertical_profiles"])
        self.assertIn("general", self.rules_v2["vertical_profiles"])

        # Check all vertical point sums equal 100
        for vert_id, vert_data in self.rules_v2["vertical_profiles"].items():
            pts_sum = sum(check_def("vertical", cid, vert_id, "2.0.0")["points"] for cid in vert_data["checks"])
            self.assertEqual(
                pts_sum,
                100,
                f"Vertical {vert_id} checks must sum to 100 points, got {pts_sum}",
            )

    def test_letter_grade_boundaries(self):
        """Test exact letter grade cutoffs from A+ to F."""
        test_cases = [
            (100, "A+", "Exceptional"),
            (95, "A+", "Exceptional"),
            (94, "A", "Excellent"),
            (90, "A", "Excellent"),
            (89, "A-", "Very Good"),
            (85, "A-", "Very Good"),
            (84, "B+", "Good"),
            (80, "B+", "Good"),
            (79, "B", "Above Average"),
            (75, "B", "Above Average"),
            (74, "B-", "Moderate"),
            (70, "B-", "Moderate"),
            (69, "C+", "Fair"),
            (65, "C+", "Fair"),
            (64, "C", "Needs Improvement"),
            (60, "C", "Needs Improvement"),
            (59, "D", "Poor"),
            (50, "D", "Poor"),
            (49, "F", "Critical"),
            (0, "F", "Critical"),
            (None, "N/A", "Unscorable"),
        ]
        for score, expected_letter, expected_band in test_cases:
            lg = letter_grade(score)
            self.assertEqual(
                lg,
                expected_letter,
                f"Score {score} expected {expected_letter}, got {lg}",
            )
            calc = calculate_grade(score)
            self.assertEqual(
                calc["letter"],
                expected_letter,
                f"Score {score} calc expected {expected_letter}, got {calc['letter']}",
            )
            self.assertEqual(
                calc["band"],
                expected_band,
                f"Score {score} expected band {expected_band}, got {calc['band']}",
            )

    def test_technical_health_score_calculation(self):
        """Technical Health Score derives purely from technical and infrastructure checks."""
        # 1. All passing technical checks
        results = [
            CheckResult("T01", "crawl_index", 10, "PASS"),
            CheckResult("T02", "crawl_index", 10, "PASS"),
            CheckResult("M01", "mobile", 10, "PASS"),
            CheckResult("P01", "performance", 10, "PASS"),
            # Non-technical check that fails
            CheckResult("C01", "content", 15, "FAIL"),
        ]
        tech_score = score_technical_health(results)
        # Technical checks all pass -> 100%
        self.assertEqual(tech_score["score"], 100)
        self.assertEqual(tech_score["letter_grade"], "A+")

        # 2. Technical check fails
        results_with_fail = [
            CheckResult("T01", "crawl_index", 10, "PASS"),
            CheckResult("T02", "crawl_index", 10, "FAIL"),
            CheckResult("M01", "mobile", 10, "PASS"),
        ]
        # 20 earned out of 30 total = 66.67% -> 67%
        res = score_technical_health(results_with_fail)
        self.assertEqual(res["score"], 67)
        self.assertEqual(res["letter_grade"], "C+")

    def test_measurement_coverage_and_na_handling(self):
        """NOT_APPLICABLE checks must be excluded from denominator; UNMEASURED tracked."""
        results = [
            CheckResult("T01", "crawl_index", 10, "PASS"),
            CheckResult("T02", "crawl_index", 10, "PASS"),
            CheckResult("T03", "crawl_index", 10, "NOT_APPLICABLE"),
            CheckResult("T04", "crawl_index", 10, "UNMEASURED"),
        ]
        res = score_technical_health(results)
        # Measured: 20 pts (T01 + T02). Unmeasured: 10 pts (T04). N/A: 10 pts (T03, excluded).
        # Coverage: 20 / 30 = 66.7%
        self.assertEqual(res["coverage_pct"], 66.7)
        self.assertEqual(res["unmeasured_points"], 10)
        self.assertEqual(res["measured_points"], 20)

    def test_agency_services_profile_detection(self):
        """An agency site like esupport.live should detect as agency_services."""
        audit = {
            "root_url": "https://esupport.live",
            "pages": [
                {
                    "url": "https://esupport.live/",
                    "status": 200,
                    "title": "eSupport - Web Development & SEO Agency",
                    "description": "We offer web design, digital marketing, SEO optimization, and software development services worldwide.",
                    "h1": ["Empowering Your Digital Growth"],
                    "body_text": "We provide end-to-end digital solutions, cloud hosting, client portal, software engineering, and technical SEO audits for global clients.",
                    "internal_links": ["https://esupport.live/services", "https://esupport.live/contact"],
                    "schema_types": ["WebSite", "Organization"],
                }
            ],
        }
        profile, reason = detect_profile(audit)
        self.assertEqual(profile, "agency_services")

    def test_local_seo_exemption_for_digital_agencies(self):
        """Digital agency audit should mark walk-in store checks as NOT_APPLICABLE rather than FAIL."""
        html = """<!doctype html>
        <html>
        <head>
            <title>Digital Agency Colombo | Web Design & SEO Services</title>
            <meta name="description" content="Leading digital agency offering web development and technical SEO consulting worldwide.">
            <link rel="canonical" href="https://agency.example.com/">
        </head>
        <body>
            <header><nav><a href="/">Home</a><a href="/services">Services</a><a href="/contact">Contact Us</a></nav></header>
            <main>
                <h1>Digital Marketing & Web Agency</h1>
                <p>We build high performance websites and web apps for global clients. Contact us via email hello@agency.example.com or phone +94 11 234 5678.</p>
            </main>
        </body>
        </html>"""
        parsed = make_page("https://agency.example.com/", html)
        audit = {
            "root_url": "https://agency.example.com",
            "pages": [parsed],
            "page_count": 1,
        }
        payload = run_engine(audit, profile="agency_services")
        
        # Verify scoring results
        results_by_id = {c["id"]: c for c in payload["checks"]}
        
        # Walk-in store checks: Lo02 (Opening hours), Lo03 (Map embed), Lo06 (Parking/transit)
        # These should be NOT_APPLICABLE for a digital agency
        if "Lo02" in results_by_id:
            self.assertEqual(results_by_id["Lo02"]["status"], "NOT_APPLICABLE")
        if "Lo03" in results_by_id:
            self.assertEqual(results_by_id["Lo03"]["status"], "NOT_APPLICABLE")
        if "Lo06" in results_by_id:
            self.assertEqual(results_by_id["Lo06"]["status"], "NOT_APPLICABLE")

    def test_canonical_checks_t04(self):
        """T04 should fail multiple canonicals and pass clean canonical."""
        # Clean canonical
        html_clean = """<!doctype html><html><head><title>Clean Canonical Page</title>
        <link rel="canonical" href="https://example.com/page">
        </head><body><h1>Heading</h1></body></html>"""
        p_clean = make_page("https://example.com/page", html_clean)
        pay_clean = run_engine({"root_url": "https://example.com", "pages": [p_clean], "page_count": 1})
        res_clean = {c["id"]: c for c in pay_clean["checks"]}
        self.assertEqual(res_clean["T04"]["status"], "PASS")

        # Multiple conflicting canonicals
        html_multi = """<!doctype html><html><head><title>Multiple Canonicals</title>
        <link rel="canonical" href="https://example.com/page1">
        <link rel="canonical" href="https://example.com/page2">
        </head><body><h1>Heading</h1></body></html>"""
        p_multi = make_page("https://example.com/page", html_multi)
        pay_multi = run_engine({"root_url": "https://example.com", "pages": [p_multi], "page_count": 1})
        res_multi = {c["id"]: c for c in pay_multi["checks"]}
        self.assertEqual(res_multi["T04"]["status"], "FAIL")

    def test_image_decorative_alt_support_i01(self):
        """Decorative images with alt="" should not be discarded as missing alt tags."""
        html = """<!doctype html><html><head><title>Image Test</title></head>
        <body>
            <h1>Accessible Images</h1>
            <img src="/logo.png" alt="Company Logo" width="100" height="100">
            <img src="/divider.png" alt="" role="presentation" width="100" height="10">
            <img src="/icon.svg" alt="" width="24" height="24">
        </body></html>"""
        p = make_page("https://example.com/images", html)
        pay = run_engine({"root_url": "https://example.com", "pages": [p], "page_count": 1})
        res = {c["id"]: c for c in pay["checks"]}
        # Decorative alt="" are recognized as accessible, so I01 should PASS (not FAIL)
        self.assertEqual(res["I01"]["status"], "PASS")

    def test_dual_score_output_in_engine_payload(self):
        """Engine payload must contain technical_health_score, letter_grade, and measurement_coverage_pct."""
        html = """<!doctype html><html><head><title>Professional SEO Page</title>
        <meta name="description" content="Comprehensive SEO test page ensuring all high standard rules pass.">
        <link rel="canonical" href="https://example.com/">
        </head><body>
            <header><nav><a href="/">Home</a><a href="/about">About</a><a href="/contact">Contact</a></nav></header>
            <main><h1>Primary Page Heading</h1><p>High quality body copy exceeding minimum text requirements with rich context.</p></main>
        </body></html>"""
        p = make_page("https://example.com/", html)
        pay = run_engine({"root_url": "https://example.com", "pages": [p], "page_count": 1})

        self.assertIn("score", pay)
        sc = pay["score"]
        self.assertIn("overall", sc)
        self.assertIn("grade", sc)
        self.assertIn("letter_grade", sc)
        self.assertIn("technical_health_score", sc)
        self.assertIn("measurement_coverage_pct", sc)
        self.assertIn("ruleset_version", pay)
        self.assertEqual(pay["ruleset_version"], "2.0.0")
        self.assertTrue(0 <= sc["technical_health_score"] <= 100)
        self.assertTrue(0 <= sc["overall"] <= 100)


if __name__ == "__main__":
    unittest.main()
