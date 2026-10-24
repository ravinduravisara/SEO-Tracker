import unittest
from unittest.mock import MagicMock
from backend import keyword_engine
from backend.database import SessionLocal, AdminUser, KeywordProject, SavedKeyword
from backend.main import (
    keyword_magic_search_endpoint,
    keyword_projects_list_endpoint,
    keyword_project_create_endpoint,
    keyword_project_detail_endpoint,
    keyword_project_add_keywords_endpoint,
    keyword_project_remove_keyword_endpoint,
    keyword_project_delete_endpoint,
    keyword_magic_export_csv_endpoint,
    keyword_magic_export_excel_endpoint,
    keyword_magic_export_pdf_endpoint,
    KeywordProjectCreateRequest,
    AddKeywordsToProjectRequest
)


class TestPhase4KeywordResearch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db = SessionLocal()
        admin = db.query(AdminUser).first()
        if not admin:
            admin = AdminUser(email="testadmin@example.com", name="Test Admin", role="SUPER_ADMIN", status="ACTIVE")
            db.add(admin)
            db.commit()
            db.refresh(admin)
        cls.mock_admin = admin
        db.close()

    def test_seed_keyword_search_and_provenance(self):
        res = keyword_engine.run_keyword_magic_research("seo tools", location_code=2840, language_code="en", limit=20)
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("seed"), "seo tools")
        self.assertIn("summary", res)
        self.assertIn("clusters", res)
        self.assertIn("keywords", res)
        self.assertIn("integrity_statement", res)
        self.assertIn("data_provider", res)
        self.assertGreater(len(res["keywords"]), 0)

        # Provenance check: If provider is not connected, search volume must be None
        if not res.get("has_live_provider"):
            for k in res["keywords"]:
                self.assertIsNone(k.get("search_volume"))
                self.assertIsNone(k.get("keyword_difficulty"))
                self.assertIn(k.get("intent"), ("Informational", "Commercial", "Transactional", "Navigational"))

    def test_match_types_and_intent_heuristics(self):
        self.assertEqual(keyword_engine.evaluate_match_type("seo tools", "seo tools"), "Exact")
        self.assertEqual(keyword_engine.evaluate_match_type("best seo tools for beginners", "seo tools"), "Phrase")
        self.assertEqual(keyword_engine.evaluate_match_type("how to choose seo tools", "seo tools"), "Questions")

        self.assertEqual(keyword_engine.classify_intent("buy seo software"), "Transactional")
        self.assertEqual(keyword_engine.classify_intent("best seo audit tools"), "Commercial")
        self.assertEqual(keyword_engine.classify_intent("how to do keyword research"), "Informational")
        self.assertEqual(keyword_engine.classify_intent("google.com"), "Navigational")

    def test_semantic_clustering(self):
        sample_kws = [
            {"keyword": "seo tools free", "intent": "Transactional"},
            {"keyword": "free seo tools online", "intent": "Transactional"},
            {"keyword": "best seo agency in new york", "intent": "Commercial"},
            {"keyword": "seo agency pricing", "intent": "Commercial"},
            {"keyword": "how to learn seo basics", "intent": "Informational"},
            {"keyword": "seo tutorial guide", "intent": "Informational"},
        ]
        clusters = keyword_engine.generate_clusters(sample_kws, "seo")
        self.assertIsInstance(clusters, list)
        self.assertGreater(len(clusters), 0)
        cluster_names = [c["name"].lower() for c in clusters]
        self.assertTrue(any("free" in c or "agency" in c or "intent" in c for c in cluster_names))

    def test_project_lifecycle_and_keyword_saving(self):
        # 1. Create project
        proj = keyword_engine.create_keyword_project("E-Commerce Target Keywords", description="Phase 4 test project")
        self.assertIn("id", proj)
        p_id = proj["id"]

        # 2. Add keywords
        add_res = keyword_engine.add_keywords_to_project(p_id, [
            {"keyword": "ecommerce seo audit", "intent": "Commercial", "cluster": "Audit"},
            {"keyword": "buy online shoes", "intent": "Transactional", "cluster": "Shop"}
        ])
        self.assertTrue(add_res.get("ok"))
        self.assertEqual(add_res.get("added_count"), 2)

        # 3. Get details
        details = keyword_engine.get_keyword_project(p_id)
        self.assertIsNotNone(details)
        self.assertEqual(len(details["keywords"]), 2)

        # 4. Remove one keyword
        kw_id = details["keywords"][0]["id"]
        rem_ok = keyword_engine.remove_keyword_from_project(p_id, kw_id)
        self.assertTrue(rem_ok)

        # 5. Delete project
        del_ok = keyword_engine.delete_keyword_project(p_id)
        self.assertTrue(del_ok)
        self.assertIsNone(keyword_engine.get_keyword_project(p_id))

    def test_export_formats(self):
        res = keyword_engine.run_keyword_magic_research("content marketing", limit=10)
        keywords = res["keywords"]
        seed = res["seed"]

        # CSV Export
        csv_data = keyword_engine.generate_keyword_csv(keywords, seed)
        self.assertTrue(csv_data.startswith("\ufeffKeyword,"))
        self.assertIn("Search Intent", csv_data)

        # Excel XML Export
        xls_data = keyword_engine.generate_keyword_excel_xml(keywords, seed, "United States")
        self.assertIn('<?xml version="1.0" encoding="UTF-8"?>', xls_data)
        self.assertIn('Worksheet ss:Name="Keyword Magic Research"', xls_data)

        # PDF Export
        pdf_bytes = keyword_engine.generate_keyword_pdf(
            keywords=keywords,
            seed=seed,
            loc_name="United States",
            lang="en",
            summary=res["summary"],
            clusters=res["clusters"],
            data_provider=res["data_provider"]
        )
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_api_endpoints_direct(self):
        # 1. Search endpoint
        search_res = keyword_magic_search_endpoint(seed="seo analysis", limit=15, current_admin=self.mock_admin)
        self.assertTrue(search_res.get("ok"))
        self.assertEqual(search_res.get("seed"), "seo analysis")

        # 2. Projects list endpoint
        projects = keyword_projects_list_endpoint(current_admin=self.mock_admin)
        self.assertIsInstance(projects, list)

        # 3. Create project via endpoint
        create_req = KeywordProjectCreateRequest(name="Endpoint Test Project", description="Testing")
        created = keyword_project_create_endpoint(req=create_req, current_admin=self.mock_admin)
        self.assertEqual(created.get("status"), "success")
        proj_id = created["project"]["id"]

        # 4. Add keywords via endpoint
        add_req = AddKeywordsToProjectRequest(keywords=[{"keyword": "seo test keyword", "intent": "Informational"}])
        add_res = keyword_project_add_keywords_endpoint(project_id=proj_id, req=add_req, current_admin=self.mock_admin)
        self.assertTrue(add_res.get("ok"))

        # 5. Get project detail endpoint
        detail = keyword_project_detail_endpoint(project_id=proj_id, current_admin=self.mock_admin)
        self.assertEqual(detail["id"], proj_id)
        self.assertEqual(len(detail["keywords"]), 1)

        # 6. Export endpoints
        csv_resp = keyword_magic_export_csv_endpoint(seed="seo analysis", current_admin=self.mock_admin)
        self.assertEqual(csv_resp.media_type, "text/csv")

        excel_resp = keyword_magic_export_excel_endpoint(seed="seo analysis", current_admin=self.mock_admin)
        self.assertEqual(excel_resp.media_type, "application/vnd.ms-excel")

        pdf_resp = keyword_magic_export_pdf_endpoint(seed="seo analysis", current_admin=self.mock_admin)
        self.assertEqual(pdf_resp.media_type, "application/pdf")

        # 7. Delete project endpoint
        del_res = keyword_project_delete_endpoint(project_id=proj_id, current_admin=self.mock_admin)
        self.assertEqual(del_res.get("status"), "success")


if __name__ == "__main__":
    unittest.main()



if __name__ == "__main__":
    unittest.main()
