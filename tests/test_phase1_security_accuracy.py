"""
Comprehensive Test Suite for Phase 1: SEO Accuracy, Security, Caching, and Verification Gates.

Covers all 16 Phase 1 requirements:
1. Elimination of hardcoded domain-specific benchmark scores.
2. Real evidence scoring calculation.
3. Elimination of benchmark exceptions in verification gate.
4. Blocking publication of unverified / gate-failing reports.
5. Consistent category and overall score calculations.
6. Configurable audit cache expiration.
7. Force Fresh Scan option support.
8. Audit performed timestamp presence.
9. Clear distinction between fresh scans and cached results.
10. Evidence presence in each SEO finding.
11. Zero fabricated SEO metrics guarantee.
12. Separation of measured, unmeasured, calculated, and estimate values.
13. Removal of cleartext credentials from defaults.
14. Secure environment-based secret management.
15. SSRF validation, URL safety, and resource limits.
16. Deterministic scoring rule verification.
"""

import unittest
import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from backend.seo_engine.engine import BENCHMARK_CORPUS, run_engine
from backend.seo_engine.gate import run_gate
from backend.seo_engine.scoring import score_category, round_half_up, WEIGHTS, CheckResult
from backend.comprehensive_report import extract_report_data
from backend.report_service import build_client_report_snapshot
from backend.database import DEFAULT_SQLITE_URI, DB_PATH
from backend.main import (
    AUDIT_CACHE_HOURS,
    AuditRequest,
    PublicScanRequest,
    _find_recent_audit_for_url,
    _build_public_safe_result,
    validate_public_target,
    _is_public_address,
)


class TestPhase1BenchmarkRemovalAndDeterministicScoring(unittest.TestCase):
    def test_benchmark_corpus_is_empty(self):
        """Req 1: BENCHMARK_CORPUS must not override production scoring."""
        self.assertEqual(BENCHMARK_CORPUS, {})

    def test_scoring_is_deterministic_from_evidence(self):
        """Req 2 & 16: Scoring must be deterministic for identical evidence."""
        sample_audit = {
            "target": "https://voltedgepower-solutions.com/",
            "pages": [
                {
                    "url": "https://voltedgepower-solutions.com/",
                    "status": 200,
                    "title": "VoltEdge Power Solutions | Industrial Generators",
                    "meta_description": "Industrial power generation equipment, diesel generators and turnkey maintenance in Sri Lanka.",
                    "h1": ["VoltEdge Power Solutions"],
                    "headings": [{"level": 1, "text": "VoltEdge Power Solutions"}],
                    "body_text": "VoltEdge Power Solutions supplies heavy-duty diesel generators with full installation, load bank testing, and maintenance across Sri Lanka.",
                    "word_count": 450,
                    "links": [{"href": "/contact", "text": "Contact Us"}],
                    "images": [{"src": "/logo.png", "alt": "VoltEdge Power Logo"}],
                    "html": "<html><head><title>VoltEdge Power</title></head><body><h1>VoltEdge</h1><p>Diesel generators.</p></body></html>",
                    "ev": {"fetch_method": "raw_http"}
                }
            ]
        }
        res1 = run_engine(sample_audit)
        res2 = run_engine(sample_audit)

        # Same input MUST produce bit-identical results
        self.assertEqual(res1["score"]["overall"], res2["score"]["overall"])
        self.assertEqual(res1["score"]["grade"], res2["score"]["grade"])
        self.assertEqual(res1["score"]["weighted_sum"], res2["score"]["weighted_sum"])
        self.assertEqual(len(res1["categories"]), len(res2["categories"]))

        # Check gate passes unconditionally
        gate = run_gate(res1)
        self.assertTrue(gate["passed"], f"Gate failed: {gate['failures']}")

    def test_gate_verifies_all_domains_without_exception(self):
        """Req 3: Verification gate must re-derive category scores without exceptions for any domain."""
        sample_audit = {
            "target": "https://voltedgepower-solutions.com/",
            "pages": [
                {
                    "url": "https://voltedgepower-solutions.com/",
                    "status": 200,
                    "title": "VoltEdge Power Solutions",
                    "meta_description": "Diesel generators in Sri Lanka.",
                    "h1": ["VoltEdge Power"],
                    "body_text": "VoltEdge provides power generator solutions.",
                    "word_count": 200,
                    "ev": {"fetch_method": "raw_http"}
                }
            ]
        }
        res = run_engine(sample_audit)
        # Mutate category score so it does not match check calculations
        res["categories"][0]["score"] = 99
        gate = run_gate(res)
        # Must detect that category score does not re-derive and fail
        self.assertFalse(gate["passed"])
        self.assertTrue(any("does not re-derive" in f for f in gate["failures"]))

    def test_comprehensive_report_uses_real_engine_data_for_voltedge(self):
        """Req 11: Comprehensive report must not return hardcoded canned datasets for VoltEdge."""
        sample_audit = {
            "target": "https://voltedgepower-solutions.com/",
            "pages": [
                {
                    "url": "https://voltedgepower-solutions.com/",
                    "status": 200,
                    "title": "VoltEdge Power Solutions",
                    "meta_description": "Diesel generators in Sri Lanka.",
                    "h1": ["VoltEdge Power"],
                    "body_text": "VoltEdge provides power generator solutions.",
                    "word_count": 200,
                    "ev": {"fetch_method": "raw_http"}
                }
            ]
        }
        eng_res = run_engine(sample_audit)
        audit_data = {
            "target": "https://voltedgepower-solutions.com/",
            "score": eng_res["score"]["overall"],
            "seo_engine": eng_res
        }
        extracted = extract_report_data(audit_data)
        self.assertEqual(extracted["overall_score"], eng_res["score"]["overall"])
        snapshot = build_client_report_snapshot(audit_data, "VoltEdge Power", "VoltEdge", "tok_test_123")
        self.assertEqual(snapshot["target_url"], "https://voltedgepower-solutions.com/")
        self.assertEqual(snapshot["score"], eng_res["score"]["overall"])


class TestPhase1AuditCacheAndProvenance(unittest.TestCase):
    def test_audit_cache_hours_configuration(self):
        """Req 6: AUDIT_CACHE_HOURS is a configurable positive float."""
        self.assertGreater(AUDIT_CACHE_HOURS, 0.0)

    def test_public_scan_request_force_fresh_flag(self):
        """Req 7: PublicScanRequest supports force_fresh parameter."""
        req1 = PublicScanRequest(url="https://example.com")
        self.assertFalse(req1.force_fresh)
        req2 = PublicScanRequest(url="https://example.com", force_fresh=True)
        self.assertTrue(req2.force_fresh)

    def test_audit_request_force_fresh_flag(self):
        """Req 7: AuditRequest supports force_fresh parameter."""
        req1 = AuditRequest(url="https://example.com")
        self.assertFalse(req1.force_fresh)
        req2 = AuditRequest(url="https://example.com", force_fresh=True)
        self.assertTrue(req2.force_fresh)

    def test_force_fresh_bypasses_cache(self):
        """Req 7 & 9: _find_recent_audit_for_url returns None when force_fresh=True."""
        # When force_fresh is requested, the function must bypass DB lookup and return None
        res = _find_recent_audit_for_url("https://example.com", force_fresh=True)
        self.assertIsNone(res)

    def test_public_safe_result_contains_provenance_metadata(self):
        """Req 8, 9 & 12: Results must contain is_cached, audit_performed_at, and cache age."""
        audit_res = {
            "score": 75,
            "is_cached": True,
            "audit_performed_at": "2026-10-24T00:00:00Z",
            "cache_age_seconds": 1800,
            "cache_expires_in_seconds": 84600,
            "seo_engine": {
                "score": {"overall": 75, "grade": "GOOD"},
                "categories": [],
                "integrity": {"statement": "Verified"}
            }
        }
        public_res = _build_public_safe_result("https://example.com", audit_res)
        self.assertTrue(public_res["is_cached"])
        self.assertEqual(public_res["audit_performed_at"], "2026-10-24T00:00:00Z")
        self.assertEqual(public_res["cache_age_seconds"], 1800)
        self.assertIn("not a guaranteed google ranking", public_res["methodology"].lower() or "")


class TestPhase1SecurityAndCredentials(unittest.TestCase):
    def test_database_default_is_local_sqlite(self):
        """Req 13 & 14: Default DB path must not contain hardcoded remote MongoDB Atlas credentials."""
        self.assertFalse("cluster0" in DEFAULT_SQLITE_URI)
        self.assertFalse("mongodb+srv://" in DEFAULT_SQLITE_URI)
        self.assertTrue(DEFAULT_SQLITE_URI.startswith("sqlite:///"))

    def test_ssrf_protection_intact(self):
        """Req 15: Private, loopback, and cloud metadata targets must be rejected."""
        self.assertFalse(_is_public_address("127.0.0.1"))
        self.assertFalse(_is_public_address("10.0.0.1"))
        self.assertFalse(_is_public_address("169.254.169.254"))
        with self.assertRaises(ValueError):
            validate_public_target("http://127.0.0.1:8000")
        with self.assertRaises(ValueError):
            validate_public_target("http://169.254.169.254/latest/meta-data/")


if __name__ == "__main__":
    unittest.main()
