"""Automated Test Suite: Phase 6 Professional SEO Accuracy & Verification.

Covers 20 precision scenarios:
1.  robots.txt 404/410 unrestricted crawling (PASS, not FAIL)
2.  robots.txt 5xx temporary server error (WARN)
3.  robots.txt timeout handling (UNMEASURED)
4.  XML sitemap discovered without robots.txt declaration (PASS/WARN, not FAIL)
5.  Malformed XML sitemap returning 200 with 0 URLs (FAIL)
6.  Sitemap optional lastmod timestamps (PASS per sitemaps.org)
7.  Missing self-referencing canonical tag (WARN, not critical FAIL)
8.  Broken canonical target pointing to 404 (FAIL)
9.  Title length bounds (WARN rather than hard FAIL for slight variations)
10. Zero hardcoded client strings in engine checks
11. Multiple H1 tags on HTML5 sections (WARN, not FAIL)
12. Contact and utility pages excluded from thin content penalty
13. Dynamic numeric spec contradiction detection in C06
14. Phone reachability calibrated with contact page touchpoint
15. Strict pre-release verification gate blocking exports on validation failure
16. Measurement coverage percentage correctly tracked
17. Historical audit comparison: COMPARABLE classification
18. Historical audit comparison: PARTIALLY COMPARABLE with like-for-like delta
19. Historical audit comparison: NOT COMPARABLE for mismatched targets
20. SSRF post-redirect destination re-validation
"""
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
import requests

from backend.main import (
    BlockedTargetError,
    _ssrf_response_hook,
    assert_release_gate,
    compare_audits_endpoint,
    parse_page,
)
from backend.seo_engine.checks import (
    C02,
    C03,
    C06,
    O02,
    O03,
    O09,
    R,
    T04,
    T05,
    T06,
    T07,
    T10,
    X01,
)
from backend.seo_engine.context import build_context
from backend.seo_engine.engine import run_engine
from backend.seo_engine.ruleset import check_def, load_ruleset
from tests.test_seo_engine import BASE, audit, doc, good_site, page, probes, run, chk


class TestPhase6AccuracyVerification(unittest.TestCase):

    # 1. robots.txt 404/410 unrestricted crawling
    def test_robots_404_unrestricted_crawling(self):
        ctx_mock = MagicMock()
        ctx_mock.robots = {"url": BASE + "/robots.txt", "status": 404, "found": False}
        r = R(ctx_mock, "technical", check_def("technical", "T05", "general"))
        res = T05(r)
        self.assertEqual(res.status, "PASS")
        self.assertIn("unrestricted", res.evidence["statement"].lower())

    # 2. robots.txt 5xx temporary server error
    def test_robots_5xx_temporary_server_warning(self):
        ctx_mock = MagicMock()
        ctx_mock.robots = {"url": BASE + "/robots.txt", "status": 503, "found": False}
        r = R(ctx_mock, "technical", check_def("technical", "T05", "general"))
        res = T05(r)
        self.assertEqual(res.status, "WARN")
        self.assertEqual(res.evidence["values"]["status"], 503)

    # 3. robots.txt timeout handling
    def test_robots_timeout_unmeasured(self):
        ctx_mock = MagicMock()
        ctx_mock.robots = {"url": BASE + "/robots.txt", "status": 0, "error": "timeout"}
        r = R(ctx_mock, "technical", check_def("technical", "T05", "general"))
        res = T05(r)
        self.assertEqual(res.status, "UNMEASURED")
        self.assertEqual(res.unmeasured_reason, "not_attempted:robots_timeout")

    # 4. XML sitemap discovered without robots.txt declaration
    def test_sitemap_discovered_without_robots_declaration(self):
        ctx_mock = MagicMock()
        ctx_mock.robots = {"url": BASE + "/robots.txt", "status": 200, "found": True, "sitemaps": []}
        ctx_mock.sitemap = {"detected": BASE + "/sitemap.xml", "files": [{"url": BASE + "/sitemap.xml", "status": 200}], "urls": [BASE + "/"]}
        r = R(ctx_mock, "technical", check_def("technical", "T06", "general"))
        res = T06(r)
        self.assertIn(res.status, ("PASS", "WARN"))
        self.assertNotEqual(res.status, "FAIL")

    # 5. Malformed XML sitemap returning 200 with 0 URLs
    def test_sitemap_malformed_xml_fails(self):
        ctx_mock = MagicMock()
        ctx_mock.robots = {"url": BASE + "/robots.txt", "sitemaps": [BASE + "/sitemap.xml"]}
        ctx_mock.sitemap = {"detected": "", "files": [{"url": BASE + "/sitemap.xml", "status": 200, "url_count": 0}], "urls": []}
        r = R(ctx_mock, "technical", check_def("technical", "T07", "general"))
        res = T07(r)
        self.assertEqual(res.status, "FAIL")
        self.assertIn("malformed", res.evidence["statement"].lower())

    # 6. Sitemap optional lastmod timestamps
    def test_sitemap_optional_lastmod_not_failing(self):
        ctx_mock = MagicMock()
        ctx_mock.sitemap = {"detected": BASE + "/sitemap.xml", "urls": [BASE + "/p1", BASE + "/p2"], "lastmod": {}}
        r = R(ctx_mock, "technical", check_def("technical", "T10", "general"))
        res = T10(r)
        self.assertEqual(res.status, "PASS")
        self.assertIn("optional", res.evidence["statement"].lower())

    # 7. Missing self-referencing canonical tag (WARN, not FAIL)
    def test_missing_canonical_not_critical_failure(self):
        pages = [page("/", doc(canonical=False)), page("/water-pumps-1", doc(canonical=False, url=BASE + "/water-pumps-1"))]
        p = run(audit(pages), probes=probes())
        self.assertEqual(chk(p, "T04")["status"], "WARN")
        self.assertEqual(next(i for i in p["issues"] if i["check_id"] == "T04")["severity"], "medium")

    # 8. Broken canonical target pointing to 404 (FAIL)
    def test_broken_canonical_target_critical_failure(self):
        broken_url = BASE + "/broken-canonical-target"
        pages = [
            page("/", doc(head=f'<link rel="canonical" href="{broken_url}">', canonical=False)),
            page("/broken-canonical-target", "<h1>Not Found</h1>", status=404)
        ]
        p = run(audit(pages), probes=probes())
        self.assertEqual(chk(p, "T04")["status"], "FAIL")
        self.assertEqual(next(i for i in p["issues"] if i["check_id"] == "T04")["severity"], "high")

    # 9. Title length bounds (WARN rather than hard FAIL)
    def test_title_length_bounds_warn_not_fail(self):
        # 63 characters: ideal range
        p = run(audit([page("/", doc(title="Industrial Water Pumps Manufacturer Colombo | Best Example Pumps"))]))
        self.assertIn(chk(p, "O02")["status"], ("PASS", "WARN"))

    # 10. Zero hardcoded client strings in engine checks
    def test_no_hardcoded_client_strings_in_engine(self):
        checks_src = Path("backend/seo_engine/checks.py").read_text(encoding="utf-8")
        self.assertNotIn("iyaelectricals.lk", checks_src)
        self.assertNotIn('"buy electrical items"', checks_src)
        self.assertNotIn("'buy electrical items'", checks_src)

    # 11. Multiple H1 tags on HTML5 sections (WARN, not FAIL)
    def test_multiple_h1_semantic_warning_not_failure(self):
        p = run(audit([page("/", doc(h1=("Primary Heading", "Secondary Section Heading")))]))
        self.assertEqual(chk(p, "O09")["status"], "WARN")
        self.assertNotEqual(chk(p, "O09")["status"], "FAIL")

    # 12. Contact and utility pages excluded from thin content penalty
    def test_utility_pages_excluded_from_thin_content(self):
        contact_html = "<!doctype html><html><head><title>Contact Us | Example</title></head><body><h1>Contact</h1><p>Call us at 0112345678 or visit our office.</p></body></html>"
        pages = good_site(3) + [page("/contact-us", contact_html)]
        p = run(audit(pages))
        c02_vals = chk(p, "C02")["evidence"]["values"]["word_counts"]
        # Contact page must not be penalized in C02
        self.assertNotIn(BASE + "/contact-us", c02_vals)

    # 13. Dynamic numeric spec contradiction detection in C06
    def test_numeric_spec_contradiction_detection(self):
        html = doc(title="Heavy Duty Industrial Water Pump 50W | Example Pumps",
                   desc="Heavy Duty Industrial Water Pump with 100W motor specifications.")
        p = run(audit([page("/", html)]))
        c06 = chk(p, "C06")
        self.assertEqual(c06["status"], "WARN")
        self.assertIn("discrepancies", c06["evidence"]["statement"].lower())

    # 14. Phone reachability calibrated with contact page touchpoint
    def test_phone_reachability_with_contact_page(self):
        # Site has phone on contact page and homepage
        p = run(audit(good_site(3)))
        x01 = chk(p, "X01")
        self.assertIn(x01["status"], ("PASS", "WARN"))
        self.assertNotEqual(x01["status"], "FAIL")

    # 15. Strict pre-release verification gate blocking exports on validation failure
    def test_release_gate_blocks_invalid_report_export(self):
        invalid_audit = {
            "target": "https://example.com",
            "seo_engine": {
                "ruleset_version": "1.0.0",
                "score": {"overall": 99, "weighted_sum": 50},  # Mismatch: 50 != 9900
                "categories": [
                    {"id": "technical", "name": "Technical", "weight": 100, "score": 50, "weighted_contribution": 5000}
                ],
                "checks": [],
                "issues": [],
                "issue_summary": {"critical": 0, "high": 0, "medium": 0, "low": 0}
            }
        }
        with self.assertRaises(HTTPException) as cm:
            assert_release_gate(invalid_audit)
        self.assertEqual(cm.exception.status_code, 422)
        self.assertIn("release verification gate failed", str(cm.exception.detail).lower())

    # 16. Measurement coverage percentage correctly tracked
    def test_measurement_coverage_calculated_correctly(self):
        p = run_engine(audit(good_site(2)))
        cov = p.get("measurement_coverage")
        self.assertIsNotNone(cov)
        self.assertIn("coverage_percentage", cov)
        self.assertGreater(cov["coverage_percentage"], 0.0)
        self.assertLessEqual(cov["coverage_percentage"], 100.0)

    # 17. Historical audit comparison: COMPARABLE classification
    def test_historical_audit_comparability_comparable(self):
        mock_db = MagicMock()
        a1 = MagicMock(id=1, target_url="https://example.com/", score=75.0, created_at=None,
                       result_json={"page_count": 10, "seo_engine": {"ruleset_version": "v1.0", "audit": {"vertical_profile": "general"}, "measurement_coverage": {"coverage_percentage": 95.0}}})
        a2 = MagicMock(id=2, target_url="https://example.com/", score=80.0, created_at=None,
                       result_json={"page_count": 11, "seo_engine": {"ruleset_version": "v1.0", "audit": {"vertical_profile": "general"}, "measurement_coverage": {"coverage_percentage": 96.0}}})
        mock_db.query().filter().first.side_effect = [a1, a2]

        res = compare_audits_endpoint(1, 2, db=mock_db, current_admin=MagicMock())
        self.assertEqual(res["comparability"], "COMPARABLE")
        self.assertEqual(res["score_delta"], 5.0)

    # 18. Historical audit comparison: PARTIALLY COMPARABLE with like-for-like delta
    def test_historical_audit_comparability_partially_comparable(self):
        mock_db = MagicMock()
        # Pages crawled differ by >40% (10 pages vs 25 pages)
        a1 = MagicMock(id=1, target_url="https://example.com/", score=70.0, created_at=None,
                       result_json={"page_count": 10, "seo_engine": {"ruleset_version": "v1.0", "audit": {"vertical_profile": "general"}, "measurement_coverage": {"coverage_percentage": 80.0}}})
        a2 = MagicMock(id=2, target_url="https://example.com/", score=75.0, created_at=None,
                       result_json={"page_count": 25, "seo_engine": {"ruleset_version": "v1.0", "audit": {"vertical_profile": "general"}, "measurement_coverage": {"coverage_percentage": 95.0}}})
        mock_db.query().filter().first.side_effect = [a1, a2]

        res = compare_audits_endpoint(1, 2, db=mock_db, current_admin=MagicMock())
        self.assertEqual(res["comparability"], "PARTIALLY COMPARABLE")
        self.assertIn("like_for_like_delta", res)

    # 19. Historical audit comparison: NOT COMPARABLE for mismatched targets
    def test_historical_audit_comparability_not_comparable(self):
        mock_db = MagicMock()
        a1 = MagicMock(id=1, target_url="https://example.com/", score=70.0, created_at=None,
                       result_json={"page_count": 10, "seo_engine": {"ruleset_version": "v1.0", "audit": {"vertical_profile": "general"}}})
        a2 = MagicMock(id=2, target_url="https://different-client.lk/", score=85.0, created_at=None,
                       result_json={"page_count": 10, "seo_engine": {"ruleset_version": "v1.0", "audit": {"vertical_profile": "general"}}})
        mock_db.query().filter().first.side_effect = [a1, a2]

        res = compare_audits_endpoint(1, 2, db=mock_db, current_admin=MagicMock())
        self.assertEqual(res["comparability"], "NOT COMPARABLE")
        self.assertIn("Target hosts differ", res["comparability_reasons"][0])

    # 20. SSRF post-redirect destination re-validation
    def test_ssrf_post_redirect_revalidation(self):
        resp = MagicMock(spec=requests.Response)
        resp.url = "https://public-site.com/redirect"
        resp.status_code = 302
        resp.is_redirect = True
        resp.headers = {"Location": "http://127.0.0.1:8080/internal-admin"}

        def mock_is_pub(h):
            if "127.0.0.1" in str(h) or "localhost" in str(h):
                return (False, "Loopback addresses are blocked")
            return (True, "")

        with patch("backend.main._hostname_is_public", side_effect=mock_is_pub):
            with self.assertRaises(BlockedTargetError) as cm:
                _ssrf_response_hook(resp)
            self.assertIn("Blocked unsafe redirect", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
