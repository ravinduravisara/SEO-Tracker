"""
Unit tests for Phase 10: Professional Report Generation Engine.
Tests all 10 client-ready report types, agency branding customization,
progress comparison deltas, multi-format exports (PDF, Excel XML, CSV, JSON),
data provenance labeling, and FastAPI endpoints.
"""

from __future__ import annotations

import io
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from backend import reporting_engine
from backend.database import SessionLocal, Audit, Client, Website, PublicReport, AgencyBranding, AdminUser
from backend.main import (
    get_report_types_endpoint,
    get_agency_branding_endpoint,
    update_agency_branding_endpoint,
    build_report_data_endpoint,
    export_report_endpoint,
    export_public_report_endpoint,
    generate_public_report,
    ReportBuildRequest,
    ReportGenerateRequest,
    AgencyBrandingUpdateRequest,
)


def _make_sample_audit(score=72.0, target="https://pro-client.com"):
    return {
        "target": target,
        "score": score,
        "pages_crawled": 6,
        "total_issues": 4,
        "status": "COMPLETED",
        "scores": {
            "categories": {
                "technical": 75,
                "content": 70,
                "performance": 65,
                "mobile": 80
            }
        },
        "issues": [
            {
                "code": "MISSING_CANONICAL",
                "severity": "CRITICAL",
                "title": "Missing Canonical Tag",
                "evidence": "No canonical tag found in head",
                "affected_url": f"{target}/products",
                "recommendation": "Add a self-referencing canonical tag."
            },
            {
                "code": "TITLE_TOO_LONG",
                "severity": "HIGH",
                "title": "Title Tag Exceeds Recommended Length",
                "evidence": "Title length is 78 characters (recommended 50-60)",
                "affected_url": target,
                "recommendation": "Shorten title tag to between 50 and 60 characters."
            },
            {
                "code": "SLOW_RESPONSE",
                "severity": "MEDIUM",
                "title": "Slow Server Response",
                "evidence": "TTFB measured at 1350ms",
                "affected_url": target,
                "recommendation": "Implement server-side page caching."
            }
        ],
        "pages": [
            {
                "url": target,
                "status": 200,
                "title": "Pro Client - Premium Enterprise Software and Consulting Services",
                "meta_description": "We build scalable enterprise tools and digital intelligence workflows.",
                "h1": ["Enterprise Software Leaders"],
                "word_count": 820,
                "images": 14,
                "internal_links": [f"{target}/products", f"{target}/contact"],
                "canonical_url": target
            },
            {
                "url": f"{target}/products",
                "status": 200,
                "title": "Products Catalog",
                "meta_description": "Browse our software catalog.",
                "h1": ["Products Catalog"],
                "word_count": 340,
                "images": 8,
                "internal_links": [target],
                "canonical_url": ""
            },
            {
                "url": f"{target}/contact",
                "status": 200,
                "title": "Contact Us",
                "meta_description": "Get in touch with our team today.",
                "h1": ["Contact Us"],
                "word_count": 190,
                "images": 2,
                "internal_links": [target],
                "canonical_url": f"{target}/contact"
            }
        ],
        "real_data": {
            "search_console": {
                "ok": True,
                "start_date": "2026-09-25",
                "end_date": "2026-10-23",
                "totals": {"clicks": 1420, "impressions": 38400, "ctr": 0.037, "position": 14.2},
                "top_queries": [
                    {"query": "enterprise software", "clicks": 210, "impressions": 4200, "ctr": 0.05, "position": 6.4},
                    {"query": "consulting services", "clicks": 140, "impressions": 2800, "ctr": 0.05, "position": 8.1}
                ],
                "top_pages": [
                    {"page": target, "clicks": 950, "impressions": 24000}
                ]
            },
            "pagespeed": {
                "mobile": {"score": 0.74, "lcp_ms": 2800, "cls": 0.08, "ttfb_ms": 620},
                "field": {
                    "core_web_vitals_assessment": "PASSED",
                    "largest_contentful_paint_ms": 2200,
                    "cumulative_layout_shift": 0.04,
                    "interaction_to_next_paint_ms": 110
                }
            },
            "dataforseo": {
                "backlinks": {
                    "ok": True,
                    "backlinks": 1840,
                    "referring_domains": 142,
                    "dofollow_ratio": 78.4,
                    "top_anchors": [
                        {"anchor": "Pro Client", "count": 64, "percentage": "45%"},
                        {"anchor": "Visit Website", "count": 22, "percentage": "15%"}
                    ]
                },
                "ranked_keywords": {
                    "ok": True,
                    "total_count": 88,
                    "keywords": [
                        {"keyword": "enterprise tools", "intent": "Commercial", "difficulty": 42, "search_volume": 2400, "cpc": 3.80},
                        {"keyword": "cloud consulting", "intent": "Informational", "difficulty": 38, "search_volume": 1600, "cpc": 2.50}
                    ]
                }
            }
        }
    }


class TestPhase10ProfessionalReports(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin_user = AdminUser(
            id=1,
            email="admin@esupport.live",
            role="super_admin",
            status="active"
        )
        cls.db = SessionLocal()
        cls.sample_audit = _make_sample_audit(score=72.0)
        cls.baseline_audit = _make_sample_audit(score=58.0)
        # Modify baseline audit to have an additional issue and lower score
        cls.baseline_audit["issues"].append({
            "code": "MISSING_H1",
            "severity": "HIGH",
            "title": "Missing H1 Heading",
            "evidence": "No H1 detected",
            "affected_url": "https://pro-client.com",
            "recommendation": "Add a primary H1."
        })

        # DB Client & Website
        test_client = cls.db.query(Client).filter(Client.email == "phase10@example.com").first()
        if not test_client:
            test_client = Client(
                name="Phase 10 Corp",
                company="Phase 10 Holdings",
                email="phase10@example.com",
                status="active"
            )
            cls.db.add(test_client)
            cls.db.commit()
            cls.db.refresh(test_client)
        cls.test_client = test_client

        test_site = cls.db.query(Website).filter(Website.url == "https://pro-client.com").first()
        if not test_site:
            test_site = Website(
                client_id=cls.test_client.id,
                url="https://pro-client.com",
                name="Pro Client Site",
                status="active"
            )
            cls.db.add(test_site)
            cls.db.commit()
            cls.db.refresh(test_site)
        cls.test_site = test_site

        # Base and Current Audits in DB
        base_audit_row = Audit(
            client_id=cls.test_client.id,
            website_id=cls.test_site.id,
            job_id="phase10-base-audit-001",
            status="COMPLETED",
            target_url="https://pro-client.com",
            score=58.0,
            result_json=json.dumps(cls.baseline_audit),
            created_at=datetime.now(timezone.utc)
        )
        curr_audit_row = Audit(
            client_id=cls.test_client.id,
            website_id=cls.test_site.id,
            job_id="phase10-curr-audit-002",
            status="COMPLETED",
            target_url="https://pro-client.com",
            score=72.0,
            result_json=json.dumps(cls.sample_audit),
            created_at=datetime.now(timezone.utc)
        )
        cls.db.add(base_audit_row)
        cls.db.add(curr_audit_row)
        cls.db.commit()
        cls.db.refresh(base_audit_row)
        cls.db.refresh(curr_audit_row)
        cls.base_audit_row = base_audit_row
        cls.curr_audit_row = curr_audit_row

    @classmethod
    def tearDownClass(cls):
        try:
            cls.db.query(PublicReport).filter(PublicReport.audit_id.in_([cls.base_audit_row.id, cls.curr_audit_row.id])).delete(synchronize_session=False)
            cls.db.query(Audit).filter(Audit.job_id.in_(["phase10-base-audit-001", "phase10-curr-audit-002"])).delete(synchronize_session=False)
            cls.db.commit()
        except Exception:
            cls.db.rollback()
        finally:
            cls.db.close()

    def test_01_report_types_registry(self):
        """All 10 required report types must be registered with complete metadata."""
        expected_types = [
            "EXECUTIVE", "TECHNICAL", "ONPAGE", "KEYWORDS", "COMPETITORS",
            "BACKLINKS", "GSC_PERFORMANCE", "PAGESPEED", "RECOMMENDATIONS", "PROGRESS_COMPARISON"
        ]
        self.assertEqual(len(reporting_engine.REPORT_TYPES), 10)
        for r_id in expected_types:
            self.assertIn(r_id, reporting_engine.REPORT_TYPES)
            item = reporting_engine.REPORT_TYPES[r_id]
            self.assertEqual(item["id"], r_id)
            self.assertTrue(len(item["name"]) > 0)
            self.assertIn("pdf", item["supported_formats"])
            self.assertIn("excel", item["supported_formats"])
            self.assertIn("csv", item["supported_formats"])
            self.assertIn("json", item["supported_formats"])

    def test_02_agency_branding_normalization(self):
        """Branding engine must merge custom styling with defaults cleanly."""
        custom = {
            "agency_name": "Apex Search Partners",
            "primary_color": "#2563EB",
            "phone": "+1 555-9876"
        }
        b = reporting_engine.normalize_branding(custom)
        self.assertEqual(b["agency_name"], "Apex Search Partners")
        self.assertEqual(b["primary_color"], "#2563EB")
        self.assertEqual(b["phone"], "+1 555-9876")
        self.assertEqual(b["secondary_color"], "#0F172A")  # Preserved default

    def test_03_build_all_10_report_data_types(self):
        """Master dispatcher must build valid data payloads for all 10 report types without errors."""
        branding = reporting_engine.get_default_branding()
        client_info = {"name": "Phase 10 Corp", "company": "Phase 10 Holdings"}

        for rep_type in reporting_engine.REPORT_TYPES.keys():
            data = reporting_engine.generate_report_data(
                report_type=rep_type,
                audit_data=self.sample_audit,
                baseline_audit=self.baseline_audit,
                branding=branding,
                client_info=client_info
            )
            self.assertEqual(data["report_type"], rep_type)
            self.assertEqual(data["target"], "https://pro-client.com")
            self.assertIn("generated_at", data)
            self.assertIn("provenance", data)
            self.assertTrue(len(data["provenance"]) > 0)

    def test_04_progress_comparison_report_calculations(self):
        """Progress comparison must calculate accurate score delta and identify resolved vs new issues."""
        comp = reporting_engine.build_comparison_report(
            baseline_audit=self.baseline_audit,
            current_audit=self.sample_audit,
            branding=reporting_engine.get_default_branding(),
            client_info={"name": "Test Client"}
        )
        delta = comp["score_delta"]
        # Baseline was 58.0, current is 72.0 -> delta is +14.0
        self.assertEqual(delta["baseline"], 58.0)
        self.assertEqual(delta["current"], 72.0)
        self.assertEqual(delta["delta"], 14.0)
        self.assertEqual(delta["trajectory"], "SIGNIFICANT_IMPROVEMENT")

        # MISSING_H1 was present in baseline but removed in current
        prog = comp["issues_progress"]
        self.assertIn("MISSING_H1", prog["resolved_codes"])
        self.assertEqual(prog["resolved_count"], 1)

    def test_05_multi_format_exporters(self):
        """Exporters must generate valid PDF, Excel XML, CSV, and JSON representations."""
        branding = reporting_engine.get_default_branding()
        client_info = {"name": "Test Client"}
        rep_data = reporting_engine.generate_report_data(
            report_type="EXECUTIVE",
            audit_data=self.sample_audit,
            branding=branding,
            client_info=client_info
        )

        # 1. PDF
        pdf_bytes = reporting_engine.generate_report_pdf(rep_data, "EXECUTIVE")
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertGreater(len(pdf_bytes), 1500)

        # 2. Excel XML
        excel_xml = reporting_engine.generate_report_excel_xml(rep_data, "EXECUTIVE")
        self.assertTrue(excel_xml.startswith('<?xml version="1.0"'))
        self.assertIn('<Worksheet ss:Name="Overview">', excel_xml)

        # 3. CSV
        csv_text = reporting_engine.generate_report_csv(rep_data, "EXECUTIVE")
        self.assertIn("Executive SEO Performance Report", csv_text)
        self.assertIn("https://pro-client.com", csv_text)

        # 4. JSON
        json_text = reporting_engine.generate_report_json(rep_data, "EXECUTIVE")
        parsed = json.loads(json_text)
        self.assertEqual(parsed["report_type"], "EXECUTIVE")
        self.assertEqual(parsed["score"], 72.0)

    def test_06_fastapi_report_endpoints(self):
        """FastAPI REST endpoints must serve report types, branding, build, and export downloads."""
        # 1. Report types endpoint
        types_res = get_report_types_endpoint(current_admin=self.admin_user)
        self.assertEqual(len(types_res), 10)

        # 2. Agency branding GET & POST endpoints
        b_get = get_agency_branding_endpoint(db=self.db, current_admin=self.admin_user)
        self.assertIn("agency_name", b_get)

        b_update_req = AgencyBrandingUpdateRequest(agency_name="Quantum SEO Agency", primary_color="#10B981")
        b_post = update_agency_branding_endpoint(req=b_update_req, db=self.db, current_admin=self.admin_user)
        self.assertEqual(b_post["agency_name"], "Quantum SEO Agency")
        self.assertEqual(b_post["primary_color"], "#10B981")

        # 3. Report build endpoint
        build_req = ReportBuildRequest(
            report_type="TECHNICAL",
            audit_id=self.curr_audit_row.id
        )
        built_data = build_report_data_endpoint(req=build_req, db=self.db, current_admin=self.admin_user)
        self.assertEqual(built_data["report_type"], "TECHNICAL")
        self.assertIn("infrastructure", built_data)

        # 4. Report export PDF endpoint
        export_payload = {
            "report_type": "TECHNICAL",
            "audit_id": self.curr_audit_row.id
        }
        pdf_res = export_report_endpoint(format="pdf", payload=export_payload, db=self.db, current_admin=self.admin_user)
        self.assertEqual(pdf_res.media_type, "application/pdf")
        self.assertTrue(pdf_res.body.startswith(b"%PDF-"))

        # 5. Report export Excel endpoint
        xls_res = export_report_endpoint(format="excel", payload=export_payload, db=self.db, current_admin=self.admin_user)
        self.assertEqual(xls_res.media_type, "application/vnd.ms-excel; charset=utf-8")
        self.assertIn(".xls", xls_res.headers["Content-Disposition"])

        # 6. Report export CSV endpoint
        csv_res = export_report_endpoint(format="csv", payload=export_payload, db=self.db, current_admin=self.admin_user)
        self.assertEqual(csv_res.media_type, "text/csv; charset=utf-8")

        # 7. Generate public report with specialized report_type
        gen_req = ReportGenerateRequest(
            audit_id=self.curr_audit_row.id,
            report_type="ONPAGE",
            status="PUBLISHED"
        )
        gen_res = generate_public_report(req=gen_req, db=self.db, current_admin=self.admin_user)
        self.assertEqual(gen_res["status"], "success")
        self.assertIn("token", gen_res)

        # 8. Public export endpoint
        pub_pdf_res = export_public_report_endpoint(token=gen_res["token"], format="pdf", db=self.db)
        self.assertEqual(pub_pdf_res.media_type, "application/pdf")
        self.assertTrue(pub_pdf_res.body.startswith(b"%PDF-"))


if __name__ == "__main__":
    unittest.main()
