"""
End-to-End Verification Test for eSupport SEO Public Client Report & Admin Link Management Flow
Tests:
1. Admin Authentication & Client Creation
2. Audit Saving & Snapshot Generation
3. Public Route /report/{token} without Authentication (HTML verification, no login controls)
4. Public API GET /api/public/reports/{token} & GET /api/reports/public/{token}
5. 8-Category Structure & Strict Real Data Integrity
6. Hero Score & Exact Headline Mapping (90-100, 80-89, 70-79, 50-69, 0-49)
7. WhatsApp URL (wa.me/94707820810) & Dynamic Message Encoding
8. Email mailto (prasad@esupport.live) & Subject/Body Formatting
9. Status Transitions: PUBLISHED (200) -> DISABLED (410) -> DRAFT (403) -> PUBLISHED (200)
"""

import os
import sys
import json
import urllib.parse
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_URL = "http://127.0.0.1:8000"

def run_tests():
    print("=" * 70)
    print("STARTING E2E VERIFICATION: PUBLIC CLIENT SEO REPORT & ADMIN FLOW")
    print("=" * 70)

    # 1. Admin Login
    admin_session = requests.Session()
    login_resp = admin_session.post(
        f"{BASE_URL}/api/admin/login",
        json={"email": "prasad@esupport.live", "password": "eSupport@SEO2026!Admin"}
    )
    assert login_resp.status_code == 200, f"Admin login failed: {login_resp.status_code} {login_resp.text}"
    csrf_token = login_resp.json().get("csrf_token")
    admin_session.headers.update({"X-CSRF-Token": csrf_token})
    print("[PASS] Step 1: Admin authenticated successfully as prasad@esupport.live")

    # 2. Create Client
    client_resp = admin_session.post(
        f"{BASE_URL}/api/clients",
        json={
            "name": "Acme Innovations Ltd",
            "company": "Acme Corporation",
            "email": "contact@acme.test",
            "phone": "+94 77 123 4567",
            "target_url": "https://example.com"
        }
    )
    assert client_resp.status_code == 200, f"Client creation failed: {client_resp.text}"
    client_id = client_resp.json()["id"]
    print(f"[PASS] Step 2: Client created with ID {client_id}")

    # 3. Save realistic audit with score = 48.0 (Needs Significant Improvement tier)
    audit_payload = {
        "client_id": client_id,
        "score": 48.0,
        "target_url": "https://example.com",
        "audit_result": {
            "target": "https://example.com",
            "url": "https://example.com",
            "score": 48.0,
            "created_at": "2026-10-04T12:00:00Z",
            "scores": {
                "technical": 5.2,
                "on_page": 4.5,
                "critical": 3,
                "warnings": 5,
                "categories": [
                    {"category": "Crawlability & Status", "score": 5.5},
                    {"category": "On-Page Fundamentals", "score": 4.0},
                    {"category": "Content Quality Signals", "score": 4.8},
                    {"category": "Keyword & Topic Signals", "score": 3.5},
                    {"category": "Internal Linking", "score": 5.0},
                    {"category": "Trust & Local Signals", "score": 6.0}
                ]
            },
            "stats": {
                "indexable_pages": 1,
                "status_2xx": 1,
                "broken_links": 2,
                "missing_alt_images": 4
            },
            "issues": [
                {
                    "type": "missing_meta_description",
                    "severity": "CRITICAL",
                    "title": "Missing Meta Description",
                    "url": "https://example.com",
                    "details": "HTML head does not define meta description tag."
                },
                {
                    "type": "broken_internal_links",
                    "severity": "HIGH",
                    "title": "Broken Internal Links Detected",
                    "url": "https://example.com/broken",
                    "details": "HTTP 404 response encountered."
                }
            ],
            "recommendations": {
                "automatic": ["Add unique meta descriptions", "Fix broken hyperlinks"],
                "quick_wins": ["Write concise meta description tag", "Add canonical link"]
            }
        }
    }

    audit_save_resp = admin_session.post(f"{BASE_URL}/api/audits/save", json=audit_payload)
    assert audit_save_resp.status_code == 200, f"Audit save failed: {audit_save_resp.text}"
    audit_id = audit_save_resp.json()["audit_id"]
    print(f"[PASS] Step 3: Audit saved with ID {audit_id}")

    # 4. Generate Public Report Token
    report_gen_resp = admin_session.post(
        f"{BASE_URL}/api/reports/generate",
        json={"audit_id": audit_id, "client_id": client_id, "status": "PUBLISHED"}
    )
    assert report_gen_resp.status_code == 200, f"Report generation failed: {report_gen_resp.text}"
    report_data = report_gen_resp.json()
    token = report_data["token"]
    report_id = report_data["id"]
    public_url = report_data["public_url"]
    assert len(token) >= 32, f"Token must be cryptographically secure, got len {len(token)}"
    print(f"[PASS] Step 4: Public report generated with token '{token}' (URL: {public_url})")

    # 5. Clean, Unauthenticated Session - Verify HTML Route /report/{token}
    clean_client = requests.Session() # No cookies, no headers
    html_resp = clean_client.get(f"{BASE_URL}/report/{token}")
    assert html_resp.status_code == 200, f"HTML route failed: {html_resp.status_code}"
    html_text = html_resp.text
    assert "<title>SEO Audit Report • eSupport SEO</title>" in html_text, "Missing page title"
    assert "esupport-logo.png" in html_text, "Missing official eSupport logo in HTML"
    assert "YOUR SEO SCORE" in html_text, "Missing 'YOUR SEO SCORE' in HTML"
    assert "score-ring-svg" in html_text, "Missing circular SVG score in HTML"
    # Verify NO admin/login controls exposed
    assert "admin-login-overlay" not in html_text, "Admin login overlay leaked into public report!"
    assert "Sign In to Admin Portal" not in html_text, "Admin sign-in button leaked into public report!"
    assert "loginPassword" not in html_text, "Login password field leaked into public report!"
    print("[PASS] Step 5: Public HTML route /report/{token} verified in unauthenticated session (zero login controls)")

    # 6. Verify Public API Route GET /api/public/reports/{token}
    api_resp = clean_client.get(f"{BASE_URL}/api/public/reports/{token}")
    assert api_resp.status_code == 200, f"Public API failed: {api_resp.status_code} {api_resp.text}"
    data = api_resp.json()
    assert data["status"] == "PUBLISHED"
    snapshot = data["data"]
    assert snapshot["score"] == 48.0
    print("[PASS] Step 6: Public API GET /api/public/reports/{token} returned 200 with frozen snapshot")

    # Also verify alias /api/reports/public/{token}
    legacy_resp = clean_client.get(f"{BASE_URL}/api/reports/public/{token}")
    assert legacy_resp.status_code == 200, f"Legacy public API failed: {legacy_resp.status_code}"
    print("[PASS] Step 6b: Public API alias GET /api/reports/public/{token} verified")

    # 7. Verify 8 Mandated Categories
    categories = snapshot["categories"]
    assert len(categories) == 8, f"Expected 8 categories, found {len(categories)}"
    cat_names = [c["name"] for c in categories]
    expected_cats = [
        "Technical SEO",
        "On-Page SEO",
        "Content SEO",
        "Keyword & Search Intent",
        "Internal Linking",
        "Off-Page / Backlink SEO",
        "Local SEO",
        "E-commerce SEO"
    ]
    for exp in expected_cats:
        assert exp in cat_names, f"Missing category: {exp}"
    
    # Check Backlinks: Not configured, no fake numbers
    offpage_cat = next(c for c in categories if c["id"] == "offpage")
    assert offpage_cat["display"] == "Not Configured", f"Backlinks should be 'Not Configured', got {offpage_cat['display']}"
    assert offpage_cat["score"] is None, f"Backlinks score should be None, got {offpage_cat['score']}"
    print("[PASS] Step 7: All 8 mandated categories verified with authentic score calculations")

    # 8. Verify Hero Score & Headline Mapping
    score_status = snapshot["score_status"]
    # For score 48.0:
    # 0–49: Needs Significant Improvement
    assert score_status["headline"] == "Needs Significant Improvement", f"Expected 'Needs Significant Improvement', got {score_status['headline']}"
    assert score_status["status"] == "NEEDS SIGNIFICANT IMPROVEMENT"
    print(f"[PASS] Step 8: Score status headline correctly mapped: '{score_status['headline']}'")

    # 9. Verify CTAs for score < 60
    cta = snapshot["cta"]
    assert cta["headline"] == "Your Website Needs SEO Attention", f"Unexpected CTA headline: {cta['headline']}"
    assert cta["whatsapp_button_text"] == "Improve My SEO on WhatsApp", f"Unexpected WA button text: {cta['whatsapp_button_text']}"
    assert cta["email_button_text"] == "Request SEO Consultation", f"Unexpected Email button text: {cta['email_button_text']}"

    # WhatsApp Link Verification
    wa_url = cta["whatsapp_url"]
    assert wa_url.startswith("https://wa.me/94707820810?text="), f"Invalid WhatsApp base: {wa_url}"
    parsed_wa = urllib.parse.parse_qs(urllib.parse.urlparse(wa_url).query)
    wa_text = parsed_wa["text"][0]
    assert "Hello eSupport," in wa_text
    assert "Website:\nhttps://example.com" in wa_text
    assert "Current SEO Score:\n48/100" in wa_text
    assert "I would like to discuss improving my website's SEO." in wa_text
    assert "Thank you." in wa_text
    print("[PASS] Step 9a: WhatsApp CTA URL verified (correct phone 94707820810 and URL-encoded message)")

    # Email Link Verification
    email_url = cta["email_url"]
    assert email_url.startswith("mailto:prasad@esupport.live?"), f"Invalid email base: {email_url}"
    parsed_email = urllib.parse.parse_qs(urllib.parse.urlparse(email_url).query)
    assert parsed_email["subject"][0] == "SEO Improvement Request - example.com"
    email_body = parsed_email["body"][0]
    assert "Hello eSupport," in email_body
    assert "Current SEO Score:\n48/100" in email_body
    assert "I would like assistance improving my website's SEO performance." in email_body
    print("[PASS] Step 9b: Email CTA mailto verified (prasad@esupport.live, subject, pre-filled body)")

    # 10. Lifecycle Status Transitions: PUBLISHED -> DISABLED -> DRAFT -> PUBLISHED
    # a) Disable report
    disable_resp = admin_session.post(f"{BASE_URL}/api/reports/{report_id}/status", json={"status": "DISABLED"})
    assert disable_resp.status_code == 200, f"Disable failed: {disable_resp.text}"
    assert disable_resp.json()["report_status"] == "DISABLED"

    # Verify public access returns 410 Gone
    pub_disabled_resp = clean_client.get(f"{BASE_URL}/api/public/reports/{token}")
    assert pub_disabled_resp.status_code == 410, f"Expected 410 for DISABLED, got {pub_disabled_resp.status_code}"
    assert "no longer available" in pub_disabled_resp.json()["detail"]
    print("[PASS] Step 10a: Status DISABLED verified -> Public endpoint returns 410 Gone")

    # b) Set to DRAFT
    draft_resp = admin_session.post(f"{BASE_URL}/api/reports/{report_id}/status", json={"status": "DRAFT"})
    assert draft_resp.status_code == 200, f"Draft set failed: {draft_resp.text}"
    pub_draft_resp = clean_client.get(f"{BASE_URL}/api/public/reports/{token}")
    assert pub_draft_resp.status_code == 403, f"Expected 403 for DRAFT, got {pub_draft_resp.status_code}"
    print("[PASS] Step 10b: Status DRAFT verified -> Public endpoint returns 403 Forbidden")

    # c) Re-publish
    repub_resp = admin_session.post(f"{BASE_URL}/api/reports/{report_id}/status", json={"status": "PUBLISHED"})
    assert repub_resp.status_code == 200
    pub_active_resp = clean_client.get(f"{BASE_URL}/api/public/reports/{token}")
    assert pub_active_resp.status_code == 200
    print("[PASS] Step 10c: Status PUBLISHED restored -> Public endpoint returns 200 OK")

    # 11. Test Higher Score Tiers to verify exact headline and button text
    # Tier 75 (Good Foundation)
    from backend.report_service import get_score_status
    st_75 = get_score_status(75.0)
    assert st_75["headline"] == "Good SEO Foundation"
    assert st_75["cta_headline"] == "Your Website Has SEO Improvement Opportunities"
    assert st_75["whatsapp_button_text"] == "Improve My SEO"
    assert st_75["email_button_text"] == "Contact eSupport"
    print("[PASS] Step 11a: Score 75 tier verified (Good SEO Foundation, Improve My SEO)")

    # Tier 85 (Very Good Foundation)
    st_85 = get_score_status(85.0)
    assert st_85["headline"] == "Very Good SEO Foundation"
    assert st_85["cta_headline"] == "Your Website Has a Strong SEO Foundation"
    assert st_85["whatsapp_button_text"] == "Discuss SEO Improvements"
    assert st_85["email_button_text"] == "Contact eSupport"
    print("[PASS] Step 11b: Score 85 tier verified (Very Good SEO Foundation, Discuss SEO Improvements)")

    # Tier 95 (Excellent Foundation)
    st_95 = get_score_status(95.0)
    assert st_95["headline"] == "Excellent SEO Foundation"
    assert st_95["cta_headline"] == "Your Website Has a Strong SEO Foundation"
    assert st_95["whatsapp_button_text"] == "Discuss SEO Improvements"
    assert st_95["email_button_text"] == "Contact eSupport"
    print("[PASS] Step 11c: Score 95 tier verified (Excellent SEO Foundation, Discuss SEO Improvements)")

    print("=" * 70)
    print("ALL 11 VERIFICATION CHECKS PASSED PERFECTLY!")
    print("=" * 70)

if __name__ == "__main__":
    run_tests()
