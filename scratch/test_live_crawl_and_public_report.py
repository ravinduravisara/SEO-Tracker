"""
Live Crawl & Public Report Verification Test
Triggers real crawler engine against https://example.com, waits for completion,
generates public report, and validates client page.
"""

import os
import sys
import time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASE_URL = "http://127.0.0.1:8000"

def test_live():
    # 1. Admin login
    session = requests.Session()
    login_resp = session.post(f"{BASE_URL}/api/admin/login", json={"email": "prasad@esupport.live", "password": "eSupport@SEO2026!Admin"})
    assert login_resp.status_code == 200
    session.headers.update({"X-CSRF-Token": login_resp.json().get("csrf_token")})

    # 2. Start Live Audit
    start_resp = session.post(f"{BASE_URL}/api/audit/start", json={
        "url": "https://example.com",
        "max_pages": 10,
        "respect_robots": True,
        "check_links": True,
        "check_resources": True
    })
    assert start_resp.status_code == 200
    job_id = start_resp.json()["job_id"]
    print(f"Live audit started with job_id: {job_id}")

    # 3. Poll until completed
    max_wait = 30
    start_time = time.time()
    audit_result = None
    while time.time() - start_time < max_wait:
        st_resp = session.get(f"{BASE_URL}/api/audit/status/{job_id}")
        assert st_resp.status_code == 200
        st_data = st_resp.json()
        print(f"Audit state: {st_data['state']} | Phase: {st_data.get('progress', {}).get('phase')}")
        if st_data["state"] == "completed":
            audit_result = st_data["result"]
            break
        elif st_data["state"] in ("failed", "cancelled"):
            raise RuntimeError(f"Audit failed: {st_data.get('error')}")
        time.sleep(2)

    assert audit_result is not None, "Audit timed out"
    score = audit_result.get("score")
    print(f"Audit completed! Real calculated score: {score}")

    # 4. Save audit
    save_resp = session.post(f"{BASE_URL}/api/audits/save", json={
        "audit_result": audit_result,
        "score": score,
        "target_url": "https://example.com",
        "job_id": job_id
    })
    assert save_resp.status_code == 200
    audit_id = save_resp.json()["audit_id"]

    # 5. Generate public report
    rep_resp = session.post(f"{BASE_URL}/api/reports/generate", json={
        "audit_id": audit_id,
        "status": "PUBLISHED"
    })
    assert rep_resp.status_code == 200
    token = rep_resp.json()["token"]
    print(f"Public report generated with token: {token}")

    # 6. Verify public access in fresh unauthenticated session
    clean = requests.Session()
    pub_resp = clean.get(f"{BASE_URL}/api/public/reports/{token}")
    assert pub_resp.status_code == 200
    snapshot = pub_resp.json()["data"]
    assert snapshot["score"] == score
    assert len(snapshot["categories"]) == 8
    print("Snapshot successfully loaded with real crawler data!")
    print("Hero score:", snapshot["score"])
    print("Status headline:", snapshot["score_status"]["headline"])
    print("Passed checks:", snapshot["summary"]["passed_checks"])
    print("WhatsApp link:", snapshot["cta"]["whatsapp_url"][:60] + "...")
    print("Email link:", snapshot["cta"]["email_url"][:60] + "...")

    # 7. Check HTML rendering
    html_resp = clean.get(f"{BASE_URL}/report/{token}")
    assert html_resp.status_code == 200
    assert "YOUR SEO SCORE" in html_resp.text
    print("ALL LIVE CRAWLER & PUBLIC REPORT VERIFICATION PASSED!")

if __name__ == "__main__":
    test_live()
