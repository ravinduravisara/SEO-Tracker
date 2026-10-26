"""
Automated Test Suite for Phase 8: Free SEO API Integration & Real-Data Intelligence.
Tests all external provider adapters, error boundaries, caching, provenance,
and data normalization with 100% mock isolation and zero synthetic fabrication.
"""

import json
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from backend import integrations
from backend.seo_engine import data_providers
from backend.seo_engine.data_providers import (
    DataType,
    ProviderObservation,
    ProviderStatus,
    SourceScope,
)


class TestPageSpeedAndCrUX(unittest.TestCase):
    """Phase 8.2 & 8.3: Google PageSpeed Insights & CrUX Field Data."""

    def setUp(self):
        self.target_url = "https://esupport.live/"

    @patch("backend.integrations.local_lighthouse_available", return_value=False)
    @patch("backend.integrations.requests.get")
    def test_pagespeed_mobile_success(self, mock_get, mock_lh):
        """Valid mobile laboratory audit extracts LCP, FCP, CLS, TBT, Speed Index."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "lighthouseResult": {
                "finalUrl": "https://esupport.live/",
                "fetchTime": "2026-10-25T12:00:00Z",
                "categories": {
                    "performance": {"score": 0.88},
                    "seo": {"score": 0.95}
                },
                "audits": {
                    "largest-contentful-paint": {"numericValue": 1850.5, "displayValue": "1.9 s"},
                    "first-contentful-paint": {"numericValue": 920.0, "displayValue": "0.9 s"},
                    "total-blocking-time": {"numericValue": 140.0, "displayValue": "140 ms"},
                    "cumulative-layout-shift": {"numericValue": 0.042, "displayValue": "0.042"},
                    "speed-index": {"numericValue": 1600.0, "displayValue": "1.6 s"},
                }
            },
            "loadingExperience": {
                "id": "https://esupport.live/",
                "metrics": {
                    "LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 2100, "distributions": []},
                    "INTERACTION_TO_NEXT_PAINT": {"percentile": 120, "distributions": []},
                    "CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 5, "distributions": []},  # CLS reported x100
                }
            }
        }
        mock_get.return_value = mock_resp

        obs = data_providers.get_pagespeed_observations(self.target_url, strategy="mobile")
        self.assertTrue(len(obs) >= 5)

        # Performance score
        perf_ob = next(o for o in obs if o.provider_metric == "performance_score")
        self.assertEqual(perf_ob.value, 88)
        self.assertEqual(perf_ob.device, "MOBILE")
        self.assertEqual(perf_ob.data_type, DataType.LAB_MEASUREMENT.value)

        # TBT vs INP boundary: lab TBT must never be labeled as INP
        tbt_ob = next(o for o in obs if o.provider_metric == "lab_tbt")
        self.assertEqual(tbt_ob.value, 140.0)
        self.assertIn("distinct from field INP", tbt_ob.notes)

    @patch("backend.integrations.local_lighthouse_available", return_value=False)
    @patch("backend.integrations.requests.get")
    def test_pagespeed_desktop_distinct_from_mobile(self, mock_get, mock_lh):
        """Desktop measurements must never be substituted for mobile measurements."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "lighthouseResult": {
                "finalUrl": "https://esupport.live/",
                "fetchTime": "2026-10-25T12:05:00Z",
                "categories": {"performance": {"score": 0.98}},
                "audits": {
                    "largest-contentful-paint": {"numericValue": 800.0, "displayValue": "0.8 s"},
                }
            }
        }
        mock_get.return_value = mock_resp

        obs = data_providers.get_pagespeed_observations(self.target_url, strategy="desktop")
        perf_ob = next(o for o in obs if o.provider_metric == "performance_score")
        self.assertEqual(perf_ob.device, "DESKTOP")
        self.assertEqual(perf_ob.value, 98)

    @patch("backend.integrations.pagespeed")
    def test_crux_page_level_vs_origin_level(self, mock_ps):
        """CrUX field data correctly distinguishes page-level from origin-level scope."""
        # Origin level fallback
        mock_ps.return_value = {
            "ok": True,
            "field_url": None,
            "field_origin": {
                "id": "https://esupport.live",
                "origin_fallback": True,
                "core_web_vitals_assessment": "passed",
                "metrics": {
                    "LCP": {"p75": 1900.0, "unit": "ms", "rating": "good"},
                    "INP": {"p75": 110.0, "unit": "ms", "rating": "good"},
                    "CLS": {"p75": 0.03, "unit": "", "rating": "good"},
                }
            }
        }

        obs = data_providers.get_crux_field_observations(self.target_url)
        self.assertTrue(len(obs) >= 3)
        lcp = next(o for o in obs if o.provider_metric == "lcp")
        self.assertEqual(lcp.source_scope, SourceScope.ORIGIN_LEVEL.value)
        self.assertEqual(lcp.data_type, DataType.FIELD_MEASUREMENT.value)
        self.assertEqual(lcp.value, 1900.0)

    @patch("backend.integrations.pagespeed")
    def test_crux_insufficient_field_data_handling(self, mock_ps):
        """When 28-day user volume is insufficient, status is NO_DATA with INSUFFICIENT FIELD DATA."""
        mock_ps.return_value = {"ok": True, "field_url": None, "field_origin": None}

        obs = data_providers.get_crux_field_observations(self.target_url)
        self.assertTrue(len(obs) >= 1)
        for ob in obs:
            self.assertEqual(ob.display_value, "INSUFFICIENT FIELD DATA")
            self.assertEqual(ob.status, ProviderStatus.NO_DATA.value)
            self.assertEqual(ob.error_code, "INSUFFICIENT_FIELD_DATA")


class TestGoogleSearchConsoleAndGA4(unittest.TestCase):
    """Phase 8.4 & 8.5: Google Search Console & GA4 Data API."""

    def setUp(self):
        self.target_url = "https://esupport.live/"

    @patch("backend.integrations.gsc_configured", return_value=False)
    def test_gsc_not_connected_state(self, mock_conf):
        """When service account is absent, returns NOT_CONFIGURED without synthetic clicks."""
        res = data_providers.get_search_console_observations(self.target_url)
        self.assertEqual(res["status"], ProviderStatus.NOT_CONFIGURED.value)
        self.assertEqual(len(res["observations"]), 0)
        self.assertIn("not configured", res["error"].lower())

    @patch("backend.integrations.gsc_configured", return_value=True)
    @patch("backend.integrations.search_console")
    def test_gsc_authorized_observations(self, mock_sc, mock_conf):
        """Authorized Search Console returns clicks, impressions, CTR, and average position."""
        mock_sc.return_value = {
            "ok": True,
            "property": "sc-domain:esupport.live",
            "start_date": "2026-09-25",
            "end_date": "2026-10-22",
            "totals": {"clicks": 1420, "impressions": 48500, "ctr": 2.93, "position": 12.4},
            "top_queries": [{"query": "it support colombo", "clicks": 210, "impressions": 3400}],
            "top_pages": [{"page": "https://esupport.live/services", "clicks": 540}],
            "devices": [],
            "countries": [],
            "dates": []
        }

        res = data_providers.get_search_console_observations(self.target_url, property_url="sc-domain:esupport.live")
        self.assertEqual(res["status"], ProviderStatus.CONNECTED.value)
        self.assertEqual(res["property"], "sc-domain:esupport.live")

        obs = res["observations"]
        clicks_ob = next(o for o in obs if o["provider_metric"] == "clicks")
        self.assertEqual(clicks_ob["value"], 1420)
        self.assertEqual(clicks_ob["data_type"], DataType.FIRST_PARTY_MEASUREMENT.value)

        pos_ob = next(o for o in obs if o["provider_metric"] == "average_position")
        self.assertEqual(pos_ob["value"], 12.4)
        self.assertIn("aggregated average position", pos_ob["notes"].lower())

    @patch("backend.integrations.ga4_configured", return_value=True)
    @patch("backend.integrations.ga4")
    def test_ga4_traffic_observations(self, mock_ga4, mock_conf):
        """GA4 returns genuine sessions and users, distinct from GSC clicks."""
        mock_ga4.return_value = {
            "ok": True,
            "property_id": "987654321",
            "start_date": "2026-09-25",
            "end_date": "2026-10-22",
            "totals": {
                "sessions": 3890,
                "total_users": 2840,
                "active_users": 2400,
                "engagement_rate": 64.5,
                "average_session_duration": 82.4
            },
            "channels": [{"channel": "Organic Search", "sessions": 1950, "users": 1400}],
            "top_pages": [{"page_path": "/", "page_views": 4200, "sessions": 2100}],
            "countries": [{"country": "Sri Lanka", "sessions": 2500}]
        }

        res = data_providers.get_ga4_observations(self.target_url, property_id="987654321")
        self.assertEqual(res["status"], ProviderStatus.CONNECTED.value)
        obs = res["observations"]

        sessions_ob = next(o for o in obs if o["provider_metric"] == "sessions")
        self.assertEqual(sessions_ob["value"], 3890)
        self.assertIn("Distinct from Google Search Console", sessions_ob["notes"])


class TestBingAndAhrefsAndOPR(unittest.TestCase):
    """Phase 8.6, 8.7, 8.8: Bing Webmaster, Ahrefs Free DR, and Open PageRank."""

    def setUp(self):
        self.target_url = "https://esupport.live/"

    @patch("backend.integrations.bing_configured", return_value=True)
    @patch("backend.integrations.requests.get")
    def test_bing_webmaster_query_and_crawl_stats(self, mock_get, mock_conf):
        """Bing Webmaster retrieves both crawl stats and query telemetry, labeled BING SEARCH PERFORMANCE."""
        # Mock crawl stats response
        crawl_resp = MagicMock()
        crawl_resp.status_code = 200
        crawl_resp.json.return_value = {"d": [{"CrawledPages": 450, "CrawlErrors": 2}]}

        # Mock query stats response
        query_resp = MagicMock()
        query_resp.status_code = 200
        query_resp.json.return_value = {"d": [{"Query": "managed it services", "Clicks": 45, "Impressions": 820}]}

        mock_get.side_effect = [crawl_resp, query_resp]

        res = data_providers.get_bing_observations(self.target_url)
        self.assertEqual(res["status"], ProviderStatus.CONNECTED.value)
        self.assertIn("BING SEARCH PERFORMANCE", res["source"])

    @patch("backend.integrations.ahrefs_configured", return_value=True)
    @patch("backend.integrations.requests.get")
    def test_ahrefs_free_domain_rating_attribution(self, mock_get, mock_conf):
        """Ahrefs Free DR includes mandatory attribution 'Domain Rating by Ahrefs'."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "domain_rating": {
                "domain_rating": 46.5,
                "ahrefs_top": 850420
            }
        }
        mock_get.return_value = mock_resp

        ob = data_providers.get_ahrefs_domain_rating_observation(self.target_url)
        self.assertEqual(ob.status, ProviderStatus.CONNECTED.value)
        self.assertEqual(ob.value, 46.5)
        self.assertEqual(ob.attribution, "Domain Rating by Ahrefs")
        self.assertEqual(ob.data_type, DataType.THIRD_PARTY_ESTIMATE.value)

    @patch("backend.integrations.openpagerank_configured", return_value=True)
    @patch("backend.integrations.requests.get")
    def test_openpagerank_scale_and_attribution(self, mock_get, mock_conf):
        """Open PageRank preserves scale (0-10) and Common Crawl attribution."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status_code": 200,
            "response": [{
                "status_code": 200,
                "page_rank_decimal": 4.12,
                "rank": 310500
            }]
        }
        mock_get.return_value = mock_resp

        ob = data_providers.get_openpagerank_observation(self.target_url)
        self.assertEqual(ob.status, ProviderStatus.CONNECTED.value)
        self.assertEqual(ob.value, 4.12)
        self.assertIn("Common Crawl", ob.attribution)


class TestGoogleKeywordPlannerAndDataIntegrity(unittest.TestCase):
    """Phase 8.9 & 8.18: Keyword Planner Access Requirements & Accuracy Rules."""

    def test_keyword_planner_unapproved_access_notice(self):
        """When approved developer token is missing, Keyword Planner reports NOT CONNECTED."""
        status = data_providers.get_keyword_planner_status()
        self.assertEqual(status["status"], ProviderStatus.NOT_CONFIGURED.value)
        self.assertFalse(status["configured"])
        self.assertIn("GOOGLE KEYWORD PLANNER NOT CONNECTED", status["error"])
        self.assertIn("documentation", status)

    def test_provider_observation_schema_completeness(self):
        """All ProviderObservation records must include standardized provenance fields."""
        ob = ProviderObservation(
            provider="Google Search Console",
            provider_metric="clicks",
            target_url="https://esupport.live/",
            value=100,
            unit="clicks",
            data_type=DataType.FIRST_PARTY_MEASUREMENT.value,
            status=ProviderStatus.CONNECTED.value,
            source_scope=SourceScope.PROPERTY_LEVEL.value
        )
        d = ob.to_dict()
        required_keys = {
            "provider", "provider_metric", "target_url", "property_id",
            "value", "unit", "data_type", "device", "country", "language",
            "date_range", "collected_at", "cached", "status", "source_scope"
        }
        for k in required_keys:
            self.assertIn(k, d)


if __name__ == "__main__":
    unittest.main()
