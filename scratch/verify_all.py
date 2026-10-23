import json
import time
import requests

BASE_URL = "http://127.0.0.1:8000"

def run_tests():
    session = requests.Session()
    print("[1] Testing Public SEO Checker UI Page (/seo-check)...")
    r = session.get(f"{BASE_URL}/seo-check")
    assert r.status_code == 200, f"Expected 200 for /seo-check, got {r.status_code}"
    html = r.text
    assert "eSupport SEO" in html, "eSupport SEO branding missing"
    assert "Check Your Website SEO Score" in html, "Hero title missing"
    assert "How It Works" in html, "Navigation missing"
    assert "Why eSupport" in html, "Navigation missing"
    assert "wa.me/94707820810" in html, "WhatsApp link missing"
    assert "admin-sidebar" not in html, "LEAK: Admin sidebar in public page!"
    assert "adminLoginForm" not in html, "LEAK: Admin login in public page!"
    print("  -> /seo-check HTML verified successfully!")

    print("\n[2] Testing Public Scan Start & Poll API...")
    scan_req = session.post(f"{BASE_URL}/api/public/scan/start", json={"url": "https://example.com"})
    assert scan_req.status_code == 200, f"Scan start failed: {scan_req.text}"
    job_data = scan_req.json()
    job_id = job_data.get("job_id")
    assert job_id, "No job_id returned"
    print(f"  -> Scan started, job_id: {job_id}")

    # Poll status
    complete = False
    for _ in range(40):
        time.sleep(1)
        st_req = session.get(f"{BASE_URL}/api/public/scan/status/{job_id}")
        assert st_req.status_code == 200
        st_data = st_req.json()
        print(f"  -> Polling: state={st_data.get('state')}, phase={st_data.get('phase')}, message={st_data.get('message')}")
        if st_data.get("phase") == "COMPLETE" or st_data.get("state") in ("completed", "COMPLETE"):
            complete = True
            break
        elif st_data.get("phase") == "FAILED" or st_data.get("state") in ("failed", "FAILED"):
            raise Exception(f"Scan failed: {st_data.get('error')}")

    assert complete, "Scan did not complete in time"
    result = st_data.get("result")
    assert result, "No result payload in completed scan"
    assert "overall_score" in result, "overall_score missing"
    assert "categories" in result, "categories missing"
    assert len(result["categories"]) == 8, f"Expected 8 categories, got {len(result['categories'])}"
    assert "cta" in result, "cta missing"
    assert "whatsapp_url" in result["cta"], "whatsapp_url missing"
    assert "email_url" in result["cta"], "email_url missing"

    # Strict public leak check
    for forbidden_key in ["pages", "crawled_urls", "issues", "recommendations", "developer_actions", "raw_crawl"]:
        assert forbidden_key not in result, f"SECURITY LEAK: Found forbidden key '{forbidden_key}' in public scan result!"
    print(f"  -> Scan completed! Overall Score: {result['overall_score']}/100. Categories: {len(result['categories'])}. Zero internal leaks.")

    print("\n[3] Testing Lead Submission API (POST /api/leads)...")
    lead_payload = {
        "name": "Jane Developer",
        "company": "Apex Dynamics Ltd",
        "email": "jane@apexdynamics.example",
        "phone": "+94 77 123 4567",
        "website": "https://example.com",
        "initial_score": result["overall_score"],
        "message": "We would like a full SEO overhaul and monthly retainer proposal."
    }
    lead_res = session.post(f"{BASE_URL}/api/leads", json=lead_payload)
    assert lead_res.status_code == 200, f"Lead submission failed: {lead_res.text}"
    lead_data = lead_res.json()
    assert lead_data.get("status") == "success"
    lead_id = lead_data.get("lead_id")
    assert lead_id, "No lead_id returned"
    print(f"  -> Lead submitted successfully! Lead ID: {lead_id}")

    print("\n[4] Testing Admin Authentication & Leads Endpoints...")
    # Admin login
    login_res = session.post(f"{BASE_URL}/api/admin/login", json={
        "email": "prasad@esupport.live",
        "password": "eSupport@SEO2026!Admin"
    })
    assert login_res.status_code == 200, f"Admin login failed: {login_res.text}"
    csrf_token = login_res.json().get("csrf_token")
    headers = {"X-CSRF-Token": csrf_token}
    print("  -> Admin logged in successfully.")

    # Get leads
    leads_list_res = session.get(f"{BASE_URL}/api/leads", headers=headers)
    assert leads_list_res.status_code == 200, f"Get leads failed: {leads_list_res.text}"
    leads = leads_list_res.json()
    assert any(l["id"] == lead_id for l in leads), f"Created lead {lead_id} not in leads list"
    print(f"  -> Found lead in leads list (Total leads: {len(leads)})")

    # Get lead detail
    detail_res = session.get(f"{BASE_URL}/api/leads/{lead_id}", headers=headers)
    assert detail_res.status_code == 200, f"Get lead detail failed: {detail_res.text}"
    detail = detail_res.json()
    assert detail["name"] == "Jane Developer"
    assert detail["company"] == "Apex Dynamics Ltd"
    assert len(detail.get("timeline", [])) >= 1, "Timeline events missing"
    print(f"  -> Lead detail retrieved with {len(detail['timeline'])} timeline events.")

    # Update lead status
    status_update_res = session.post(
        f"{BASE_URL}/api/leads/{lead_id}/status",
        json={"status": "CONTACTED", "note": "Called Jane, scheduled a review meeting."},
        headers=headers
    )
    assert status_update_res.status_code == 200, f"Status update failed: {status_update_res.text}"
    print("  -> Lead status updated to CONTACTED.")

    # Convert lead to Client & Website
    convert_res = session.post(f"{BASE_URL}/api/leads/{lead_id}/convert", headers=headers)
    assert convert_res.status_code == 200, f"Lead conversion failed: {convert_res.text}"
    conv_data = convert_res.json()
    client_id = conv_data.get("client_id")
    website_id = conv_data.get("website_id")
    assert client_id and website_id, "Conversion did not return client_id and website_id"
    print(f"  -> Lead converted successfully! Created Client #{client_id}, Website #{website_id}")

    # Check client was created in official Clients API
    client_res = session.get(f"{BASE_URL}/api/clients/{client_id}", headers=headers)
    assert client_res.status_code == 200, f"Fetching converted client failed: {client_res.text}"
    created_client = client_res.json()
    assert created_client["name"] == "Jane Developer"
    assert created_client["company"] == "Apex Dynamics Ltd"
    print("  -> Verified client exists in official eSupport Client table!")

    print("\n[5] Non-Regression Testing Existing Admin Endpoints...")
    dash_res = session.get(f"{BASE_URL}/api/dashboard/stats", headers=headers)
    assert dash_res.status_code == 200, "Dashboard stats failed"
    clients_res = session.get(f"{BASE_URL}/api/clients", headers=headers)
    assert clients_res.status_code == 200, "Clients list failed"
    audits_res = session.get(f"{BASE_URL}/api/audits", headers=headers)
    assert audits_res.status_code == 200, "Audits list failed"
    reports_res = session.get(f"{BASE_URL}/api/reports", headers=headers)
    assert reports_res.status_code == 200, "Reports list failed"
    print("  -> All core Admin endpoints verified intact and functional!")

    print("\n==========================================")
    print("ALL TESTS PASSED! IMPLEMENTATION VERIFIED.")
    print("==========================================")

if __name__ == "__main__":
    run_tests()
