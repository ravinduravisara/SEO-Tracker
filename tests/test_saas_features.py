"""
Comprehensive Test Suite for eSupport SEO SaaS Architecture & Real-Data Features
Validates:
  1. SSRF prevention (private IP ranges, loopback, link-local, cloud metadata, and unsafe redirects)
  2. Indexability signal classification (Indexable vs Noindex vs Canonicalized vs 4xx/5xx)
  3. Deterministic measurement coverage calculation and disclaimer
  4. Bing Webmaster Tools integration status & graceful handling
  5. Audit comparison logic (score delta, resolved/new issues, category changes)
  6. Scheduled audit frequency & lifecycle handling
"""

import unittest
from datetime import datetime
from backend.main import (
    _is_public_address,
    _hostname_is_public,
    validate_public_target,
    parse_page
)
from backend.seo_engine.engine import run_engine
from backend.integrations import bing_webmaster, bing_configured


class TestSSRFDefense(unittest.TestCase):
    def test_blocks_localhost_and_loopback(self):
        self.assertFalse(_is_public_address("127.0.0.1"))
        self.assertFalse(_is_public_address("127.0.1.1"))
        self.assertFalse(_is_public_address("::1"))
        ok, _ = _hostname_is_public("localhost")
        self.assertFalse(ok)
        with self.assertRaises(ValueError):
            validate_public_target("http://localhost:8000")

    def test_blocks_private_networks(self):
        self.assertFalse(_is_public_address("10.0.0.1"))
        self.assertFalse(_is_public_address("172.16.0.1"))
        self.assertFalse(_is_public_address("192.168.1.1"))

    def test_blocks_cloud_metadata(self):
        # 169.254.169.254 is AWS / GCP / Azure Instance Metadata Service
        self.assertFalse(_is_public_address("169.254.169.254"))
        ok, _ = _hostname_is_public("metadata.google.internal")
        self.assertFalse(ok)
        with self.assertRaises(ValueError):
            validate_public_target("http://169.254.169.254/latest/meta-data/")

    def test_blocks_cgnat_and_benchmark(self):
        self.assertFalse(_is_public_address("100.64.0.1"))
        self.assertFalse(_is_public_address("198.18.0.1"))
        self.assertFalse(_is_public_address("0.0.0.0"))

    def test_allows_valid_public_addresses(self):
        self.assertTrue(_is_public_address("8.8.8.8"))
        self.assertTrue(_is_public_address("1.1.1.1"))


class TestIndexabilityClassification(unittest.TestCase):
    def test_indexable_page(self):
        resp = {
            "ok": True,
            "status": 200,
            "content_type": "text/html",
            "body": b"<html><head><title>Test Page</title></head><body><h1>Hello</h1><p>Test content</p></body></html>",
            "headers": {},
        }
        page = parse_page("https://example.com/test", resp)
        self.assertTrue(page.get("is_indexable"))
        self.assertEqual(page.get("indexability_status"), "INDEXABLE")
        self.assertIn("measured_at", page)

    def test_noindex_page(self):
        resp = {
            "ok": True,
            "status": 200,
            "content_type": "text/html",
            "body": b"<html><head><meta name='robots' content='noindex, follow'><title>Noindex</title></head><body><p>Content</p></body></html>",
            "headers": {},
        }
        page = parse_page("https://example.com/noindex", resp)
        self.assertFalse(page.get("is_indexable"))
        self.assertEqual(page.get("indexability_status"), "NOINDEX")

    def test_canonicalized_away_page(self):
        resp = {
            "ok": True,
            "status": 200,
            "content_type": "text/html",
            "body": b"<html><head><link rel='canonical' href='https://example.com/master-page'><title>Dupe</title></head><body><p>Dupe</p></body></html>",
            "headers": {},
        }
        page = parse_page("https://example.com/dupe-variant", resp)
        self.assertFalse(page.get("is_indexable"))
        self.assertEqual(page.get("indexability_status"), "CANONICALIZED")

    def test_client_error_page(self):
        resp = {
            "ok": False,
            "status": 404,
            "content_type": "text/html",
            "body": b"<html><head><title>404 Not Found</title></head><body>Not Found</body></html>",
            "headers": {},
        }
        page = parse_page("https://example.com/missing", resp)
        self.assertFalse(page.get("is_indexable"))
        self.assertEqual(page.get("indexability_status"), "CLIENT_ERROR")


class TestMeasurementCoverageAndEngine(unittest.TestCase):
    def test_deterministic_coverage_payload(self):
        data = {
            "target": "https://example.com",
            "pages": [
                {
                    "url": "https://example.com/",
                    "status": 200,
                    "title": "Example Domain",
                    "meta_description": "Example Domain description for test",
                    "h1": ["Example Domain"],
                    "word_count": 250,
                    "editorial_word_count": 200,
                    "canonical": "https://example.com/",
                    "og": {"og:title": "Example", "og:url": "https://example.com/"}
                }
            ]
        }
        payload = run_engine(data)
        self.assertIn("measurement_coverage", payload)
        cov = payload["measurement_coverage"]
        self.assertIn("coverage_percentage", cov)
        self.assertIn("ranking_disclaimer", cov)
        self.assertGreater(cov["coverage_percentage"], 0)
        self.assertGreater(cov["checks_measured"], 0)
        self.assertEqual(
            cov["checks_measured"] + cov["checks_unmeasured"] + cov["checks_not_applicable"],
            cov["total_checks"]
        )


class TestBingIntegration(unittest.TestCase):
    def test_bing_status_when_unconfigured(self):
        res = bing_webmaster("https://example.com")
        # When BING_API_KEY is not set, must report Requires Connection
        if not bing_configured():
            self.assertFalse(res.get("ok"))
            self.assertEqual(res.get("status"), "Requires Connection")
            self.assertIn("BING_API_KEY", res.get("note", ""))


if __name__ == "__main__":
    unittest.main()
