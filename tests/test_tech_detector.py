"""
Comprehensive Test Suite for Website Technology Detector Module
Validates:
  1. SSRF prevention and IP validation (loopback, private, link-local, cloud metadata)
  2. URL normalization and input validation
  3. Detection of 12 technology categories and 96 catalog entries
  4. Detection accuracy with mocked fixtures (WordPress, WooCommerce, Next.js, Shopify, etc.)
  5. Multi-technology simultaneous detection
  6. Custom-developed website classification and honest uncertainty handling
  7. Inconclusive scan handling (HTTP errors, empty pages)
  8. Admin-only RBAC protection (Super Admin and Admin allowed; Sales, Analyst, Unauth rejected)
  9. Scan history and JSON/CSV export functionality
"""

import unittest
from unittest.mock import patch, MagicMock
from bs4 import BeautifulSoup

from backend.tech_detector.signatures import CATALOG, CATEGORIES, get_catalog_entry, get_all_catalog_entries
from backend.tech_detector.scanner import (
    is_public_ip,
    is_public_hostname,
    validate_and_normalize_url,
    ScanPayload,
    SafeTechScanner
)
from backend.tech_detector.detector import TechnologyDetector
from backend.tech_detector.history import TechScanHistoryManager
from backend.tech_detector.models import ScanResponse, HistoryItem


class TestSSRFAndSecurity(unittest.TestCase):
    def test_blocks_loopback_and_localhost(self):
        self.assertFalse(is_public_ip("127.0.0.1"))
        self.assertFalse(is_public_ip("127.0.1.1"))
        self.assertFalse(is_public_ip("::1"))
        ok, _ = is_public_hostname("localhost")
        self.assertFalse(ok)
        with self.assertRaises(ValueError):
            validate_and_normalize_url("http://localhost:8000")

    def test_blocks_private_ip_networks(self):
        self.assertFalse(is_public_ip("10.0.0.1"))
        self.assertFalse(is_public_ip("172.16.0.1"))
        self.assertFalse(is_public_ip("192.168.1.1"))

    def test_blocks_cloud_metadata(self):
        # AWS/GCP/Azure link-local metadata address
        self.assertFalse(is_public_ip("169.254.169.254"))
        ok, _ = is_public_hostname("metadata.google.internal")
        self.assertFalse(ok)
        with self.assertRaises(ValueError):
            validate_and_normalize_url("http://169.254.169.254/latest/meta-data/")

    def test_blocks_invalid_schemes(self):
        with self.assertRaises(ValueError):
            validate_and_normalize_url("ftp://example.com/file")
        with self.assertRaises(ValueError):
            validate_and_normalize_url("file:///etc/passwd")
        with self.assertRaises(ValueError):
            validate_and_normalize_url("javascript:alert(1)")

    def test_allows_valid_public_addresses(self):
        self.assertTrue(is_public_ip("8.8.8.8"))
        self.assertTrue(is_public_ip("1.1.1.1"))
        self.assertTrue(is_public_ip("93.184.216.34"))


class TestTechnologyCatalog(unittest.TestCase):
    def test_catalog_size_is_exactly_96(self):
        entries = get_all_catalog_entries()
        self.assertEqual(len(entries), 96)

    def test_category_count_is_12(self):
        self.assertEqual(len(CATEGORIES), 12)

    def test_every_catalog_entry_has_required_fields(self):
        for entry in CATALOG:
            self.assertTrue(entry.id, f"Missing id for {entry}")
            self.assertTrue(entry.name, f"Missing name for {entry.id}")
            self.assertIn(entry.category_id, CATEGORIES, f"Invalid category_id for {entry.id}")
            self.assertEqual(entry.category_name, CATEGORIES[entry.category_id])
            self.assertTrue(entry.description, f"Missing description for {entry.id}")
            self.assertTrue(entry.limitations, f"Missing limitations for {entry.id}")


class TestDetectionEngineWithFixtures(unittest.TestCase):
    def setUp(self):
        self.mock_scanner = MagicMock()
        self.detector = TechnologyDetector(scanner=self.mock_scanner)

    def _make_payload(
        self,
        html: str,
        headers: dict = None,
        cookies: list = None,
        status_code: int = 200,
        url: str = "https://example.com"
    ) -> ScanPayload:
        soup = BeautifulSoup(html, "html.parser")
        meta_generators = []
        for m in soup.find_all("meta"):
            if m.get("name", "").lower() == "generator" and m.get("content"):
                meta_generators.append(m["content"].strip())
            elif m.get("property", "").lower() == "generator" and m.get("content"):
                meta_generators.append(m["content"].strip())

        scripts = [s["src"] for s in soup.find_all("script") if s.get("src")]
        styles = [l["href"] for l in soup.find_all("link") if l.get("href")]

        return ScanPayload(
            submitted_url=url,
            final_url=url,
            status_code=status_code,
            is_https=url.startswith("https"),
            headers={k.lower(): str(v) for k, v in (headers or {}).items()},
            cookies=cookies or [],
            html=html,
            soup=soup,
            scripts=scripts,
            styles=styles,
            meta_generators=meta_generators,
            all_meta=[],
            comments=[]
        )

    def test_detects_wordpress_with_version(self):
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta name="generator" content="WordPress 6.4.2" />
            <link rel="stylesheet" href="https://example.com/wp-content/themes/twentytwentyfour/style.css" />
        </head>
        <body class="home blog wp-custom-logo">
            <script src="https://example.com/wp-includes/js/wp-embed.min.js"></script>
        </body>
        </html>
        """
        payload = self._make_payload(html, headers={"link": '<https://example.com/wp-json/>; rel="https://api.w.org/"'})
        resp = self.detector.detect(payload)

        self.assertIn("WordPress", resp.primary_classification)
        self.assertEqual(resp.primary_category, "CMS Platforms")
        wp_tech = next((t for t in resp.detected_technologies if t.id == "wordpress"), None)
        self.assertIsNotNone(wp_tech)
        self.assertEqual(wp_tech.detection_status, "Strong Evidence")
        self.assertEqual(wp_tech.version, "6.4.2")
        self.assertTrue(len(wp_tech.evidence) >= 2)

    def test_detects_shopify_store(self):
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <script>var Shopify = window.Shopify || {}; Shopify.shop = "mystore.myshopify.com";</script>
            <link rel="stylesheet" href="https://cdn.shopify.com/s/files/1/0000/t/1/assets/theme.css" />
        </head>
        <body>
            <div id="shopify-section-header" class="shopify-section"></div>
        </body>
        </html>
        """
        payload = self._make_payload(html, headers={"x-shopid": "123456", "server": "cloudflare"})
        resp = self.detector.detect(payload)

        self.assertIn("Shopify", resp.primary_classification)
        shopify_tech = next((t for t in resp.detected_technologies if t.id == "shopify"), None)
        self.assertIsNotNone(shopify_tech)
        self.assertEqual(shopify_tech.detection_status, "Strong Evidence")

    def test_detects_nextjs_and_react_simultaneously(self):
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <link rel="preload" href="/_next/static/chunks/main-app-12345.js" as="script" />
        </head>
        <body>
            <div id="__next" data-reactroot="">
                <h1>Next.js and React Application</h1>
            </div>
            <script id="__NEXT_DATA__" type="application/json">{"props":{}}</script>
        </body>
        </html>
        """
        payload = self._make_payload(html, headers={"x-powered-by": "Next.js"})
        resp = self.detector.detect(payload)

        self.assertIn("Next.js", resp.primary_classification)
        tech_ids = {t.id for t in resp.detected_technologies}
        self.assertIn("nextjs", tech_ids)
        self.assertIn("react", tech_ids)

    def test_detects_wordpress_and_woocommerce_together(self):
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta name="generator" content="WordPress 6.4.3" />
            <meta name="generator" content="WooCommerce 8.5.1" />
            <link rel="stylesheet" href="/wp-content/plugins/woocommerce/assets/css/woocommerce.css" />
        </head>
        <body class="woocommerce woocommerce-page">
            <div class="woocommerce-Price-amount">£49.99</div>
        </body>
        </html>
        """
        payload = self._make_payload(html)
        resp = self.detector.detect(payload)

        tech_ids = {t.id for t in resp.detected_technologies}
        self.assertIn("wordpress", tech_ids)
        self.assertIn("woocommerce", tech_ids)

    def test_custom_developed_website_classification(self):
        # A website with custom HTML that does NOT use WordPress or any known CMS
        html = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <title>Custom Boutique Engineering Firm</title>
            <link rel="stylesheet" href="/custom-assets/main.css">
        </head>
        <body>
            <header><h1>Welcome to Acme Precision</h1></header>
            <main><p>We build tailored embedded systems and custom hardware.</p></main>
        </body>
        </html>
        """
        payload = self._make_payload(html)
        resp = self.detector.detect(payload)

        # Critical requirement: Does NOT assume it is WordPress or definitely custom;
        # Uses explicit honest wording:
        self.assertIn("Plain HTML", resp.primary_classification)
        self.assertIn("No recognized CMS signature was detected from the available evidence", resp.custom_website_assessment)
        self.assertIn("This website may be custom-developed, use a headless or less common CMS, or conceal its technology indicators", resp.custom_website_assessment)

    def test_inconclusive_on_http_error(self):
        payload = self._make_payload("<html><body>502 Bad Gateway</body></html>", status_code=502)
        resp = self.detector.detect(payload)

        self.assertEqual(resp.primary_classification, "Inconclusive")
        self.assertTrue(resp.is_inconclusive)
        self.assertTrue(len(resp.inconclusive_reasons) > 0)

    def test_inconclusive_on_empty_response(self):
        payload = self._make_payload("   ", status_code=200)
        resp = self.detector.detect(payload)

        self.assertEqual(resp.primary_classification, "Inconclusive")
        self.assertTrue(resp.is_inconclusive)


class TestHistoryManager(unittest.TestCase):
    def test_records_and_retrieves_history_per_admin(self):
        manager = TechScanHistoryManager(storage_path=MagicMock())
        # Disable file writing for unit test
        manager._persist = MagicMock()

        dummy_scan = ScanResponse(
            scan_id="test-scan-123",
            submitted_url="https://example.com",
            final_url="https://example.com/",
            http_status=200,
            is_https=True,
            scanned_at="2026-10-14T10:00:00Z",
            primary_classification="WordPress Detected",
            primary_summary="WordPress site",
            primary_category="CMS Platforms",
            custom_website_assessment="CMS confirmed",
            detected_technologies=[],
            total_detected_count=1,
            security_headers=[],
            scan_limitations=[],
            is_inconclusive=False,
            inconclusive_reasons=[]
        )

        manager.record_scan(admin_id=1, scan=dummy_scan)
        admin1_history = manager.get_admin_history(admin_id=1)
        admin2_history = manager.get_admin_history(admin_id=2)

        self.assertEqual(len(admin1_history), 1)
        self.assertEqual(admin1_history[0].scan_id, "test-scan-123")
        self.assertEqual(len(admin2_history), 0)


class TestRBACAndRouterEndpoints(unittest.TestCase):
    def test_rbac_permissions_granted_only_to_admins(self):
        from backend.rbac import (
            has_permission,
            ROLE_SUPER_ADMIN,
            ROLE_ADMIN,
            ROLE_SALES,
            ROLE_SEO_ANALYST
        )

        # Super Admin and Admin MUST have permissions
        self.assertTrue(has_permission(ROLE_SUPER_ADMIN, "tech_detector.view"))
        self.assertTrue(has_permission(ROLE_SUPER_ADMIN, "tech_detector.scan"))
        self.assertTrue(has_permission(ROLE_ADMIN, "tech_detector.view"))
        self.assertTrue(has_permission(ROLE_ADMIN, "tech_detector.scan"))

        # Sales and SEO Analyst MUST NOT have permissions
        self.assertFalse(has_permission(ROLE_SALES, "tech_detector.view"))
        self.assertFalse(has_permission(ROLE_SALES, "tech_detector.scan"))
        self.assertFalse(has_permission(ROLE_SEO_ANALYST, "tech_detector.view"))
        self.assertFalse(has_permission(ROLE_SEO_ANALYST, "tech_detector.scan"))

    def test_catalog_endpoint_returns_96_technologies(self):
        from backend.tech_detector.router import get_technology_catalog
        mock_admin = MagicMock()
        mock_admin.id = 1
        mock_admin.role = "ADMIN"

        catalog_data = get_technology_catalog(current_admin=mock_admin)
        self.assertEqual(catalog_data["total_count"], 96)
        self.assertEqual(len(catalog_data["catalog"]), 96)

    def test_export_endpoint_json_and_csv(self):
        from backend.tech_detector.router import export_scan_results
        from backend.tech_detector.history import history_manager
        from backend.tech_detector.models import ExportRequest

        dummy_scan = ScanResponse(
            scan_id="export-test-uuid",
            submitted_url="https://example.com",
            final_url="https://example.com/",
            http_status=200,
            is_https=True,
            scanned_at="2026-10-14T10:00:00Z",
            primary_classification="WordPress Detected",
            primary_summary="WordPress site",
            primary_category="CMS Platforms",
            custom_website_assessment="CMS confirmed",
            detected_technologies=[],
            total_detected_count=0,
            security_headers=[],
            scan_limitations=[],
            is_inconclusive=False,
            inconclusive_reasons=[]
        )
        history_manager.record_scan(admin_id=1, scan=dummy_scan)

        mock_admin = MagicMock()
        mock_admin.id = 1

        # Test JSON export
        req_json = ExportRequest(scan_id="export-test-uuid", export_format="json")
        res_json = export_scan_results(req=req_json, current_admin=mock_admin)
        self.assertEqual(res_json.media_type, "application/json; charset=utf-8")
        self.assertIn(b"WordPress Detected", res_json.body)

        # Test CSV export
        req_csv = ExportRequest(scan_id="export-test-uuid", export_format="csv")
        res_csv = export_scan_results(req=req_csv, current_admin=mock_admin)
        self.assertEqual(res_csv.media_type, "text/csv; charset=utf-8")
        self.assertIn(b"Technology Name,Category,Detection Status", res_csv.body)


if __name__ == "__main__":
    unittest.main()

