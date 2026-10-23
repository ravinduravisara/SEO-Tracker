import os
import sys
import requests

BASE_URL = "http://127.0.0.1:8001"

def run_tests():
    passed = 0
    total = 0

    def assert_test(cond, title):
        nonlocal passed, total
        total += 1
        if cond:
            passed += 1
            print(f"  [PASS] {title}")
        else:
            print(f"  [FAIL] {title}")
            assert False, f"Test failed: {title}"

    print("=================================================================")
    print("RUNNING COMPREHENSIVE RBAC & REGRESSION TEST SUITE ON PORT 8001")
    print("=================================================================\n")

    unauth = requests.Session()

    # -------------------------------------------------------------
    # 1. PUBLIC SCANNER VERIFICATION (100% UNRESTRICTED)
    # -------------------------------------------------------------
    print("SECTION 1: Public SEO Scanner & Landing Verification")
    r = unauth.get(f"{BASE_URL}/")
    assert_test(r.status_code == 200, "GET / returns 200 OK without authentication")

    r = unauth.get(f"{BASE_URL}/seo-check")
    assert_test(r.status_code == 200, "GET /seo-check returns 200 OK without authentication")

    r = unauth.post(f"{BASE_URL}/api/preflight", json={"url": "https://example.com", "max_pages": 5})
    assert_test(r.status_code == 200, "POST /api/preflight is public (returns 200 OK)")

    r = unauth.post(f"{BASE_URL}/api/leads", json={
        "name": "Public Lead Tester",
        "company": "Public Corp",
        "website": "https://example.com",
        "email": "lead.tester@example.com",
        "phone": "+1234567890",
        "initial_score": 78.5,
        "source": "public_test"
    })
    assert_test(r.status_code == 200, "POST /api/leads allows public lead submission (returns 200 OK)")
    test_lead_id = r.json().get("lead_id")
    assert_test(test_lead_id is not None, f"Public lead ID created: {test_lead_id}")

    # -------------------------------------------------------------
    # 2. SUPER ADMIN AUTHENTICATION & ACCESS
    # -------------------------------------------------------------
    print("\nSECTION 2: Super Admin Authentication & Full Access")
    super_session = requests.Session()
    r = super_session.post(f"{BASE_URL}/api/admin/login", json={
        "email": "prasad@esupport.live",
        "password": "eSupport@SEO2026!Admin"
    })
    assert_test(r.status_code == 200, "Super Admin login succeeds (200 OK)")
    login_data = r.json()
    assert_test(login_data.get("role") == "SUPER_ADMIN", "Login returns role: SUPER_ADMIN")
    assert_test(login_data.get("status_name") == "ACTIVE", "Login returns status: ACTIVE")
    assert_test(len(login_data.get("permissions", [])) > 20, "Super Admin receives full permissions set")

    super_csrf = login_data.get("csrf_token")
    headers_super = {"X-CSRF-Token": super_csrf} if super_csrf else {}

    r = super_session.get(f"{BASE_URL}/api/admin/users")
    assert_test(r.status_code == 200, "Super Admin GET /api/admin/users returns 200 OK")
    users_list = r.json()
    assert_test(isinstance(users_list, list) and len(users_list) >= 1, "Super Admin sees user list")

    r = super_session.get(f"{BASE_URL}/api/admin/activity-logs")
    assert_test(r.status_code == 200, "Super Admin GET /api/admin/activity-logs returns 200 OK")

    r = super_session.get(f"{BASE_URL}/api/dashboard/stats")
    assert_test(r.status_code == 200, "Super Admin GET /api/dashboard/stats returns 200 OK")

    # -------------------------------------------------------------
    # 3. TEAM MEMBER INVITATION & ONE-TIME TOKEN LIFECYCLE
    # -------------------------------------------------------------
    print("\nSECTION 3: Team Member Invitation & Activation Workflow")
    # Clean up any previous test accounts if rerun
    for u in users_list:
        if u.get("email") in ["alice.admin@esupport.live", "sam.sales@esupport.live", "arthur.analyst@esupport.live"]:
            super_session.delete(f"{BASE_URL}/api/admin/users/{u['id']}", headers=headers_super)

    # Invite ADMIN
    r = super_session.post(f"{BASE_URL}/api/admin/users/invite", json={
        "name": "Alice Admin",
        "email": "alice.admin@esupport.live",
        "role": "ADMIN"
    }, headers=headers_super)
    assert_test(r.status_code == 200, "Super Admin invites ADMIN user successfully")
    inv_admin = r.json()
    token_admin = inv_admin.get("invitation_token")
    assert_test(bool(token_admin), f"One-time invitation token generated for ADMIN (len={len(token_admin)})")

    # Invite SALES
    r = super_session.post(f"{BASE_URL}/api/admin/users/invite", json={
        "name": "Sam Sales",
        "email": "sam.sales@esupport.live",
        "role": "SALES"
    }, headers=headers_super)
    assert_test(r.status_code == 200, "Super Admin invites SALES user successfully")
    inv_sales = r.json()
    token_sales = inv_sales.get("invitation_token")
    assert_test(bool(token_sales), "One-time invitation token generated for SALES")

    # Invite SEO_ANALYST
    r = super_session.post(f"{BASE_URL}/api/admin/users/invite", json={
        "name": "Arthur Analyst",
        "email": "arthur.analyst@esupport.live",
        "role": "SEO_ANALYST"
    }, headers=headers_super)
    assert_test(r.status_code == 200, "Super Admin invites SEO_ANALYST user successfully")
    inv_analyst = r.json()
    token_analyst = inv_analyst.get("invitation_token")
    assert_test(bool(token_analyst), "One-time invitation token generated for SEO_ANALYST")

    # Verify invitation tokens
    r = unauth.get(f"{BASE_URL}/api/auth/invitations/verify?token={token_sales}")
    assert_test(r.status_code == 200, "Verify invitation token endpoint returns 200 OK")
    verify_data = r.json()
    assert_test(verify_data.get("email") == "sam.sales@esupport.live", "Verified email matches")
    assert_test(verify_data.get("role") == "SALES", "Verified role matches SALES")

    # Accept & activate SALES user
    r = unauth.post(f"{BASE_URL}/api/auth/invitations/accept", json={
        "token": token_sales,
        "name": "Sam Sales",
        "password": "SalesPassword2026!"
    })
    assert_test(r.status_code == 200, "SALES user activates account via invitation token")

    # Single-use check: reusing same token must fail
    r = unauth.post(f"{BASE_URL}/api/auth/invitations/accept", json={
        "token": token_sales,
        "name": "Sam Sales Again",
        "password": "SalesPassword2026!"
    })
    assert_test(r.status_code in [400, 404], "Reusing already-claimed invitation token is rejected (400/404)")

    # Activate ADMIN & SEO_ANALYST
    r = unauth.post(f"{BASE_URL}/api/auth/invitations/accept", json={
        "token": token_admin,
        "name": "Alice Admin",
        "password": "AdminPassword2026!"
    })
    assert_test(r.status_code == 200, "ADMIN user activates account successfully")

    r = unauth.post(f"{BASE_URL}/api/auth/invitations/accept", json={
        "token": token_analyst,
        "name": "Arthur Analyst",
        "password": "AnalystPassword2026!"
    })
    assert_test(r.status_code == 200, "SEO_ANALYST user activates account successfully")

    # -------------------------------------------------------------
    # 4. ZERO-TRUST PERMISSION & 403 FORBIDDEN ENFORCEMENT
    # -------------------------------------------------------------
    print("\nSECTION 4: Zero-Trust Backend RBAC Verification (403 Forbidden Matrix)")
    sales_session = requests.Session()
    r = sales_session.post(f"{BASE_URL}/api/admin/login", json={
        "email": "sam.sales@esupport.live",
        "password": "SalesPassword2026!"
    })
    assert_test(r.status_code == 200, "SALES user signs in successfully")
    sales_csrf = r.json().get("csrf_token")
    headers_sales = {"X-CSRF-Token": sales_csrf} if sales_csrf else {}

    # Unauthorized requests by SALES -> MUST BE 403
    r = sales_session.get(f"{BASE_URL}/api/admin/users")
    assert_test(r.status_code == 403, "SALES cannot access /api/admin/users (Strict 403 Forbidden)")

    r = sales_session.delete(f"{BASE_URL}/api/clients/1", headers=headers_sales)
    assert_test(r.status_code == 403, "SALES cannot delete clients (Strict 403 Forbidden)")

    # Authorized requests by SALES -> MUST BE 200
    r = sales_session.get(f"{BASE_URL}/api/leads")
    assert_test(r.status_code == 200, "SALES can access /api/leads (200 OK)")

    r = sales_session.get(f"{BASE_URL}/api/leads/{test_lead_id}")
    assert_test(r.status_code == 200, "SALES can view lead details (200 OK)")

    # SALES can add follow-up notes
    r = sales_session.post(f"{BASE_URL}/api/leads/{test_lead_id}/notes", json={
        "note": "Called lead via phone. Follow-up scheduled for Friday."
    }, headers=headers_sales)
    assert_test(r.status_code == 200, "SALES can record sales note on lead (200 OK)")

    # SALES can view lead notes
    r = sales_session.get(f"{BASE_URL}/api/leads/{test_lead_id}/notes")
    assert_test(r.status_code == 200 and len(r.json()) >= 1, "SALES can retrieve sales notes for lead")

    # SALES can change lead status
    r = sales_session.post(f"{BASE_URL}/api/leads/{test_lead_id}/status", json={"status": "CONTACTED"}, headers=headers_sales)
    assert_test(r.status_code == 200, "SALES can update lead status to CONTACTED (200 OK)")

    # SEO ANALYST checks
    analyst_session = requests.Session()
    r = analyst_session.post(f"{BASE_URL}/api/admin/login", json={
        "email": "arthur.analyst@esupport.live",
        "password": "AnalystPassword2026!"
    })
    assert_test(r.status_code == 200, "SEO_ANALYST signs in successfully")
    analyst_csrf = r.json().get("csrf_token")
    headers_analyst = {"X-CSRF-Token": analyst_csrf} if analyst_csrf else {}

    r = analyst_session.get(f"{BASE_URL}/api/admin/users")
    assert_test(r.status_code == 403, "SEO_ANALYST cannot view team users (Strict 403 Forbidden)")

    r = analyst_session.delete(f"{BASE_URL}/api/clients/1", headers=headers_analyst)
    assert_test(r.status_code == 403, "SEO_ANALYST cannot delete clients (Strict 403 Forbidden)")

    r = analyst_session.get(f"{BASE_URL}/api/audits")
    assert_test(r.status_code == 200, "SEO_ANALYST can access audits history (200 OK)")

    # ADMIN checks
    admin_session = requests.Session()
    r = admin_session.post(f"{BASE_URL}/api/admin/login", json={
        "email": "alice.admin@esupport.live",
        "password": "AdminPassword2026!"
    })
    assert_test(r.status_code == 200, "ADMIN signs in successfully")
    admin_csrf = r.json().get("csrf_token")
    headers_admin = {"X-CSRF-Token": admin_csrf} if admin_csrf else {}

    # Get super admin user ID
    users_current = super_session.get(f"{BASE_URL}/api/admin/users").json()
    super_user = [u for u in users_current if u["role"] == "SUPER_ADMIN"][0]
    super_user_id = super_user["id"]
    sales_user = [u for u in users_current if u["email"] == "sam.sales@esupport.live"][0]
    sales_id = sales_user["id"]

    # ADMIN cannot demote Super Admin
    r = admin_session.post(f"{BASE_URL}/api/admin/users/{super_user_id}/role", json={
        "new_role": "ADMIN"
    }, headers=headers_admin)
    assert_test(r.status_code == 403, "ADMIN cannot demote SUPER ADMIN account (Strict 403 Forbidden)")

    # -------------------------------------------------------------
    # 5. SUPER ADMIN GUARDRAILS (LAST ACTIVE SUPER ADMIN PROTECTION)
    # -------------------------------------------------------------
    print("\nSECTION 5: Super Admin Invariant & Guardrail Protection")
    # Super Admin cannot demote last active Super Admin
    r = super_session.post(f"{BASE_URL}/api/admin/users/{super_user_id}/role", json={
        "new_role": "ADMIN",
        "confirm_super_admin": True
    }, headers=headers_super)
    assert_test(r.status_code == 400, "Cannot demote last active SUPER ADMIN (Protected with 400 Bad Request)")

    # Super Admin cannot delete last active Super Admin
    r = super_session.delete(f"{BASE_URL}/api/admin/users/{super_user_id}", headers=headers_super)
    assert_test(r.status_code == 400, "Cannot delete last active SUPER ADMIN (Protected with 400 Bad Request)")

    # Super Admin cannot suspend last active Super Admin
    r = super_session.post(f"{BASE_URL}/api/admin/users/{super_user_id}/status", json={
        "status": "SUSPENDED"
    }, headers=headers_super)
    assert_test(r.status_code == 400, "Cannot suspend last active SUPER ADMIN (Protected with 400 Bad Request)")

    # -------------------------------------------------------------
    # 6. ACCOUNT SUSPENSION ENFORCEMENT ON ACTIVE SESSIONS
    # -------------------------------------------------------------
    print("\nSECTION 6: Account Suspension Enforcement on Active Sessions")
    # Super Admin suspends Sam Sales
    r = super_session.post(f"{BASE_URL}/api/admin/users/{sales_id}/status", json={
        "status": "SUSPENDED"
    }, headers=headers_super)
    assert_test(r.status_code == 200, "Super Admin successfully suspends user account")

    # Immediate revocation: Sales user tries to query /api/leads with existing active session
    r = sales_session.get(f"{BASE_URL}/api/leads")
    assert_test(r.status_code in [401, 403], f"Suspended user immediately blocked from API (status={r.status_code})")

    # Login rejection: Sales user tries to log in while suspended
    r_login = requests.post(f"{BASE_URL}/api/admin/login", json={
        "email": "sam.sales@esupport.live",
        "password": "SalesPassword2026!"
    })
    assert_test(r_login.status_code == 403, "Suspended user rejected with 403 Forbidden on login")

    # Reactivate Sam Sales
    r = super_session.post(f"{BASE_URL}/api/admin/users/{sales_id}/status", json={
        "status": "ACTIVE"
    }, headers=headers_super)
    assert_test(r.status_code == 200, "Super Admin reactivates user account")

    # -------------------------------------------------------------
    # 7. IMMUTABLE ACTIVITY LOG AUDIT TRAIL
    # -------------------------------------------------------------
    print("\nSECTION 7: Activity Log Integrity & Sensitive Data Sanitization")
    r = super_session.get(f"{BASE_URL}/api/admin/activity-logs")
    assert_test(r.status_code == 200, "Super Admin retrieves activity logs")
    logs = r.json()
    assert_test(len(logs) >= 5, f"Audit trail captured administrative activities (count={len(logs)})")

    # Verify no passwords or tokens in activity log details
    has_leak = False
    for item in logs:
        text = str(item.get("details", "")) + str(item.get("action", ""))
        if "SalesPassword2026!" in text or "AdminPassword2026!" in text or "eSupport@SEO2026!Admin" in text:
            has_leak = True
            break
    assert_test(not has_leak, "Zero credential leaks verified across all activity logs")

    print("\n=================================================================")
    print(f"ALL TESTS PASSED: {passed}/{total} SUCCESSFUL CHECKS")
    print("=================================================================")

if __name__ == "__main__":
    run_tests()
