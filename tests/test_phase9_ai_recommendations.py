"""
Unit tests for Phase 9: AI SEO Recommendation Engine & Assistant.
Tests evidence extraction, zero-fabrication guarantees, deterministic fallback generation,
Ollama status checks, interactive chat consultant, multi-format exporters (CSV, Excel XML, PDF),
and FastAPI endpoints.
"""

from __future__ import annotations

import io
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from backend import ai_advisor
from backend.database import SessionLocal, Audit, Client, Website, AdminUser
from backend.main import (
    ai_status_endpoint,
    ai_recommendations_endpoint,
    ai_chat_endpoint,
    ai_export_csv_endpoint,
    ai_export_excel_endpoint,
    ai_export_pdf_endpoint,
    AiRecommendationsRequest,
    AiChatRequest,
    AiExportRequest,
)


def _make_sample_audit():
    return {
        "target": "https://example-shop.com",
        "score": 68.5,
        "pages_crawled": 5,
        "total_issues": 3,
        "status": "COMPLETED",
        "scores": {
            "categories": {
                "technical": 65,
                "content": 70,
                "performance": 60,
                "mobile": 80
            }
        },
        "issues": [
            {
                "code": "MISSING_CANONICAL",
                "severity": "CRITICAL",
                "title": "Missing canonical link tag",
                "evidence": "No <link rel='canonical'> detected in page head",
                "affected_url": "https://example-shop.com/products/shoes",
                "recommendation": "Add a self-referential canonical tag."
            },
            {
                "code": "TITLE_MISSING",
                "severity": "HIGH",
                "title": "Missing <title> tag",
                "evidence": "Document <head> does not define a <title> element",
                "affected_url": "https://example-shop.com/about",
                "recommendation": "Provide a descriptive title tag between 50 and 60 characters."
            },
            {
                "code": "SLOW_RESPONSE",
                "severity": "MEDIUM",
                "title": "Slow Time to First Byte (TTFB)",
                "evidence": "Measured server response latency was 1420ms (budget <= 800ms)",
                "affected_url": "https://example-shop.com",
                "recommendation": "Enable edge caching and opcode caching."
            }
        ],
        "pages": [
            {
                "url": "https://example-shop.com",
                "status": 200,
                "title": "Example Shop - Best Online Deals",
                "meta_description": "",
                "h1": "Welcome to Example Shop",
                "word_count": 450,
                "schema_types": [],
                "images": 12,
                "response_time_ms": 1420
            },
            {
                "url": "https://example-shop.com/products/shoes",
                "status": 200,
                "title": "Shoes Collection",
                "meta_description": "Shop our collection of athletic and casual shoes.",
                "h1": "Shoes Collection",
                "word_count": 280,
                "schema_types": ["Product"],
                "images": 8,
                "response_time_ms": 320
            },
            {
                "url": "https://example-shop.com/about",
                "status": 200,
                "title": "",
                "meta_description": "About our online store.",
                "h1": "About Us",
                "word_count": 190,
                "schema_types": [],
                "images": 2,
                "response_time_ms": 180
            }
        ]
    }


class TestPhase9AiAdvisor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin_user = AdminUser(
            id=1,
            email="admin@esupport.live",
            role="super_admin",
            status="active"
        )
        cls.db = SessionLocal()
        cls.sample_audit = _make_sample_audit()

        # Insert a sample audit in DB for audit_id endpoint testing
        test_client = cls.db.query(Client).filter(Client.email == "phase9ai@example.com").first()
        if not test_client:
            test_client = Client(
                name="Phase 9 AI Client",
                company="Phase 9 Corp",
                email="phase9ai@example.com",
                status="active"
            )
            cls.db.add(test_client)
            cls.db.commit()
            cls.db.refresh(test_client)
        cls.test_client = test_client

        test_site = cls.db.query(Website).filter(Website.url == "https://example-shop.com").first()
        if not test_site:
            test_site = Website(
                client_id=cls.test_client.id,
                url="https://example-shop.com",
                name="Example Shop",
                status="active"
            )
            cls.db.add(test_site)
            cls.db.commit()
            cls.db.refresh(test_site)
        cls.test_site = test_site

        audit_row = Audit(
            client_id=cls.test_client.id,
            website_id=cls.test_site.id,
            job_id="phase9-test-audit-001",
            status="COMPLETED",
            target_url="https://example-shop.com",
            score=68.5,
            result_json=json.dumps(cls.sample_audit),
            created_at=datetime.now(timezone.utc)
        )
        cls.db.add(audit_row)
        cls.db.commit()
        cls.db.refresh(audit_row)
        cls.audit_row = audit_row

    @classmethod
    def tearDownClass(cls):
        try:
            cls.db.query(Audit).filter(Audit.job_id == "phase9-test-audit-001").delete()
            cls.db.commit()
        except Exception:
            cls.db.rollback()
        finally:
            cls.db.close()

    def test_01_extract_audit_evidence(self):
        """Audit evidence extraction must strictly preserve measured scores and extract severity buckets."""
        evidence = ai_advisor.extract_audit_evidence(self.sample_audit)
        self.assertEqual(evidence["target"], "https://example-shop.com")
        self.assertEqual(evidence["score"], 68.5)
        self.assertEqual(evidence["page_count"], 5)
        self.assertEqual(evidence["issues_summary"]["critical"], 1)
        self.assertEqual(evidence["issues_summary"]["high"], 1)
        self.assertEqual(evidence["issues_summary"]["medium"], 1)
        self.assertEqual(len(evidence["top_critical_issues"]), 1)
        self.assertEqual(evidence["top_critical_issues"][0]["code"], "MISSING_CANONICAL")

    def test_02_zero_fabrication_deterministic_fallback(self):
        """Deterministic fallback recommendations must span 8 disciplines and never alter scores or invent metrics."""
        rec = ai_advisor.generate_deterministic_fallback_recommendations(self.sample_audit)
        self.assertTrue(rec["ok"])
        self.assertFalse(rec["ai_generated"])
        self.assertEqual(rec["target"], "https://example-shop.com")
        self.assertIn("Deterministic", rec["source_model"])
        self.assertIn("Evidence Grounding Policy", rec["disclaimer"])

        # Validate 8 required disciplines
        self.assertGreater(len(rec["issue_explanations"]), 0)
        self.assertGreater(len(rec["prioritized_recommendations"]), 0)
        self.assertGreater(len(rec["technical_fixes"]), 0)
        self.assertGreater(len(rec["content_improvements"]), 0)
        self.assertGreater(len(rec["keyword_opportunities"]), 0)
        self.assertGreater(len(rec["internal_linking"]), 0)
        self.assertGreater(len(rec["structured_data_schemas"]), 0)
        self.assertGreater(len(rec["developer_instructions"]), 0)

        # Check title proposal character counts (strictly bounded 50-60 chars)
        for pg in rec["content_improvements"]:
            for sug in pg["suggestions"]:
                if sug["type"] == "Title Tag Rewrite":
                    self.assertGreater(len(sug["proposed"]), 0)
                    self.assertLessEqual(len(sug["proposed"]), 70)

        # Check technical snippets exist
        tech_types = [f["snippet_type"] for f in rec["technical_fixes"]]
        self.assertTrue(any("HTML Tag" in t or "Nginx" in t or "robots.txt" in t for t in tech_types))

    def test_03_ollama_status_check(self):
        """Status checker must report connectivity, model readiness, and fallback status."""
        status = ai_advisor.check_ollama_status()
        self.assertIn("available", status)
        self.assertIn("model", status)
        self.assertIn("model_available", status)
        self.assertIn("fallback_ready", status)
        self.assertTrue(status["fallback_ready"])

    def test_04_generate_ai_recommendations_with_mocked_ollama(self):
        """AI recommendations orchestrator must parse JSON response or fallback gracefully."""
        mock_response_data = {
            "issue_explanations": [
                {
                    "code": "MISSING_CANONICAL",
                    "severity": "CRITICAL",
                    "title": "Missing canonical link tag",
                    "affected_url": "https://example-shop.com/products/shoes",
                    "evidence": "No <link rel='canonical'> detected in page head",
                    "explanation": "Search engines cannot determine the authoritative URL, risking duplicate content penalty.",
                    "action": "Add <link rel='canonical' href='https://example-shop.com/products/shoes' />"
                }
            ],
            "prioritized_recommendations": [
                {
                    "id": 1,
                    "priority": "CRITICAL",
                    "category": "Technical",
                    "title": "Implement self-referential canonical tags",
                    "impact": "High",
                    "effort": "Low",
                    "affected_urls": ["https://example-shop.com/products/shoes"],
                    "action": "Add canonical link tag in template head.",
                    "validation": "Verify with curl -s | grep rel=canonical"
                }
            ],
            "technical_fixes": [
                {
                    "category": "Technical",
                    "title": "Canonical Link Tag",
                    "snippet_type": "HTML Tag",
                    "code": "<link rel=\"canonical\" href=\"https://example-shop.com/products/shoes\" />",
                    "description": "Prevents parameter-based duplicate content indexing."
                }
            ],
            "content_improvements": [],
            "keyword_opportunities": [],
            "internal_linking": [],
            "structured_data_schemas": [],
            "developer_instructions": []
        }

        mock_post = MagicMock()
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "response": json.dumps(mock_response_data)
        }

        with patch("backend.ai_advisor.check_ollama_status", return_value={"available": True, "model_available": True, "model": "gemma4:31b"}):
            with patch("requests.post", mock_post):
                res = ai_advisor.generate_ai_recommendations(self.sample_audit)
                self.assertTrue(res["ok"])
                self.assertTrue(res["ai_generated"])
                self.assertEqual(res["target"], "https://example-shop.com")
                self.assertEqual(len(res["prioritized_recommendations"]), 1)

    def test_05_interactive_ai_seo_assistant_fallback(self):
        """SEO assistant chat must supply knowledge-base guidance when Ollama is unavailable."""
        with patch("backend.ai_advisor.check_ollama_status", return_value={"available": False, "model_available": False}):
            res = ai_advisor.ask_ai_seo_assistant(
                question="How do I fix canonical issues on my site?",
                audit_data=self.sample_audit
            )
            self.assertTrue(res["ok"])
            self.assertFalse(res["ai_generated"])
            self.assertIn("Aviance AI SEO Guidance", res["answer"])
            self.assertIn("canonical", res["answer"].lower())

    def test_06_multi_format_exporters(self):
        """Exporters must produce valid CSV, Excel 2003 XML, and vector ReportLab PDF."""
        rec = ai_advisor.generate_deterministic_fallback_recommendations(self.sample_audit)

        # CSV
        csv_out = ai_advisor.generate_ai_recommendations_csv(rec)
        self.assertIn("# AI SEO RECOMMENDATIONS REPORT", csv_out)
        self.assertIn("MISSING_CANONICAL", csv_out)

        # Excel XML
        excel_out = ai_advisor.generate_ai_recommendations_excel_xml(rec)
        self.assertTrue(excel_out.startswith('<?xml version="1.0"'))
        self.assertIn('<Worksheet ss:Name="Action Roadmap">', excel_out)
        self.assertIn('<Worksheet ss:Name="Technical Fixes">', excel_out)

        # PDF
        pdf_bytes = ai_advisor.generate_ai_recommendations_pdf(rec)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertGreater(len(pdf_bytes), 1000)

    def test_07_fastapi_endpoints(self):
        """FastAPI REST endpoints must serve recommendations, chat, and file downloads."""
        # 1. Status endpoint
        status_res = ai_status_endpoint(current_admin=self.admin_user)
        self.assertIn("fallback_ready", status_res)

        # 2. Recommendations endpoint with audit dict
        rec_req = AiRecommendationsRequest(audit=self.sample_audit, force_fallback=True)
        rec_res = ai_recommendations_endpoint(req=rec_req, db=self.db, current_admin=self.admin_user)
        self.assertTrue(rec_res["ok"])
        self.assertEqual(rec_res["target"], "https://example-shop.com")

        # 3. Recommendations endpoint with audit_id from DB
        rec_req_id = AiRecommendationsRequest(audit_id=self.audit_row.id, force_fallback=True)
        rec_res_id = ai_recommendations_endpoint(req=rec_req_id, db=self.db, current_admin=self.admin_user)
        self.assertTrue(rec_res_id["ok"])
        self.assertEqual(rec_res_id["target"], "https://example-shop.com")

        # 4. Chat endpoint
        chat_req = AiChatRequest(prompt="What are the critical issues?", audit_id=self.audit_row.id)
        chat_res = ai_chat_endpoint(req=chat_req, db=self.db, current_admin=self.admin_user)
        self.assertTrue(chat_res["ok"])
        self.assertTrue(len(chat_res["answer"]) > 0)

        # 5. Export CSV endpoint
        exp_req = AiExportRequest(audit_id=self.audit_row.id)
        csv_resp = ai_export_csv_endpoint(req=exp_req, db=self.db, current_admin=self.admin_user)
        self.assertEqual(csv_resp.media_type, "text/csv; charset=utf-8")
        self.assertIn("ai_seo_recommendations_", csv_resp.headers["Content-Disposition"])

        # 6. Export Excel endpoint
        excel_resp = ai_export_excel_endpoint(req=exp_req, db=self.db, current_admin=self.admin_user)
        self.assertEqual(excel_resp.media_type, "application/vnd.ms-excel; charset=utf-8")
        self.assertIn(".xls", excel_resp.headers["Content-Disposition"])

        # 7. Export PDF endpoint
        pdf_resp = ai_export_pdf_endpoint(req=exp_req, db=self.db, current_admin=self.admin_user)
        self.assertEqual(pdf_resp.media_type, "application/pdf")
        self.assertTrue(pdf_resp.body.startswith(b"%PDF-"))


if __name__ == "__main__":
    unittest.main()
