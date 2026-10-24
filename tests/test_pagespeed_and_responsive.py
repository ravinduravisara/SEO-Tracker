import unittest
from pathlib import Path
from backend import integrations
from backend.main import get_dashboard_stats
from backend.database import SessionLocal, AdminUser


class TestPageSpeedAndResponsive(unittest.TestCase):
    def test_pagespeed_configured_and_status(self):
        self.assertTrue(integrations.pagespeed_configured())
        status = integrations.status()
        self.assertIn("pagespeed", status)
        self.assertTrue(status["pagespeed"]["configured"])
        self.assertIn(status["pagespeed"]["mode"], ("api", "local_lighthouse", "api_public"))

    def test_dashboard_stats_reports_pagespeed_connected(self):
        db = SessionLocal()
        admin = db.query(AdminUser).first()
        stats = get_dashboard_stats(current_admin=admin)
        data_sources = stats.get("data_sources", {})
        self.assertTrue(data_sources.get("pagespeed"))
        self.assertIn("pagespeed_mode", data_sources)

    def test_responsive_css_and_profile_grid(self):
        root = Path(__file__).resolve().parents[1]
        css = (root / "frontend" / "style.css").read_text(encoding="utf-8")
        html = (root / "frontend" / "index.html").read_text(encoding="utf-8")

        # Verify profile grid class exists and responsive rules are present
        self.assertIn("profile-grid", html)
        self.assertIn(".profile-grid", css)
        self.assertIn("grid-template-columns: 1fr !important", css)
        self.assertIn("#viewProfile .card", css)
        self.assertIn("style.css?v=10.4.", html)


if __name__ == "__main__":
    unittest.main()

