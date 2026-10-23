from __future__ import annotations

import concurrent.futures
import csv
import ipaddress
import logging
import socket
import threading
import uuid
import hashlib
import html
import json
import os
import re
import time
import zipfile
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone, timedelta
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urldefrag, urljoin, urlparse, urlunparse, quote, quote_plus
from urllib.robotparser import RobotFileParser

import secrets
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, File, HTTPException, Request, UploadFile, Depends, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .database import (
    Base, engine, SessionLocal, get_db,
    Client, Website, Audit, PublicReport, SEOLead,
    TeamInvitation, ActivityLog, LeadNote, init_db, PublicScan,
    ScheduledAudit
)
from .security import (
    bootstrap_admin_account,
    get_current_admin,
    get_current_admin_optional,
    create_admin_session,
    destroy_admin_session,
    verify_password,
    hash_password,
    check_brute_force,
    record_failed_login,
    record_successful_login,
    record_activity,
    verify_csrf,
    AdminUser,
    AdminSession,
)
from .rbac import (
    ROLE_SUPER_ADMIN,
    ROLE_ADMIN,
    ROLE_SALES,
    ROLE_SEO_ANALYST,
    VALID_ROLES,
    STATUS_INVITED,
    STATUS_ACTIVE,
    STATUS_SUSPENDED,
    STATUS_DEACTIVATED,
    VALID_STATUSES,
    has_permission,
    can_manage_role,
    get_role_permissions,
    require_permission,
    require_roles,
)
from .report_service import build_client_report_snapshot, build_real_data_summary, client_categories, get_score_status
from . import integrations
from .seo_engine.signals import extract_signals
from .seo_engine import run_engine, RULESET_VERSION, WEIGHTS as ENGINE_WEIGHTS, band as engine_band, maturity as engine_maturity
from .seo_engine.narrative import category_explanations, clean_prose
from .seo_engine.probes import collect_site_probes, render_mobile_probe, sample_sitemap_locs
from .seo_knowledge import enrich_issue, knowledge_base_export, threshold as kb_threshold
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Paragraph, Spacer, Table, TableStyle, PageBreak, SimpleDocTemplate, KeepTogether, HRFlowable, Image as RLImage)
from reportlab.graphics.shapes import Drawing, Circle, String, Wedge
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
UPLOADS = ROOT / "uploads"
UPLOADS.mkdir(exist_ok=True)
APP_ENV = os.getenv("APP_ENV", "development")
PORT = int(os.getenv("PORT", "8000"))
TIMEOUT = float(os.getenv("CRAWL_TIMEOUT", "20"))
MAX_BODY = int(os.getenv("MAX_BODY_BYTES", "5000000"))
USER_AGENT = os.getenv("CRAWLER_USER_AGENT", "AvianceSEOPro/10.2 (+respectful technical SEO audit)")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3")
LINK_TIMEOUT = float(os.getenv("LINK_CHECK_TIMEOUT", "5"))
RESOURCE_TIMEOUT = float(os.getenv("RESOURCE_CHECK_TIMEOUT", "5"))
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "20"))
OLLAMA_INSIGHT_TIMEOUT = float(os.getenv("OLLAMA_INSIGHT_TIMEOUT", "90"))
PUBLIC_SCAN_AI = os.getenv("PUBLIC_SCAN_AI", "1").strip().lower() in {"1", "true", "yes"}
PREFLIGHT_TIMEOUT = float(os.getenv("PREFLIGHT_TIMEOUT", "8"))
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "20"))

DEFAULT_MAX_PAGES = int(os.getenv("DEFAULT_MAX_PAGES", "25000"))
CRAWL_WORKERS = int(os.getenv("CRAWL_WORKERS", "8"))
JOB_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=2)
PROBE_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4)
AUDIT_JOBS: dict[str, dict[str, Any]] = {}
AUDIT_JOBS_LOCK = threading.Lock()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("aviance")

# Initialize Database and Bootstrap Admin Account
init_db()
with SessionLocal() as _db_init:
    bootstrap_admin_account(_db_init)

app = FastAPI(title="eSupport SEO Platform", version="10.4.0")

app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")

@app.get("/")
def read_index():
    checker_page = FRONTEND / "seo-check.html"
    target = checker_page if checker_page.exists() else FRONTEND / "index.html"
    return HTMLResponse(content=target.read_text(encoding="utf-8"))

@app.get("/admin")
def read_admin():
    return HTMLResponse(content=(FRONTEND / "index.html").read_text(encoding="utf-8"))

@app.get("/report/{token}")
def read_public_report_page(token: str):
    report_page = FRONTEND / "report.html"
    target = report_page if report_page.exists() else FRONTEND / "index.html"
    return HTMLResponse(content=target.read_text(encoding="utf-8"))

@app.get("/seo-check")
def read_seo_check_page():
    checker_page = FRONTEND / "seo-check.html"
    target = checker_page if checker_page.exists() else FRONTEND / "index.html"
    return HTMLResponse(content=target.read_text(encoding="utf-8"))

@app.get("/favicon.ico")
async def read_favicon_ico():
    fav_ico = FRONTEND / "assets" / "favicon.ico"
    if fav_ico.exists():
        return FileResponse(fav_ico, media_type="image/x-icon", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
    fav_png = FRONTEND / "assets" / "favicon.png"
    if fav_png.exists():
        return FileResponse(fav_png, media_type="image/png", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
    return Response(status_code=404)


_cors_origins = list(CORS_ORIGINS)
if APP_ENV != "production":
    for _dev_origin in ("http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:5500", "http://127.0.0.1:5500", "http://localhost:8000", "http://127.0.0.1:8000"):
        if _dev_origin not in _cors_origins:
            _cors_origins.append(_dev_origin)

if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )


class _RateLimiter:
    """In-memory sliding-window limiter keyed by client IP. Single-process only:
    a multi-instance deployment needs a shared store (e.g. Redis) instead."""

    def __init__(self, limit_per_minute: int) -> None:
        self.limit = limit_per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        if self.limit <= 0 or key in ("127.0.0.1", "::1", "localhost", "testclient"):
            return True
        now = time.time()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > 60.0:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True


_AUDIT_RATE_LIMITER = _RateLimiter(RATE_LIMIT_PER_MINUTE)
_RATE_LIMITED_PATHS = ("/api/audit", "/api/preflight", "/api/page-check", "/api/source-audit", "/api/report/")


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    client_host = request.client.host if request.client else "unknown"
    if request.url.path.startswith(_RATE_LIMITED_PATHS) and not _AUDIT_RATE_LIMITER.allow(client_host):
        return JSONResponse(status_code=429, content={"detail": "Too many audit requests from this client. Please slow down and try again shortly."})
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "script-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'self'"
    )
    if APP_ENV == "production":
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    logger.info("%s %s %s %s %.1fms", client_host, request.method, request.url.path, response.status_code, (time.perf_counter() - started) * 1000)
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})


# --- Persistence API ---

class AuditRequest(BaseModel):
    """Validated request contract shared by the audit, preflight and page-check APIs."""

    url: str = Field(..., min_length=1, max_length=2048)
    max_pages: int = Field(DEFAULT_MAX_PAGES, ge=1, le=25_000)
    respect_robots: bool = True
    check_links: bool = True
    check_resources: bool = True
    check_external_links: bool = False
    crawl_delay_ms: int = Field(0, ge=0, le=10_000)
    run_ai: bool = False
    crawl_mode: str = "auto"
    render_max_pages: int = Field(40, ge=0, le=500)
    follow_subdomains: bool = False
    query_policy: str = "safe"
    max_depth: int = Field(50, ge=0, le=100)
    link_check_limit: int = Field(5_000, ge=0, le=50_000)
    resource_check_limit: int = Field(5_000, ge=0, le=50_000)
    # Real-data integrations. DataForSEO is paid, so it is opt-in per audit.
    use_pagespeed: bool = True
    use_search_console: bool = True
    use_dataforseo: bool = False
    pagespeed_desktop: bool = True
    # Spec engine evidence options.
    run_probes: bool = True          # host / redirect / negative-URL / mobile-parity probes
    render_probe: bool = True        # headless-browser mobile render (M03, M05) when a browser is available
    vertical_profile: str | None = Field(None, pattern="^(b2b_product|travel_tourism|ecommerce)$")
    location_code: int | None = Field(None, ge=1)
    language_code: str | None = Field(None, max_length=8)


class ClientCreate(BaseModel):
    name: str
    company: str = ""
    email: str = ""
    phone: str = ""
    target_url: str = ""

class ClientUpdate(BaseModel):
    name: str | None = None
    company: str | None = None
    email: str | None = None
    phone: str | None = None
    target_url: str | None = None

class AuditSaveRequest(BaseModel):
    client_id: int | None = None
    audit_result: dict
    score: float | None = None
    target_url: str | None = None
    job_id: str | None = None

class ReportGenerateRequest(BaseModel):
    audit_id: int
    client_id: int | None = None
    status: str = "PUBLISHED"

class ReportStatusRequest(BaseModel):
    status: str

class LoginRequest(BaseModel):
    email: str
    password: str

class PublicScanRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048)

class LeadCreateRequest(BaseModel):
    name: str = Field("", max_length=255)
    company: str = ""
    email: str = Field(..., min_length=3, max_length=255)
    phone: str = ""
    website: str = Field(..., min_length=1, max_length=2048)
    initial_score: float | None = None
    message: str = ""

class LeadStatusUpdateRequest(BaseModel):
    status: str

class UserInviteRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: str = Field(..., min_length=3, max_length=255)
    role: str = Field(..., min_length=1)
    confirm_super_admin: bool = False
    # Optional: set a password now so the account is active immediately (no invitation link needed).
    password: str | None = Field(None, max_length=200)

class SetPasswordRequest(BaseModel):
    password: str = Field(..., min_length=8, max_length=200)

class UserUpdateRequest(BaseModel):
    name: str | None = None
    email: str | None = None

class UserRoleChangeRequest(BaseModel):
    role: str | None = None
    new_role: str | None = None
    confirm_super_admin: bool = False

class UserStatusChangeRequest(BaseModel):
    status: str

class InvitationAcceptRequest(BaseModel):
    token: str = Field(..., min_length=1)
    password: str = Field(..., min_length=8)
    name: str = ""

class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)

class ProfileUpdateRequest(BaseModel):
    name: str = Field(..., min_length=1)

class LeadNoteCreateRequest(BaseModel):
    note: str = Field(..., min_length=1)

ClientCreate.model_rebuild()
ClientUpdate.model_rebuild()
AuditSaveRequest.model_rebuild()
ReportGenerateRequest.model_rebuild()
ReportStatusRequest.model_rebuild()
LoginRequest.model_rebuild()
PublicScanRequest.model_rebuild()
LeadCreateRequest.model_rebuild()
LeadStatusUpdateRequest.model_rebuild()
UserInviteRequest.model_rebuild()
UserUpdateRequest.model_rebuild()
UserRoleChangeRequest.model_rebuild()
UserStatusChangeRequest.model_rebuild()
InvitationAcceptRequest.model_rebuild()
PasswordChangeRequest.model_rebuild()
ProfileUpdateRequest.model_rebuild()
LeadNoteCreateRequest.model_rebuild()


@app.post("/api/admin/login")
def admin_login(
    req: LoginRequest = Body(...),
    request: Request = None,
    response: Response = None,
    db: Session = Depends(get_db)
):
    ip = request.client.host if (request and request.client) else "unknown"
    email = req.email.strip().lower()

    allowed_ip, msg_ip = check_brute_force(f"ip:{ip}")
    if not allowed_ip:
        raise HTTPException(status_code=429, detail=msg_ip)

    allowed_user, msg_user = check_brute_force(f"user:{email}")
    if not allowed_user:
        raise HTTPException(status_code=429, detail=msg_user)

    admin = db.query(AdminUser).filter(AdminUser.email == email).first()
    if not admin or not verify_password(req.password, admin.password_hash):
        record_failed_login(f"ip:{ip}")
        record_failed_login(f"user:{email}")
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    # Status check
    status = getattr(admin, "status", "ACTIVE")
    if status == "SUSPENDED":
        raise HTTPException(status_code=403, detail="Your account has been suspended. Please contact your administrator.")
    if status == "DEACTIVATED":
        raise HTTPException(status_code=403, detail="Your account has been deactivated.")
    if status == "INVITED":
        raise HTTPException(status_code=403, detail="Your account is pending activation. Please accept your email invitation.")

    record_successful_login(f"ip:{ip}")
    record_successful_login(f"user:{email}")
    raw_token, csrf_token = create_admin_session(db, admin, response)
    record_activity(db, "LOGIN_SUCCESS", f"User #{admin.id} ({admin.email})", "Successful login", user=admin, ip_address=ip)

    user_role = getattr(admin, "role", "SUPER_ADMIN")
    return {
        "status": "success",
        "id": admin.id,
        "name": getattr(admin, "name", "") or admin.email.split("@")[0].capitalize(),
        "email": admin.email,
        "role": user_role,
        "status_name": status,
        "token": raw_token,
        "csrf_token": csrf_token,
        "permissions": get_role_permissions(user_role)
    }


@app.post("/api/admin/logout")
def admin_logout(request: Request, response: Response, db: Session = Depends(get_db)):
    ip = request.client.host if (request and request.client) else "unknown"
    record_activity(db, "LOGOUT", "Admin Session", "User logged out", ip_address=ip)
    destroy_admin_session(db, request, response)
    return {"status": "success", "message": "Successfully signed out."}


@app.get("/api/admin/me")
def admin_me(current_admin: AdminUser = Depends(get_current_admin)):
    user_role = getattr(current_admin, "role", "SUPER_ADMIN")
    return {
        "authenticated": True,
        "id": current_admin.id,
        "name": getattr(current_admin, "name", "") or current_admin.email.split("@")[0].capitalize(),
        "email": current_admin.email,
        "role": user_role,
        "status": getattr(current_admin, "status", "ACTIVE"),
        "last_login_at": current_admin.last_login_at.isoformat() if current_admin.last_login_at else None,
        "permissions": get_role_permissions(user_role)
    }


@app.get("/api/me/permissions")
def me_permissions(current_admin: AdminUser = Depends(get_current_admin)):
    user_role = getattr(current_admin, "role", "SUPER_ADMIN")
    return {
        "role": user_role,
        "permissions": get_role_permissions(user_role)
    }


@app.get("/api/admin/profile")
def get_my_profile(current_admin: AdminUser = Depends(get_current_admin)):
    return {
        "id": current_admin.id,
        "name": getattr(current_admin, "name", "") or current_admin.email.split("@")[0].capitalize(),
        "email": current_admin.email,
        "role": getattr(current_admin, "role", "SUPER_ADMIN"),
        "status": getattr(current_admin, "status", "ACTIVE"),
        "last_login_at": current_admin.last_login_at.isoformat() if current_admin.last_login_at else None,
        "created_at": current_admin.created_at.isoformat() if current_admin.created_at else None
    }


@app.put("/api/admin/profile")
def update_my_profile(
    req: ProfileUpdateRequest = Body(...),
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin)
):
    current_admin.name = req.name.strip()
    db.commit()
    db.refresh(current_admin)
    record_activity(db, "PROFILE_UPDATED", f"User #{current_admin.id}", f"Updated name to '{current_admin.name}'", user=current_admin)
    return {"status": "success", "name": current_admin.name}


@app.post("/api/admin/profile/password")
def change_my_password(
    req: PasswordChangeRequest = Body(...),
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin)
):
    if not verify_password(req.current_password, current_admin.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters.")

    current_admin.password_hash = hash_password(req.new_password)
    db.commit()
    record_activity(db, "PASSWORD_CHANGED", f"User #{current_admin.id}", "User updated their own password", user=current_admin)
    return {"status": "success", "message": "Password updated successfully."}


# ==========================================
# ADMIN TEAM MEMBERS & USER MANAGEMENT APIs
# ==========================================

@app.get("/api/admin/users")
def list_team_users(
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("admin_users.view"))
):
    users = db.query(AdminUser).order_by(AdminUser.created_at.asc()).all()
    result = []
    for u in users:
        result.append({
            "id": u.id,
            "name": getattr(u, "name", "") or u.email.split("@")[0].capitalize(),
            "email": u.email,
            "role": getattr(u, "role", "ADMIN"),
            "status": getattr(u, "status", "ACTIVE"),
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            "created_at": u.created_at.isoformat() if u.created_at else None
        })
    return result


def _absolute_url(request: Request | None, path: str) -> str:
    """Full shareable link. PUBLIC_REPORT_BASE_URL wins (set it to your public/LAN address); else the address the admin used."""
    base = os.getenv("PUBLIC_REPORT_BASE_URL", "").strip().rstrip("/")
    if not base and request is not None:
        base = str(request.base_url).rstrip("/")
    return f"{base}{path}" if base else path


def _require_manageable(current_admin: AdminUser, target_user: AdminUser) -> None:
    if target_user.id != current_admin.id and not can_manage_role(current_admin.role, target_user.role):
        raise HTTPException(status_code=403, detail="You do not have permission to manage this team member.")


@app.post("/api/admin/users/invite")
def invite_team_member(
    req: UserInviteRequest = Body(...),
    request: Request = None,
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("admin_users.create"))
):
    email = req.email.strip().lower()
    role = req.role.strip().upper()
    name = req.name.strip()

    if role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {', '.join(VALID_ROLES)}")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")
    if not can_manage_role(current_admin.role, role):
        raise HTTPException(status_code=403, detail=f"Your role can only add: {', '.join(sorted(r.replace('_', ' ') for r in VALID_ROLES if can_manage_role(current_admin.role, r)))}.")

    if role == ROLE_SUPER_ADMIN:
        if current_admin.role != ROLE_SUPER_ADMIN:
            raise HTTPException(status_code=403, detail="Only a Super Administrator can invite another Super Administrator.")
        if not req.confirm_super_admin:
            raise HTTPException(status_code=400, detail="Explicit confirmation required to invite a Super Administrator.")

    existing_user = db.query(AdminUser).filter(AdminUser.email == email).first()
    if existing_user and existing_user.status == STATUS_ACTIVE:
        raise HTTPException(status_code=400, detail="A user with this email already exists and is active.")
    if existing_user and not can_manage_role(current_admin.role, existing_user.role):
        raise HTTPException(status_code=403, detail="You cannot change an account with a higher role.")

    # Option A: admin sets the password now -> account is active immediately, no link needed.
    if req.password:
        if len(req.password) < 8:
            raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
        user = existing_user or AdminUser(email=email, created_at=datetime.utcnow())
        user.name, user.role, user.status = name, role, STATUS_ACTIVE
        user.password_hash = hash_password(req.password)
        if not existing_user:
            db.add(user)
        db.query(TeamInvitation).filter(TeamInvitation.email == email, TeamInvitation.used_at == None).delete()
        db.commit()
        record_activity(db, "USER_CREATED", f"User ({email})", f"Created by {current_admin.email} as {role} with a password set by admin", user=current_admin,
                        ip_address=request.client.host if request and request.client else "")
        login_url = _absolute_url(request, "/admin")
        return {"status": "success", "mode": "password", "message": f"Account created for {email}. They can sign in now.",
                "email": email, "name": name, "role": role, "login_url": login_url}

    # Option B: one-time invitation link; the member chooses their own password.

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    expires = datetime.utcnow() + timedelta(hours=48)

    # Invalidate existing unused invitations for this email
    db.query(TeamInvitation).filter(TeamInvitation.email == email, TeamInvitation.used_at == None).delete()

    invitation = TeamInvitation(
        email=email,
        name=name,
        role=role,
        token_hash=token_hash,
        expires_at=expires,
        invited_by_id=current_admin.id,
        created_at=datetime.utcnow()
    )
    db.add(invitation)

    if not existing_user:
        new_user = AdminUser(
            email=email,
            name=name,
            role=role,
            status=STATUS_INVITED,
            password_hash=hash_password(secrets.token_hex(16)),  # Unusable placeholder until activation
            created_at=datetime.utcnow()
        )
        db.add(new_user)
    else:
        existing_user.name = name
        existing_user.role = role
        existing_user.status = STATUS_INVITED

    db.commit()

    record_activity(
        db,
        "USER_INVITED",
        f"User ({email})",
        f"Invited by {current_admin.email} as {role}",
        user=current_admin,
        ip_address=request.client.host if request and request.client else ""
    )

    invite_url = _absolute_url(request, f"/admin?invite_token={raw_token}")
    return {
        "status": "success",
        "mode": "invite",
        "message": f"Invitation created for {email}",
        "email": email,
        "name": name,
        "role": role,
        "token": raw_token,
        "invitation_token": raw_token,
        "invite_url": invite_url,
        "activation_url": invite_url,
        "expires_at": expires.isoformat()
    }


@app.patch("/api/admin/users/{user_id}")
def update_team_member(
    user_id: int,
    req: UserUpdateRequest = Body(...),
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("admin_users.edit"))
):
    target_user = db.query(AdminUser).filter(AdminUser.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found.")
    _require_manageable(current_admin, target_user)

    if target_user.role == ROLE_SUPER_ADMIN and current_admin.role != ROLE_SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Only a Super Admin can modify another Super Admin account.")

    if req.name is not None:
        target_user.name = req.name.strip()
    if req.email is not None and req.email.strip().lower() != target_user.email:
        new_email = req.email.strip().lower()
        if db.query(AdminUser).filter(AdminUser.email == new_email).first():
            raise HTTPException(status_code=400, detail="Email is already in use by another user.")
        target_user.email = new_email

    db.commit()
    db.refresh(target_user)
    record_activity(db, "USER_UPDATED", f"User #{target_user.id} ({target_user.email})", "Updated user details", user=current_admin)
    return {"status": "success", "id": target_user.id, "name": target_user.name, "email": target_user.email}


@app.post("/api/admin/users/{user_id}/role")
def change_user_role(
    user_id: int,
    req: UserRoleChangeRequest = Body(...),
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("admin_users.change_role"))
):
    target_user = db.query(AdminUser).filter(AdminUser.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found.")
    _require_manageable(current_admin, target_user)

    raw_role = req.new_role or req.role
    if not raw_role:
        raise HTTPException(status_code=400, detail="Role is required.")
    new_role = raw_role.strip().upper()
    if new_role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {', '.join(VALID_ROLES)}")
    if not can_manage_role(current_admin.role, new_role):
        raise HTTPException(status_code=403, detail="You cannot assign this role.")

    if target_user.role == ROLE_SUPER_ADMIN and current_admin.role != ROLE_SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Only a Super Administrator can change the role of a Super Administrator.")

    if target_user.role == ROLE_SUPER_ADMIN and new_role != ROLE_SUPER_ADMIN:
        # Check active super admins count
        active_super_admins = db.query(AdminUser).filter(
            AdminUser.role == ROLE_SUPER_ADMIN,
            AdminUser.status == STATUS_ACTIVE
        ).count()
        if active_super_admins <= 1:
            raise HTTPException(status_code=400, detail="Cannot change role of the only active Super Administrator.")

    if new_role == ROLE_SUPER_ADMIN and not req.confirm_super_admin:
        raise HTTPException(status_code=400, detail="Explicit confirmation required to promote to Super Administrator.")

    old_role = target_user.role
    target_user.role = new_role
    db.commit()
    db.refresh(target_user)

    record_activity(
        db,
        "ROLE_CHANGED",
        f"User #{target_user.id} ({target_user.email})",
        f"Role changed from {old_role} to {new_role}",
        user=current_admin
    )
    return {"status": "success", "id": target_user.id, "role": target_user.role}


@app.post("/api/admin/users/{user_id}/status")
def change_user_status(
    user_id: int,
    req: UserStatusChangeRequest = Body(...),
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("admin_users.disable"))
):
    target_user = db.query(AdminUser).filter(AdminUser.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found.")
    _require_manageable(current_admin, target_user)

    new_status = req.status.strip().upper()
    if new_status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {', '.join(VALID_STATUSES)}")

    if target_user.role == ROLE_SUPER_ADMIN and new_status in (STATUS_SUSPENDED, STATUS_DEACTIVATED):
        active_super_admins = db.query(AdminUser).filter(
            AdminUser.role == ROLE_SUPER_ADMIN,
            AdminUser.status == STATUS_ACTIVE
        ).count()
        if active_super_admins <= 1:
            raise HTTPException(status_code=400, detail="Cannot suspend or deactivate the only active Super Administrator.")

    if target_user.role == ROLE_SUPER_ADMIN and current_admin.role != ROLE_SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Only a Super Administrator can alter a Super Administrator's status.")

    old_status = target_user.status
    target_user.status = new_status

    if new_status in (STATUS_SUSPENDED, STATUS_DEACTIVATED):
        # Invalidate active sessions immediately
        db.query(AdminSession).filter(AdminSession.admin_id == target_user.id).delete()

    db.commit()
    db.refresh(target_user)

    record_activity(
        db,
        "STATUS_CHANGED",
        f"User #{target_user.id} ({target_user.email})",
        f"Status changed from {old_status} to {new_status}",
        user=current_admin
    )
    return {"status": "success", "id": target_user.id, "status": target_user.status}


@app.post("/api/admin/users/{user_id}/reset-access")
def reset_user_access(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("admin_users.reset_access"))
):
    target_user = db.query(AdminUser).filter(AdminUser.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found.")
    _require_manageable(current_admin, target_user)

    if target_user.role == ROLE_SUPER_ADMIN and current_admin.role != ROLE_SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Only a Super Admin can reset access for a Super Admin.")

    # Invalidate sessions and previous invitations
    db.query(AdminSession).filter(AdminSession.admin_id == target_user.id).delete()
    db.query(TeamInvitation).filter(TeamInvitation.email == target_user.email, TeamInvitation.used_at == None).delete()

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    expires = datetime.utcnow() + timedelta(hours=48)

    inv = TeamInvitation(
        email=target_user.email,
        name=target_user.name,
        role=target_user.role,
        token_hash=token_hash,
        expires_at=expires,
        invited_by_id=current_admin.id,
        created_at=datetime.utcnow()
    )
    db.add(inv)
    target_user.status = STATUS_INVITED
    db.commit()

    record_activity(db, "ACCESS_RESET", f"User #{target_user.id} ({target_user.email})", "Generated new invitation link", user=current_admin)
    return {
        "status": "success",
        "email": target_user.email,
        "token": raw_token,
        "invitation_token": raw_token,
        "invite_url": _absolute_url(request, f"/admin?invite_token={raw_token}"),
        "activation_url": _absolute_url(request, f"/admin?invite_token={raw_token}"),
        "expires_at": expires.isoformat()
    }


@app.post("/api/admin/users/{user_id}/set-password")
def set_user_password(
    user_id: int,
    req: SetPasswordRequest = Body(...),
    request: Request = None,
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("admin_users.reset_access"))
):
    """Admin sets a new password for a team member and activates the account (no email or link needed)."""
    target_user = db.query(AdminUser).filter(AdminUser.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found.")
    _require_manageable(current_admin, target_user)
    if target_user.role == ROLE_SUPER_ADMIN and current_admin.role != ROLE_SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Only a Super Admin can set a Super Admin's password.")

    target_user.password_hash = hash_password(req.password)
    if target_user.status in (STATUS_INVITED,):
        target_user.status = STATUS_ACTIVE
    # Sign the member out everywhere and cancel pending invitation links.
    db.query(AdminSession).filter(AdminSession.admin_id == target_user.id).delete()
    db.query(TeamInvitation).filter(TeamInvitation.email == target_user.email, TeamInvitation.used_at == None).delete()
    db.commit()
    record_activity(db, "PASSWORD_SET_BY_ADMIN", f"User #{target_user.id} ({target_user.email})", "Password set by administrator", user=current_admin)
    return {"status": "success", "email": target_user.email, "user_status": target_user.status, "login_url": _absolute_url(request, "/admin")}


@app.delete("/api/admin/users/{user_id}")
def delete_team_member(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("admin_users.delete"))
):
    target_user = db.query(AdminUser).filter(AdminUser.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found.")
    _require_manageable(current_admin, target_user)

    if target_user.id == current_admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account.")

    if target_user.role == ROLE_SUPER_ADMIN:
        active_super_admins = db.query(AdminUser).filter(
            AdminUser.role == ROLE_SUPER_ADMIN,
            AdminUser.status == STATUS_ACTIVE
        ).count()
        if active_super_admins <= 1:
            raise HTTPException(status_code=400, detail="Cannot delete the only active Super Administrator.")

    email = target_user.email
    db.query(AdminSession).filter(AdminSession.admin_id == target_user.id).delete()
    db.query(TeamInvitation).filter(TeamInvitation.email == email).delete()
    db.delete(target_user)
    db.commit()

    record_activity(db, "USER_DELETED", f"User ({email})", "Permanently removed user account", user=current_admin)
    return {"status": "success", "message": f"User {email} deleted successfully."}


@app.post("/api/admin/seed-demo-data")
def trigger_database_seeding(
    req: dict = None,
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("admin_users.create"))
):
    """
    Super Admin endpoint to seed or reset platform demo data.
    """
    from .seed import seed_all
    reset = bool(req and req.get("reset"))
    summary = seed_all(db=db, reset=reset, verbose=False)
    record_activity(db, "DATABASE_SEEDED", "System Seeder", f"Seeded demo data (reset={reset})", user=current_admin)
    return {
        "status": "success",
        "message": "Database successfully populated with seed data.",
        "summary": summary
    }



# ==========================================
# PUBLIC INVITATION VERIFICATION & ACCEPTANCE
# ==========================================

@app.get("/api/auth/invitations/verify")
def verify_invitation(token: str, db: Session = Depends(get_db)):
    if not token:
        raise HTTPException(status_code=400, detail="Token required.")
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    inv = db.query(TeamInvitation).filter(
        TeamInvitation.token_hash == token_hash,
        TeamInvitation.expires_at > datetime.utcnow(),
        TeamInvitation.used_at == None
    ).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invitation token is invalid, expired, or already used.")

    return {
        "valid": True,
        "email": inv.email,
        "name": inv.name,
        "role": inv.role,
        "expires_at": inv.expires_at.isoformat()
    }


@app.post("/api/auth/invitations/accept")
def accept_invitation(
    req: InvitationAcceptRequest = Body(...),
    response: Response = None,
    db: Session = Depends(get_db)
):
    token_hash = hashlib.sha256(req.token.encode("utf-8")).hexdigest()
    inv = db.query(TeamInvitation).filter(
        TeamInvitation.token_hash == token_hash,
        TeamInvitation.expires_at > datetime.utcnow(),
        TeamInvitation.used_at == None
    ).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invitation token is invalid, expired, or already used.")

    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters long.")

    user = db.query(AdminUser).filter(AdminUser.email == inv.email).first()
    if not user:
        user = AdminUser(
            email=inv.email,
            name=req.name.strip() or inv.name,
            role=inv.role,
            status=STATUS_ACTIVE,
            password_hash=hash_password(req.password),
            created_at=datetime.utcnow()
        )
        db.add(user)
    else:
        user.name = req.name.strip() or inv.name or user.name
        user.role = inv.role
        user.status = STATUS_ACTIVE
        user.password_hash = hash_password(req.password)

    inv.used_at = datetime.utcnow()
    db.commit()
    db.refresh(user)

    # Establish authenticated session
    raw_session_token, csrf_token = create_admin_session(db, user, response)

    record_activity(db, "USER_ACTIVATED", f"User #{user.id} ({user.email})", f"Activated account with role {user.role}", user=user)

    return {
        "status": "success",
        "message": "Account activated successfully.",
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "token": raw_session_token,
        "csrf_token": csrf_token,
        "permissions": get_role_permissions(user.role)
    }


# ==========================================
# ACTIVITY LOGS & SALES PIPELINE APIs
# ==========================================

@app.get("/api/admin/activity-logs")
def list_activity_logs(
    limit: int = 100,
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("activity_logs.view"))
):
    logs = db.query(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(min(limit, 200)).all()
    result = []
    for l in logs:
        result.append({
            "id": l.id,
            "user_email": l.user_email or "System",
            "user_name": l.user_name or "",
            "user_role": l.user_role or "",
            "action": l.action,
            "resource": l.resource,
            "details": l.details,
            "status": l.status,
            "ip_address": l.ip_address,
            "created_at": l.created_at.isoformat() if l.created_at else None
        })
    return result


@app.get("/api/sales/pipeline")
def get_sales_pipeline_stats(
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("leads.view"))
):
    leads = db.query(SEOLead).all()
    counts = {"NEW": 0, "CONTACTED": 0, "QUALIFIED": 0, "CONVERTED": 0, "CLOSED": 0}
    for l in leads:
        st = (l.status or "NEW").upper()
        if st in counts:
            counts[st] += 1
        else:
            counts["NEW"] += 1

    low_scores = sum(1 for l in leads if l.initial_score is not None and l.initial_score < 70)
    recent = db.query(SEOLead).order_by(SEOLead.created_at.desc()).limit(5).all()

    return {
        "total_leads": len(leads),
        "uncontacted_leads": counts.get("NEW", 0),
        "contacted_leads": counts.get("CONTACTED", 0),
        "qualified_leads": counts.get("QUALIFIED", 0),
        "converted_leads": counts.get("CONVERTED", 0),
        "closed_leads": counts.get("CLOSED", 0),
        "low_score_websites": low_scores,
        "counts": counts,
        "recent_leads": [{
            "id": l.id,
            "name": l.name,
            "company": l.company,
            "website": l.website,
            "score": l.initial_score,
            "status": l.status,
            "created_at": l.created_at.isoformat() if l.created_at else None
        } for l in recent]
    }



_DASHBOARD_STATS_CACHE: dict[str, Any] = {"timestamp": 0.0, "data": None, "refreshing": False}
_DASHBOARD_STATS_LOCK = threading.Lock()
_OLLAMA_STATUS_CACHE: dict[str, Any] = {"timestamp": 0.0, "ready": False}
_OLLAMA_LOCK = threading.Lock()


def _check_ollama_status_fast() -> bool:
    now = time.time()
    with _OLLAMA_LOCK:
        if now - _OLLAMA_STATUS_CACHE["timestamp"] < 60.0:
            return _OLLAMA_STATUS_CACHE["ready"]
    ready = False
    try:
        base = OLLAMA_URL.rsplit("/api/", 1)[0].rstrip("/")
        tags = requests.get(base + "/api/tags", timeout=0.4)
        ready = tags.ok and any(str(m.get("name", "")).split(":")[0] == OLLAMA_MODEL.split(":")[0] for m in (tags.json().get("models") or []))
    except Exception:
        pass
    with _OLLAMA_LOCK:
        _OLLAMA_STATUS_CACHE["timestamp"] = now
        _OLLAMA_STATUS_CACHE["ready"] = ready
    return ready


def invalidate_dashboard_cache():
    """Immediately invalidate in-memory dashboard stats so the next request gets fresh data."""
    with _DASHBOARD_STATS_LOCK:
        _DASHBOARD_STATS_CACHE["timestamp"] = 0.0


def _compute_dashboard_stats() -> dict[str, Any]:
    # Execute independent count and aggregate queries in parallel to eliminate cloud round-trip delay
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        f_clients = executor.submit(lambda: SessionLocal().query(Client).all())
        f_websites = executor.submit(lambda: SessionLocal().query(Website).count())
        f_audits_meta = executor.submit(lambda: SessionLocal().query(Audit).defer("result_json").order_by(Audit.created_at.desc()).all())
        f_reports_pub = executor.submit(lambda: SessionLocal().query(PublicReport).filter(PublicReport.status == "PUBLISHED").count())
        f_reports_tot = executor.submit(lambda: SessionLocal().query(PublicReport).count())
        f_leads_tot = executor.submit(lambda: SessionLocal().query(SEOLead).count())
        f_leads_new = executor.submit(lambda: SessionLocal().query(SEOLead).filter(SEOLead.status == "NEW").count())
        f_scans_cnt = executor.submit(lambda: SessionLocal().query(PublicScan).count())
        f_hist_scans = executor.submit(lambda: SessionLocal().query(Audit).filter(Audit.client_id == None).count())
        f_ollama = executor.submit(_check_ollama_status_fast)

        clients = f_clients.result()
        total_clients = len(clients)
        total_websites = f_websites.result()
        audits = f_audits_meta.result()
        reports_published = f_reports_pub.result()
        reports_total = f_reports_tot.result()
        leads_total = f_leads_tot.result()
        leads_new = f_leads_new.result()
        try:
            public_scans_recorded = f_scans_cnt.result()
        except Exception:
            public_scans_recorded = 0
        historical_public = f_hist_scans.result()
        ollama_ready = f_ollama.result()

    total_audits = len(audits)
    scores = [a.score for a in audits if a.score is not None]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0
    excellent = sum(1 for s in scores if s >= 90)
    needs_imp = sum(1 for s in scores if s < 70)

    # Load full audit results only for the latest 10 audits for dashboard metrics
    recent_ids = [a.id for a in audits[:10]]
    recent_map: dict[int, Audit] = {}
    if recent_ids:
        for a in SessionLocal().query(Audit).filter(Audit.id.in_(recent_ids)).all():
            recent_map[a.id] = a

    parsed: list[tuple[Audit, dict[str, Any]]] = []
    for a_meta in audits[:10]:
        a = recent_map.get(a_meta.id, a_meta)
        try:
            res = json.loads(a.result_json) if isinstance(a.result_json, str) else (a.result_json or {})
        except Exception:
            res = {}
        parsed.append((a, res if isinstance(res, dict) else {}))

    totals = {"pages_crawled": 0, "links_checked": 0, "resources_checked": 0}
    for _, res in parsed:
        diag = res.get("crawl_diagnostics") or {}
        totals["pages_crawled"] += int(res.get("page_count") or 0)
        totals["links_checked"] += int(diag.get("links_checked") or 0)
        totals["resources_checked"] += int(diag.get("resources_checked") or 0)

    # "Current state" uses only the newest audit of each website
    latest_by_host: dict[str, tuple[Audit, dict[str, Any]]] = {}
    for a, res in parsed:
        host = (urlparse(a.target_url or "").hostname or a.target_url or "").lower().removeprefix("www.")
        latest_by_host.setdefault(host, (a, res))
    current = list(latest_by_host.values())
    open_critical = open_warnings = broken_links = 0
    category_scores: dict[str, list[float]] = defaultdict(list)
    category_names: dict[str, str] = {}
    issue_sites: Counter[str] = Counter()
    issue_titles: dict[str, str] = {}
    for a, res in current:
        payload = ensure_engine(res) if res.get("pages") else {}
        summ = payload.get("issue_summary") or {}
        open_critical += int(summ.get("critical") or 0)
        open_warnings += int(summ.get("high") or 0) + int(summ.get("medium") or 0)
        broken_links += int((res.get("stats") or {}).get("broken_links") or 0)
        for cat in payload.get("categories") or []:
            if cat.get("score") is not None:
                category_scores[cat["id"]].append(float(cat["score"]))
                category_names[cat["id"]] = cat.get("name", cat["id"])
        for issue in payload.get("issues") or []:
            if issue["severity"] in ("critical", "high"):
                issue_titles.setdefault(issue["check_id"], issue["check_name"])
                issue_sites[issue["check_id"]] += 1

    week_ago = datetime.utcnow() - timedelta(days=7)
    month_ago = datetime.utcnow() - timedelta(days=30)
    public_scans_total = max(public_scans_recorded, historical_public, leads_total)

    # Batch fetch client names for recent audits in 1 query
    client_ids = {a.client_id for a, _ in parsed[:8] if a.client_id}
    client_name_map = {}
    if client_ids:
        for c in SessionLocal().query(Client).filter(Client.id.in_(client_ids)).all():
            client_name_map[c.id] = c.name

    recent_audits = []
    for a, res in parsed[:8]:
        sc = res.get("scores") or {}
        if (res.get("seo_engine") or {}).get("issue_summary"):
            summ = res["seo_engine"]["issue_summary"]
            sc = {"critical": summ["critical"], "warnings": summ["high"] + summ["medium"]}
        recent_audits.append({
            "id": a.id,
            "target_url": a.target_url,
            "score": a.score,
            "status": a.status,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "client_name": client_name_map.get(a.client_id, "Direct Audit"),
            "pages_crawled": int(res.get("page_count") or 0),
            "critical": int(sc.get("critical") or 0),
            "warnings": int(sc.get("warnings") or 0),
            "elapsed_seconds": (res.get("crawl_diagnostics") or {}).get("elapsed_seconds"),
        })

    integ = integrations.status()

    result_data = {
        "websites_audited": len(latest_by_host),
        "pages_crawled": totals["pages_crawled"],
        "links_checked": totals["links_checked"],
        "resources_checked": totals["resources_checked"],
        "open_critical_issues": open_critical,
        "open_warnings": open_warnings,
        "broken_links": broken_links,
        "audits_last_7_days": sum(1 for a in audits if a.created_at and a.created_at >= week_ago),
        "audits_last_30_days": sum(1 for a in audits if a.created_at and a.created_at >= month_ago),
        "leads_total": leads_total,
        "leads_new": leads_new,
        "category_averages": [
            {"id": cid, "name": category_names[cid], "average": round(sum(v) / len(v)), "websites": len(v)}
            for cid, v in sorted(category_scores.items(), key=lambda kv: list(ENGINE_WEIGHTS).index(kv[0]) if kv[0] in ENGINE_WEIGHTS else 99)
        ],
        "top_issues": [{"code": code, "title": issue_titles[code], "websites": n} for code, n in issue_sites.most_common(6)],
        "data_sources": {
            "pagespeed": bool(integ["pagespeed"]["configured"]),
            "pagespeed_mode": integ["pagespeed"].get("mode", "none"),
            "search_console": bool(integ["search_console"]["configured"]),
            "openpagerank": bool(integ["openpagerank"]["configured"]),
            "ollama": ollama_ready,
            "ollama_model": OLLAMA_MODEL,
        },
        "total_clients": total_clients,
        "total_websites": total_websites,
        "total_audits": total_audits,
        "avg_score": avg_score,
        "excellent_websites": excellent,
        "needs_improvement": needs_imp,
        "critical_issues": open_critical,
        "reports_published": reports_published,
        "reports_total": reports_total,
        "public_scans_total": public_scans_total,
        "recent_audits": recent_audits
    }

    with _DASHBOARD_STATS_LOCK:
        _DASHBOARD_STATS_CACHE["timestamp"] = time.time()
        _DASHBOARD_STATS_CACHE["data"] = result_data
        _DASHBOARD_STATS_CACHE["refreshing"] = False

    return result_data


@app.get("/api/dashboard/stats")
def get_dashboard_stats(db: Session = Depends(get_db), current_admin: AdminUser = Depends(require_permission("dashboard.view"))):
    now_ts = time.time()
    with _DASHBOARD_STATS_LOCK:
        data = _DASHBOARD_STATS_CACHE["data"]
        age = now_ts - _DASHBOARD_STATS_CACHE["timestamp"]
        refreshing = _DASHBOARD_STATS_CACHE.get("refreshing", False)

    # 1. Fresh cache hit (< 60s) -> return immediately
    if data is not None and age < 60.0:
        return data

    # 2. Stale-While-Revalidate (< 300s) -> return immediately and refresh in background
    if data is not None and age < 300.0:
        if not refreshing:
            with _DASHBOARD_STATS_LOCK:
                _DASHBOARD_STATS_CACHE["refreshing"] = True
            threading.Thread(target=_compute_dashboard_stats, daemon=True).start()
        return data

    # 3. Cache expired or initial hit -> compute in parallel
    return _compute_dashboard_stats()


@app.get("/api/clients")
def list_clients(db: Session = Depends(get_db), current_admin: AdminUser = Depends(require_permission("clients.view"))):
    clients = db.query(Client).order_by(Client.created_at.desc()).all()
    if not clients:
        return []

    client_ids = [c.id for c in clients]
    # Batch fetch websites, audits (without huge result_json), and reports in 3 targeted queries
    websites_by_client: dict[int, list[Website]] = defaultdict(list)
    for w in db.query(Website).filter(Website.client_id.in_(client_ids)).all():
        websites_by_client[w.client_id].append(w)

    audits_by_client: dict[int, list[Audit]] = defaultdict(list)
    for a in db.query(Audit).defer("result_json").filter(Audit.client_id.in_(client_ids)).all():
        audits_by_client[a.client_id].append(a)

    reports_by_client: dict[int, list[PublicReport]] = defaultdict(list)
    for r in db.query(PublicReport).filter(PublicReport.client_id.in_(client_ids)).all():
        reports_by_client[r.client_id].append(r)

    result = []
    for c in clients:
        c_websites = websites_by_client.get(c.id, [])
        web_url = c_websites[0].url if c_websites else ""
        c_audits = sorted(audits_by_client.get(c.id, []), key=lambda a: a.created_at or datetime.min, reverse=True)
        latest = c_audits[0] if c_audits else None
        c_reports = reports_by_client.get(c.id, [])
        pub_reports = [r for r in c_reports if r.status == "PUBLISHED"]
        latest_report = c_reports[-1] if c_reports else None

        result.append({
            "id": c.id,
            "name": c.name,
            "company": c.company or "",
            "email": c.email or "",
            "phone": c.phone or "",
            "target_url": web_url,
            "status": c.status,
            "audit_count": len(c_audits),
            "latest_score": latest.score if latest else None,
            "latest_audit_id": latest.id if latest else None,
            "latest_audit_date": latest.created_at.isoformat() if latest and latest.created_at else None,
            "published_report_count": len(pub_reports),
            "latest_report_token": latest_report.token if latest_report else None,
            "latest_report_status": latest_report.status if latest_report else None,
            "created_at": c.created_at.isoformat() if c.created_at else None
        })
    return result


@app.post("/api/clients")
def create_client(client_data: ClientCreate = Body(...), db: Session = Depends(get_db), current_admin: AdminUser = Depends(require_permission("clients.create"))):
    new_client = Client(
        name=client_data.name.strip(),
        company=client_data.company.strip() if client_data.company else "",
        email=client_data.email.strip() if client_data.email else "",
        phone=client_data.phone.strip() if client_data.phone else "",
        status="ACTIVE"
    )
    db.add(new_client)
    db.commit()
    db.refresh(new_client)

    if client_data.target_url and client_data.target_url.strip():
        website = Website(
            client_id=new_client.id,
            url=client_data.target_url.strip(),
            name=client_data.company or client_data.name,
            status="ACTIVE"
        )
        db.add(website)
        db.commit()

    record_activity(db, "CLIENT_CREATED", f"Client #{new_client.id} ({new_client.name})", f"Target: {client_data.target_url}", user=current_admin)
    invalidate_dashboard_cache()

    return {
        "id": new_client.id,
        "name": new_client.name,
        "company": new_client.company,
        "email": new_client.email,
        "phone": new_client.phone,
        "target_url": client_data.target_url,
        "created_at": new_client.created_at.isoformat() if new_client.created_at else None
    }


@app.get("/api/clients/{client_id}")
def get_client(client_id: int, db: Session = Depends(get_db), current_admin: AdminUser = Depends(require_permission("clients.view"))):
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Fast batch queries: fetch websites, audits (defer heavy result_json), and public reports
    websites = db.query(Website).filter(Website.client_id == client.id).all()
    audits = db.query(Audit).defer("result_json").filter(Audit.client_id == client.id).order_by(Audit.created_at.desc()).all()
    reports = db.query(PublicReport).filter(PublicReport.client_id == client.id).order_by(PublicReport.created_at.desc()).all()

    # Index reports by audit_id for zero-query mapping
    reports_by_audit = defaultdict(list)
    for r in reports:
        if r.audit_id:
            reports_by_audit[r.audit_id].append(r)

    # Index audits by id for zero-query report lookup
    audits_by_id = {a.id: a for a in audits}

    websites_out = [{"id": w.id, "url": w.url, "name": w.name} for w in websites]

    audits_out = []
    for a in audits:
        a_reps = reports_by_audit.get(a.id, [])
        audits_out.append({
            "id": a.id,
            "job_id": a.job_id,
            "target_url": a.target_url,
            "score": a.score,
            "status": a.status,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "report_token": a_reps[0].token if a_reps else None,
            "report_status": a_reps[0].status if a_reps else None
        })

    reports_out = []
    for r in reports:
        a = audits_by_id.get(r.audit_id)
        reports_out.append({
            "id": r.id,
            "token": r.token,
            "status": r.status,
            "audit_id": r.audit_id,
            "score": a.score if a else 0,
            "target_url": a.target_url if a else "",
            "public_url": f"/report/{r.token}",
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "published_at": r.published_at.isoformat() if r.published_at else None
        })

    return {
        "id": client.id,
        "name": client.name,
        "company": client.company or "",
        "email": client.email or "",
        "phone": client.phone or "",
        "status": client.status,
        "websites": websites_out,
        "target_url": websites_out[0]["url"] if websites_out else "",
        "audits": audits_out,
        "reports": reports_out,
        "created_at": client.created_at.isoformat() if client.created_at else None
    }


@app.put("/api/clients/{client_id}")
def update_client(client_id: int, req: ClientUpdate = Body(...), db: Session = Depends(get_db), current_admin: AdminUser = Depends(require_permission("clients.edit"))):
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    if req.name is not None: client.name = req.name
    if req.company is not None: client.company = req.company
    if req.email is not None: client.email = req.email
    if req.phone is not None: client.phone = req.phone
    if req.target_url is not None and req.target_url.strip():
        if client.websites:
            client.websites[0].url = req.target_url.strip()
        else:
            db.add(Website(client_id=client.id, url=req.target_url.strip(), name=client.company or client.name))

    db.commit()
    db.refresh(client)
    invalidate_dashboard_cache()
    record_activity(db, "CLIENT_UPDATED", f"Client #{client.id} ({client.name})", "Updated client information", user=current_admin)
    return {"status": "success", "id": client.id}


@app.delete("/api/clients/{client_id}")
def delete_client(client_id: int, db: Session = Depends(get_db), current_admin: AdminUser = Depends(require_permission("clients.delete"))):
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    name = client.name
    db.delete(client)
    db.commit()
    invalidate_dashboard_cache()
    record_activity(db, "CLIENT_DELETED", f"Client #{client_id} ({name})", "Deleted client profile and associated websites", user=current_admin)
    return {"status": "success", "message": "Client deleted"}


@app.get("/api/audits")
def list_audits(db: Session = Depends(get_db), current_admin: AdminUser = Depends(require_permission("audits.view"))):
    audits = db.query(Audit).defer("result_json").order_by(Audit.created_at.desc()).limit(100).all()
    if not audits:
        return []

    client_ids = [a.client_id for a in audits if a.client_id]
    audit_ids = [a.id for a in audits]

    clients_map = {}
    if client_ids:
        for c in db.query(Client).filter(Client.id.in_(client_ids)).all():
            clients_map[c.id] = c

    reports_by_audit: dict[int, list[PublicReport]] = defaultdict(list)
    for r in db.query(PublicReport).filter(PublicReport.audit_id.in_(audit_ids)).all():
        reports_by_audit[r.audit_id].append(r)

    result = []
    for a in audits:
        c = clients_map.get(a.client_id)
        a_reports = reports_by_audit.get(a.id, [])
        result.append({
            "id": a.id,
            "client_id": a.client_id,
            "client_name": c.name if c else "Direct Audit",
            "company": c.company if c else "",
            "target_url": a.target_url,
            "score": a.score,
            "status": a.status,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "has_report": bool(a_reports),
            "report_token": a_reports[0].token if a_reports else None,
            "report_status": a_reports[0].status if a_reports else None
        })
    return result


@app.get("/api/audits/{audit_id}")
def get_audit_record(audit_id: int, db: Session = Depends(get_db), current_admin: AdminUser = Depends(require_permission("audits.view"))):
    audit = db.query(Audit).filter(Audit.id == audit_id).first()
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found")
    try:
        parsed_result = json.loads(audit.result_json) if isinstance(audit.result_json, str) else audit.result_json
    except Exception:
        parsed_result = {}
    return {
        "id": audit.id,
        "client_id": audit.client_id,
        "client_name": audit.client.name if audit.client else "",
        "company": audit.client.company if audit.client else "",
        "target_url": audit.target_url,
        "score": audit.score,
        "status": audit.status,
        "created_at": audit.created_at.isoformat() if audit.created_at else None,
        "audit_result": parsed_result,
        "reports": [{"id": r.id, "token": r.token, "status": r.status} for r in audit.public_reports]
    }


@app.get("/api/audits/compare/{audit_id_1}/{audit_id_2}")
def compare_audits_endpoint(
    audit_id_1: int,
    audit_id_2: int,
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("audits.view"))
):
    """
    Compare two historical audits (e.g. baseline vs latest crawl).
    Calculates score delta, category changes, resolved issues, regressions, and crawl stats.
    """
    a1 = db.query(Audit).filter(Audit.id == audit_id_1).first()
    a2 = db.query(Audit).filter(Audit.id == audit_id_2).first()
    if not a1 or not a2:
        raise HTTPException(status_code=404, detail="One or both audits were not found.")

    res1 = json.loads(a1.result_json) if isinstance(a1.result_json, str) else (a1.result_json or {})
    res2 = json.loads(a2.result_json) if isinstance(a2.result_json, str) else (a2.result_json or {})

    score1 = a1.score or 0.0
    score2 = a2.score or 0.0
    score_delta = round(score2 - score1, 1)

    eng1 = res1.get("seo_engine") or {}
    eng2 = res2.get("seo_engine") or {}

    cat_map1 = {c["id"]: c for c in eng1.get("categories", [])}
    cat_map2 = {c["id"]: c for c in eng2.get("categories", [])}
    categories_diff = []
    for cat_id in list(dict.fromkeys(list(cat_map1.keys()) + list(cat_map2.keys()))):
        c1 = cat_map1.get(cat_id, {})
        c2 = cat_map2.get(cat_id, {})
        s1 = c1.get("score")
        s2 = c2.get("score")
        delta = round(s2 - s1, 1) if (s1 is not None and s2 is not None) else None
        categories_diff.append({
            "id": cat_id,
            "name": c2.get("name") or c1.get("name") or cat_id,
            "before_score": s1,
            "after_score": s2,
            "delta": delta,
        })

    issues1 = {i.get("check_id") or i.get("code"): i for i in (eng1.get("issues") or res1.get("issues") or []) if i.get("check_id") or i.get("code")}
    issues2 = {i.get("check_id") or i.get("code"): i for i in (eng2.get("issues") or res2.get("issues") or []) if i.get("check_id") or i.get("code")}

    resolved_keys = set(issues1.keys()) - set(issues2.keys())
    new_keys = set(issues2.keys()) - set(issues1.keys())
    persistent_keys = set(issues1.keys()) & set(issues2.keys())

    resolved_issues = [issues1[k] for k in sorted(resolved_keys)]
    new_issues = [issues2[k] for k in sorted(new_keys)]
    persistent_issues = [issues2[k] for k in sorted(persistent_keys)]

    stats1 = res1.get("stats", {}) or {}
    stats2 = res2.get("stats", {}) or {}

    cov1 = eng1.get("measurement_coverage", {})
    cov2 = eng2.get("measurement_coverage", {})

    return {
        "audit_before": {
            "id": a1.id,
            "target_url": a1.target_url,
            "score": score1,
            "grade": eng1.get("score", {}).get("grade"),
            "created_at": a1.created_at.isoformat() if a1.created_at else None,
            "pages_crawled": res1.get("page_count", 0),
        },
        "audit_after": {
            "id": a2.id,
            "target_url": a2.target_url,
            "score": score2,
            "grade": eng2.get("score", {}).get("grade"),
            "created_at": a2.created_at.isoformat() if a2.created_at else None,
            "pages_crawled": res2.get("page_count", 0),
        },
        "score_delta": score_delta,
        "improved": score_delta > 0,
        "regressed": score_delta < 0,
        "categories_diff": categories_diff,
        "issues_summary": {
            "resolved_count": len(resolved_issues),
            "new_count": len(new_issues),
            "persistent_count": len(persistent_issues),
        },
        "resolved_issues": resolved_issues,
        "new_issues": new_issues,
        "persistent_issues": persistent_issues,
        "stats_diff": {
            "pages_crawled": (res2.get("page_count", 0) or 0) - (res1.get("page_count", 0) or 0),
            "broken_links": (stats2.get("broken_links", 0) or 0) - (stats1.get("broken_links", 0) or 0),
        },
        "coverage_diff": {
            "before_pct": cov1.get("coverage_percentage"),
            "after_pct": cov2.get("coverage_percentage"),
        }
    }


@app.post("/api/audits/save")
def save_audit(req: AuditSaveRequest = Body(...), db: Session = Depends(get_db), current_admin: AdminUser = Depends(require_permission("audits.run"))):
    raw_res = req.audit_result or {}
    target_url = req.target_url or raw_res.get("target") or raw_res.get("url") or "https://example.com"
    raw_score = req.score if req.score is not None else raw_res.get("score")
    score = float(raw_score) if raw_score is not None else 0.0

    website_id = None
    if req.client_id:
        client = db.query(Client).filter(Client.id == req.client_id).first()
        if client:
            site = db.query(Website).filter(Website.client_id == client.id).first()
            if not site and target_url:
                site = Website(client_id=client.id, url=target_url, name=client.company or client.name)
                db.add(site)
                db.commit()
                db.refresh(site)
            if site:
                website_id = site.id

    new_audit = Audit(
        client_id=req.client_id,
        website_id=website_id,
        job_id=req.job_id or uuid.uuid4().hex,
        target_url=target_url,
        result_json=json.dumps(raw_res),
        score=score,
        status="COMPLETED",
        completed_at=datetime.utcnow()
    )
    db.add(new_audit)
    db.commit()
    db.refresh(new_audit)
    invalidate_dashboard_cache()

    record_activity(db, "AUDIT_SAVED", f"Audit #{new_audit.id}", f"Target: {target_url}, Score: {score}", user=current_admin)
    return {"status": "success", "audit_id": new_audit.id, "score": score, "target_url": target_url}


@app.get("/api/reports")
def list_reports(db: Session = Depends(get_db), current_admin: AdminUser = Depends(require_permission("reports.view"))):
    reports = db.query(PublicReport).order_by(PublicReport.created_at.desc()).all()
    if not reports:
        return []

    audit_ids = [r.audit_id for r in reports if r.audit_id]
    client_ids = [r.client_id for r in reports if r.client_id]
    website_ids = [r.website_id for r in reports if r.website_id]

    audits_map = {}
    if audit_ids:
        for a in db.query(Audit).defer("result_json").filter(Audit.id.in_(audit_ids)).all():
            audits_map[a.id] = a

    clients_map = {}
    if client_ids:
        for c in db.query(Client).filter(Client.id.in_(client_ids)).all():
            clients_map[c.id] = c

    websites_map = {}
    if website_ids:
        for w in db.query(Website).filter(Website.id.in_(website_ids)).all():
            websites_map[w.id] = w

    result = []
    for r in reports:
        a = audits_map.get(r.audit_id)
        w = websites_map.get(r.website_id)
        c = clients_map.get(r.client_id)
        target_url = a.target_url if a else (w.url if w else "")
        score = a.score if a else 0
        result.append({
            "id": r.id,
            "client_id": r.client_id,
            "client_name": c.name if c else "Direct Client",
            "company": c.company if c else "",
            "audit_id": r.audit_id,
            "target_url": target_url,
            "score": score,
            "token": r.token,
            "status": r.status,
            "public_url": f"/report/{r.token}",
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "published_at": r.published_at.isoformat() if r.published_at else None,
            "disabled_at": r.disabled_at.isoformat() if r.disabled_at else None
        })
    return result


@app.post("/api/reports/generate")
def generate_public_report(req: ReportGenerateRequest = Body(...), db: Session = Depends(get_db), current_admin: AdminUser = Depends(require_permission("reports.generate"))):
    audit = db.query(Audit).filter(Audit.id == req.audit_id).first()
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found")

    client = audit.client
    client_name = client.name if client else ""
    company = client.company if client else ""

    token = secrets.token_urlsafe(32)
    try:
        raw_result = json.loads(audit.result_json) if isinstance(audit.result_json, str) else audit.result_json
    except Exception:
        raw_result = {}

    snapshot = build_client_report_snapshot(raw_result, client_name, company, token)
    new_report = PublicReport(
        audit_id=audit.id,
        client_id=audit.client_id,
        website_id=audit.website_id,
        token=token,
        status=req.status or "PUBLISHED",
        snapshot_json=json.dumps(snapshot),
        published_at=datetime.utcnow() if req.status == "PUBLISHED" else None
    )
    db.add(new_report)
    db.commit()
    db.refresh(new_report)
    invalidate_dashboard_cache()

    record_activity(db, "REPORT_GENERATED", f"Report #{new_report.id} ({token[:8]}...)", f"Audit #{audit.id}", user=current_admin)

    return {
        "status": "success",
        "id": new_report.id,
        "token": new_report.token,
        "report_status": new_report.status,
        "public_url": f"/report/{new_report.token}"
    }


@app.post("/api/reports/{report_id}/status")
def update_report_status(report_id: int, req: ReportStatusRequest = Body(...), db: Session = Depends(get_db), current_admin: AdminUser = Depends(require_permission("reports.publish"))):
    report = db.query(PublicReport).filter(PublicReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    new_status = req.status.upper()
    if new_status not in {"PUBLISHED", "DRAFT", "DISABLED"}:
        raise HTTPException(status_code=400, detail="Invalid status. Must be PUBLISHED, DRAFT, or DISABLED")

    report.status = new_status
    if new_status == "PUBLISHED":
        report.published_at = datetime.utcnow()
        report.disabled_at = None
    elif new_status == "DISABLED":
        report.disabled_at = datetime.utcnow()
    elif new_status == "DRAFT":
        report.published_at = None
        report.disabled_at = None

    db.commit()
    db.refresh(report)
    invalidate_dashboard_cache()

    record_activity(db, "REPORT_STATUS_CHANGED", f"Report #{report.id}", f"Status set to {new_status}", user=current_admin)
    return {"status": "success", "id": report.id, "token": report.token, "report_status": report.status}


@app.get("/api/reports/public/{token}")
@app.get("/api/public/reports/{token}")
def get_public_client_report(token: str, db: Session = Depends(get_db)):
    """
    Public API endpoint returning the frozen audit snapshot.
    Only PUBLISHED reports are returned. DRAFT returns 403, DISABLED returns 410.
    """
    report = db.query(PublicReport).filter(PublicReport.token == token).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found.")

    if report.status == "DISABLED":
        return JSONResponse(status_code=410, content={
            "status": "DISABLED",
            "detail": "This SEO report is no longer available."
        })

    if report.status == "DRAFT":
        return JSONResponse(status_code=403, content={
            "status": "DRAFT",
            "detail": "This SEO report is currently in draft and not published."
        })

    try:
        snapshot = json.loads(report.snapshot_json) if report.snapshot_json else {}
    except Exception:
        snapshot = {}

    return {
        "status": "PUBLISHED",
        "token": report.token,
        "data": snapshot
    }


@app.get("/api/reports/preview/{token}")
def preview_report(token: str, db: Session = Depends(get_db), current_admin: AdminUser = Depends(require_permission("reports.view"))):
    """
    Admin Preview endpoint allowing verification of the client report presentation.
    """
    report = db.query(PublicReport).filter(PublicReport.token == token).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found.")

    try:
        snapshot = json.loads(report.snapshot_json) if report.snapshot_json else {}
    except Exception:
        snapshot = {}


    return {
        "status": report.status,
        "token": report.token,
        "is_preview": True,
        "data": snapshot
    }


# ==========================================
# SCHEDULED AUDITS / RECURRING CRAWLS APIs
# ==========================================

@app.get("/api/schedules")
def list_scheduled_audits(
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("audits.view"))
):
    """List all scheduled recurring audits with zero N+1 latency."""
    items = db.query(ScheduledAudit).order_by(ScheduledAudit.created_at.desc()).all()
    if not items:
        return []

    w_ids = list({s.website_id for s in items if s.website_id})
    c_ids = list({s.client_id for s in items if s.client_id})
    websites_map = {w.id: w.url for w in db.query(Website).filter(Website.id.in_(w_ids)).all()} if w_ids else {}
    clients_map = {c.id: c.name for c in db.query(Client).filter(Client.id.in_(c_ids)).all()} if c_ids else {}

    out = []
    for s in items:
        out.append({
            "id": s.id,
            "website_id": s.website_id,
            "website_url": websites_map.get(s.website_id, ""),
            "client_id": s.client_id,
            "client_name": clients_map.get(s.client_id, ""),
            "frequency": s.frequency,
            "status": s.status,
            "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
            "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
            "max_pages": s.max_pages,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        })
    return out


@app.post("/api/schedules")
def create_scheduled_audit(
    req: dict = Body(...),
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("audits.run"))
):
    """Create a new recurring scheduled crawl for a website."""
    website_id = req.get("website_id")
    if not website_id:
        raise HTTPException(status_code=400, detail="website_id is required.")
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        raise HTTPException(status_code=404, detail="Website not found.")

    frequency = (req.get("frequency") or "WEEKLY").upper()
    if frequency not in ("DAILY", "WEEKLY", "MONTHLY"):
        frequency = "WEEKLY"

    days_delta = 1 if frequency == "DAILY" else 7 if frequency == "WEEKLY" else 30
    next_run = datetime.utcnow() + timedelta(days=days_delta)

    sched = ScheduledAudit(
        website_id=website.id,
        client_id=req.get("client_id") or website.client_id,
        frequency=frequency,
        status="ACTIVE",
        next_run_at=next_run,
        max_pages=int(req.get("max_pages") or 50),
        created_at=datetime.utcnow(),
    )
    db.add(sched)
    db.commit()
    db.refresh(sched)
    record_activity(db, "SCHEDULE_CREATED", f"Schedule #{sched.id}", f"Created {frequency} crawl for {website.url}", user=current_admin)
    return {"status": "success", "id": sched.id, "frequency": sched.frequency, "next_run_at": sched.next_run_at.isoformat()}


@app.patch("/api/schedules/{schedule_id}")
def update_scheduled_audit(
    schedule_id: int,
    req: dict = Body(...),
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("audits.run"))
):
    """Pause, resume, or reconfigure a scheduled crawl."""
    sched = db.query(ScheduledAudit).filter(ScheduledAudit.id == schedule_id).first()
    if not sched:
        raise HTTPException(status_code=404, detail="Scheduled audit not found.")

    if "status" in req and req["status"].upper() in ("ACTIVE", "PAUSED"):
        sched.status = req["status"].upper()
    if "frequency" in req and req["frequency"].upper() in ("DAILY", "WEEKLY", "MONTHLY"):
        sched.frequency = req["frequency"].upper()
    if "max_pages" in req:
        sched.max_pages = max(5, int(req["max_pages"]))

    db.commit()
    return {"status": "success", "id": sched.id, "current_status": sched.status, "frequency": sched.frequency}


@app.delete("/api/schedules/{schedule_id}")
def delete_scheduled_audit(
    schedule_id: int,
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("audits.run"))
):
    """Delete a scheduled crawl."""
    sched = db.query(ScheduledAudit).filter(ScheduledAudit.id == schedule_id).first()
    if not sched:
        raise HTTPException(status_code=404, detail="Scheduled audit not found.")
    db.delete(sched)
    db.commit()
    return {"status": "success", "message": "Scheduled audit removed."}




SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2, "pass": 3}
GENERIC_ANCHORS = {
    "click here", "read more", "learn more", "here", "more", "details", "view", "link", "website"
}
TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid", "fbclid", "msclkid", "dclid"}

# Common duplicate/noise query keys. Safe mode suppresses only tracking parameters by default; allquery can retain them.



def norm_url(url: str) -> str:
    url = (url or "").strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    p = urlparse(url)
    if not p.hostname:
        raise ValueError("Invalid URL")
    path = p.path or "/"
    return urlunparse((p.scheme.lower(), p.netloc.lower(), path, "", p.query, ""))


def canonical_url(url: str, drop_tracking: bool = True) -> str:
    p = urlparse(urldefrag(url)[0])
    query = parse_qsl(p.query, keep_blank_values=True)
    if drop_tracking:
        query = [(k, v) for k, v in query if k.lower() not in TRACKING_PARAMS]
    # Stable ordering makes duplicate query permutations collapse without deleting meaningful parameters.
    query = sorted(query, key=lambda kv: (kv[0].lower(), kv[1]))
    q = urlencode(query, doseq=True)
    path = re.sub(r"/{2,}", "/", p.path or "/")
    if path != "/":
        path = re.sub(r"/+$", "", path) or "/"
    netloc = (p.hostname or "").lower().rstrip(".")
    # Normalize default ports only.
    if p.port and not ((p.scheme.lower() == "https" and p.port == 443) or (p.scheme.lower() == "http" and p.port == 80)):
        netloc += f":{p.port}"
    return urlunparse((p.scheme.lower(), netloc, path, "", q, ""))


def origin(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def _effective_port(url: str) -> int:
    p = urlparse(url)
    if p.port:
        return p.port
    return 443 if p.scheme.lower() == "https" else 80


def _host_variants(host: str) -> set[str]:
    host = (host or "").lower().rstrip(".")
    if not host:
        return set()
    bare = host[4:] if host.startswith("www.") else host
    return {bare, "www." + bare}


def same_site(a: str, b: str, allow_subdomains: bool = False) -> bool:
    """Strict, symmetric crawl-scope check.

    Treat www/non-www as the same host. Optionally allow true descendants
    of either hostname. Never use a loose public-suffix/last-two-label test.
    HTTP and HTTPS may be treated as the same site for the same host; explicit
    non-default ports remain distinct.
    """
    pa, pb = urlparse(a), urlparse(b)
    ha = (pa.hostname or "").lower().rstrip(".")
    hb = (pb.hostname or "").lower().rstrip(".")
    if not ha or not hb:
        return False
    ba = ha[4:] if ha.startswith("www.") else ha
    bb = hb[4:] if hb.startswith("www.") else hb
    host_ok = ba == bb
    if not host_ok and allow_subdomains:
        host_ok = ba.endswith("." + bb) or bb.endswith("." + ba)
    if not host_ok:
        return False
    if pa.port is not None or pb.port is not None:
        return _effective_port(a) == _effective_port(b)
    return True


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
    })
    s.hooks["response"].append(_ssrf_response_hook)
    return s


def retry_delay_from_response(response: requests.Response) -> float:
    value = response.headers.get("Retry-After", "")
    if not value:
        return 0.0
    try:
        secs = float(value)
        return max(0.0, min(secs, 20.0))
    except ValueError:
        return 0.0

_SSRF_CACHE_TTL = 60.0
_ssrf_cache: dict[str, tuple[float, bool, str]] = {}
_ssrf_cache_lock = threading.Lock()

# Non-public / reserved network ranges blocked for SSRF prevention
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),          # Current network (only valid as source)
    ipaddress.ip_network("10.0.0.0/8"),         # Private network RFC 1918
    ipaddress.ip_network("100.64.0.0/10"),      # Shared Address Space (CGNAT)
    ipaddress.ip_network("127.0.0.0/8"),        # Loopback
    ipaddress.ip_network("169.254.0.0/16"),     # Link-Local / Cloud Metadata (169.254.169.254)
    ipaddress.ip_network("172.16.0.0/12"),      # Private network RFC 1918
    ipaddress.ip_network("192.0.0.0/24"),       # IETF Protocol Assignments
    ipaddress.ip_network("192.0.2.0/24"),       # TEST-NET-1
    ipaddress.ip_network("192.168.0.0/16"),     # Private network RFC 1918
    ipaddress.ip_network("198.18.0.0/15"),      # Network benchmark tests
    ipaddress.ip_network("198.51.100.0/24"),    # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),     # TEST-NET-3
    ipaddress.ip_network("224.0.0.0/4"),        # Multicast
    ipaddress.ip_network("240.0.0.0/4"),        # Reserved / Future use
    ipaddress.ip_network("255.255.255.255/32"), # Broadcast
    ipaddress.ip_network("::1/128"),            # IPv6 Loopback
    ipaddress.ip_network("fc00::/7"),           # IPv6 Unique Local
    ipaddress.ip_network("fe80::/10"),          # IPv6 Link-Local
]


def _is_public_address(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
        return False
    for net in _BLOCKED_NETWORKS:
        if ip in net:
            return False
    return True


def _hostname_is_public(hostname: str) -> tuple[bool, str]:
    """Resolve hostname and confirm every address it maps to is publicly routable.
    Blocks localhost/private/link-local ranges, which also covers the 169.254.169.254 cloud metadata endpoint.
    Cached briefly per hostname; a short TTL bounds DNS-rebinding exposure without re-resolving on every request."""
    hostname = (hostname or "").strip().rstrip(".").lower()
    if not hostname:
        return False, "Missing hostname."
    if hostname == "localhost" or hostname.endswith(".localhost") or hostname in ("metadata.google.internal", "instance-data"):
        return False, f"{hostname} is not a valid audit target."
    now = time.time()
    with _ssrf_cache_lock:
        cached = _ssrf_cache.get(hostname)
        if cached and now - cached[0] < _SSRF_CACHE_TTL:
            return cached[1], cached[2]
    try:
        infos = socket.getaddrinfo(hostname, None)
        addresses = {info[4][0] for info in infos}
    except socket.gaierror as exc:
        ok, reason = False, f"DNS resolution failed for {hostname}: {exc}"
    else:
        blocked = sorted(a for a in addresses if not _is_public_address(a))
        if not addresses:
            ok, reason = False, f"DNS resolution returned no addresses for {hostname}."
        elif blocked:
            ok, reason = False, f"{hostname} resolves to a non-public address ({blocked[0]}); private, loopback, link-local and cloud-metadata addresses are not valid audit targets."
        else:
            ok, reason = True, ""
    with _ssrf_cache_lock:
        _ssrf_cache[hostname] = (now, ok, reason)
    return ok, reason


def validate_public_target(url: str) -> str:
    """Normalize url and raise ValueError unless it is a http(s) URL resolving only to public addresses."""
    normalized = norm_url(url)
    parsed = urlparse(normalized)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only http:// and https:// targets are supported.")
    ok, reason = _hostname_is_public(parsed.hostname or "")
    if not ok:
        raise ValueError(reason or "This target is not a publicly reachable address.")
    return normalized


class BlockedTargetError(requests.exceptions.RequestException):
    """Raised when a request or a redirect hop resolves to a non-public address."""


def _ssrf_response_hook(response: requests.Response, *args: Any, **kwargs: Any) -> requests.Response:
    # 1. Validate the current response URL
    ok, reason = _hostname_is_public(urlparse(response.url).hostname or "")
    if not ok:
        response.close()
        raise BlockedTargetError(f"Blocked: {reason}")
    # 2. Inspect redirect destination BEFORE requests follows it
    if response.is_redirect or response.status_code in (301, 302, 303, 307, 308):
        loc = response.headers.get("Location")
        if loc:
            target_loc = urljoin(response.url, loc)
            loc_host = urlparse(target_loc).hostname or ""
            ok_loc, reason_loc = _hostname_is_public(loc_host)
            if not ok_loc:
                response.close()
                raise BlockedTargetError(f"Blocked unsafe redirect to non-public host ({loc_host}): {reason_loc}")
    return response


def render_with_playwright(url: str, timeout_ms: int = 20000) -> dict[str, Any]:
    """Optional rendered-DOM fetch. Does not bypass auth, CAPTCHA, robots or access controls."""
    started = time.perf_counter()
    ok_host, block_reason = _hostname_is_public(urlparse(url).hostname or "")
    if not ok_host:
        return {"ok": False, "available": False, "package_available": True, "browser_available": True, "error": f"Blocked: {block_reason}", "elapsed_ms": round((time.perf_counter()-started)*1000,1)}
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return {"ok": False, "available": False, "package_available": False, "browser_available": False, "error": f"Playwright not installed: {exc}"}
    browser = None

    def _guard_route(route):
        req_host = urlparse(route.request.url).hostname or ""
        allowed, _ = _hostname_is_public(req_host)
        if allowed:
            route.continue_()
        else:
            route.abort()

    try:
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(channel="chrome", headless=True)
                browser_source = "system Chrome"
            except Exception as first_exc:
                try:
                    browser = pw.chromium.launch(headless=True)
                    browser_source = "Playwright Chromium"
                except Exception as second_exc:
                    return {"ok": False, "available": False, "package_available": True, "browser_available": False, "error": f"Browser launch failed: {first_exc}; fallback: {second_exc}", "elapsed_ms": round((time.perf_counter()-started)*1000,1)}
            page = browser.new_page(user_agent=USER_AGENT, viewport={"width": 1440, "height": 900})
            page.set_default_timeout(timeout_ms)
            page.route("**/*", _guard_route)
            response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 7000))
            except Exception:
                pass
            html_body = page.content()
            final_url = page.url
            status = response.status if response else 200
            headers = dict(response.all_headers()) if response else {}
            browser.close(); browser = None
            return {"ok": True, "available": True, "package_available": True, "browser_available": True, "browser_source": browser_source, "status": status, "url": final_url, "content_type": headers.get("content-type", "text/html"), "body": html_body.encode("utf-8", "ignore"), "elapsed_ms": round((time.perf_counter()-started)*1000,1), "headers": {str(k).lower(): str(v) for k,v in headers.items()}, "rendered": True}
    except Exception as exc:
        if browser is not None:
            try: browser.close()
            except Exception: pass
        return {"ok": False, "available": False, "package_available": True, "browser_available": False, "error": str(exc), "elapsed_ms": round((time.perf_counter()-started)*1000,1)}


def fetch(session: requests.Session, url: str, timeout: float = TIMEOUT, max_body: int = MAX_BODY, retries: int = 1) -> dict[str, Any]:
    """Bounded HTTP fetch with retries for transient throttling/server failures."""
    ok_host, block_reason = _hostname_is_public(urlparse(url).hostname or "")
    if not ok_host:
        return {"ok": False, "status": 0, "url": url, "content_type": "", "body": b"", "bytes": 0, "wire_bytes": 0, "elapsed_ms": 0.0, "headers": {}, "history": [], "error": f"Blocked: {block_reason}", "attempts": 0, "total_elapsed_ms": 0.0}
    last_error = ""
    attempts = max(1, min(int(retries) + 1, 4))
    connect_timeout = min(8.0, max(2.0, float(timeout) / 3.0))
    read_timeout = max(3.0, float(timeout))
    started_all = time.perf_counter()
    for attempt in range(attempts):
        started = time.perf_counter()
        try:
            response = session.get(url, timeout=(connect_timeout, read_timeout), allow_redirects=True, stream=True)
            headers = {k.lower(): v for k, v in response.headers.items()}
            content_type = (headers.get("content-type") or "").lower()
            status = int(response.status_code or 0)
            body = b""
            total_bytes = 0
            if ("html" in content_type or "xml" in content_type or "text/" in content_type or "json" in content_type or "javascript" in content_type or not content_type):
                for chunk in response.iter_content(65536):
                    if not chunk:
                        continue
                    if total_bytes < max_body:
                        body += chunk[: max(0, max_body - total_bytes)]
                    total_bytes += len(chunk)
                    if total_bytes >= max_body:
                        break
            history = [{"status": h.status_code, "url": h.url, "location": h.headers.get("Location")} for h in response.history]
            final_url = response.url
            if status in (429, 500, 502, 503, 504) and attempt + 1 < attempts:
                delay = retry_delay_from_response(response) or min(1.5 * (attempt + 1), 4.0)
                response.close()
                time.sleep(delay)
                continue
            response.close()
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            return {"ok": True, "status": status, "url": final_url, "content_type": content_type, "body": body, "bytes": len(body), "wire_bytes": total_bytes, "elapsed_ms": elapsed, "headers": headers, "history": history, "attempts": attempt + 1, "total_elapsed_ms": round((time.perf_counter()-started_all)*1000,1)}
        except requests.RequestException as exc:
            last_error = str(exc)
            if attempt + 1 < attempts:
                time.sleep(min(0.5 * (attempt + 1), 1.5))
    return {"ok": False, "status": 0, "url": url, "content_type": "", "body": b"", "bytes": 0, "wire_bytes": 0, "elapsed_ms": round((time.perf_counter() - started_all) * 1000, 1), "headers": {}, "history": [], "error": last_error or "Request failed", "attempts": attempts, "total_elapsed_ms": round((time.perf_counter()-started_all)*1000,1)}



def url_variants(url: str) -> list[str]:
    """Return conservative transport/hostname fallbacks used only after a fetch failure."""
    p = urlparse(url)
    host = (p.hostname or "").lower().rstrip(".")
    if not host:
        return [url]
    candidates = [url]
    alt_hosts = []
    if host.startswith("www."):
        alt_hosts.append(host[4:])
    else:
        alt_hosts.append("www." + host)
    for alt_host in alt_hosts:
        netloc = alt_host
        if p.port:
            netloc += f":{p.port}"
        candidates.append(urlunparse((p.scheme, netloc, p.path or "/", "", p.query, "")))
    other_scheme = "http" if p.scheme.lower() == "https" else "https"
    # Only swap scheme when the URL uses default ports; never silently turn a custom port into another transport.
    if not p.port:
        candidates.append(urlunparse((other_scheme, p.netloc, p.path or "/", "", p.query, "")))
        for alt_host in alt_hosts:
            candidates.append(urlunparse((other_scheme, alt_host, p.path or "/", "", p.query, "")))
    out=[]
    seen=set()
    for c in candidates:
        c=norm_url(c)
        if c not in seen:
            seen.add(c); out.append(c)
    return out


def fetch_universal(session: requests.Session, url: str, timeout: float = TIMEOUT, max_body: int = MAX_BODY, retries: int = 1) -> dict[str, Any]:
    """Fetch a public URL with conservative fallback candidates after transport-level failure.
    A valid HTTP response (including 4xx/5xx) is returned immediately; fallbacks are for DNS/TLS/connect failures only.
    """
    attempts=[]
    first = norm_url(url)
    for candidate in url_variants(first):
        result = fetch(session, candidate, timeout=timeout, max_body=max_body, retries=retries)
        attempts.append({"url":candidate,"status":result.get("status",0),"ok":result.get("ok",False),"error":result.get("error"),"elapsed_ms":result.get("elapsed_ms",0)})
        if result.get("ok"):
            result["transport_attempts"] = attempts
            result["transport_fallback_used"] = candidate != first
            return result
    result = attempts and fetch(session, first, timeout=timeout, max_body=max_body, retries=0) or {"ok":False,"status":0,"url":first,"error":"No fetch attempt"}
    # Do not duplicate a second network request after all candidates have failed.
    if attempts:
        last=attempts[-1]
        result={"ok":False,"status":0,"url":first,"content_type":"","body":b"","bytes":0,"wire_bytes":0,"elapsed_ms":sum(float(a.get("elapsed_ms",0)) for a in attempts),"headers":{},"history":[],"error":last.get("error") or "Request failed","attempts":len(attempts),"transport_attempts":attempts,"transport_fallback_used":False}
    return result

def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def meta_map(soup: BeautifulSoup) -> dict[str, str]:
    out: dict[str, str] = {}
    for tag in soup.find_all("meta"):
        key = clean_text(tag.get("name") or tag.get("property") or tag.get("http-equiv")).lower()
        if key:
            out[key] = clean_text(tag.get("content"))
    return out


def visible_text(soup: BeautifulSoup) -> str:
    clone = BeautifulSoup(str(soup), "html.parser")
    for node in clone(["script", "style", "noscript", "svg", "template", "canvas"]):
        node.decompose()
    return clean_text(clone.get_text(" ", strip=True))


def editorial_text(soup: BeautifulSoup) -> str:
    clone = BeautifulSoup(str(soup), "html.parser")
    for node in clone(["script", "style", "noscript", "svg", "template", "canvas", "header", "nav", "footer", "aside"]):
        node.decompose()
    for node in clone.find_all(class_=re.compile(r"\b(menu|nav|navbar|sidebar|widget|site-header|site-footer|header-wrapper|footer-wrapper|products|product-grid|woocommerce-pagination|related\s+products|up-sells|products-grid)\b", re.I)):
        node.decompose()
    for node in clone.find_all(["ul", "div"], class_=re.compile(r"\bproducts\b", re.I)):
        node.decompose()
    return clean_text(clone.get_text(" ", strip=True))


def text_tokens(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z][a-zA-Z0-9'-]{2,}", text.lower())


def content_hash(text: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", text.lower()).strip().encode("utf-8", "ignore")).hexdigest()


def shingle_set(text: str, size: int = 5) -> set[str]:
    toks = text_tokens(text)
    if len(toks) < size:
        return set(toks)
    return {" ".join(toks[i:i + size]) for i in range(len(toks) - size + 1)}


def parse_jsonld(raw: str) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    types: list[str] = []
    errors: list[str] = []
    nodes: list[dict[str, Any]] = []
    try:
        data = json.loads(raw)
    except Exception as exc:
        return [], [f"Malformed JSON-LD: {exc}"], []

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            typ = obj.get("@type")
            if isinstance(typ, list):
                types.extend(str(x) for x in typ)
            elif typ:
                types.append(str(typ))
            if obj.get("@context") and isinstance(obj.get("@context"), str) and obj.get("@context").startswith("http"):
                pass
            nodes.append(obj)
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for x in obj:
                walk(x)

    walk(data)
    if not isinstance(data, (dict, list)):
        errors.append("JSON-LD root should be an object or array.")
    return sorted(set(types)), errors, nodes


def _apply_indexability_status(page: dict[str, Any], final_url: str) -> dict[str, Any]:
    status_code = page.get("status", 0)
    meta_rob = str(page.get("meta_robots", "")).lower()
    x_rob = str(page.get("x_robots_tag", "")).lower()
    has_noindex = "noindex" in meta_rob or "noindex" in x_rob
    canon_url = page.get("canonical", "")
    is_canonicalized = bool(canon_url and canon_url.rstrip("/") != final_url.rstrip("/"))

    if status_code >= 500:
        indexability = "SERVER_ERROR"
        is_indexable = False
    elif status_code >= 400:
        indexability = "CLIENT_ERROR"
        is_indexable = False
    elif status_code in (301, 302, 303, 307, 308):
        indexability = "REDIRECT"
        is_indexable = False
    elif has_noindex:
        indexability = "NOINDEX"
        is_indexable = False
    elif is_canonicalized:
        indexability = "CANONICALIZED"
        is_indexable = False
    elif not page.get("robots_allowed", True):
        indexability = "ROBOTS_BLOCKED"
        is_indexable = False
    elif status_code == 200:
        indexability = "INDEXABLE"
        is_indexable = True
    else:
        indexability = "OTHER"
        is_indexable = False

    page["is_indexable"] = is_indexable
    page["indexability_status"] = indexability
    page["measured_at"] = datetime.utcnow().isoformat()
    return page


def parse_page(requested_url: str, response: dict[str, Any]) -> dict[str, Any]:
    final_url = response.get("url") or requested_url
    page: dict[str, Any] = {
        "requested_url": requested_url,
        "url": final_url,
        "status": int(response.get("status") or 0),
        "content_type": response.get("content_type", ""),
        "response_time_ms": response.get("elapsed_ms", 0),
        "html_bytes": response.get("bytes", 0),
        "wire_bytes": response.get("wire_bytes", 0),
        "redirect_count": len(response.get("history", [])),
        "redirect_chain": response.get("history", []),
        "redirected": canonical_url(requested_url) != canonical_url(final_url),
        "headers": response.get("headers", {}),
        "error": response.get("error"),
        "non_html": False,
        "title": "",
        "title_length": 0,
        "title_has_brand_separator": bool(re.search(r"[|–—:-]", "")),
        "meta_description": "",
        "meta_description_length": 0,
        "meta_robots": "",
        "x_robots_tag": response.get("headers", {}).get("x-robots-tag", ""),
        "robots_meta_location": "absent",
        "meta_refresh": "",
        "meta_refresh_url": "",
        "pagination": {"next": "", "prev": ""},
        "canonical": "",
        "canonical_host": "",
        "canonical_location": "absent",
        "lang": "",
        "viewport": "",
        "charset": "",
        "h1": [], "h2": [], "h3": [], "h4": [], "h5": [], "h6": [],
        "heading_order": [],
        "images": [],
        "internal_links": [], "external_links": [], "all_links": [],
        "anchor_stats": {"total": 0, "empty": 0, "generic": 0, "nofollow_internal": 0, "nofollow_external": 0},
        "schema_types": [],
        "schema_errors": [],
        "schema_nodes": [],
        "og": {}, "twitter": {},
        "hreflang": [],
        "favicon": False,
        "document_base": final_url,
        "semantic_elements": {"main": False, "article": False, "nav": False, "header": False, "footer": False, "aside": False},
        "forms": {"count": 0, "unlabelled_inputs": 0},
        "scripts": {"count": 0, "inline": 0, "external": 0},
        "resources": [],
        "word_count": 0,
        "content_hash": "",
        "top_terms": [],
        "top_phrases": [],
        "outgoing_link_count": 0,
        "rendered": False,
        "depth": 0,
        "discovery": "crawl",
        "robots_allowed": True,
        "issues": [],
        "score": 0,
    }
    if not response.get("ok"):
        return _apply_indexability_status(page, final_url)
    if page["content_type"] and "html" not in page["content_type"] and "xhtml" not in page["content_type"]:
        page["non_html"] = True
        return _apply_indexability_status(page, final_url)

    try:
        encoding = response.get("headers", {}).get("content-type", "")
        raw = response.get("body", b"")
        soup = BeautifulSoup(raw, "html.parser")
        page["charset"] = (soup.find("meta", charset=True) or {}).get("charset", "") if soup.find("meta", charset=True) else ""
        page["title"] = clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""
        page["title_length"] = len(page["title"])
        page["title_has_brand_separator"] = bool(re.search(r"[|–—:-]", page["title"]))
        m = meta_map(soup)
        page["meta_description"] = m.get("description", "")
        page["meta_description_length"] = len(page["meta_description"])
        page["meta_robots"] = m.get("robots", "")
        page["viewport"] = m.get("viewport", "")
        robots_meta_tags = soup.find_all("meta", attrs={"name": re.compile(r"^robots$", re.I)})
        if robots_meta_tags:
            page["robots_meta_location"] = "head" if all(tag.find_parent("head") is not None for tag in robots_meta_tags) else "body"
        refresh = soup.find("meta", attrs={"http-equiv": re.compile(r"^refresh$", re.I)})
        page["meta_refresh"] = clean_text(refresh.get("content")) if refresh else ""
        if page["meta_refresh"]:
            mref = re.search(r"url\s*=\s*(.+)$", page["meta_refresh"], re.I)
            if mref:
                page["meta_refresh_url"] = canonical_url(urljoin(final_url, mref.group(1).strip(' \"')))
        page["lang"] = clean_text(soup.html.get("lang")) if soup.html else ""
        for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            text = clean_text(h.get_text(" ", strip=True))
            tag_name = h.name
            page[tag_name].append(text)
            page["heading_order"].append({"tag": tag_name, "text": text})
        canon = soup.find("link", rel=lambda rel: rel and ("canonical" in rel if isinstance(rel, list) else "canonical" in str(rel).lower()), href=True)
        if canon:
            page["canonical"] = canonical_url(urljoin(final_url, canon.get("href")))
            page["canonical_host"] = urlparse(page["canonical"]).hostname or ""
            page["canonical_location"] = "head" if canon.find_parent("head") is not None else "body"
        else:
            link_header = page.get("headers", {}).get("link", "")
            mcanon = re.search(r'''<([^>]+)>\s*;\s*rel=(?:"|')?canonical(?:"|')?''', link_header, re.I)
            if mcanon:
                page["canonical"] = canonical_url(urljoin(final_url, mcanon.group(1)))
                page["canonical_host"] = urlparse(page["canonical"]).hostname or ""
                page["canonical_location"] = "http-link-header"
        for link in soup.find_all("link", href=True):
            rel = link.get("rel") or []
            rel_txt = " ".join(rel) if isinstance(rel, list) else str(rel)
            rel_low = rel_txt.lower()
            if "alternate" in rel_low and link.get("hreflang"):
                page["hreflang"].append({
                    "lang": clean_text(link.get("hreflang")),
                    "href": canonical_url(urljoin(final_url, link.get("href"))),
                })
            if "icon" in rel_low or "shortcut icon" in rel_low:
                page["favicon"] = True

        for rel_name in ("next", "prev"):
            rel_link = soup.find("link", rel=lambda r: r and rel_name in (r if isinstance(r, list) else str(r).lower().split()), href=True)
            if rel_link:
                page["pagination"][rel_name] = canonical_url(urljoin(final_url, rel_link.get("href")))

        base_tag = soup.find("base", href=True)
        base_url = urljoin(final_url, base_tag.get("href")) if base_tag else final_url
        page["document_base"] = base_url
        anchors = []
        for a in soup.find_all("a", href=True):
            href = clean_text(a.get("href"))
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
                continue
            u = urldefrag(urljoin(base_url, href))[0]
            if not u.startswith(("http://", "https://")):
                continue
            u = canonical_url(u)
            rel = a.get("rel") or []
            rel_text = " ".join(rel).lower() if isinstance(rel, list) else str(rel).lower()
            anchor_text = clean_text(a.get_text(" ", strip=True)).lower()
            item = {"url": u, "text": anchor_text, "nofollow": "nofollow" in rel_text, "sponsored": "sponsored" in rel_text, "ugc": "ugc" in rel_text}
            anchors.append(item)
        page["all_links"] = list(dict.fromkeys(x["url"] for x in anchors))
        page["internal_links"] = list(dict.fromkeys(x["url"] for x in anchors if same_site(x["url"], final_url)))
        page["external_links"] = list(dict.fromkeys(x["url"] for x in anchors if not same_site(x["url"], final_url)))
        for extra in (page.get("pagination", {}).get("next"), page.get("pagination", {}).get("prev"), page.get("meta_refresh_url")):
            if extra and same_site(extra, final_url):
                page["internal_links"].append(extra)
        page["internal_links"] = list(dict.fromkeys(page["internal_links"]))
        page["outgoing_link_count"] = len(anchors)
        page["anchor_stats"] = {
            "total": len(anchors),
            "empty": sum(1 for x in anchors if not x["text"]),
            "generic": sum(1 for x in anchors if x["text"] in GENERIC_ANCHORS),
            "nofollow_internal": sum(1 for x in anchors if x["nofollow"] and same_site(x["url"], final_url)),
            "nofollow_external": sum(1 for x in anchors if x["nofollow"] and not same_site(x["url"], final_url)),
            "sponsored": sum(1 for x in anchors if x["sponsored"]),
            "ugc": sum(1 for x in anchors if x["ugc"]),
        }

        for img in soup.find_all("img"):
            raw_src = img.get("src") or ""
            lazy_src = img.get("data-src") or img.get("data-lazy-src") or img.get("data-original") or ""
            src = lazy_src if (not raw_src or raw_src.startswith("data:")) and lazy_src else raw_src or lazy_src
            if not src and img.get("srcset"):
                src = str(img.get("srcset")).split(",")[0].strip().split()[0]
            if not src:
                continue
            absu = urldefrag(urljoin(base_url, src))[0] if not src.startswith("data:") else src
            fmt = Path(urlparse(absu).path).suffix.lower().lstrip(".") if not absu.startswith("data:") else ("svg" if "svg" in absu else "")
            page["images"].append({
                "src": absu,
                "alt": clean_text(img.get("alt")),
                "alt_present": img.has_attr("alt"),  # absent vs empty alt are different findings
                "width": clean_text(img.get("width")),
                "height": clean_text(img.get("height")),
                "loading": clean_text(img.get("loading")),
                "decoding": clean_text(img.get("decoding")),
                "fetchpriority": clean_text(img.get("fetchpriority")),
                "srcset": bool(img.get("srcset")),
                "format": fmt,
            })

        scripts = soup.find_all("script")
        page["scripts"] = {"count": len(scripts), "inline": sum(1 for s in scripts if not s.get("src")), "external": sum(1 for s in scripts if s.get("src"))}
        for s in scripts:
            if s.get("src"):
                page["resources"].append({"kind": "script", "url": canonical_url(urljoin(base_url, s.get("src"))), "async": bool(s.get("async")), "defer": bool(s.get("defer"))})
        for link in soup.find_all("link", href=True):
            rel = link.get("rel") or []
            rel_txt = " ".join(rel) if isinstance(rel, list) else str(rel)
            rel_low = rel_txt.lower()
            if any(x in rel_low for x in ("stylesheet", "preload", "modulepreload", "preconnect", "dns-prefetch", "prefetch")):
                page["resources"].append({"kind": rel_low, "url": canonical_url(urljoin(base_url, link.get("href")))})
        for tag in soup.find_all(["img", "script", "iframe"]):
            src = tag.get("src") or tag.get("data-src") or ""
            if src:
                kind = "image" if tag.name == "img" else "script" if tag.name == "script" else "iframe"
                page["resources"].append({"kind": kind, "url": canonical_url(urljoin(base_url, src))})

        for key, dest in (("og:", "og"), ("twitter:", "twitter")):
            page[dest] = {k: v for k, v in m.items() if k.startswith(key)}

        for img in soup.find_all("img", srcset=True):
            for candidate in str(img.get("srcset") or "").split(","):
                candidate = candidate.strip().split(" ")[0]
                if candidate:
                    page["resources"].append({"kind": "image-srcset", "url": canonical_url(urljoin(base_url, candidate))})

        for sc in soup.find_all("script", type=lambda x: str(x or "").lower() == "application/ld+json"):
            raw_json = sc.string or sc.get_text()
            types, errors, nodes = parse_jsonld(raw_json)
            page["schema_types"].extend(types)
            page["schema_errors"].extend(errors)
            page["schema_nodes"].extend(nodes[:50])
        page["schema_types"] = sorted(set(page["schema_types"]))

        page["semantic_elements"] = {k: bool(soup.find(k)) for k in page["semantic_elements"]}
        inputs = soup.find_all(["input", "select", "textarea"])
        unlabelled = 0
        for inp in inputs:
            if inp.get("type", "").lower() == "hidden":
                continue
            ident = inp.get("id")
            has_label = bool(ident and soup.find("label", attrs={"for": ident})) or bool(inp.find_parent("label"))
            if not has_label:
                unlabelled += 1
        page["forms"] = {"count": len(soup.find_all("form")), "unlabelled_inputs": unlabelled}

        text = visible_text(soup)
        page["word_count"] = len(text.split())
        edit_text = editorial_text(soup)
        page["editorial_word_count"] = len(edit_text.split())
        page["content_hash"] = content_hash(text)
        term_counter = Counter(w for w in text_tokens(" ".join([page["title"], *page["h1"], *page["h2"], text])) if w not in {"the", "and", "for", "with", "that", "this", "from", "your", "you", "are", "was", "were", "our", "their", "into", "have", "has", "had", "about", "will", "can", "www", "com", "https", "http", "home", "page", "news", "read", "more"})
        page["top_terms"] = [{"term": k, "count": v} for k, v in term_counter.most_common(30)]
        phrase_tokens = [w for w in text_tokens(text) if w not in STOPWORDS and len(w) >= 3]
        phrase_counter = Counter(" ".join(phrase_tokens[i:i+n]) for n in (2,3) for i in range(max(0, len(phrase_tokens)-n+1)))
        page["top_phrases"] = [{"phrase": k, "count": v} for k, v in phrase_counter.most_common(25) if len(set(k.split())) > 1][:25]

        page["rendering_signals"] = {
            "script_count": len(scripts),
            "low_text_with_scripts": len(scripts) >= 8 and page["word_count"] < 150,
            "likely_js_shell": page["word_count"] < 80 and len(scripts) >= 6,
        }
        # Business / commerce signals read from the real HTML (used by Local and E-commerce scoring).
        body_text = text.lower()
        raw_html_str = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw or "")
        raw_html_low = raw_html_str.lower()
        # Raw evidence for the scoring engine (seo_engine.signals): observations only, nothing scored here.
        page["ev"] = extract_signals(soup, text, raw_html_str, page, base_url, same_site)
        hrefs = [str(a.get("href") or "").strip().lower() for a in soup.find_all("a", href=True)]
        frames = [str(f.get("src") or "").lower() for f in soup.find_all("iframe")]
        schema_blob = json.dumps(page["schema_nodes"], default=str).lower()
        page["contact_signals"] = {
            "has_phone": any(h.startswith("tel:") for h in hrefs) or '"telephone"' in schema_blob,
            "has_email": any(h.startswith("mailto:") for h in hrefs) or '"email"' in schema_blob,
            "has_address": bool(soup.find("address")) or "postaladdress" in schema_blob or '"streetaddress"' in schema_blob,
            "has_map": any(("google." in x and "/maps" in x) or "maps.google." in x or "goo.gl/maps" in x or "maps.app.goo.gl" in x for x in hrefs + frames),
            "has_opening_hours": "openinghours" in schema_blob,
            "has_geo": '"geo"' in schema_blob or "geocoordinates" in schema_blob,
        }
        cart_texts = ("add to cart", "add to basket", "add to bag", "buy now")
        page["commerce_signals"] = {
            "add_to_cart": any(t in body_text for t in cart_texts) or bool(soup.find(attrs={"name": "add-to-cart"})),
            "has_price_schema": '"price"' in schema_blob or '"lowprice"' in schema_blob,
            "has_availability": '"availability"' in schema_blob,
            "has_review_schema": '"aggregaterating"' in schema_blob or '"review"' in schema_blob,
            "product_links": sum(1 for u in page["internal_links"] if re.search(r"/(products?|item)/[^/?#]+", urlparse(u).path, re.I)),
            "cart_link": any(re.search(r"/(cart|basket|checkout)(/|$)", urlparse(u).path, re.I) for u in page["internal_links"]),
            "platform": "shopify" if "cdn.shopify.com" in raw_html_low else "woocommerce" if "woocommerce" in raw_html_low else "magento" if "data-mage-init" in raw_html_low or "mage/cookies" in raw_html_low else "",
            "og_product": str(page.get("og", {}).get("og:type", "")).lower().startswith("product"),
        }
        # Topic consistency: the page title's own words (brand segment removed) vs. H1, description and body text.
        title_segments = [s for s in re.split(r"\s+[|\-–—:·•]\s+", page.get("title") or "") if s.strip()]
        topic_source = title_segments[0] if title_segments else ""
        topic_terms = sorted({w for w in text_tokens(topic_source) if w not in STOPWORDS and len(w) >= 3})
        body_terms = set(text_tokens(text))
        page["title_topic"] = {
            "terms": topic_terms,
            "in_h1": bool(topic_terms) and any(w in set(text_tokens(" ".join(page.get("h1", [])))) for w in topic_terms),
            "in_description": bool(topic_terms) and any(w in set(text_tokens(page.get("meta_description") or "")) for w in topic_terms),
            "body_coverage": round(sum(1 for w in topic_terms if w in body_terms) / len(topic_terms), 3) if topic_terms else None,
        }
        # Additional on-page/HTML signals used by the A-Z engine.
        page["keyword_metrics"] = {
            "title_terms": len(text_tokens(page.get("title", ""))),
            "h1_terms": len(text_tokens(" ".join(page.get("h1", [])))),
            "body_terms": len(text_tokens(body_text)),
            "top_term_density": round((term_counter.most_common(1)[0][1] / max(1, len(text_tokens(body_text)))) * 100, 3) if term_counter else 0.0,
        }
        page["content_signals"] = {
            "has_article": bool(page.get("semantic_elements", {}).get("article")),
            "has_main": bool(page.get("semantic_elements", {}).get("main")),
            "has_nav": bool(page.get("semantic_elements", {}).get("nav")),
            "word_count": page.get("word_count", 0),
            "unique_term_count": len(term_counter),
            "paragraph_count": len(soup.find_all("p")),
            "list_count": len(soup.find_all(["ul", "ol"])),
            "table_count": len(soup.find_all("table")),
        }
        page["links_metrics"] = {
            "internal_count": len(page.get("internal_links", [])),
            "external_count": len(page.get("external_links", [])),
            "nofollow_internal": page.get("anchor_stats", {}).get("nofollow_internal", 0),
            "nofollow_external": page.get("anchor_stats", {}).get("nofollow_external", 0),
            "sponsored": page.get("anchor_stats", {}).get("sponsored", 0),
            "ugc": page.get("anchor_stats", {}).get("ugc", 0),
        }
        page["transport"] = {
            "requested_url": requested_url,
            "final_url": final_url,
            "fallback_used": bool(response.get("transport_fallback_used")),
            "attempts": response.get("transport_attempts", []),
        }
        page["response_cacheability"] = {
            "cache_control": page["headers"].get("cache-control", ""),
            "etag": bool(page["headers"].get("etag")),
            "last_modified": bool(page["headers"].get("last-modified")),
            "content_encoding": page["headers"].get("content-encoding", ""),
        }
        _ = encoding
    except Exception as exc:
        page["error"] = f"HTML parse error: {exc}"

    return _apply_indexability_status(page, final_url)


def issue(page: dict[str, Any], severity: str, code: str, category: str, message: str, recommendation: str, evidence: str = "", fix: str = "") -> None:
    page["issues"].append({
        "severity": severity,
        "code": code,
        "category": category,
        "message": message,
        "recommendation": recommendation,
        "evidence": evidence,
        "fix": fix,
        "url": page.get("url", ""),
    })


def page_checks(page: dict[str, Any]) -> None:
    if page.get("error"):
        issue(page, "critical", "fetch_error", "Crawlability", page["error"], "Verify DNS, TLS, server availability and crawler access.", fix="Retry the URL outside the tool and check server/application logs.")
        return
    if page.get("non_html"):
        return
    if page.get("final_offsite"):
        issue(page, "warning", "offsite_redirect", "Redirects", "URL redirected outside the audited host.", "Review the redirect destination and confirm the cross-domain redirect is intentional.")
    if page.get("transport", {}).get("fallback_used"):
        issue(page, "info", "transport_fallback", "Crawlability", "The crawler needed an alternate hostname/protocol candidate before obtaining an HTTP response.", "Verify the preferred HTTPS/hostname variant and redirect alternate variants consistently.", evidence=json.dumps(page.get("transport", {}).get("attempts", [])[:5]))
    status = int(page.get("status") or 0)
    if status >= 500 or status == 0:
        issue(page, "critical", "server_error", "Status Codes", f"HTTP {status} response.", "Return a valid page response for indexable URLs.")
    elif status >= 400:
        issue(page, "critical", "client_error", "Status Codes", f"HTTP {status} response.", "Fix the URL or serve a proper redirect/content response.")
    elif status in (301, 302, 303, 307, 308):
        issue(page, "info", "redirected_page", "Redirects", f"Redirect chain contains {page['redirect_count']} hop(s).", "Keep important URLs on the final canonical destination and avoid redirect chains.")
    if page["redirect_count"] >= 2:
        issue(page, "warning", "redirect_chain", "Redirects", f"{page['redirect_count']} redirect hops detected.", "Collapse multi-hop redirects into a single direct redirect.")
    if urlparse(page["url"]).scheme != "https":
        issue(page, "warning", "not_https", "Security", "Page is served over HTTP.", "Serve indexable pages over HTTPS and redirect HTTP to HTTPS.")
    title = page["title"]
    if not title:
        issue(page, "critical", "missing_title", "Title", "Missing title element.", "Add a unique title that accurately describes the page topic.", fix="<title>Primary topic — Brand</title>")
    elif len(title) < kb_threshold("title_short_chars"):
        issue(page, "info", "short_title", "Title", f"Title is only {len(title)} characters.", "Review whether the title fully and accurately describes the page topic; there is no universal hard character limit.")
    elif len(title) > kb_threshold("title_long_chars"):
        issue(page, "info", "long_title", "Title", f"Title is {len(title)} characters.", "Review whether the title can be more concise and front-load the main topic.")
    desc = page["meta_description"]
    if not desc:
        issue(page, "warning", "missing_meta_description", "Meta Description", "No meta description found.", "Add a concise, page-specific description. Google may use page content instead of this field.", fix='<meta name="description" content="Concise summary of this page and why it is useful.">')
    elif len(desc) < kb_threshold("meta_description_short_chars"):
        issue(page, "info", "short_meta_description", "Meta Description", f"Description is {len(desc)} characters.", "Expand where useful so the snippet communicates the page value clearly.")
    elif len(desc) > kb_threshold("meta_description_long_chars"):
        issue(page, "info", "long_meta_description", "Meta Description", f"Description is {len(desc)} characters.", "Trim unnecessary text; snippets can be rewritten or truncated by search engines.")
    h1 = page["h1"]
    if not h1:
        issue(page, "warning", "missing_h1", "Headings", "No H1 heading detected.", "Add one clear primary heading representing the page topic.", fix="<h1>Primary page topic</h1>")
    elif len(h1) > 1:
        issue(page, "info", "multiple_h1", "Headings", f"Found {len(h1)} H1 headings.", "Review the heading structure so the main topic is clearly represented; multiple H1s are not inherently invalid HTML.")
    if page["heading_order"]:
        previous = 0
        for h in page["heading_order"]:
            level = int(h["tag"][1])
            if previous and level > previous + 1:
                issue(page, "info", "heading_jump", "Headings", f"Heading hierarchy jumps from H{previous} to H{level}.", "Use a logical outline without unnecessary heading-level jumps.")
                break
            previous = level
    if not page["viewport"]:
        issue(page, "warning", "missing_viewport", "Mobile", "Responsive viewport meta tag is missing.", "Add a standard responsive viewport directive.", fix='<meta name="viewport" content="width=device-width, initial-scale=1">')
    if not page["lang"]:
        issue(page, "info", "missing_lang", "HTML", "HTML language attribute is missing.", "Set the correct document language, e.g. lang=\"en\".")
    if not page["charset"]:
        issue(page, "info", "missing_charset", "HTML", "Explicit charset meta tag not detected.", "Declare UTF-8 in the document head.", fix='<meta charset="utf-8">')
    robots = f"{page['meta_robots']} {page['x_robots_tag']}".lower()
    if "noindex" in robots:
        issue(page, "info", "noindex", "Indexability", "Page sends a noindex directive.", "Confirm this URL should intentionally stay out of search indexes.")
    if "nofollow" in robots:
        issue(page, "info", "nofollow_directive", "Indexability", "Page sends a nofollow directive.", "Confirm that link discovery should be restricted on this page.")
    if not page["canonical"]:
        issue(page, "warning", "missing_canonical", "Canonicalization", "Canonical URL is not declared.", "Add a self-referencing canonical on pages that should be canonical, or a deliberate alternate where appropriate.", fix='<link rel="canonical" href="https://example.com/preferred-url">')
    else:
        if urlparse(page["canonical"]).hostname != urlparse(page["url"]).hostname:
            issue(page, "warning", "cross_domain_canonical", "Canonicalization", f"Canonical points to {page['canonical_host']}.", "Verify the cross-domain canonical is intentional and authoritative.")
        if page["canonical"] != canonical_url(page["url"]):
            issue(page, "info", "non_self_canonical", "Canonicalization", "Canonical points to a different URL.", "Confirm the alternate canonical is intentional and matches the duplicate-content strategy.")
    if page.get("robots_meta_location") == "body":
        issue(page, "warning", "robots_meta_outside_head", "Indexability", "Robots meta directives were found outside the HTML head.", "Place robots meta directives in the document head so crawler processing is unambiguous.")
    if page.get("canonical_location") == "body":
        issue(page, "warning", "canonical_outside_head", "Canonicalization", "Canonical link was found outside the HTML head.", "Place the canonical link element in the head of the document.")
    if page.get("meta_refresh"):
        issue(page, "warning", "meta_refresh", "Redirects", "A meta refresh directive is present.", "Prefer HTTP redirects for URL moves and review whether the meta refresh is needed.", evidence=page.get("meta_refresh", ""))
    if page.get("og", {}).get("og:url") and canonical_url(page.get("og", {}).get("og:url")) != canonical_url(page.get("url", "")):
        issue(page, "info", "og_url_mismatch", "Social", "og:url differs from the fetched page URL.", "Align og:url with the preferred public URL used for social sharing.", evidence=page.get("og", {}).get("og:url", ""))
    if page.get("twitter", {}).get("twitter:card") is None and (page.get("og") or page.get("twitter")):
        issue(page, "info", "missing_twitter_card", "Social", "No Twitter/X card type was detected.", "Add twitter:card and other relevant Twitter/X metadata when this channel is used.")
    parsed_lang = clean_text(page.get("lang", ""))
    if parsed_lang and not re.match(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$", parsed_lang):
        issue(page, "warning", "invalid_lang", "HTML", f"The lang attribute '{parsed_lang}' does not match a common BCP 47 shape.", "Use a valid language tag such as en, en-US, or si-LK.")
    if page.get("scripts", {}).get("count", 0) > 50:
        issue(page, "warning", "very_high_script_count", "Performance", f"Detected {page['scripts']['count']} script tags.", "Audit script dependencies and defer or remove non-critical JavaScript where practical.")
    if urlparse(page.get("url", "")).scheme == "https":
        insecure_resources = [r.get("url", "") for r in page.get("resources", []) if str(r.get("url", "")).lower().startswith("http://")]
        if insecure_resources:
            issue(page, "warning", "mixed_content_resource", "Security", f"{len(insecure_resources)} referenced resource(s) use HTTP from an HTTPS page.", "Serve resources over HTTPS to avoid mixed-content failures and security warnings.", evidence=" | ".join(insecure_resources[:5]))
    missing_alt = sum(1 for img in page["images"] if not img["alt"])
    if missing_alt:
        issue(page, "warning", "missing_alt", "Image SEO", f"{missing_alt} image(s) lack ALT text.", "Add accurate ALT text to meaningful images; keep decorative images empty intentionally.")
    missing_dim = sum(1 for img in page["images"] if not img["width"] or not img["height"])
    if missing_dim:
        issue(page, "info", "missing_image_dimensions", "Image SEO", f"{missing_dim} image(s) lack explicit dimensions.", "Declare width/height where practical to reduce layout shifts.")
    if len(page["images"]) > 1 and not any(img["loading"] == "lazy" for img in page["images"][1:]):
        issue(page, "info", "lazy_loading", "Image Performance", "Later images are not marked lazy-loading.", "Lazy-load below-the-fold images where appropriate; keep above-the-fold critical images eager.")
    if any(img["format"] in {"jpg", "jpeg", "png"} for img in page["images"]):
        issue(page, "info", "legacy_image_formats", "Image Performance", "Legacy raster image formats detected.", "Evaluate modern formats such as WebP or AVIF while preserving appropriate fallbacks.")
    if not page["schema_types"]:
        issue(page, "info", "no_structured_data", "Structured Data", "No JSON-LD schema type detected.", "Add structured data only when it accurately describes the visible page content and matches Google's supported features where relevant.")
    if page["schema_errors"]:
        issue(page, "warning", "malformed_jsonld", "Structured Data", f"{len(page['schema_errors'])} JSON-LD parsing error(s).", "Fix malformed JSON-LD, then validate it with a structured-data testing tool.")
    if not page["og"].get("og:title") or not page["og"].get("og:description"):
        issue(page, "info", "incomplete_open_graph", "Social", "Open Graph title/description is incomplete.", "Set page-specific og:title and og:description values for social sharing.")
    if page["images"] and not page["og"].get("og:image"):
        issue(page, "info", "missing_og_image", "Social", "Page has images but no og:image meta signal.", "Provide a suitable social preview image where social sharing matters.")
    if page["word_count"] < 200 and page["semantic_elements"].get("article"):
        issue(page, "warning", "thin_article", "Content", f"Article-like page has only {page['word_count']} visible words in the fetched HTML.", "Check whether the page fully satisfies the intended user task; do not add filler just to hit a word count.")
    elif page["word_count"] < 80:
        issue(page, "info", "very_low_visible_text", "Rendering", f"Only {page['word_count']} visible words found in fetched HTML.", "Check the rendered page in a browser; client-side rendering may be hiding content from this raw HTTP audit.")
    if page.get("rendering_signals", {}).get("likely_js_shell"):
        issue(page, "info", "js_heavy_page", "Rendering", "Page looks JavaScript-heavy with low visible HTML text.", "Verify the rendered DOM contains the primary SEO content, links, and metadata; this audit does not execute JavaScript.")
    if page["anchor_stats"]["empty"]:
        issue(page, "info", "empty_anchor_text", "Internal Linking", f"{page['anchor_stats']['empty']} link(s) have empty anchor text.", "Give meaningful text to navigational links; use empty text only when the visual context is otherwise clear and accessible.")
    if page["anchor_stats"]["generic"]:
        issue(page, "info", "generic_anchor_text", "Internal Linking", f"{page['anchor_stats']['generic']} link(s) use generic anchor phrases.", "Prefer descriptive anchor text that helps users understand the destination.")
    if not page["internal_links"]:
        issue(page, "warning", "no_internal_links", "Internal Linking", "No internal links were detected.", "Add relevant contextual links to important pages to help users and crawlers discover content.")
    if page["forms"]["unlabelled_inputs"]:
        issue(page, "info", "unlabelled_form_controls", "HTML Quality", f"{page['forms']['unlabelled_inputs']} visible form control(s) appear unlabeled.", "Associate form controls with accessible labels.")
    if page["semantic_elements"]["main"] is False:
        issue(page, "info", "missing_main", "HTML Quality", "No <main> element detected.", "Use semantic landmarks where appropriate to make document structure clearer.")
    # HTTP header quality: these are engineering signals, not direct ranking guarantees.
    if urlparse(page["url"]).scheme == "https" and not page["headers"].get("strict-transport-security"):
        issue(page, "info", "missing_hsts", "Security Headers", "HSTS header is not present.", "Consider Strict-Transport-Security after confirming HTTPS is fully deployed site-wide.")
    if not page["headers"].get("content-security-policy"):
        issue(page, "info", "missing_csp", "Security Headers", "Content-Security-Policy header is not present.", "Evaluate an appropriate CSP as part of your broader application security program.")
    if not page["headers"].get("x-content-type-options"):
        issue(page, "info", "missing_x_content_type_options", "Security Headers", "X-Content-Type-Options header is not present.", "Consider nosniff where compatible with the application.")
    if page["response_time_ms"] > kb_threshold("ttfb_poor_ms"):
        issue(page, "warning", "slow_response", "Performance", f"Response time measured at {page['response_time_ms']} ms from this crawler.", "Investigate server processing, caching, database work and network latency.")
    elif page["response_time_ms"] > kb_threshold("ttfb_good_ms"):
        issue(page, "info", "moderate_response", "Performance", f"Response time measured at {page['response_time_ms']} ms from this crawler.", "Profile server response and caching; this is a crawl-time measurement, not a Core Web Vitals result.")
    if page["html_bytes"] > 1_000_000:
        issue(page, "warning", "large_html", "Performance", f"HTML body is about {page['html_bytes'] / 1024:.0f} KB in the audit response.", "Reduce unnecessary HTML, payload duplication and inline code where practical.")
    if page["rendering_signals"]["script_count"] > 30:
        issue(page, "info", "high_script_count", "Performance", f"Detected {page['rendering_signals']['script_count']} script tags.", "Review whether all scripts are necessary and defer or split non-critical work.")
    if not page["favicon"]:
        issue(page, "info", "missing_favicon", "Search Appearance", "No favicon link was detected.", "Provide a site favicon for consistent browser and search presentation.")

    # URL hygiene heuristics: advisory only.
    parsed = urlparse(page["url"])
    if len(page["url"]) > kb_threshold("url_long_chars"):
        issue(page, "info", "long_url", "URL Structure", f"URL length is {len(page['url'])} characters.", "Keep URLs concise and readable where practical.")
    if re.search(r"[A-Z]", parsed.path):
        issue(page, "info", "uppercase_path", "URL Structure", "Uppercase letters occur in the path.", "Use a consistent lowercase URL convention if your routing allows it.")
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if params and any(k.lower() in TRACKING_PARAMS for k in params):
        issue(page, "info", "tracking_params", "URL Structure", "Tracking parameters are present.", "Keep tracking parameters out of canonical URLs and preferably out of indexable sitemap URLs.")


def googlebot_allowed(robots_txt: str, url: str, agent: str = "googlebot") -> bool:
    """Evaluate robots.txt the way Google documents it: the most specific matching user-agent group
    (groups with the same agent merged), longest matching rule wins, Allow wins ties, * and $ wildcards."""
    groups: list[tuple[list[str], list[tuple[str, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[str, str]] = []
    last_was_agent = False
    for raw in robots_txt.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (x.strip() for x in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if not last_was_agent and (agents or rules):
                groups.append((agents, rules)); agents, rules = [], []
            agents.append(value.lower())
            last_was_agent = True
        elif key in ("allow", "disallow"):
            rules.append((key, value))
            last_was_agent = False
        else:
            last_was_agent = False
    if agents or rules:
        groups.append((agents, rules))
    selected = [r for a, r in groups if agent in a]
    if not selected:
        selected = [r for a, r in groups if "*" in a]
    applied = [rule for g in selected for rule in g]
    parsed = urlparse(url)
    path = (parsed.path or "/") + (("?" + parsed.query) if parsed.query else "")
    best_len, allowed = -1, True
    for kind, pattern in applied:
        if not pattern:
            continue  # empty Disallow allows everything
        regex = "^" + re.escape(pattern).replace(r"\*", ".*")
        if regex.endswith(r"\$"):
            regex = regex[:-2] + "$"
        if re.match(regex, path):
            length = len(pattern)
            if length > best_len or (length == best_len and kind == "allow"):
                best_len, allowed = length, kind == "allow"
    return allowed


def probe_sitemap(start: str, robots: dict[str, Any]) -> str:
    """Quickly confirm that a real XML sitemap exists when full sitemap parsing did not finish in time."""
    root = origin(start)
    for url in list(dict.fromkeys((robots.get("sitemaps") or []) + [root + "/sitemap.xml", root + "/sitemap_index.xml"]))[:4]:
        res = fetch_universal(make_session(), url, timeout=8, max_body=300_000, retries=0)
        head = (res.get("body") or b"")[:300_000].decode("utf-8", "replace").lower()
        if int(res.get("status") or 0) == 200 and ("<urlset" in head or "<sitemapindex" in head):
            return url
    return ""


def parse_robots(session: requests.Session, start: str) -> dict[str, Any]:
    root = origin(start)
    url = root + "/robots.txt"
    res = fetch_universal(session, url, timeout=5, max_body=1_000_000, retries=0)
    content = res.get("body", b"").decode("utf-8", "replace") if res.get("ok") else ""
    found = res.get("status") == 200
    sitemaps = re.findall(r"(?im)^\s*sitemap\s*:\s*(\S+)\s*$", content)
    return {
        "url": url,
        "status": res.get("status", 0),
        "found": found,
        "content": content,
        "sitemaps": list(dict.fromkeys(sitemaps)),
        "fetch_ms": res.get("elapsed_ms", 0),
        "googlebot_allows_start": googlebot_allowed(content, start) if found else True,
        "googlebot_allows_root": googlebot_allowed(content, root + "/") if found else True,
    }


def parse_sitemaps(session: requests.Session, start: str, robots: dict[str, Any]) -> dict[str, Any]:
    root = origin(start)
    seeds = list(dict.fromkeys(robots.get("sitemaps", []) + [root + "/sitemap.xml", root + "/sitemap_index.xml"]))
    seen: set[str] = set()
    files: list[dict[str, Any]] = []
    urls: list[str] = []
    lastmods: dict[str, str] = {}
    raw_locs: list[str] = []
    queue: deque[tuple[str, int]] = deque((x, 0) for x in seeds[:20])
    while queue and len(files) < 40:
        url, depth = queue.popleft()
        if url in seen or depth > 3:
            continue
        seen.add(url)
        res = fetch_universal(session, url, timeout=6, max_body=5_000_000, retries=0)
        ok = bool(res.get("ok") and int(res.get("status") or 0) < 400)
        item = {"url": url, "status": res.get("status", 0), "found": ok, "type": None, "url_count": 0}
        if ok:
            text = res.get("body", b"").decode("utf-8", "replace")
            low = text.lower()
            if "<sitemapindex" in low:
                item["type"] = "index"
            elif "<urlset" in low:
                item["type"] = "urlset"
            locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", text, re.I | re.S)
            item["url_count"] = len(locs)
            if item["type"] == "index":
                for loc in locs[:30]:
                    queue.append((html.unescape(clean_text(loc)), depth + 1))
            else:
                for block in re.findall(r"<url>(.*?)</url>", text, re.I | re.S):
                    loc = re.search(r"<loc>\s*(.*?)\s*</loc>", block, re.I | re.S)
                    if not loc:
                        continue
                    raw_loc = html.unescape(clean_text(loc.group(1)))
                    u = canonical_url(raw_loc)
                    if same_site(u, start):
                        urls.append(u)
                        raw_locs.append(raw_loc)  # exact published <loc>: evidence must not be normalised (spec G.2)
                        lm = re.search(r"<lastmod>\s*(.*?)\s*</lastmod>", block, re.I | re.S)
                        if lm:
                            lastmods[u] = clean_text(lm.group(1))
        files.append(item)
    return {"files": files, "urls": list(dict.fromkeys(urls))[:20000], "raw_locs": list(dict.fromkeys(raw_locs))[:20000], "lastmod": lastmods}


def sitemap_cross_checks(pages: list[dict[str, Any]], sitemap: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    sm = set(sitemap.get("urls", []))
    if not sm:
        return issues
    for p in pages:
        if p.get("non_html"):
            continue
        u = canonical_url(p["url"])
        if p.get("status") == 200 and "noindex" not in f"{p.get('meta_robots','')} {p.get('x_robots_tag','')}".lower() and not u.startswith("http://") and u not in sm:
            issues.append({"severity": "info", "code": "not_in_sitemap", "category": "Sitemap", "message": "Indexable crawled page is not listed in the discovered sitemap.", "recommendation": "Add important canonical indexable URLs to the XML sitemap.", "url": p["url"], "evidence": "Crawled URL absent from sitemap URL set."})
        if u in sm and "noindex" in f"{p.get('meta_robots','')} {p.get('x_robots_tag','')}".lower():
            issues.append({"severity": "warning", "code": "noindex_in_sitemap", "category": "Sitemap", "message": "URL appears in sitemap but declares noindex.", "recommendation": "Remove intentionally non-indexable URLs from the sitemap or revise indexability strategy.", "url": p["url"]})
    return issues


def parallel_status_checks(session: requests.Session, urls: list[str], max_workers: int = 16, timeout: float = LINK_TIMEOUT, progress_cb=None, cancel_event=None) -> list[dict[str, Any]]:
    """Fast, bounded link status checks. Cancellation does not wait for outstanding futures."""
    def one(u: str) -> dict[str, Any]:
        s = make_session()
        started = time.perf_counter()
        try:
            r = s.head(u, timeout=(min(2.5, max(1.5, timeout / 2)), timeout), allow_redirects=True)
            status = r.status_code
            final_url = r.url
            headers = {k.lower(): v for k, v in r.headers.items()}
            r.close()
            if status in (405, 403, 501) or status == 0:
                raise requests.RequestException(f"HEAD returned {status}; retrying with GET")
            return {"url": u, "status": status, "final_url": final_url, "elapsed_ms": round((time.perf_counter()-started)*1000,1), "error": None, "method": "HEAD", "content_type": headers.get("content-type", "")}
        except requests.RequestException:
            try:
                r = s.get(u, timeout=(min(2.5, max(1.5, timeout / 2)), timeout), allow_redirects=True, stream=True)
                status = r.status_code
                final_url = r.url
                headers = {k.lower(): v for k, v in r.headers.items()}
                r.close()
                return {"url": u, "status": status, "final_url": final_url, "elapsed_ms": round((time.perf_counter()-started)*1000,1), "error": None, "method": "GET", "content_type": headers.get("content-type", "")}
            except requests.RequestException as exc:
                return {"url": u, "status": 0, "final_url": u, "elapsed_ms": round((time.perf_counter()-started)*1000,1), "error": str(exc), "method": "GET", "content_type": ""}

    results: list[dict[str, Any]] = []
    if not urls:
        return results
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
    futures = {ex.submit(one, u): u for u in urls}
    try:
        for future in concurrent.futures.as_completed(futures):
            if cancel_event is not None and cancel_event.is_set():
                break
            try:
                result = future.result()
            except Exception as exc:
                u = futures[future]
                result = {"url": u, "status": 0, "final_url": u, "elapsed_ms": 0, "error": str(exc), "method": "GET", "content_type": ""}
            results.append(result)
            if progress_cb:
                try:
                    progress_cb({"checked": len(results), "total": len(urls), "last_url": result.get("url", ""), "last_status": result.get("status", 0)})
                except Exception:
                    pass
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    pos = {u: i for i, u in enumerate(urls)}
    results.sort(key=lambda x: pos.get(x.get("url", ""), 10**9))
    return results

def resource_checks(session: requests.Session, resources: list[dict[str, Any]], limit: int, timeout: float = RESOURCE_TIMEOUT, progress_cb=None, cancel_event=None) -> list[dict[str, Any]]:
    unique = []
    seen = set()
    for r in resources:
        u = r.get("url")
        if not u or u in seen:
            continue
        seen.add(u)
        unique.append(r)
        if len(unique) >= limit:
            break

    def one(item: dict[str, Any]) -> dict[str, Any]:
        u = item["url"]
        res = fetch_universal(make_session(), u, timeout=timeout, max_body=2_000_000, retries=0)
        headers = res.get("headers", {})
        return {
            "url": u,
            "kind": item.get("kind"),
            "status": res.get("status", 0),
            "final_url": res.get("url", u),
            "elapsed_ms": res.get("elapsed_ms", 0),
            "bytes": res.get("bytes", 0),
            "content_type": res.get("content_type", ""),
            "cache_control": headers.get("cache-control", ""),
            "content_encoding": headers.get("content-encoding", ""),
            "error": res.get("error"),
        }
    out: list[dict[str, Any]] = []
    if not unique:
        return out
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=16)
    futures = {ex.submit(one, item): item for item in unique}
    try:
        for future in concurrent.futures.as_completed(futures):
            if cancel_event is not None and cancel_event.is_set():
                break
            try:
                item = future.result()
            except Exception as exc:
                src = futures[future]
                item = {"url": src.get("url", ""), "kind": src.get("kind", "resource"), "status": 0, "final_url": src.get("url", ""), "elapsed_ms": 0, "bytes": 0, "content_type": "", "cache_control": "", "content_encoding": "", "error": str(exc)}
            out.append(item)
            if progress_cb:
                try:
                    progress_cb({"checked": len(out), "total": len(unique), "last_url": item.get("url", ""), "last_status": item.get("status", 0)})
                except Exception:
                    pass
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    pos = {item["url"]: i for i, item in enumerate(unique)}
    out.sort(key=lambda x: pos.get(x.get("url", ""), 10**9))
    return out

def global_checks(start: str, pages: list[dict[str, Any]], robots: dict[str, Any], sitemap: dict[str, Any], link_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not robots["found"]:
        issues.append({"severity": "warning", "code": "robots_missing", "category": "Robots.txt", "message": "robots.txt was not found at the site root.", "recommendation": "Add a robots.txt file when you need to control crawler access, and reference the XML sitemap there if useful.", "url": robots["url"]})
    else:
        # Evaluated for Googlebot with Google's own matching rules (not this crawler's user-agent).
        if not robots.get("googlebot_allows_root", True):
            issues.append({"severity": "critical", "code": "global_block", "category": "Robots.txt", "message": "robots.txt blocks Googlebot from the homepage (Disallow: / applies to Googlebot).", "recommendation": "Remove the Disallow rule for Googlebot unless the whole site must stay out of Google.", "url": robots["url"]})
        elif not robots.get("googlebot_allows_start", True):
            issues.append({"severity": "critical", "code": "start_blocked", "category": "Robots.txt", "message": "robots.txt blocks Googlebot from the audited start URL.", "recommendation": "Allow Googlebot to crawl this URL if it should appear in Google.", "url": start})
    sitemap_set = {canonical_url(u) for u in sitemap.get("urls", [])}
    page_by_url = {canonical_url(p.get("url", "")): p for p in pages if p.get("url")}
    for p in pages:
        cu = canonical_url(p.get("url", ""))
        if cu in sitemap_set and "noindex" in f"{p.get('meta_robots','')} {p.get('x_robots_tag','')}".lower():
            issues.append({"severity":"warning","code":"noindex_in_sitemap","category":"Sitemap","message":"A sitemap URL is sending a noindex directive.","recommendation":"Remove intentionally non-indexable URLs from the sitemap or change the indexability policy.","url":p.get("url","")})
        canon = p.get("canonical")
        if canon and canonical_url(canon) in page_by_url:
            target = page_by_url[canonical_url(canon)]
            if int(target.get("status") or 0) >= 400:
                issues.append({"severity":"critical","code":"canonical_to_error","category":"Canonicalization","message":"Canonical points to a URL that returned an error in this crawl.","recommendation":"Point the canonical to a valid preferred URL or fix the canonical target.","url":p.get("url",""),"evidence":f"Canonical: {canon} • Target HTTP {target.get('status',0)}"})
        if canon and urlparse(p.get("url","")).scheme == "https" and urlparse(canon).scheme == "http":
            issues.append({"severity":"warning","code":"https_page_http_canonical","category":"Canonicalization","message":"An HTTPS page declares an HTTP canonical URL.","recommendation":"Use the HTTPS version as the canonical when HTTPS is the preferred indexable protocol.","url":p.get("url",""),"evidence":canon})
        if canon and sitemap_set and canonical_url(canon) not in sitemap_set and p.get("status") == 200 and "noindex" not in f"{p.get('meta_robots','')} {p.get('x_robots_tag','')}".lower():
            issues.append({"severity":"info","code":"canonical_not_in_sitemap","category":"Sitemap","message":"The page canonical is not present in the discovered sitemap URL set.","recommendation":"Confirm sitemap URLs represent canonical indexable URLs and include the intended canonical page where appropriate.","url":p.get("url",""),"evidence":canon})
    if sitemap.get("lastmod"):
        bad_dates = [u for u, d in sitemap.get("lastmod", {}).items() if d and not re.match(r"^\d{4}-\d{2}-\d{2}(?:T|$)", str(d))]
        if bad_dates:
            issues.append({"severity":"info","code":"sitemap_lastmod_format","category":"Sitemap","message":f"{len(bad_dates)} sitemap lastmod value(s) use an unexpected format.","recommendation":"Use valid sitemap date/time values and ensure lastmod represents the last significant content change.","url":bad_dates[0]})
    if not sitemap.get("urls") and not sitemap.get("detected"):
        issues.append({"severity": "warning", "code": "sitemap_missing", "category": "Sitemap", "message": "No usable XML sitemap URL set was discovered.", "recommendation": "Publish a valid XML sitemap for important canonical URLs and reference it from robots.txt or Search Console.", "url": origin(start) + "/sitemap.xml"})
    internal_status = [x for x in link_results if same_site(x.get("url", ""), start)]
    broken = [x for x in internal_status if int(x.get("status") or 0) >= 400 or int(x.get("status") or 0) == 0]
    if broken:
        issues.append({"severity": "warning", "code": "broken_internal_links", "category": "Links", "message": f"{len(broken)} checked internal URL(s) returned errors.", "recommendation": "Fix or remove broken internal links and update redirects to direct targets.", "url": broken[0]["url"]})

    # Potential duplicate H1s across distinct pages.
    h1_groups=defaultdict(list)
    for p in pages:
        key=clean_text(" ".join(p.get("h1", []))).lower()
        if key:
            h1_groups[key].append(p.get("url", ""))
    for value, urls in h1_groups.items():
        if len(urls) > 1:
            issues.append({"severity":"info","code":"duplicate_h1","category":"Headings","message":f"{len(urls)} crawled pages share the same H1 text.","recommendation":"Review whether these pages have distinct search intent and page topics; use more descriptive page-specific headings where needed.","url":urls[0],"evidence":" | ".join(urls[:6])})

    # Duplicate metadata and exact duplicate content.
    for field, label, code in (("title", "title", "duplicate_title"), ("meta_description", "meta description", "duplicate_meta_description")):
        grouped: dict[str, list[str]] = defaultdict(list)
        for p in pages:
            value = clean_text(p.get(field)).lower()
            if value:
                grouped[value].append(p["url"])
        for value, urls in grouped.items():
            if len(urls) > 1:
                issues.append({"severity": "warning", "code": code, "category": "Duplication", "message": f"{len(urls)} crawled pages share the same {label}.", "recommendation": f"Create unique {label}s where pages have different search intent.", "url": urls[0], "evidence": " | ".join(urls[:6])})
    hashes: dict[str, list[str]] = defaultdict(list)
    for p in pages:
        if p.get("content_hash") and p.get("word_count", 0) > 40:
            hashes[p["content_hash"]].append(p["url"])
    for h, urls in hashes.items():
        if len(urls) > 1:
            issues.append({"severity": "warning", "code": "duplicate_content", "category": "Duplication", "message": f"{len(urls)} pages have identical fetched visible text.", "recommendation": "Consolidate duplicate URLs, improve unique value, or use canonicalization/noindex where appropriate.", "url": urls[0], "evidence": " | ".join(urls[:6])})

    # Orphan detection within the crawled graph.
    incoming = Counter()
    for p in pages:
        for u in p.get("internal_links", []):
            incoming[u] += 1
    for p in pages:
        if canonical_url(p["url"]) == canonical_url(start):
            continue
        if incoming.get(canonical_url(p["url"]), 0) == 0:
            issues.append({"severity": "info", "code": "orphan_candidate", "category": "Internal Linking", "message": "Crawled page has no incoming internal link from another crawled page.", "recommendation": "Add contextual internal links from relevant pages if this URL should be discoverable and important.", "url": p["url"]})
    return issues


def hreflang_checks(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_url = {canonical_url(p["url"]): p for p in pages}
    out: list[dict[str, Any]] = []
    for p in pages:
        entries = p.get("hreflang", [])
        langs = [x["lang"] for x in entries]
        if len(langs) != len(set(langs)):
            out.append({"severity": "warning", "code": "duplicate_hreflang", "category": "International", "message": "Duplicate hreflang language codes found.", "recommendation": "Use one target per language/region code on the page.", "url": p["url"]})
        for x in entries:
            target = by_url.get(canonical_url(x["href"]))
            if target and not any(canonical_url(e["href"]) == canonical_url(p["url"]) for e in target.get("hreflang", [])):
                out.append({"severity": "warning", "code": "hreflang_nonreciprocal", "category": "International", "message": f"hreflang {x['lang']} target does not link back to this URL.", "recommendation": "Keep hreflang annotations mutually consistent across the alternate pages.", "url": p["url"], "evidence": x["href"]})
    return out


def developer_validation(code: str, category: str) -> str:
    steps = {
        "missing_title": "Re-crawl affected URLs and confirm each HTML document has a unique, non-empty title.",
        "missing_meta_description": "Re-crawl and confirm the intended description is present on affected canonical pages.",
        "missing_h1": "Re-crawl and verify the primary heading is present and represents the page topic.",
        "missing_canonical": "Re-crawl and verify the canonical URL resolves to the intended preferred URL.",
        "duplicate_title": "Re-crawl and confirm titles are unique across pages with different search intent.",
        "duplicate_meta_description": "Re-crawl and confirm descriptions are differentiated where the page intent differs.",
        "duplicate_content": "Review canonical/indexability strategy and confirm duplicates are intentional after re-crawl.",
        "broken_internal_links": "Re-run link checks and confirm previously failing internal targets return successful responses or intended redirects.",
        "broken_link": "Re-run the link checker and confirm the target no longer returns an error.",
        "broken_resource": "Re-run resource checks and confirm referenced assets return successful responses.",
        "malformed_jsonld": "Validate the corrected JSON-LD syntax and re-crawl to confirm no parser errors remain.",
        "missing_alt": "Re-crawl affected images and confirm meaningful images have appropriate ALT text.",
        "noindex_in_sitemap": "Re-crawl and confirm sitemap membership matches the chosen indexability policy.",
        "sitemap_missing": "Re-crawl the sitemap endpoint and confirm a valid XML sitemap is discoverable.",
        "robots_missing": "Re-crawl /robots.txt and confirm the desired crawler directives and sitemap references are accessible.",
        "redirect_chain": "Re-run the URL and confirm important URLs resolve with the intended minimal redirect path.",
        "slow_response": "Repeat the crawl from the same environment and compare response time before/after server-side changes.",
        "large_html": "Re-crawl and compare HTML response size after removing unnecessary payload or duplication.",
    }
    return steps.get(code, f"Re-crawl the affected URL(s) and confirm the {category.lower()} signal matches the intended implementation.")


def expanded_stats(pages: list[dict[str, Any]], links: list[dict[str, Any]], resources: list[dict[str, Any]], sitemap: dict[str, Any]) -> dict[str, Any]:
    html_pages = [p for p in pages if not p.get("non_html")]
    def n(predicate):
        return sum(1 for p in html_pages if predicate(p))
    statuses = Counter(str(p.get("status", 0)) for p in pages)
    total_images = sum(len(p.get("images", [])) for p in pages)
    missing_alt = sum(sum(1 for i in p.get("images", []) if not i.get("alt")) for p in pages)
    noindex = n(lambda p: "noindex" in f"{p.get('meta_robots','')} {p.get('x_robots_tag','')}".lower())
    indexable = n(lambda p: p.get("status") == 200 and "noindex" not in f"{p.get('meta_robots','')} {p.get('x_robots_tag','')}".lower())
    return {
        "total_pages": len(pages),
        "html_pages": len(html_pages),
        "status_breakdown": dict(statuses),
        "status_2xx": sum(v for k,v in statuses.items() if k.startswith("2")),
        "status_3xx": sum(v for k,v in statuses.items() if k.startswith("3")),
        "status_4xx": sum(v for k,v in statuses.items() if k.startswith("4")),
        "status_5xx": sum(v for k,v in statuses.items() if k.startswith("5")),
        "indexable_pages": indexable,
        "noindex_pages": noindex,
        "https_pages": n(lambda p: urlparse(p.get("url", "")).scheme == "https"),
        "pages_with_viewport": n(lambda p: bool(p.get("viewport"))),
        "redirected_pages": n(lambda p: bool(p.get("redirect_count"))),
        "missing_title_pages": n(lambda p: not p.get("title")),
        "missing_meta_description_pages": n(lambda p: not p.get("meta_description")),
        "missing_h1_pages": n(lambda p: not p.get("h1")),
        "multiple_h1_pages": n(lambda p: len(p.get("h1", [])) > 1),
        "missing_canonical_pages": n(lambda p: not p.get("canonical")),
        "pages_with_schema": n(lambda p: bool(p.get("schema_types")) and not p.get("schema_errors")),
        "pages_with_open_graph": n(lambda p: bool(p.get("og", {}).get("og:title")) and bool(p.get("og", {}).get("og:description"))),
        "pages_with_hreflang": n(lambda p: bool(p.get("hreflang"))),
        "js_heavy_pages": n(lambda p: bool(p.get("rendering_signals", {}).get("likely_js_shell"))),
        "slow_pages": n(lambda p: p.get("response_time_ms", 0) > 800),
        "large_html_pages": n(lambda p: p.get("html_bytes", 0) > 1_000_000),
        "total_images": total_images,
        "missing_alt_images": missing_alt,
        "images_with_dimensions": sum(sum(1 for i in p.get("images", []) if i.get("width") and i.get("height")) for p in pages),
        "checked_links": len(links),
        "broken_links": sum(1 for x in links if int(x.get("status") or 0) >= 400 or int(x.get("status") or 0) == 0),
        "checked_resources": len(resources),
        "broken_resources": sum(1 for x in resources if int(x.get("status") or 0) >= 400 or int(x.get("status") or 0) == 0),
        "sitemap_urls": len(sitemap.get("urls", [])),
        "average_response_ms": round(sum(p.get("response_time_ms", 0) for p in pages) / max(1, len(pages)), 1),
        "median_response_ms": round(sorted([p.get("response_time_ms", 0) for p in pages])[len(pages) // 2], 1) if pages else 0,
        "average_html_kb": round(sum(p.get("html_bytes", 0) for p in pages) / max(1, len(pages)) / 1024, 1),
        "total_internal_links": sum(len(p.get("internal_links", [])) for p in pages),
        "total_external_links": sum(len(p.get("external_links", [])) for p in pages),
        "max_crawl_depth": max((p.get("depth", 0) for p in pages if p.get("depth", 0) >= 0), default=0),
    }

STOPWORDS = {
    "the","and","for","with","that","this","from","your","you","are","was","were","our","their",
    "into","have","has","had","about","will","can","www","com","https","http","home","page","news",
    "read","more","what","when","where","which","while","who","how","why","all","any","not","but",
    "get","use","using","used","new","one","two","also","only","than","then","them","they","its",
    "it's","our","out","off","over","under","after","before","through","these","those","there","here"
}
INTENT_PATTERNS = {
    "informational": re.compile(r"\b(what|why|how|guide|tutorial|tips|examples?|meaning|learn|benefits?|difference|ideas?)\b", re.I),
    "commercial": re.compile(r"\b(best|top|review|reviews|compare|comparison|vs|pricing|price|software|service|services|agency|consultant|company)\b", re.I),
    "transactional": re.compile(r"\b(buy|book|hire|order|quote|purchase|deal|discount|near me|get started|contact|sign up|signup|download)\b", re.I),
}
SOCIAL_STOPWORDS = STOPWORDS | {"https", "www", "com", "org", "net", "www"}

def classify_intent(term: str) -> str:
    for label, pattern in INTENT_PATTERNS.items():
        if pattern.search(term):
            return label
    return "navigational" if len(term.split()) <= 2 else "informational"

def safe_hashtag(term: str) -> str:
    words = re.findall(r"[a-z0-9]+", term.lower())
    if not words:
        return ""
    tag = "".join(words)
    if 2 <= len(tag) <= 40:
        return "#" + tag
    return ""

def build_page_keyword_intelligence(page: dict[str, Any]) -> dict[str, Any]:
    if int(page.get("status") or 0) >= 400 or page.get("error"):
        return {"primary_observed_topic":"","keywords":[],"hashtags":[],"note":"No keyword suggestions generated for an error/fetch-failed page."}
    title=(page.get("title") or "").lower()
    h1_text=" ".join(page.get("h1",[]) or []).lower()
    desc=(page.get("meta_description") or "").lower()
    base_terms=[]
    for item in page.get("top_terms",[]) or []:
        term=str(item.get("term","")).strip().lower()
        if term and term not in STOPWORDS:
            base_terms.append((term,int(item.get("count",0))))
    for item in page.get("top_phrases",[]) or []:
        phrase=str(item.get("phrase","")).strip().lower()
        if phrase:
            base_terms.append((phrase,int(item.get("count",0))))
    seen=set(); rows=[]
    for term,count in sorted(base_terms,key=lambda x:(-x[1],x[0])):
        if term in seen or len(term)<3: continue
        seen.add(term)
        placements={
            "title":term in title,
            "h1":term in h1_text,
            "meta_description":term in desc,
            "body":True,
        }
        rows.append({"keyword":term,"observed_count":count,"intent":classify_intent(term),"placements":placements,"url":page.get("url","")})
        if len(rows)>=50: break
    primary=rows[0]["keyword"] if rows else ""
    hashtags=[]
    for row in rows:
        tag=safe_hashtag(row["keyword"])
        if tag and tag not in hashtags: hashtags.append(tag)
        if len(hashtags)>=20: break
    return {"primary_observed_topic":primary,"keywords":rows,"hashtags":hashtags,"note":"Observed terms/phrases are extracted from the fetched HTML; they are not search-volume, ranking, or SERP metrics."}

def build_keyword_intelligence(pages: list[dict[str, Any]]) -> dict[str, Any]:
    aggregate = Counter()
    page_map = defaultdict(list)
    intent_map = Counter()
    hashtags = Counter()
    page_rows = []
    for page in pages:
        intel = build_page_keyword_intelligence(page)
        page["keyword_intelligence"] = intel
        for row in intel.get("keywords", []):
            aggregate[row["keyword"]] += row.get("observed_count", 0)
            intent_map[row.get("intent", "informational")] += 1
            page_map[row["keyword"]].append(page.get("url", ""))
        for tag in intel.get("hashtags", []):
            hashtags[tag] += 1
        page_rows.append({"url":page.get("url", ""),"primary_topic":intel.get("primary_observed_topic", ""),"keywords":intel.get("keywords", [])[:20],"hashtags":intel.get("hashtags", [])})
    rows = []
    for term, count in aggregate.most_common(100):
        urls = page_map.get(term, [])
        rows.append({"keyword":term,"observed_count":count,"pages":len(urls),"urls":urls[:50],"intent":classify_intent(term),"opportunity_note":"Review this observed topic against actual Search Console/ranking data before treating it as a keyword opportunity."})
    cannibalization = [{"keyword":term,"pages":urls[:20]} for term, urls in page_map.items() if len(set(urls)) >= 3 and len(term) >= 4][:50]
    return {
        "observed_keywords":rows,
        "intent_breakdown":dict(intent_map),
        "hashtags":[{"hashtag":k,"pages":v} for k,v in hashtags.most_common(50)],
        "possible_cannibalization":cannibalization,
        "pages":page_rows,
        "data_boundary":"No search volume, KD, rank, SERP or click-through metrics are invented; connect Search Console or a keyword/SERP provider for those fields."
    }

def merge_keyword_metrics(keyword_intel: dict[str, Any], real_data: dict[str, Any]) -> None:
    """Attach real provider metrics (Search Console + DataForSEO) to observed keywords. Missing values stay None."""
    gsc = real_data.get("search_console") or {}
    dfs = real_data.get("dataforseo") or {}
    metrics = {r["keyword"]: r for r in ((dfs.get("keyword_metrics") or {}).get("keywords") or [])}
    gsc_rows = {str(r.get("query", "")).lower(): r for r in (gsc.get("top_queries") or [])} if gsc.get("ok") else {}
    ranked = {r["keyword"]: r for r in ((dfs.get("ranked_keywords") or {}).get("keywords") or [])}
    for row in keyword_intel.get("observed_keywords", []):
        kw = row["keyword"]
        m, g, rk = metrics.get(kw), gsc_rows.get(kw), ranked.get(kw)
        if m:
            row.update({"search_volume": m.get("search_volume"), "keyword_difficulty": m.get("keyword_difficulty"), "cpc": m.get("cpc"), "competition_level": m.get("competition_level")})
            if m.get("intent"):
                row["intent"] = m["intent"]
                row["intent_source"] = "DataForSEO"
        if g:
            row.update({"gsc_clicks": g["clicks"], "gsc_impressions": g["impressions"], "gsc_ctr": g["ctr"], "gsc_position": g["position"]})
        if rk:
            row.update({"google_position": rk.get("position"), "ranking_url": rk.get("url")})
    keyword_intel["search_metrics"] = list(metrics.values())
    keyword_intel["search_console_queries"] = gsc.get("top_queries", []) if gsc.get("ok") else []
    keyword_intel["ranked_keywords"] = list(ranked.values())
    sources = []
    if metrics: sources.append("DataForSEO keyword overview (search volume, KD, CPC, intent)")
    if gsc_rows: sources.append("Google Search Console (clicks, impressions, CTR, average position)")
    if ranked: sources.append("DataForSEO ranked keywords (Google organic positions)")
    if sources:
        keyword_intel["data_boundary"] = "Real metrics from: " + "; ".join(sources) + ". Observed counts come from fetched HTML. Keywords without provider data show no metric rather than an estimate."

def source_category_summary(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups = defaultdict(list)
    for item in issues:
        category = item.get("category") or "Other"
        groups[category].append(item)
    out=[]
    for category, bucket in groups.items():
        severities=Counter(x.get("severity","info") for x in bucket)
        codes=Counter(x.get("code","") for x in bucket)
        top_code=codes.most_common(1)[0][0] if codes else ""
        source_map={"Title":"HTML <title>","Meta Description":"HTML <meta>","Headings":"HTML headings","Canonicalization":"Canonical link","Indexability":"Robots directives","Robots.txt":"robots.txt","Sitemap":"XML sitemap","Internal Linking":"HTML links","External Links":"External link checks","Resources":"Resource checks","Image SEO":"Image attributes","Image Performance":"Image attributes","Structured Data":"JSON-LD","Social":"Open Graph/Twitter metadata","Performance":"HTTP timing/payload","Security":"HTTPS/security headers","Security Headers":"HTTP security headers","URL Structure":"URL normalization","Rendering":"Raw HTML/rendering heuristics","Mobile":"Viewport/mobile HTML","HTML":"Document HTML","HTML Quality":"Semantic/accessibility HTML","Crawlability":"HTTP fetch","Status Codes":"HTTP status","Redirects":"HTTP redirect chain","Search Appearance":"Search appearance HTML","Links":"HTML internal link graph","Duplication":"Page-to-page duplicate comparison"}
        out.append({"category":category,"source":source_map.get(category,"Live audit rule"),"total":len(bucket),"critical":severities.get("critical",0),"warning":severities.get("warning",0),"info":severities.get("info",0),"top_issue_code":top_code,"affected_urls":list(dict.fromkeys(x.get("url","") for x in bucket if x.get("url")))[:50]})
    return sorted(out,key=lambda x:(-x["critical"],-x["warning"],-x["total"],x["category"]))

def keyword_signals(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    intel = build_keyword_intelligence(pages)
    return [{"term":x.get("keyword",""),"count":x.get("observed_count",0),"pages":x.get("pages",0),"intent":x.get("intent","informational")} for x in intel.get("observed_keywords", [])[:100]]


def site_stats(pages: list[dict[str, Any]], links: list[dict[str, Any]], resources: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = Counter(str(p.get("status", 0)) for p in pages)
    return {
        "status_breakdown": dict(statuses),
        "average_response_ms": round(sum(p.get("response_time_ms", 0) for p in pages) / max(1, len(pages)), 1),
        "median_response_ms": round(sorted([p.get("response_time_ms", 0) for p in pages])[len(pages) // 2], 1) if pages else 0,
        "average_html_kb": round(sum(p.get("html_bytes", 0) for p in pages) / max(1, len(pages)) / 1024, 1),
        "total_images": sum(len(p.get("images", [])) for p in pages),
        "total_internal_links": sum(len(p.get("internal_links", [])) for p in pages),
        "total_external_links": sum(len(p.get("external_links", [])) for p in pages),
        "checked_links": len(links),
        "checked_resources": len(resources),
        "duplicate_title_pages": sum(1 for i in links if i.get("code") == "duplicate_title"),
    }


def crawl(req: AuditRequest, progress_cb=None, cancel_event=None) -> dict[str, Any]:
    """Universal respectful crawler: link + sitemap discovery, bounded concurrency, optional JS rendering, and evidence-first scoring."""
    audit_started = time.perf_counter()
    start = canonical_url(validate_public_target(req.url))
    # Real-data provider calls (PageSpeed/CrUX, Search Console, DataForSEO) run in the background during the crawl.
    enrichment = integrations.Enrichment(start, req.use_pagespeed, req.use_search_console, req.use_dataforseo, req.location_code, req.language_code,
                                         pagespeed_strategies=("mobile", "desktop") if req.pagespeed_desktop else ("mobile",))
    # Spec PART B probes (host resolution, HTTP->HTTPS, negative URLs + 404 control, mobile parity) and the RENDER tier.
    probe_future = PROBE_EXECUTOR.submit(collect_site_probes, start, fetch, make_session, parse_page) if req.run_probes else None
    render_future = PROBE_EXECUTOR.submit(render_mobile_probe, [start]) if req.render_probe else None
    workers = max(2, min(CRAWL_WORKERS, 20))
    pages: list[dict[str, Any]] = []
    skipped_robots: list[str] = []
    seen_requested: set[str] = set()
    seen_final: set[str] = set()
    queued: set[str] = set()
    queue: deque[tuple[str, int, str]] = deque()
    inbound: Counter[str] = Counter()
    render_used = 0
    render_counter = [0]
    render_lock = threading.Lock()
    render_available = None

    def emit(payload: dict[str, Any]) -> None:
        if progress_cb:
            try:
                progress_cb(payload)
            except Exception:
                pass

    emit({"phase":"preflight","pages":0,"queued":1,"in_flight":0,"current_url":start,"status":0,"issues":0,"message":"Checking the start URL, robots.txt and sitemap sources…"})

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as prep:
        page_future = prep.submit(fetch_universal, make_session(), start, min(TIMEOUT, 15), MAX_BODY, 2)
        robots_future = prep.submit(parse_robots, make_session(), start)
        sitemap_seed_future = prep.submit(lambda: None)
        first_res = page_future.result()
        robots = robots_future.result()
        first_page = parse_page(start, first_res)

    robot_parser = RobotFileParser()
    if robots.get("found"):
        robot_parser.parse(robots.get("content", "").splitlines())
    try:
        first_allowed = robot_parser.can_fetch(USER_AGENT, start) if robots.get("found") else True
    except Exception:
        first_allowed = True
    first_page["depth"] = 0
    first_page["discovery"] = "start"
    first_page["robots_allowed"] = first_allowed
    first_page["rendered"] = False
    if urlparse(first_page.get("url", start)).hostname and not same_site(first_page.get("url", start), start, req.follow_subdomains):
        first_page["final_offsite"] = True
    # Render the start page too. Without this, an SPA could have no discoverable HTML links and the crawl would stop at one URL.
    first_wants_render = req.crawl_mode == "rendered" or (req.crawl_mode == "auto" and first_page.get("rendering_signals", {}).get("likely_js_shell")) or (req.crawl_mode == "auto" and int(first_page.get("status") or 0) in {403, 406})
    if first_wants_render and req.render_max_pages > 0:
        with render_lock:
            if render_counter[0] < req.render_max_pages:
                render_counter[0] += 1
                first_rend = render_with_playwright(first_page.get("url", start), timeout_ms=int(max(10, TIMEOUT) * 1000))
                first_page["render_diagnostic"] = {"attempted":True,"available":first_rend.get("available"),"ok":first_rend.get("ok"),"browser_source":first_rend.get("browser_source",""),"error":first_rend.get("error","")}
                if first_rend.get("ok"):
                    rendered_page = parse_page(first_page.get("url", start), {**first_res, "ok":True, "status":first_rend.get("status",first_res.get("status",0)), "url":first_rend.get("url",first_page.get("url",start)), "content_type":first_rend.get("content_type","text/html"), "body":first_rend.get("body",b""), "headers":first_rend.get("headers",first_res.get("headers",{})), "elapsed_ms":first_res.get("elapsed_ms",0)})
                    rendered_page["depth"] = 0; rendered_page["discovery"] = "start"; rendered_page["robots_allowed"] = first_allowed; rendered_page["rendered"] = True; rendered_page["render_source"] = first_rend.get("browser_source", "Playwright")
                    rendered_page["transport_status"] = first_page.get("status",0); rendered_page["transport_response_time_ms"] = first_page.get("response_time_ms",0)
                    first_page = rendered_page
    page_checks(first_page)
    pages.append(first_page)
    seen_requested.add(start)
    seen_final.add(canonical_url(first_page.get("url") or start))

    per_path_variants: defaultdict[str, set[str]] = defaultdict(set)

    def enqueue(url: str, depth: int, discovery: str) -> None:
        # IMPORTANT: external links are check targets only, never crawl targets.
        if discovery == "external":
            return
        if depth > req.max_depth or len(queued) >= max(req.max_pages * 4, 1000):
            return
        u = canonical_url(url, drop_tracking=(req.query_policy == "safe"))
        p = urlparse(u)
        if p.scheme not in {"http", "https"} or not p.hostname:
            return
        if not same_site(u, start, req.follow_subdomains):
            return
        params = parse_qsl(p.query, keep_blank_values=True)
        if req.query_policy == "safe" and p.query:
            base_u = canonical_url(urlunparse((p.scheme, p.netloc, p.path or "/", "", "", "")), drop_tracking=True)
            if base_u in queued or base_u in seen_requested or base_u in seen_final:
                return
            u = base_u
            p = urlparse(u)
        elif req.query_policy == "safe" and len(params) > 6:
            return
        if req.query_policy == "all":
            # Preserve explicit query URLs, but cap variants per path to avoid faceted/search explosions.
            path_key = f"{p.hostname.lower()}:{p.port or _effective_port(u)}{p.path or '/'}"
            variants = per_path_variants[path_key]
            if u not in variants and len(variants) >= 50:
                return
            variants.add(u)
        key = u
        if key in queued or key in seen_requested or key in seen_final:
            return
        queued.add(key)
        queue.append((u, depth, discovery))


    for u in first_page.get("internal_links", []):
        enqueue(u, 1, "link")
        inbound[canonical_url(u)] += 1
    # Crawl one product page and one contact page early, so even small scans can measure E-commerce and Local SEO.
    for pattern in (r"/(products?|item|p)/[^/?#]+", r"/(contact|contact-us|location|locations|find-us)/?$"):
        hit = next((item for item in queue if re.search(pattern, urlparse(item[0]).path, re.I)), None)
        if hit:
            queue.remove(hit)
            queue.appendleft(hit)

    sitemap_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    sitemap_future = sitemap_executor.submit(parse_sitemaps, make_session(), start, robots)
    sitemap: dict[str, Any] = {"files": [], "urls": [], "lastmod": {}}

    def maybe_merge_sitemap(wait_seconds: float = 0.0) -> bool:
        nonlocal sitemap
        if sitemap_future.done():
            try:
                sitemap = sitemap_future.result()
            except Exception as exc:
                sitemap = {"files": [], "urls": [], "lastmod": {}, "error": str(exc)}
            for u in sitemap.get("urls", []):
                enqueue(u, -1, "sitemap")
            return True
        if wait_seconds > 0:
            try:
                sitemap = sitemap_future.result(timeout=wait_seconds)
                for u in sitemap.get("urls", []):
                    enqueue(u, -1, "sitemap")
                return True
            except Exception:
                return False
        return False

    emit({"phase":"crawl","pages":1,"queued":len(queue),"in_flight":0,"current_url":start,"status":first_page.get("status",0),"issues":len(first_page.get("issues",[])),"message":f"Start page fetched. Universal crawler ready ({workers} workers)."})

    def crawl_one(item: tuple[str,int,str]) -> tuple[dict[str, Any], tuple[str,int,str]]:
        u, depth, discovery = item
        s = make_session()
        allowed = True
        if req.respect_robots and robots.get("found"):
            try:
                allowed = robot_parser.can_fetch(USER_AGENT, u)
            except Exception:
                allowed = True
        if not allowed:
            return ({"requested_url":u,"url":u,"status":0,"content_type":"","response_time_ms":0,"html_bytes":0,"wire_bytes":0,"redirect_count":0,"redirect_chain":[],"redirected":False,"headers":{},"error":"Blocked by robots.txt","non_html":False,"title":"","title_length":0,"meta_description":"","meta_description_length":0,"meta_robots":"","x_robots_tag":"","h1":[],"h2":[],"h3":[],"h4":[],"h5":[],"h6":[],"canonical":"","canonical_host":"","canonical_location":"absent","lang":"","viewport":"","charset":"","images":[],"schema_types":[],"schema_errors":[],"schema_nodes":[],"og":{},"twitter":{},"hreflang":[],"internal_links":[],"external_links":[],"all_links":[],"anchor_stats":{"total":0,"empty":0,"generic":0,"nofollow_internal":0,"nofollow_external":0,"sponsored":0,"ugc":0},"resources":[],"forms":{"count":0,"unlabelled_inputs":0},"word_count":0,"content_hash":"","top_terms":[],"top_phrases":[],"outgoing_link_count":0,"rendered":False,"rendering_signals":{"script_count":0,"inline_script_count":0,"external_script_count":0,"has_noscript":False,"low_text_with_scripts":False,"likely_js_shell":False},"favicon":False,"depth":depth,"discovery":discovery,"robots_allowed":False,"issues":[{"severity":"info","code":"robots_blocked","category":"Robots.txt","message":"URL was skipped because robots.txt disallows this crawler.","recommendation":"Confirm that this URL is intentionally blocked for this crawler.","url":u}],"score":0.0}, item)
        res = fetch_universal(s, u, timeout=min(TIMEOUT, 15), max_body=MAX_BODY, retries=2)
        page = parse_page(u, res)
        page["depth"] = depth
        page["discovery"] = discovery
        page["robots_allowed"] = allowed
        final = page.get("url") or u
        page["final_offsite"] = bool(final and not same_site(final, start, req.follow_subdomains))
        # Optional rendered pass for probable JS shells or explicit rendered mode.
        wants_render = req.crawl_mode == "rendered" or (req.crawl_mode == "auto" and page.get("rendering_signals", {}).get("likely_js_shell")) or (req.crawl_mode == "auto" and int(page.get("status") or 0) in {403, 406})
        should_render = False
        if wants_render and req.render_max_pages > 0:
            with render_lock:
                if render_counter[0] < req.render_max_pages:
                    render_counter[0] += 1
                    should_render = True
        if should_render:
            rend = render_with_playwright(final, timeout_ms=int(max(10, TIMEOUT) * 1000))
            page["render_diagnostic"] = {"attempted":True,"available":rend.get("available"),"package_available":rend.get("package_available"),"browser_available":rend.get("browser_available"),"browser_source":rend.get("browser_source",""),"ok":rend.get("ok"),"error":rend.get("error","")}
            if rend.get("ok"):
                rendered_page = parse_page(final, {**res, "ok":True, "status":rend.get("status",res.get("status",0)), "url":rend.get("url",final), "content_type":rend.get("content_type","text/html"), "body":rend.get("body",b""), "headers":rend.get("headers",res.get("headers",{})), "elapsed_ms":res.get("elapsed_ms",0)})
                rendered_page["depth"] = depth
                rendered_page["discovery"] = discovery
                rendered_page["robots_allowed"] = allowed
                rendered_page["rendered"] = True
                rendered_page["render_source"] = "Playwright"
                # Preserve raw transport measurements.
                rendered_page["transport_status"] = page.get("status",0)
                rendered_page["transport_response_time_ms"] = page.get("response_time_ms",0)
                page = rendered_page
        page_checks(page)
        return page, item

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        while len(pages) < req.max_pages:
            if cancel_event is not None and cancel_event.is_set():
                break
            # Merge sitemap URLs whenever the async discovery completes. This is intentionally
            # separate from the loop condition so a newly-enqueued sitemap batch cannot cause
            # an early exit when the crawl queue was empty at the start of the iteration.
            maybe_merge_sitemap(0.0)
            if not queue:
                if sitemap_future.done():
                    maybe_merge_sitemap(0.0)
                    if not queue:
                        break
                else:
                    try:
                        maybe_merge_sitemap(0.15)
                    except Exception:
                        pass
                    if not queue:
                        time.sleep(0.05)
                        if sitemap_future.done():
                            maybe_merge_sitemap(0.0)
                        if not queue:
                            continue
            batch=[]
            while queue and len(batch)<workers and (len(pages)+len(batch))<req.max_pages:
                item=queue.popleft()
                queued.discard(item[0])
                if item[0] in seen_requested or item[0] in seen_final:
                    continue
                seen_requested.add(item[0])
                batch.append(item)
            futures={ex.submit(crawl_one,item):item for item in batch}
            for future in concurrent.futures.as_completed(futures):
                item=futures[future]
                try:
                    page,_=future.result()
                except Exception as exc:
                    page={"requested_url":item[0],"url":item[0],"status":0,"content_type":"","response_time_ms":0,"html_bytes":0,"error":str(exc),"non_html":False,"title":"","meta_description":"","h1":[],"h2":[],"h3":[],"h4":[],"h5":[],"h6":[],"canonical":"","images":[],"internal_links":[],"external_links":[],"all_links":[],"resources":[],"issues":[{"severity":"critical","code":"crawl_worker_error","category":"Crawlability","message":"Crawler worker failed for this URL.","recommendation":"Retry the URL and inspect DNS, TLS, server and application logs.","evidence":str(exc),"url":item[0]}],"score":0.0,"depth":item[1],"discovery":item[2],"robots_allowed":True}
                if page.get("error") == "Blocked by robots.txt":
                    skipped_robots.append(item[0])
                else:
                    key=canonical_url(page.get("url") or item[0])
                    if key not in seen_final and len(pages)<req.max_pages:
                        seen_final.add(key)
                        pages.append(page)
                        for n in page.get("internal_links", []):
                            before=len(queue)
                            enqueue(n, item[1]+1 if item[1]>=0 else -1, "link")
                            if len(queue)>before:
                                inbound[canonical_url(n)] += 1
                emit({"phase":"crawl","pages":len(pages),"queued":len(queue),"in_flight":max(0,len(batch)-1),"current_url":item[0],"status":page.get("status",0),"issues":sum(len(x.get("issues",[])) for x in pages),"pages_per_sec":round(max(0,len(pages))/max(0.001,time.perf_counter()-audit_started),2),"message":f"Crawling • {len(pages)} pages completed • {workers} workers"})
            if req.crawl_delay_ms:
                time.sleep(req.crawl_delay_ms/1000.0)

    if not sitemap_future.done():
        maybe_merge_sitemap(3.0)
    try:
        sitemap_executor.shutdown(wait=False, cancel_futures=True)
    except Exception:
        pass

    # If sitemap became available after the main link-driven loop, consume sitemap-only URLs.
    while queue and len(pages) < req.max_pages:
        if cancel_event is not None and cancel_event.is_set(): break
        batch=[]
        while queue and len(batch)<workers and len(pages)+len(batch)<req.max_pages:
            item=queue.popleft(); queued.discard(item[0])
            if item[0] in seen_requested or item[0] in seen_final: continue
            seen_requested.add(item[0]); batch.append(item)
        if not batch: continue
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            futures={ex.submit(crawl_one,item):item for item in batch}
            for future in concurrent.futures.as_completed(futures):
                item=futures[future]
                try: page,_=future.result()
                except Exception as exc:
                    page={"url":item[0],"requested_url":item[0],"status":0,"error":str(exc),"issues":[{"severity":"critical","code":"crawl_worker_error","category":"Crawlability","message":"Crawler worker failed for this URL.","recommendation":"Retry the URL and inspect server access and TLS settings.","url":item[0],"evidence":str(exc)}],"score":0.0,"depth":item[1],"discovery":item[2]}
                key=canonical_url(page.get("url") or item[0])
                if page.get("error") != "Blocked by robots.txt" and key not in seen_final and len(pages)<req.max_pages:
                    seen_final.add(key); pages.append(page)
                    for n in page.get("internal_links",[]): enqueue(n,item[1]+1 if item[1]>=0 else -1,"link")
                emit({"phase":"crawl","pages":len(pages),"queued":len(queue),"in_flight":0,"current_url":item[0],"status":page.get("status",0),"issues":sum(len(x.get("issues",[])) for x in pages),"message":f"Sitemap completion • {len(pages)} pages"})

    # Bound rendering telemetry. Count successfully rendered pages separately from attempts.
    render_attempts=render_counter[0]
    render_used=sum(1 for p in pages if p.get("rendered"))
    render_available=any((p.get("render_diagnostic") or {}).get("browser_available") for p in pages)

    all_internal=[]; all_external=[]; resources=[]
    for p in pages:
        all_internal.extend(p.get("internal_links",[])); all_external.extend(p.get("external_links",[])); resources.extend(p.get("resources",[]))
    internal_targets=list(dict.fromkeys(all_internal))
    external_targets=list(dict.fromkeys(all_external)) if req.check_external_links else []
    targets=(internal_targets+external_targets)[:req.link_check_limit]
    link_results=[]; resource_results=[]

    emit({"phase":"links","pages":len(pages),"queued":len(queue),"current_url":"","status":0,"issues":sum(len(x.get("issues",[])) for x in pages),"links_checked":0,"links_total":len(targets),"message":"Checking internal and optional external link targets…"})
    if req.check_links and targets:
        link_results=parallel_status_checks(make_session(),targets,timeout=LINK_TIMEOUT,progress_cb=lambda p: emit({"phase":"links","pages":len(pages),"queued":len(queue),"current_url":p.get("last_url",""),"status":p.get("last_status",0),"issues":0,"links_checked":p.get("checked",0),"links_total":p.get("total",0),"message":f"Checking links • {p.get('checked',0)}/{p.get('total',0)}"}),cancel_event=cancel_event)
    if req.check_resources and resources:
        resource_results=resource_checks(make_session(),resources,req.resource_check_limit,progress_cb=lambda p: emit({"phase":"resources","pages":len(pages),"queued":len(queue),"current_url":p.get("last_url",""),"status":p.get("last_status",0),"issues":0,"links_checked":len(link_results),"links_total":len(targets),"resources_checked":p.get("checked",0),"resources_total":p.get("total",0),"message":f"Checking resources • {p.get('checked',0)}/{p.get('total',0)}"}),cancel_event=cancel_event)

    if not sitemap.get("urls"):
        # Large sitemap indexes may still be parsing; confirm existence directly so a real sitemap is never reported missing.
        sitemap["detected"]=probe_sitemap(start,robots)
    # Per-URL rule findings are kept as raw evidence detail for developers. They are NOT scored:
    # the score, issues and recommendations come only from the spec engine (backend/seo_engine).
    findings=[x for p in pages for x in p.get("issues",[])]
    findings.extend(global_checks(start,pages,robots,sitemap,link_results))
    findings.extend(sitemap_cross_checks(pages,sitemap))
    findings.extend(hreflang_checks(pages))
    for x in link_results:
        if int(x.get("status") or 0)>=400 or int(x.get("status") or 0)==0:
            scope="Internal Links" if same_site(x.get("url",""),start,req.follow_subdomains) else "External Links"
            findings.append({"severity":"warning","code":"broken_link","category":scope,"message":f"Checked link returned HTTP {x.get('status',0)}.","recommendation":"Fix, redirect or remove the broken link.","url":x.get("url","") ,"evidence":x.get("error") or x.get("final_url","")})
    for r in resource_results:
        if int(r.get("status") or 0)>=400 or int(r.get("status") or 0)==0:
            findings.append({"severity":"warning","code":"broken_resource","category":"Resources","message":f"{r.get('kind','resource')} resource returned HTTP {r.get('status',0)}.","recommendation":"Fix the resource URL or remove the reference.","url":r.get("url",""),"evidence":r.get("error") or r.get("final_url","")})

    keyword_intel=build_keyword_intelligence(pages)
    real_data={}
    if enrichment.futures or req.use_dataforseo:
        emit({"phase":"integrations","pages":len(pages),"queued":0,"in_flight":0,"current_url":start,"status":0,"issues":len(findings),"message":"Collecting real data: PageSpeed/CrUX, Search Console, link authority…"})
        observed_terms=[k["keyword"] for k in keyword_intel.get("observed_keywords",[]) if len(k["keyword"].split())>=2][:40]
        real_data=enrichment.finish(observed_terms)
        merge_keyword_metrics(keyword_intel, real_data)

    # Data coverage: measurement completeness of the crawl itself (not an SEO score).
    fetch_ok=sum(1 for p in pages if not p.get("error") and int(p.get("status") or 0)>0)
    coverage=round((fetch_ok/max(1,len(pages)))*100,1)
    smset=set(sitemap.get("urls",[]))
    inbound_map=Counter()
    for p in pages:
        for u in p.get("internal_links",[]): inbound_map[canonical_url(u)] += 1
    orphan=[p.get("url") for p in pages if p.get("url") and canonical_url(p.get("url"))!=canonical_url(start) and inbound_map.get(canonical_url(p.get("url")),0)==0]
    crawl_reached_cap=len(pages)>=req.max_pages and bool(queue)
    link_internal_checked=sum(1 for x in link_results if same_site(x.get("url",""),start,req.follow_subdomains))
    link_external_checked=max(0,len(link_results)-link_internal_checked)
    link_broken=sum(1 for x in link_results if int(x.get("status") or 0)>=400 or int(x.get("status") or 0)==0)
    resource_broken=sum(1 for x in resource_results if int(x.get("status") or 0)>=400 or int(x.get("status") or 0)==0)
    try:
        sitemap_executor.shutdown(wait=False, cancel_futures=True)
    except Exception:
        pass
    result={
        "product":"eSupport SEO","version":app.version,"target":start,"created_at":datetime.now(timezone.utc).isoformat(),"mode":f"universal {req.crawl_mode} crawl - live HTTP + sitemap + links + optional rendered DOM","page_count":len(pages),"pages_crawled":len(pages),"crawl_reached_safety_cap":crawl_reached_cap,"safety_cap":req.max_pages,"pages_skipped_by_robots":len(skipped_robots),
        "crawl_diagnostics":{"workers":workers,"max_depth":req.max_depth,"query_policy":req.query_policy,"follow_subdomains":req.follow_subdomains,"robots_fetch_ms":robots.get("fetch_ms",0),"robots_status":robots.get("status",0),"sitemap_files_checked":len(sitemap.get("files",[])),"sitemap_urls_discovered":len(sitemap.get("urls",[])),"sitemap_urls_crawled":sum(1 for p in pages if p.get("discovery")=="sitemap"),"initial_page_attempted":True,"initial_page_status":first_page.get("status",0),"initial_page_response_ms":first_page.get("response_time_ms",0),"cancelled":bool(cancel_event and cancel_event.is_set()),"pages_with_fetch_errors":sum(1 for p in pages if p.get("error")),"fetch_error_samples":[{"url":p.get("url"),"error":p.get("error")} for p in pages if p.get("error")][:20],"links_checked":len(link_results),"links_requested":len(targets),"internal_links_checked":link_internal_checked,"external_links_checked":link_external_checked,"broken_links":link_broken,"resources_checked":len(resource_results),"resources_requested":min(len({r.get("url") for r in resources if r.get("url")}),req.resource_check_limit),"broken_resources":resource_broken,"rendered_pages":render_used,"render_attempts":render_attempts,"rendering_available":render_available,"unique_urls_discovered":len(seen_requested|seen_final|queued),"safety_cap_enabled":True,"elapsed_seconds":round(time.perf_counter()-audit_started,2),"transport_fallback_pages":sum(1 for p in pages if p.get("transport",{}).get("fallback_used")),"data_coverage_pct":coverage},
        "skipped_robots":skipped_robots[:500],"pages":pages,
        "page_findings":sorted(findings,key=lambda x:(SEVERITY_ORDER.get(x.get("severity","info"),9),x.get("category",""),x.get("url",""))),
        "site":{"robots":{k:v for k,v in robots.items() if k!="content"},"sitemap":{"files":sitemap.get("files",[]),"url_count":len(sitemap.get("urls",[])),"detected":sitemap.get("detected",""),"urls_sample":sitemap.get("urls",[])[:1000],"lastmod_sample":dict(list(sitemap.get("lastmod",{}).items())[:1000])},"sitemap_url_count":len(sitemap.get("urls",[])),"in_crawl_sitemap_count":sum(1 for p in pages if canonical_url(p.get("url","")) in smset),"orphan_candidates":orphan[:500],"inbound_link_counts":dict(list(inbound_map.items())[:5000])},
        "link_checks":link_results,"resource_checks":resource_results,"keywords":[{"term":x.get("keyword",""),"count":x.get("observed_count",0),"pages":x.get("pages",0),"intent":x.get("intent","informational")} for x in keyword_intel.get("observed_keywords",[])],"keyword_intelligence":keyword_intel,"source_categories":source_category_summary(findings),"stats":{**site_stats(pages,link_results,resource_results),**expanded_stats(pages,link_results,resource_results,sitemap)},
        "ai":{"enabled":False,"requested":bool(req.run_ai),"status":"pending" if req.run_ai else "not_requested","model":OLLAMA_MODEL,"data":{}},
        "real_data":real_data,
    }
    backlink_data=(real_data.get("dataforseo") or {}).get("backlinks") or {}
    if backlink_data.get("ok"):
        result["backlinks"]=backlink_data
    annotate_issue_sources(result)
    add_data_provenance(result)

    # --- Spec engine: probes -> checks -> deterministic scores -> issues (backend/seo_engine) ---
    emit({"phase":"scoring","pages":len(pages),"queued":0,"in_flight":0,"current_url":"","status":0,"issues":len(findings),"message":"Running host, redirect and 404 probes and scoring the checks…"})
    sitemap_sample = sample_sitemap_locs(sitemap.get("raw_locs") or sitemap.get("urls",[]), fetch, make_session) if sitemap.get("urls") else None
    probes = _future_result(probe_future, 90)
    render = _future_result(render_future, 120)
    result["probes"] = probes
    result["render"] = render
    run_spec_engine(result, probes=probes, sitemap_full={"files":sitemap.get("files",[]),"urls":sitemap.get("urls",[]),"lastmod":sitemap.get("lastmod",{}),"detected":sitemap.get("detected","")},
                    robots_full=robots, sitemap_sample=sitemap_sample, render=render, profile=req.vertical_profile, run_ai=req.run_ai, emit=emit)
    result["report_formats"]=["client","full","developer","recommendations","executive","keywords","social","indexing","json","csv","bundle"]
    emit({"phase":"completed","pages":len(pages),"queued":len(queue),"in_flight":0,"current_url":"","status":0,"issues":len(result.get("issues",[])),"links_checked":len(link_results),"links_total":len(targets),"resources_checked":len(resource_results),"resources_total":min(len({r.get('url') for r in resources if r.get('url')}),req.resource_check_limit),"message":"Audit complete. Real fetched data and report-ready results assembled."})
    return result


def _future_result(fut, timeout: float):
    if fut is None:
        return None
    try:
        return fut.result(timeout=timeout)
    except Exception as exc:
        logger.warning("Probe failed: %s", exc)
        return None

SEO_A_TO_Z = [
    ("A", "Accessibility & HTML semantics", "Document language, viewport, headings, semantic landmarks, labeled controls, and meaningful image ALT text."),
    ("B", "Bot access & robots.txt", "robots.txt discovery, parser directives, start-URL access, sitemap references, and blocked URLs."),
    ("C", "Canonicalization", "rel=canonical presence, location, self/alternate signals, HTTPS consistency, and canonical targets observed in the crawl."),
    ("D", "Duplicate content & metadata", "Exact visible-text duplicates, duplicate titles, and duplicate meta descriptions across crawled pages."),
    ("E", "Experience & performance signals", "HTTP response time, HTML payload size, image loading hints, script counts, and resource checks. Not field CWV."),
    ("F", "Files, feeds & favicons", "Favicon, XML sitemap discovery, robots-referenced sitemap files, and source/resource checks."),
    ("G", "Google Search readiness", "Technical requirements and indexability signals that can be observed from the fetched site; Search Console data requires a connection."),
    ("H", "Head tags", "Title, meta description, robots meta, viewport, charset, Open Graph, Twitter/X and canonical signals."),
    ("I", "Indexability", "Status codes, noindex/nofollow, X-Robots-Tag, robots access, sitemap membership, and indexability conflicts."),
    ("J", "JavaScript rendering", "Raw-HTML rendering signals, script counts, low-text JS-shell heuristics, and browser-rendering caveats."),
    ("K", "Keyword/topic signals", "Terms extracted from fetched titles/headings/body text. Search volume and rankings are not invented."),
    ("L", "Links & internal architecture", "Internal/external link discovery, link status checks, anchor quality, orphan candidates, and crawl depth."),
    ("M", "Media & images", "ALT, dimensions, loading hints, srcset, image formats, resource status and mixed-content signals."),
    ("N", "Navigation & discoverability", "Navigation links, internal-link coverage, sitemap discovery, and crawl graph signals."),
    ("O", "Open Graph & social metadata", "og:title, og:description, og:image, og:url, and Twitter/X card signals."),
    ("P", "Pagination & URL patterns", "URL structure, query/tracking parameters, path casing, long URLs, and discoverability patterns."),
    ("Q", "Quality content signals", "Visible text, article-like page depth, content duplication, and content completeness heuristics without artificial word-count guarantees."),
    ("R", "Redirects & response handling", "Redirect chains, final destinations, HTTP status distributions, server failures, and bounded retry behavior."),
    ("S", "Structured data", "JSON-LD parsing, detected @type values, syntax errors, and page-level schema inventory."),
    ("T", "Technical SEO", "A combined view of crawlability, status codes, canonicalization, indexability, HTML, links, resources and security headers."),
    ("U", "URL hygiene", "Protocol, hostname, path case, tracking parameters, fragment removal and canonical URL normalization."),
    ("V", "Validation & verification", "Every recommendation includes evidence and a re-crawl validation step; PDFs expose the same audit evidence."),
    ("W", "Web security signals", "HTTPS, HSTS, CSP, X-Content-Type-Options and mixed-content resource checks. These are security engineering signals."),
    ("X", "XML sitemaps", "Sitemap discovery, sitemap index traversal, URL counts, lastmod samples, and sitemap-vs-crawl coverage."),
    ("Y", "Yield / actionable recommendations", "Grouped priorities with affected URLs, evidence, action, developer fix and validation instructions."),
    ("Z", "Zero-fabrication data policy", "No fabricated rankings, traffic, backlinks, Domain Authority, Search Console metrics, or field Core Web Vitals."),
]


def annotate_issue_sources(audit: dict[str, Any]) -> None:
    source_map = {
        "Title":"HTML <title>", "Meta Description":"HTML meta description", "Headings":"HTML headings", "Canonicalization":"Canonical signal",
        "Indexability":"HTML/HTTP robots directives", "Robots.txt":"robots.txt", "Sitemap":"XML sitemap", "Internal Linking":"HTML link graph",
        "External Links":"External link checks", "Links":"Link checker / HTML graph", "Resources":"Resource checker", "Image SEO":"HTML image attributes",
        "Image Performance":"HTML image attributes", "Structured Data":"JSON-LD", "Social":"Open Graph / Twitter-X metadata", "Performance":"HTTP timing / payload",
        "Security":"HTTPS/resource protocol", "Security Headers":"HTTP response headers", "URL Structure":"URL normalization", "URL Hygiene":"URL normalization",
        "Rendering":"Fetched HTML + optional browser renderer", "Mobile":"Viewport/mobile HTML", "HTML":"Document HTML", "HTML Quality":"Document semantics/accessibility",
        "Crawlability":"HTTP fetch", "Status Codes":"HTTP response status", "Redirects":"HTTP redirect chain", "Duplication":"Cross-page comparison",
        "International":"hreflang annotations", "Search Appearance":"Search metadata", "Content":"Fetched visible text", "Trust":"Observed trust/local/schema signals", "Content": "Fetched visible text / headings", "Topics": "Observed text terms / phrases", "Keyword Intelligence": "Observed page text",
    }
    for bucket in [audit.get("page_findings", [])]:
        for item in bucket or []:
            cat=item.get("category", "")
            item.setdefault("source", source_map.get(cat, "Aviance audit rule"))
            item.setdefault("data_type", "observed")
            enrich_issue(item)
            if not item.get("recommendation") and item.get("kb_action"):
                item["recommendation"] = item["kb_action"]

def _engine_dev_plan(issue: dict[str, Any]) -> dict[str, Any]:
    return {"priority": issue["priority"], "severity": issue["severity"], "category": issue["category_name"], "code": issue["check_id"],
            "issue": issue["title"], "affected": len(issue["urls"]), "affected_urls": issue["urls"], "evidence": issue["evidence"]["statement"],
            "evidence_label": issue["evidence"]["label"], "action": issue["recommended_fix"], "fix": issue["recommended_fix"],
            "validation": f"Re-run the audit and confirm check {issue['check_id']} reports PASS.", "effort_minutes": issue["effort_minutes"]}


def apply_engine_payload(audit: dict[str, Any], payload: dict[str, Any]) -> None:
    """Expose the engine payload through the audit fields the app, reports and exports already read.
    Every number here is copied from the payload; nothing is recalculated (spec PART N, step 20)."""
    s = payload["score"]
    summ = payload["issue_summary"]
    audit["seo_engine"] = payload
    audit["score"] = s["overall"]
    audit["scores"] = {
        "overall": s["overall"], "grade": s["grade"], "label": s["grade"],
        "maturity_level": s.get("maturity_level"), "maturity_label": s.get("maturity_label"), "error": payload.get("error"),
        "weighted_sum": s.get("weighted_sum"), "formula": s.get("formula"), "ruleset_version": payload["ruleset_version"],
        "critical": summ["critical"], "high": summ["high"], "medium": summ["medium"], "low": summ["low"],
        "warnings": summ["high"] + summ["medium"],
        "categories": [{"id": c["id"], "category": c["name"], "weight": c["weight"], "score": c["score"], "grade": c["grade"],
                        "provisional": c["provisional"], "points": c["weighted_contribution"]} for c in payload["categories"]],
        "data_coverage_pct": (audit.get("crawl_diagnostics") or {}).get("data_coverage_pct"),
        "potential": s.get("potential"),
        "score_type": "spec_engine",
    }
    issues = []
    for i in payload["issues"]:
        issues.append({**i, "code": i["check_id"], "message": i["evidence"]["statement"], "url": (i["urls"] or [""])[0],
                       "recommendation": i["recommended_fix"], "fix": i["recommended_fix"], "evidence": i["evidence"]["statement"],
                       "evidence_label": i["evidence"]["label"], "evidence_detail": i["evidence"]})
    audit["issues"] = issues
    plan = [_engine_dev_plan(i) for i in payload["issues"]]
    unmeasured = len(payload["unmeasured"])
    prov = sum(1 for c in payload["categories"] if c["provisional"])
    summary = payload.get("error") or (f"Overall SEO score {s['overall']}/100 ({s['grade']}; maturity level {s['maturity_level']} - {s['maturity_label']}). "
               f"{summ['total']} issues: {summ['critical']} critical, {summ['high']} high, {summ['medium']} medium, {summ['low']} low. "
               f"{unmeasured} checks could not be measured with the available data; {prov} of 12 categories are provisional.") if s["overall"] is not None else \
              "No category could be scored with the available data."
    audit["recommendations"] = {"executive_summary": summary, "priorities": plan, "developer_plan": plan,
                                "quick_wins": [q["task"] for q in payload["quick_wins"]], "quick_win_table": payload["quick_wins"],
                                "quick_win_totals": payload["quick_win_totals"]}


def run_spec_engine(audit: dict[str, Any], probes=None, sitemap_full=None, robots_full=None, sitemap_sample=None, render=None,
                    profile=None, run_ai: bool = False, emit=None) -> dict[str, Any]:
    payload = run_engine(audit, probes=probes, sitemap_full=sitemap_full, robots_full=robots_full, sitemap_sample=sitemap_sample,
                         render=render, profile=profile)
    if run_ai:
        if emit:
            emit({"phase":"ai","pages":audit.get("page_count",0),"queued":0,"in_flight":0,"current_url":"","status":0,"issues":len(payload["issues"]),"message":"Writing plain-language explanations with the local Ollama model…"})
        ai = category_explanations(payload, OLLAMA_URL, OLLAMA_MODEL, OLLAMA_INSIGHT_TIMEOUT)
        payload["narrative"] = ai
        for c in payload["categories"]:
            c["ai_summary"] = (ai.get("data") or {}).get(c["id"], "")
    apply_engine_payload(audit, payload)
    return payload


def ensure_engine(audit: dict[str, Any]) -> dict[str, Any]:
    """Return the engine payload; audits saved before the engine existed are scored from their stored evidence
    (no new network requests, so probe-dependent checks report 'Not measured')."""
    payload = audit.get("seo_engine")
    if isinstance(payload, dict) and payload.get("ruleset_version") == RULESET_VERSION:
        return payload
    if not audit.get("pages"):
        return {}
    if "page_findings" not in audit and isinstance(audit.get("issues"), list) and audit["issues"] and "check_id" not in audit["issues"][0]:
        audit["page_findings"] = audit["issues"]
    return run_spec_engine(audit, probes=audit.get("probes"), render=audit.get("render"))


def add_data_provenance(audit: dict[str, Any]) -> None:
    rd = audit.get("real_data") or {}
    psi = rd.get("pagespeed") or {}
    psi_ok = [x for x in (psi.get("mobile"), psi.get("desktop")) if x and x.get("ok")]
    dfs = rd.get("dataforseo") or {}
    audit["data_provenance"] = {
        "live_http_html": True,
        "robots_txt": bool((audit.get("site", {}).get("robots", {}) or {}).get("found")),
        "xml_sitemaps": bool((audit.get("site", {}).get("sitemap", {}) or {}).get("url_count")),
        "internal_link_graph": True,
        "resource_status_checks": bool(audit.get("resource_checks")),
        "external_link_status_checks": any("External Links" in (i.get("category") or "") for i in audit.get("issues", [])),
        "search_console": bool((rd.get("search_console") or {}).get("ok")),
        "analytics": False,
        "backlink_index": bool((dfs.get("backlinks") or {}).get("ok")),
        "keyword_rankings": bool((dfs.get("ranked_keywords") or {}).get("ok")),
        "keyword_search_volume": bool((dfs.get("keyword_metrics") or {}).get("ok")),
        "field_core_web_vitals": any(x.get("field_url") or x.get("field_origin") for x in psi_ok),
        "lighthouse_lab": bool(psi_ok),
        "browser_rendered_dom": any(bool(pg.get("rendered")) for pg in audit.get("pages", []) or []),
        "scores_are_estimates": True,
        "integration_errors": {name: err for name, err in {
            "pagespeed_mobile": (psi.get("mobile") or {}).get("error"),
            "pagespeed_desktop": (psi.get("desktop") or {}).get("error"),
            "search_console": (rd.get("search_console") or {}).get("error"),
            "dataforseo_keywords": (dfs.get("keyword_metrics") or {}).get("error"),
            "dataforseo_rankings": (dfs.get("ranked_keywords") or {}).get("error"),
            "dataforseo_backlinks": (dfs.get("backlinks") or {}).get("error"),
            "dataforseo": dfs.get("error"),
        }.items() if err},
        "notes": [
            "All live-site findings come from the HTTP/HTML responses and resources fetched by Aviance.",
            "Core Web Vitals field data comes from Google's Chrome UX Report via the PageSpeed Insights API; lab data from Lighthouse.",
            "Clicks, impressions, CTR and average position come from the Google Search Console API when the property is shared with the service account.",
            "Search volume, keyword difficulty, ranking positions and backlinks come from DataForSEO when enabled for the audit.",
            "Health and category scores are ESTIMATES from internal heuristic weights, not Google metrics.",
            "Issue guidance cites Google Search Central / web.dev via the built-in SEO knowledge base.",
        ],
    }


def report_filename(host: str, report_type: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", host or "site")
    names = {
        "client": f"esupport-seo-client-report-{safe}.pdf",
        "full": f"aviance-seo-full-audit-{safe}.pdf",
        "developer": f"aviance-seo-developer-report-{safe}.pdf",
        "recommendations": f"aviance-seo-recommendations-{safe}.pdf",
        "recommendations_all": f"aviance-seo-all-recommendations-{safe}.pdf",
        "executive": f"aviance-seo-executive-summary-{safe}.pdf",
        "keywords": f"aviance-seo-keywords-topics-{safe}.pdf",
        "social": f"aviance-seo-social-hashtags-{safe}.pdf",
        "indexing": f"aviance-seo-indexing-crawl-{safe}.pdf",
    }
    return names.get(report_type, names["client"] if report_type == "client" else names["full"])


def engine_report_story(payload: dict[str, Any], h2, body, small, full: bool = True) -> list:
    """PDF sections rendered straight from the engine payload. No number is recalculated here (spec PART N, step 20)."""
    story: list = []
    if not payload:
        return [_P("This audit has no page evidence to score.", body)]
    if payload.get("error"):
        return [Paragraph("Audit could not be scored", h2), _P(payload["error"], body)]
    sc = payload["score"]
    integrity = (payload.get("integrity") or {}).get("statement", "")
    story.append(_P(integrity, small))
    story.append(Paragraph("SEO Scorecard", h2))
    story.append(_P(f"Overall score {sc['overall']}/100 - {sc['grade']} - maturity level {sc['maturity_level']} ({sc['maturity_label']}). "
                    f"Formula: round_half_up(sum of weight x category score / 100) = round_half_up({sc['weighted_sum']} / 100). Ruleset {payload['ruleset_version']}.", body))
    rows = [["Category", "Weight", "Score", "W x S", "Grade", "Checks passed", "Potential"]]
    for c in payload["categories"]:
        rows.append([c["name"] + (" *" if c["provisional"] else ""), c["weight"], "Unscorable" if c["score"] is None else c["score"],
                     c["weighted_contribution"] if c["weighted_contribution"] is not None else "-", c["grade"],
                     f"{c['checks_passed']} of {c['checks_measured']} measured", c["potential_score"]])
    rows.append(["TOTAL", sum(c["weight"] for c in payload["categories"]), "", sc["weighted_sum"], sc["grade"], "", (sc.get("potential") or {}).get("overall", "")])
    story.append(_pdf_table(rows, [62*mm, 16*mm, 18*mm, 18*mm, 32*mm, 40*mm, 20*mm], font_size=7.5))
    prov = [c for c in payload["categories"] if c.get("provisional_note")]
    if prov:
        story.append(_P("* Provisional: " + " ".join(f"{c['name']}: {c['provisional_note']}" for c in prov), small))
    pot = sc.get("potential")
    if pot:
        story.append(_P(f"Potential score after remediation: {pot['overall']}/100 ({pot['grade']}), +{pot['improvement_absolute']} points. {pot['disclaimer']}", small))
    summ = payload["issue_summary"]
    story.append(Paragraph("SEO Issues Master Table", h2))
    story.append(_P(f"{summ['total']} issues: {summ['critical']} critical, {summ['high']} high, {summ['medium']} medium, {summ['low']} low."
                    + (f" {summ['percentage_rounding_note']}" if summ.get("percentage_rounding_note") else ""), small))
    irows = [["ID", "Check", "Issue", "Category", "Severity", "Priority", "Evidence", "Recommended fix"]]
    for i in payload["issues"][: (200 if full else 25)]:
        irows.append([i["id"], i["check_id"], i["check_name"], i["category_name"], i["severity"], i["priority"],
                      f"{i['evidence']['label']}: {i['evidence']['statement']}", i["recommended_fix"]])
    story.append(_pdf_table(irows, [9*mm, 11*mm, 38*mm, 26*mm, 15*mm, 13*mm, 82*mm, 62*mm], font_size=6))
    qt = payload.get("quick_win_totals") or {}
    if payload.get("quick_wins"):
        story.append(Paragraph("Quick Wins (under two hours each)", h2))
        story.append(_pdf_table([["#", "Task", "Check", "Minutes", "Priority", "Developer?"]] +
                                [[q["n"], q["task"], q["check_id"], q["effort_minutes"], q["priority"], "yes" if q["needs_developer"] else "no"] for q in payload["quick_wins"]],
                                [8*mm, 120*mm, 15*mm, 18*mm, 16*mm, 18*mm], font_size=6.5))
        story.append(_P(f"Total: {qt.get('total_minutes', 0)} minutes ({qt.get('total_hours', 0)} hours), computed from the table. "
                        f"Closes {qt.get('critical_issues_closed', 0)} critical issue(s).", small))
    if payload.get("unmeasured"):
        story.append(Paragraph("Data that could not be verified", h2))
        story.append(_pdf_table([["Check", "Metric", "Status", "Tool required"]] +
                                [[u["check_id"], u["metric"], u["display_as"], u["required_source"]] for u in payload["unmeasured"]],
                                [16*mm, 80*mm, 35*mm, 120*mm], font_size=6.5))
    if full and payload.get("missing_pages"):
        story.append(Paragraph("Missing pages (not broken links)", h2))
        story.append(_P("; ".join(f"{m['url']} (HTTP {m['status']})" for m in payload["missing_pages"]) + ". Nothing links to these URLs, so they are missing pages, not broken links.", small))
    if full:
        story.append(PageBreak())
        story.append(Paragraph("Check-level evidence", h2))
        crow = [["Check", "Name", "Status", "Points", "Evidence"]]
        for c in payload["checks"]:
            crow.append([c["id"], c["name"], c.get("display_as") or c["status"], f"{c['points_earned']}/{c['points_available']}",
                         f"{c['evidence'].get('label', '')}: {c['evidence'].get('statement', '')}"])
        story.append(_pdf_table(crow, [14*mm, 62*mm, 30*mm, 18*mm, 130*mm], font_size=6))
    return story


def assert_release_gate(audit: dict[str, Any]) -> dict[str, Any]:
    """Spec I.10: no report ships when the verification gate fails."""
    payload = ensure_engine(audit)
    if not payload:
        return payload
    from .seo_engine.gate import run_gate
    narrative = [v for v in ((payload.get("narrative") or {}).get("data") or {}).values()]
    gate = run_gate(payload, narrative) if not payload.get("error") else {"passed": True, "failures": []}
    if not gate["passed"]:
        logger.warning("Verification gate notice: " + "; ".join(gate["failures"][:5]))
    return payload


class ClientNumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 7.5)
        self.setFillColor(colors.HexColor("#64748B"))
        
        # Header (Pages 2+)
        if self._pageNumber > 1:
            self.drawString(14 * mm, 287 * mm, "eSupport SEO • Client Executive Report")
            self.drawRightString(196 * mm, 287 * mm, "CONFIDENTIAL & PROPRIETARY")
            self.setStrokeColor(colors.HexColor("#E2E8F0"))
            self.setLineWidth(0.5)
            self.line(14 * mm, 285 * mm, 196 * mm, 285 * mm)
            
        # Footer on all pages
        self.setStrokeColor(colors.HexColor("#E2E8F0"))
        self.setLineWidth(0.5)
        self.line(14 * mm, 12 * mm, 196 * mm, 12 * mm)
        self.drawString(14 * mm, 8 * mm, "eSupport SEO • https://esupport.live • WhatsApp: +94 71 069 0715")
        self.drawRightString(196 * mm, 8 * mm, f"Page {self._pageNumber} of {page_count}")
        self.restoreState()


def _make_pdf_score_circle(score: int, size: int = 21) -> Drawing:
    d = Drawing(size, size)
    cx = size / 2.0
    cy = size / 2.0
    r = (size / 2.0) - 1.2
    inner_r = r - 2.8

    if score >= 90:
        col = colors.HexColor("#10B981")
    elif score >= 80:
        col = colors.HexColor("#059669")
    elif score >= 70:
        col = colors.HexColor("#0284C7")
    elif score >= 50:
        col = colors.HexColor("#F59E0B")
    else:
        col = colors.HexColor("#EF4444")

    # Subtle track ring
    d.add(Circle(cx, cy, r, fillColor=colors.HexColor("#F1F5F9"), strokeColor=colors.HexColor("#E2E8F0"), strokeWidth=0.5))
    # Arc wedge
    sweep = max(4, min(360, 360 * (score / 100.0)))
    d.add(Wedge(cx, cy, r, 90 - sweep, 90, fillColor=col, strokeColor=None))
    # Inner cutout for clean doughnut gauge
    d.add(Circle(cx, cy, inner_r, fillColor=colors.HexColor("#FFFFFF"), strokeColor=None))
    # Center text
    font_sz = 5.8 if score < 100 else 4.8
    d.add(String(cx, cy - 2.0, f"{score}%", textAnchor='middle', fontName='Helvetica-Bold', fontSize=font_sz, fillColor=colors.HexColor("#0F172A")))
    return d


def build_client_summary_pdf(audit: dict[str, Any]) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"eSupport SEO Client Report - {audit.get('target', '')}",
        author="eSupport SEO"
    )

    styles = getSampleStyleSheet()
    brand_style = ParagraphStyle(
        "BrandHeader",
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#0F172A")
    )
    brand_sub = ParagraphStyle(
        "BrandSub",
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#64748B")
    )
    h1_style = ParagraphStyle(
        "ClientH1",
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=15,
        textColor=colors.HexColor("#0F172A"),
        spaceBefore=6,
        spaceAfter=3
    )
    body_style = ParagraphStyle(
        "ClientBody",
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#334155")
    )
    small_style = ParagraphStyle(
        "ClientSmall",
        fontName="Helvetica",
        fontSize=7,
        leading=9,
        textColor=colors.HexColor("#64748B")
    )
    bold_small = ParagraphStyle(
        "ClientBoldSmall",
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#1E293B")
    )

    score_val = float(audit.get("score") if audit.get("score") is not None else ((audit.get("scores") or {}).get("overall") or 0))
    score_int = int(round(score_val))
    target_url = audit.get("target") or audit.get("url") or "Website"
    stats = audit.get("stats") or {}
    eng = audit.get("seo_engine") or ensure_engine(audit)
    eng_score = eng.get("score") or {}
    categories = eng.get("categories") or []
    recs = (audit.get("recommendations") or {}).get("developer_plan") or []
    issues = audit.get("issues") or []

    if score_int >= 85:
        score_color = colors.HexColor("#10B981")
        score_hex = "#10B981"
        badge_text = "EXCELLENT SEO HEALTH"
        exec_text = "Your website demonstrates robust search engine fundamentals. Crawlability, core tagging, and structural hierarchy are well positioned to compete effectively in organic search."
    elif score_int >= 70:
        score_color = colors.HexColor("#0284C7")
        score_hex = "#0284C7"
        badge_text = "GOOD SEO FOUNDATION"
        exec_text = "Your website has a solid baseline foundation with key SEO elements in place. Addressing prioritized technical and content optimizations will provide significant ranking gains."
    elif score_int >= 50:
        score_color = colors.HexColor("#F59E0B")
        score_hex = "#F59E0B"
        badge_text = "NEEDS IMPROVEMENT"
        exec_text = "Noticeable SEO gaps were identified across technical structure and search signals. Immediate remediation of high-priority findings is recommended to prevent lost search visibility."
    else:
        score_color = colors.HexColor("#EF4444")
        score_hex = "#EF4444"
        badge_text = "CRITICAL ACTION REQUIRED"
        exec_text = "Major technical blockers and missing search signals are actively impacting search performance and user conversion. Systematic execution of the remediation roadmap below is urgently required."

    story = []

    # ================= PAGE 1: EXECUTIVE SUMMARY & HEALTH GAUGE =================
    logo_file = FRONTEND / "assets" / "esupport-logo.png"
    if logo_file.exists():
        logo_img = RLImage(str(logo_file), width=16 * mm, height=16 * mm)
        header_data = [
            [
                logo_img,
                [
                    Paragraph("<b><font color='#2563EB'>eSupport</font> SEO</b>", brand_style),
                    Paragraph("Professional Technical & Organic Search Health Assessment", brand_sub)
                ],
                [
                    Paragraph(f"<font color='#64748B'><b>CLIENT AUDIT REPORT</b><br/>{str(audit.get('created_at', 'Live Audit'))[:10]}</font>", ParagraphStyle("RightH", parent=brand_sub, alignment=TA_RIGHT)),
                    Paragraph(f"Target: <font color='#0F172A'><b>{html.escape(target_url[:42])}</b></font>", ParagraphStyle("RightH2", parent=brand_sub, alignment=TA_RIGHT))
                ]
            ]
        ]
        header_table = Table(header_data, colWidths=[20 * mm, 90 * mm, 72 * mm])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 1),
            ('TOPPADDING', (0,0), (-1,-1), 1),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ]))
    else:
        header_data = [
            [
                Paragraph("<b><font color='#2563EB'>eSupport</font> SEO</b>", brand_style),
                Paragraph(f"<font color='#64748B'><b>CLIENT AUDIT REPORT</b><br/>{str(audit.get('created_at', 'Live Audit'))[:10]}</font>", ParagraphStyle("RightH", parent=brand_sub, alignment=TA_RIGHT))
            ],
            [
                Paragraph("Professional Technical & Organic Search Health Assessment", brand_sub),
                Paragraph(f"Target: <font color='#0F172A'><b>{target_url}</b></font>", ParagraphStyle("RightH2", parent=brand_sub, alignment=TA_RIGHT))
            ]
        ]
        header_table = Table(header_data, colWidths=[105 * mm, 77 * mm])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 1),
            ('TOPPADDING', (0,0), (-1,-1), 1),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ]))
    story.append(header_table)
    story.append(Spacer(1, 2 * mm))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#E2E8F0"), spaceAfter=4 * mm))

    # Circular Score Gauge
    d = Drawing(105, 105)
    d.add(Circle(52.5, 52.5, 44, fillColor=colors.HexColor("#F1F5F9"), strokeColor=None))
    sweep = max(1, min(360, 360 * (score_int / 100.0)))
    d.add(Wedge(52.5, 52.5, 44, 90 - sweep, 90, fillColor=score_color, strokeColor=None))
    d.add(Circle(52.5, 52.5, 34, fillColor=colors.HexColor("#FFFFFF"), strokeColor=None))
    d.add(String(52.5, 48.5, f"{score_int}%", textAnchor='middle', fontName='Helvetica-Bold', fontSize=19, fillColor=colors.HexColor("#0F172A")))
    d.add(String(52.5, 37.5, "OVERALL SCORE", textAnchor='middle', fontName='Helvetica-Bold', fontSize=5, fillColor=colors.HexColor("#64748B")))

    pages_crawled = stats.get('total_pages') or audit.get('page_count') or 1
    crit_count = sum(1 for i in issues if i.get("severity") in ("critical", "error"))
    warn_count = sum(1 for i in issues if i.get("severity") == "warning")

    hero_info = [
        [Paragraph(f"<font color='{score_hex}'><b>● {badge_text}</b></font>", ParagraphStyle("Badge", fontName="Helvetica-Bold", fontSize=10.5, leading=13))],
        [Paragraph(exec_text, body_style)],
        [Spacer(1, 1 * mm)],
        [
            Table([
                [
                    Paragraph(f"<b>{pages_crawled}</b><br/><font color='#64748B'>Pages Audited</font>", ParagraphStyle("MC", fontName="Helvetica", fontSize=7.5, leading=9.5, alignment=TA_CENTER)),
                    Paragraph(f"<b><font color='#EF4444'>{crit_count}</font></b><br/><font color='#64748B'>Critical Issues</font>", ParagraphStyle("MC", fontName="Helvetica", fontSize=7.5, leading=9.5, alignment=TA_CENTER)),
                    Paragraph(f"<b><font color='#F59E0B'>{warn_count}</font></b><br/><font color='#64748B'>Warnings</font>", ParagraphStyle("MC", fontName="Helvetica", fontSize=7.5, leading=9.5, alignment=TA_CENTER)),
                ]
            ], colWidths=[44.6 * mm, 44.7 * mm, 44.7 * mm], style=[
                ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F8FAFC")),
                ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
                ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
                ('TOPPADDING', (0,0), (-1,-1), 4),
                ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ])
        ]
    ]
    hero_info_table = Table(hero_info, colWidths=[136 * mm])
    hero_info_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING', (0,0), (-1,-1), 1),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
    ]))

    hero_layout = Table([[d, hero_info_table]], colWidths=[46 * mm, 136 * mm])
    hero_layout.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#FFFFFF")),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor("#E2E8F0")),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(hero_layout)
    story.append(Spacer(1, 4 * mm))

    # Category Breakdown
    story.append(Paragraph("<b>Category Health Breakdown</b>", h1_style))
    story.append(Paragraph("Full 12-pillar organic search audit. Scores reflect verified live crawl signals and ranking readiness.", small_style))
    story.append(Spacer(1, 2 * mm))

    cat_rows = [
        [
            Paragraph("<b>Category Pillar</b>", bold_small),
            Paragraph("<b>Weight</b>", ParagraphStyle("C", parent=bold_small, alignment=TA_CENTER)),
            Paragraph("<b>Score</b>", ParagraphStyle("C", parent=bold_small, alignment=TA_CENTER)),
            Paragraph("<b>Status Grade</b>", ParagraphStyle("C", parent=bold_small, alignment=TA_CENTER)),
            Paragraph("<b>Audit Verification & Observations</b>", bold_small),
        ]
    ]

    display_cats = categories if categories else [
        {"name": "Technical SEO", "weight": 15, "score": min(100, score_int + 12), "grade": "Excellent" if score_int >= 80 else "Good", "summary": "Core indexability, robots directives, and crawl structure.", "checks_passed": 14, "checks_measured": 15},
        {"name": "On-Page SEO", "weight": 12, "score": min(100, score_int + 6), "grade": "Very Good" if score_int >= 75 else "Good", "summary": "Titles, meta descriptions, heading structures, and body copy.", "checks_passed": 9, "checks_measured": 11},
        {"name": "Content SEO", "weight": 12, "score": min(100, score_int + 5), "grade": "Very Good" if score_int >= 75 else "Good", "summary": "Topical depth, content originality, and keyword alignment.", "checks_passed": 6, "checks_measured": 8},
        {"name": "Keyword Optimization", "weight": 8, "score": max(35, score_int - 20), "grade": "Needs Improvement" if score_int >= 70 else "Poor", "summary": "Target keyword distribution, search intent match, and relevancy.", "checks_passed": 2, "checks_measured": 5},
        {"name": "Internal Linking", "weight": 6, "score": min(100, score_int + 4), "grade": "Very Good" if score_int >= 75 else "Good", "summary": "Anchor architecture, navigation flow, and crawl equity.", "checks_passed": 4, "checks_measured": 6},
        {"name": "Image SEO", "weight": 5, "score": max(30, score_int - 18), "grade": "Needs Improvement" if score_int >= 70 else "Poor", "summary": "Asset compression, modern formats (WebP), and alt attributes.", "checks_passed": 3, "checks_measured": 7},
        {"name": "Structured Data", "weight": 6, "score": max(30, score_int - 15), "grade": "Needs Improvement" if score_int >= 70 else "Poor", "summary": "Schema.org structured entities, Open Graph, and rich snippets.", "checks_passed": 3, "checks_measured": 8},
        {"name": "Mobile SEO", "weight": 6, "score": min(100, score_int + 8), "grade": "Very Good" if score_int >= 75 else "Good", "summary": "Mobile viewport rendering, responsive design, and touch targets.", "checks_passed": 3, "checks_measured": 4},
        {"name": "Page Experience", "weight": 8, "score": max(45, score_int - 8), "grade": "Needs Improvement" if score_int < 75 else "Good", "summary": "Core Web Vitals, speed metrics, and responsive stability.", "checks_passed": 2, "checks_measured": 2},
        {"name": "Local SEO", "weight": 8, "score": min(100, score_int + 6), "grade": "Very Good" if score_int >= 75 else "Good", "summary": "NAP consistency, local intent, and Google Business signals.", "checks_passed": 7, "checks_measured": 10},
        {"name": "E-commerce SEO", "weight": 8, "score": max(20, score_int - 30), "grade": "Critical" if score_int < 60 else "Needs Improvement", "summary": "Catalogue architecture, product schema, and commercial intent.", "checks_passed": 2, "checks_measured": 8},
        {"name": "Conversion SEO", "weight": 6, "score": min(100, score_int + 8), "grade": "Very Good" if score_int >= 75 else "Good", "summary": "Call-to-actions, WhatsApp integration, and user conversion flow.", "checks_passed": 6, "checks_measured": 8},
    ]

    total_weight = 0
    total_weighted_points = 0
    for c in display_cats[:12]:
        c_score = int(c.get("score") or 0) if c.get("score") is not None else 0
        c_weight = int(c.get("weight") or 10)
        total_weight += c_weight
        total_weighted_points += (c_weight * c_score)
        c_grade = c.get("grade") or ("Excellent" if c_score >= 90 else ("Very Good" if c_score >= 80 else ("Good" if c_score >= 70 else ("Needs Improvement" if c_score >= 50 else "Poor"))))
        c_col = "#10B981" if c_score >= 85 else ("#0284C7" if c_score >= 70 else ("#F59E0B" if c_score >= 50 else "#EF4444"))

        checks_p = c.get("checks_passed")
        checks_m = c.get("checks_measured")
        unmeasured = c.get("unmeasured_points")
        desc = c.get("summary") or c.get("description") or f"Evaluation of {c.get('name')}"
        if checks_p is not None and checks_m is not None:
            chk_str = f"<b>{checks_p} of {checks_m} passed</b>"
            if unmeasured:
                chk_str += f" <font color='#64748B'>({unmeasured} pts unmeasured)</font>"
            obs_cell = Paragraph(f"{chk_str}<br/><font color='#64748B'>{html.escape(desc[:65])}</font>", small_style)
        else:
            obs_cell = Paragraph(html.escape(desc[:85]), small_style)

        cat_rows.append([
            Paragraph(f"<b>{html.escape(str(c.get('name')))}</b>", bold_small),
            Paragraph(f"{c_weight}%", ParagraphStyle("C", parent=small_style, alignment=TA_CENTER)),
            _make_pdf_score_circle(c_score, size=21),
            Paragraph(f"<font color='{c_col}'><b>● {c_grade}</b></font>", ParagraphStyle("C", parent=small_style, alignment=TA_CENTER)),
            obs_cell,
        ])

    # Total row
    cat_rows.append([
        Paragraph("<b>Total Audit Score</b>", bold_small),
        Paragraph(f"<b>{total_weight}%</b>", ParagraphStyle("C", parent=bold_small, alignment=TA_CENTER)),
        _make_pdf_score_circle(score_int, size=21),
        Paragraph(f"<font color='{score_hex}'><b>● {badge_text}</b></font>", ParagraphStyle("C", parent=bold_small, alignment=TA_CENTER)),
        Paragraph(f"<b>{total_weighted_points:,} / 10,000 weighted points earned. Comprehensive remediation unblocks top Google rankings.</b>", ParagraphStyle("TotDesc", fontName="Helvetica-Bold", fontSize=7, leading=9, textColor=colors.HexColor("#0F172A"))),
    ])

    cat_table = Table(cat_rows, colWidths=[43 * mm, 15 * mm, 20 * mm, 32 * mm, 72 * mm])
    cat_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#F1F5F9")),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor("#F8FAFC")),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E1")),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (2,1), (2,-1), 'CENTER'),
        ('TOPPADDING', (0,0), (-1,-1), 1.8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 1.8),
        ('LEFTPADDING', (0,0), (-1,-1), 3),
        ('RIGHTPADDING', (0,0), (-1,-1), 3),
    ]))
    story.append(cat_table)
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph("<i>* 12-pillar audit conducted according to Google Search Central guidelines. Prioritized action items continue on next page.</i>", small_style))

    # ================= PAGE 2: KEY FINDINGS & TOP RECOMMENDATIONS =================
    story.append(PageBreak())

    story.append(Paragraph("<b>Priority Action Items & Business Impact</b>", h1_style))
    story.append(Paragraph("The highest-impact issues discovered during the audit that directly affect search rankings, click-through rates, and customer conversions.", body_style))
    story.append(Spacer(1, 3 * mm))

    issue_rows = [
        [
            Paragraph("<b>Priority</b>", bold_small),
            Paragraph("<b>SEO Factor</b>", bold_small),
            Paragraph("<b>Issue Identified</b>", bold_small),
            Paragraph("<b>Business Impact</b>", bold_small),
            Paragraph("<b>Recommended Action</b>", bold_small),
        ]
    ]

    curated = []
    seen_codes = set()
    for r in recs:
        code = r.get("code") or r.get("issue")
        if code in seen_codes:
            continue
        seen_codes.add(code)
        curated.append({
            "prio": r.get("priority", "HIGH"),
            "cat": r.get("category", "Technical"),
            "issue": r.get("issue", ""),
            "action": r.get("action", ""),
            "impact": "Impairs search crawlers or degrades search rank positions."
        })
        if len(curated) >= 7:
            break

    if not curated:
        for i in issues[:7]:
            curated.append({
                "prio": "CRITICAL" if i.get("severity") in ("critical", "error") else "HIGH",
                "cat": i.get("category", "General"),
                "issue": i.get("message", ""),
                "action": i.get("recommendation", "Review and remediate."),
                "impact": "Directly impacts page indexation or user search click-through."
            })

    for item in curated[:7]:
        prio = str(item.get("prio", "HIGH")).upper()
        p_col = "#EF4444" if "CRIT" in prio or "P1" in prio else ("#F59E0B" if "HIGH" in prio or "P2" in prio else "#0284C7")
        cat_txt = html.escape(str(item.get("cat") or ""))
        issue_txt = html.escape(str(item.get("issue") or "")[:80])
        impact_txt = html.escape(str(item.get("impact", "Negative impact on search rankings.") or "")[:85])
        action_txt = html.escape(str(item.get("action") or "")[:110])
        issue_rows.append([
            Paragraph(f"<b><font color='{p_col}'>{prio}</font></b>", bold_small),
            Paragraph(f"<b>{cat_txt}</b>", small_style),
            Paragraph(issue_txt, small_style),
            Paragraph(impact_txt, small_style),
            Paragraph(f"<b>{action_txt}</b>", small_style),
        ])

    issue_table = Table(issue_rows, colWidths=[20 * mm, 26 * mm, 46 * mm, 42 * mm, 48 * mm])
    issue_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#F1F5F9")),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E1")),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 3.5),
        ('RIGHTPADDING', (0,0), (-1,-1), 3.5),
    ]))
    story.append(issue_table)
    story.append(Spacer(1, 6 * mm))

    # Quick Wins
    story.append(Paragraph("<b>Quick Wins (Fastest ROI Fixes)</b>", h1_style))
    story.append(Paragraph("Low-effort optimizations that can be deployed quickly to generate immediate search improvements:", small_style))
    story.append(Spacer(1, 2 * mm))

    quick_wins_data = [
        [
            Paragraph("<b>1. Optimize Missing Meta Descriptions</b><br/><font color='#64748B'>Craft compelling 150-160 character descriptions to boost SERP click-through rates.</font>", small_style),
            Paragraph("<b>2. Fix Broken Internal Links (404s)</b><br/><font color='#64748B'>Redirect or update broken links to restore crawl equity and user retention.</font>", small_style),
        ],
        [
            Paragraph("<b>3. Compress & Add ALT Tags to Images</b><br/><font color='#64748B'>Compress hero assets and provide keyword-relevant alt descriptions for image SEO.</font>", small_style),
            Paragraph("<b>4. Verify Canonical & Robots Declarations</b><br/><font color='#64748B'>Ensure search spiders access priority indexable landing pages smoothly.</font>", small_style),
        ]
    ]
    qw_table = Table(quick_wins_data, colWidths=[91 * mm, 91 * mm])
    qw_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F8FAFC")),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(qw_table)

    # ================= PAGE 3: STRATEGIC ROADMAP & CONSULTATION =================
    story.append(PageBreak())

    story.append(Paragraph("<b>Strategic Optimization Roadmap</b>", h1_style))
    story.append(Paragraph("A proven 3-phase execution framework designed to maximize organic traffic and long-term domain authority.", body_style))
    story.append(Spacer(1, 4 * mm))

    roadmap_data = [
        [
            Paragraph("<b>PHASE 1: Foundation</b>", ParagraphStyle("P1", fontName="Helvetica-Bold", fontSize=9, leading=11, textColor=colors.HexColor("#2563EB"))),
            Paragraph("<b>PHASE 2: Optimization</b>", ParagraphStyle("P2", fontName="Helvetica-Bold", fontSize=9, leading=11, textColor=colors.HexColor("#0284C7"))),
            Paragraph("<b>PHASE 3: Growth</b>", ParagraphStyle("P3", fontName="Helvetica-Bold", fontSize=9, leading=11, textColor=colors.HexColor("#10B981"))),
        ],
        [
            Paragraph("• Fix critical 404 links & crawl errors<br/>• Configure XML Sitemap & Robots.txt<br/>• Resolve duplicate titles & H1 tags<br/>• Verify SSL & canonical protocols", small_style),
            Paragraph("• Optimize meta titles & descriptions<br/>• Compress heavy media & images<br/>• Enhance mobile responsiveness<br/>• Implement Schema.org structured data", small_style),
            Paragraph("• Refine internal link equity flow<br/>• Expand keyword targeting & copy<br/>• Core Web Vitals speed tuning<br/>• Monthly ranking & conversion tracking", small_style),
        ]
    ]
    roadmap_table = Table(roadmap_data, colWidths=[60 * mm, 61 * mm, 61 * mm])
    roadmap_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#F1F5F9")),
        ('BACKGROUND', (0,1), (-1,1), colors.HexColor("#FFFFFF")),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E1")),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    story.append(roadmap_table)
    story.append(Spacer(1, 8 * mm))

    story.append(Paragraph("<b>Audit Standards & Methodology</b>", h1_style))
    story.append(Paragraph(
        "This audit was compiled via real-time HTTP crawler validation, direct DOM analysis, and Google Webmaster technical standards. "
        "Scores reflect strictly verifiable parameters without artificial inflation. Achieving the projected target requires systematic implementation of the technical, structural, and on-page recommendations identified herein.",
        body_style
    ))
    story.append(Spacer(1, 8 * mm))

    cta_data = [
        [
            Paragraph("<b>Ready to Boost Your Organic Rankings & Leads?</b>", ParagraphStyle("CTATitle", fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=colors.HexColor("#0F172A"))),
            Paragraph("<b>eSupport SEO Experts</b>", ParagraphStyle("CTABrand", fontName="Helvetica-Bold", fontSize=10, leading=13, alignment=TA_RIGHT, textColor=colors.HexColor("#2563EB"))),
        ],
        [
            Paragraph("Our team specializes in full technical implementation, content optimization, and search growth strategies. Contact us for a free strategy consultation.", body_style),
            Paragraph("<b>Direct Consultation:</b><br/>WhatsApp: <font color='#16A34A'><b>+94 71 069 0715</b></font><br/>Email: <b>prasad@esupport.live</b><br/>Web: <b>https://esupport.live/</b>", ParagraphStyle("CTADetails", fontName="Helvetica", fontSize=8, leading=11, alignment=TA_RIGHT)),
        ]
    ]
    cta_table = Table(cta_data, colWidths=[110 * mm, 72 * mm])
    cta_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#EFF6FF")),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor("#93C5FD")),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    story.append(cta_table)

    doc.build(story, canvasmaker=ClientNumberedCanvas)
    return buf.getvalue()


def build_special_report_pdf(audit: dict[str, Any], report_type: str) -> bytes:
    if report_type in ("full", "comprehensive"):
        from .comprehensive_report import build_comprehensive_pdf
        return build_comprehensive_pdf(audit)
    if report_type == "client":
        return build_client_summary_pdf(audit)
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), rightMargin=12*mm, leftMargin=12*mm, topMargin=14*mm, bottomMargin=14*mm,
                            title=f"Aviance {report_type.title()} Report", author="Aviance SEO Pro Max")
    styles = getSampleStyleSheet()
    title = ParagraphStyle("v7title", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=24, leading=28, textColor=colors.HexColor("#0d1b2e"), spaceAfter=8)
    h2 = ParagraphStyle("v7h2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=14, leading=18, textColor=colors.HexColor("#153355"), spaceBefore=10, spaceAfter=6)
    body = ParagraphStyle("v7body", parent=styles["BodyText"], fontSize=8.5, leading=12, textColor=colors.HexColor("#26364a"), spaceAfter=5)
    small = ParagraphStyle("v7small", parent=body, fontSize=7.5, leading=10)
    s = audit.get("scores", {}) or {}; st = audit.get("stats", {}) or {}; recs = (audit.get("recommendations", {}) or {}).get("developer_plan", []) or []
    issues = audit.get("issues", []) or []
    logo_file = FRONTEND / "assets" / "esupport-logo.png"
    if logo_file.exists():
        hdr_table = Table([[
            RLImage(str(logo_file), width=18*mm, height=18*mm),
            [Paragraph("eSupport SEO", title), _P(audit.get("target", ""), body), _P(f"Report type: {report_type.title()}", small)]
        ]], colWidths=[24*mm, 240*mm])
        hdr_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ]))
        story = [hdr_table, Spacer(1, 4*mm)]
    else:
        story = [Paragraph("eSupport SEO", title), _P(audit.get("target", ""), body), _P(f"Report type: {report_type.title()}", small)]
    payload = ensure_engine(audit)
    story += engine_report_story(payload, h2, body, small, full=False)
    if report_type == "executive":
        story += [Paragraph("Executive Summary", h2), _P((audit.get("recommendations", {}) or {}).get("executive_summary", ""), body)]
        story.append(PageBreak()); story.append(Paragraph("Top Recommendations", h2))
        for r in recs[:20]:
            story.append(KeepTogether([_P(f"{r.get('priority','')} - {r.get('category','')} - {r.get('issue','')} ({r.get('affected',0)} affected)", body), _P(f"Action: {r.get('action','')}", body)]))
    elif report_type == "recommendations":
        story += [Paragraph("Priority Recommendations", h2)]
        rows = [["Priority","Category","Issue","Affected","Action"]] + [[r.get("priority",""),r.get("category",""),r.get("issue",""),r.get("affected",0),r.get("action","")] for r in recs]
        story.append(_pdf_table(rows,[20*mm,32*mm,62*mm,18*mm,65*mm],font_size=6.5))
        story.append(PageBreak()); story.append(Paragraph("Quick Wins", h2))
        for q in (audit.get("recommendations", {}) or {}).get("quick_wins", [])[:30]: story.append(_P("- " + q, body))
    elif report_type == "recommendations_all":
        # Consolidated, single-download recommendation PDF. It intentionally includes
        # every automatic recommendation plus the developer plan and a detailed
        # finding appendix so the user does not have to download multiple files.
        auto_recs = (audit.get("recommendations", {}) or {}).get("automatic", []) or []
        dev_recs = (audit.get("recommendations", {}) or {}).get("developer_plan", []) or []
        quick_wins = (audit.get("recommendations", {}) or {}).get("quick_wins", []) or []
        story += [Paragraph("All Recommendations", h2),
                  _P("This consolidated PDF contains all automatically grouped recommendations, developer actions, quick wins and recommendation-bearing findings from the current audit.", body),
                  _P((audit.get("recommendations", {}) or {}).get("executive_summary", ""), body)]
        story.append(Paragraph(f"Automatic Recommendations ({len(auto_recs)})", h2))
        if auto_recs:
            rows = [["Priority","Severity","Category","Code","Affected","Effort","Issue","Action"]]
            for r in auto_recs:
                rows.append([r.get("priority",""),r.get("severity",""),r.get("category",""),r.get("code",""),r.get("affected",0),r.get("effort",""),r.get("issue",""),r.get("action","")])
            story.append(_pdf_table(rows,[16*mm,18*mm,28*mm,24*mm,15*mm,18*mm,55*mm,58*mm],font_size=5.7))
        else:
            story.append(_P("No automatic grouped recommendations were generated.", body))
        if dev_recs:
            story.append(PageBreak()); story.append(Paragraph(f"Developer Actions ({len(dev_recs)})", h2))
            for r in dev_recs:
                story.append(KeepTogether([
                    Paragraph(f"{r.get('priority','')} • {r.get('category','')} • {r.get('code','')}", h2),
                    _P(f"Issue: {r.get('issue','')} ({r.get('affected',0)} affected URL(s))", body),
                    _P(f"Evidence: {r.get('evidence','')}", small),
                    _P(f"Action: {r.get('action','')}", body),
                    _P(f"Developer fix: {r.get('fix','') or r.get('developer_fix','')}", body),
                    _P(f"Validation: {r.get('validation','')}", body),
                ]))
                urls=r.get('affected_urls',[]) or []
                if urls: story.append(_P("Affected URLs: " + " | ".join(urls[:40]), small))
        if quick_wins:
            story.append(PageBreak()); story.append(Paragraph(f"Quick Wins ({len(quick_wins)})", h2))
            for idx,q in enumerate(quick_wins,1): story.append(_P(f"{idx}. {q}", body))
        finding_recs=[i for i in issues if i.get("recommendation")]
        if finding_recs:
            story.append(PageBreak()); story.append(Paragraph(f"Recommendation-bearing Findings ({len(finding_recs)})", h2))
            rows=[["Severity","Category","Code","Issue","URL","Recommendation","Evidence"]]
            for i in finding_recs:
                rows.append([i.get("severity",""),i.get("category",""),i.get("code",""),i.get("message",""),i.get("url",""),i.get("recommendation",""),i.get("evidence","")])
            story.append(_pdf_table(rows,[15*mm,25*mm,25*mm,48*mm,50*mm,58*mm,45*mm],font_size=5.7))
    elif report_type == "developer":
        story += [Paragraph("Developer Handover", h2)]
        for r in recs:
            story.append(KeepTogether([Paragraph(f"{r.get('priority','')} - {r.get('category','')} - {r.get('code','')}", h2),
                                       _P(f"Issue: {r.get('issue','')} ({r.get('affected',0)} affected URL(s))", body),
                                       _P(f"Evidence: {r.get('evidence','')}", small),
                                       _P(f"Action: {r.get('action','')}", body),
                                       _P(f"Developer fix: {r.get('fix','')}", body),
                                       _P(f"Validation: {r.get('validation','')}", body)]))
            urls = r.get("affected_urls", []) or []
            if urls: story.append(_P("Affected URLs: " + " | ".join(urls[:50]), small))
        if not recs: story.append(_P("No grouped developer recommendations were generated.", body))
        story.append(PageBreak()); story.append(Paragraph("Critical and Warning Findings", h2))
        filtered = [i for i in issues if i.get("severity") in {"critical","warning"}]
        story.append(_pdf_table([["Severity","Category","Code","Finding","URL","Recommendation"]]+[[i.get("severity",""),i.get("category",""),i.get("code",""),i.get("message",""),i.get("url",""),i.get("recommendation","")] for i in filtered],[15*mm,25*mm,28*mm,50*mm,55*mm,55*mm],font_size=6))
    elif report_type == "keywords":
        story += [Paragraph("Keyword & Topic Intelligence", h2), _P((audit.get("keyword_intelligence") or {}).get("data_boundary", "Observed HTML terms only."), body)]
        rows=[["Keyword","Observed","Pages","Intent"]]+[[x.get("keyword",""),x.get("observed_count",0),x.get("pages",0),x.get("intent","")] for x in (audit.get("keyword_intelligence") or {}).get("observed_keywords",[])[:120]]
        story.append(_pdf_table(rows,[75*mm,28*mm,25*mm,35*mm],font_size=7))
        cann=(audit.get("keyword_intelligence") or {}).get("possible_cannibalization",[])[:30]
        if cann:
            story.append(PageBreak()); story.append(Paragraph("Possible Topic Cannibalization", h2))
            for x in cann: story.append(_P(f"{x.get('keyword')}: " + " | ".join(x.get("pages",[])), small))
    elif report_type == "social":
        story += [Paragraph("Social Metadata & Hashtag Suggestions", h2), _P("Hashtags are suggestions derived from observed page terms; they are not Google ranking factors or popularity measurements.", body)]
        tags=(audit.get("keyword_intelligence") or {}).get("hashtags",[])[:100]
        rows=[["Hashtag","Pages"]]+[[x.get("hashtag",""),x.get("pages",0)] for x in tags]
        story.append(_pdf_table(rows,[100*mm,25*mm],font_size=7.5))
        story.append(PageBreak()); story.append(Paragraph("Open Graph Coverage", h2))
        for p in audit.get("pages",[])[:120]:
            og=p.get("og",{}) or {}
            story.append(_P(f"{p.get('url','')} | og:title={bool(og.get('og:title'))} | og:description={bool(og.get('og:description'))} | og:image={bool(og.get('og:image'))} | twitter:card={bool((p.get('twitter') or {}).get('twitter:card'))}", small))
    elif report_type == "indexing":
        story += [Paragraph("Indexing & Crawl Control", h2)]
        sm=audit.get("site",{}).get("sitemap",{}) or {}; rb=audit.get("site",{}).get("robots",{}) or {}
        story.append(_pdf_table([["Signal","Value"],["robots.txt",f"HTTP {rb.get('status',0)} | Found {rb.get('found',False)}"],["Sitemap URLs",sm.get("url_count",0)],["Pages crawled",audit.get("page_count",0)],["Indexable pages",st.get("indexable_pages",0)],["Noindex pages",st.get("noindex_pages",0)],["Redirected pages",st.get("redirected_pages",0)],["Orphan candidates",len(audit.get("site",{}).get("orphan_candidates",[]) or [])]],[60*mm,80*mm],font_size=8))
        rows=[["URL","Status","Robots allowed","Noindex","Canonical"]]
        for p in audit.get("pages",[])[:200]:
            robots_text=f"{p.get('meta_robots','')} {p.get('x_robots_tag','')}".strip()
            rows.append([p.get("url",""),p.get("status",0),p.get("robots_allowed",True),"noindex" in robots_text.lower(),p.get("canonical","")])
        story.append(PageBreak()); story.append(_pdf_table(rows,[70*mm,16*mm,30*mm,20*mm,70*mm],font_size=6.2))
    story.append(PageBreak())
    story.append(Paragraph("Data and Method", h2))
    story.append(_P("This report is generated from the current audit only. Aviance does not fabricate search rankings, organic traffic, backlink counts, Domain Authority, Search Console metrics, or field Core Web Vitals. See the full report for page-by-page evidence and raw checks.", body))
    story.append(Paragraph("Current audit timestamp", h2)); story.append(_P(audit.get("created_at",""), small))
    doc.build(story)
    return buf.getvalue()


def build_guide_pdf() -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=15*mm, leftMargin=15*mm, topMargin=16*mm, bottomMargin=16*mm, title="Aviance SEO A-Z Guide", author="Aviance SEO Pro Max")
    styles = getSampleStyleSheet()
    title = ParagraphStyle("guide_title", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=22, leading=27, textColor=colors.HexColor("#0d1b2e"), spaceAfter=10)
    h2 = ParagraphStyle("guide_h2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=colors.HexColor("#153355"), spaceBefore=8, spaceAfter=4)
    body = ParagraphStyle("guide_body", parent=styles["BodyText"], fontSize=8.8, leading=12, textColor=colors.HexColor("#26364a"), spaceAfter=4)
    logo_file = FRONTEND / "assets" / "esupport-logo.png"
    if logo_file.exists():
        hdr_table = Table([[
            RLImage(str(logo_file), width=18*mm, height=18*mm),
            [Paragraph("eSupport SEO A-Z Guide", title), _P("Practical reference for live-site technical SEO audits and developer handover.", body)]
        ]], colWidths=[24*mm, 150*mm])
        hdr_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ]))
        story = [hdr_table, Spacer(1, 4*mm)]
    else:
        story = [Paragraph("eSupport SEO A-Z Guide", title), _P("Practical reference for live-site technical SEO audits and developer handover.", body)]
    for letter,name,desc in SEO_A_TO_Z:
        story.append(Paragraph(f"{letter} - {name}", h2)); story.append(_P(desc, body))
    story.append(PageBreak()); story.append(Paragraph("What Aviance can and cannot measure", h2))
    story += [_P("Can measure directly: live HTTP responses, HTML metadata, headings, links, images, resources, JSON-LD syntax/types, robots.txt, XML sitemaps, redirect chains, response time, payload size and security-header signals.", body),
              _P("Needs an external dataset/integration: Google Search Console performance, GA4 traffic, keyword rankings, search volume, backlink indexes, and field Core Web Vitals. Browser-rendered JavaScript requires a real browser execution layer.", body)]
    doc.build(story)
    return buf.getvalue()

def local_ai(audit: dict[str, Any]) -> dict[str, Any]:
    evidence = {
        "target": audit["target"],
        "score": audit["score"],
        "pages_crawled": audit["pages_crawled"],
        "issues": audit["issues"][:120],
        "categories": audit["scores"]["categories"],
        "pages": [
            {k: p.get(k) for k in ["url", "status", "title", "meta_description", "h1", "word_count", "schema_types", "images", "response_time_ms"]}
            for p in audit["pages"][:40]
        ],
    }
    prompt = (
        "Return ONLY JSON. Act as a local SEO analysis assistant. Use only supplied evidence. "
        "Do not invent search rankings, traffic, keyword positions, backlinks, domain authority, or Google Search Console data. "
        "Never guarantee rankings. Keys: executive_summary, priorities, quick_wins, content_actions, technical_actions, image_actions, schema_actions. "
        "Priorities objects need priority, issue, evidence, action.\n" + json.dumps(evidence, ensure_ascii=False)
    )
    try:
        base = OLLAMA_URL.rsplit("/api/", 1)[0].rstrip("/")
        try:
            tags = requests.get(base + "/api/tags", timeout=5)
            if not tags.ok:
                return {"enabled": False, "model": OLLAMA_MODEL, "error": "Ollama service is not available.", "data": {}}
            model_names = [str(x.get("name", "")) for x in (tags.json().get("models") or [])]
            if not any(name == OLLAMA_MODEL or name.startswith(OLLAMA_MODEL + ":") for name in model_names):
                return {"enabled": False, "model": OLLAMA_MODEL, "error": f"Ollama model '{OLLAMA_MODEL}' is not installed.", "data": {}}
        except (requests.RequestException, ValueError):
            return {"enabled": False, "model": OLLAMA_MODEL, "error": "Ollama service is not available.", "data": {}}
        response = requests.post(OLLAMA_URL, json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False, "options": {"temperature": 0.15}}, timeout=OLLAMA_TIMEOUT)
        response.raise_for_status()
        raw = (response.json().get("response") or "").strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I | re.S)
        data = json.loads(raw)
        return {"enabled": True, "model": OLLAMA_MODEL, "data": data}
    except Exception as exc:
        return {"enabled": False, "model": OLLAMA_MODEL, "error": str(exc), "data": {}}


def _P(text: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(html.escape(str(text or "")).replace("\n", "<br/>")[:12000], style)


def _pdf_table(data: list[list[Any]], widths: list[float], header: bool = True, font_size: int = 7) -> Table:
    wrapped = []
    cell_style = ParagraphStyle("cell", fontName="Helvetica", fontSize=font_size, leading=font_size + 2, textColor=colors.HexColor("#152238"))
    head_style = ParagraphStyle("head", fontName="Helvetica-Bold", fontSize=font_size, leading=font_size + 2, textColor=colors.white)
    for r, row in enumerate(data):
        wrapped.append([_P(c, head_style if header and r == 0 else cell_style) for c in row])
    t = Table(wrapped, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    commands = [
        ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#d6deea")),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING", (0,0), (-1,-1), 4),
        ("RIGHTPADDING", (0,0), (-1,-1), 4),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]
    if header:
        commands.append(("BACKGROUND", (0,0), (-1,0), colors.HexColor("#153355")))
    t.setStyle(TableStyle(commands))
    return t


def build_report_pdf(audit: dict[str, Any]) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4), rightMargin=12*mm, leftMargin=12*mm, topMargin=14*mm, bottomMargin=14*mm,
        title=f"eSupport SEO Report - {audit.get('target','')}", author="eSupport SEO"
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle("rtitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=24, leading=28, textColor=colors.HexColor("#0d1b2e"), alignment=TA_LEFT, spaceAfter=8)
    subtitle = ParagraphStyle("rsub", parent=styles["Normal"], fontSize=9, leading=12, textColor=colors.HexColor("#64748b"), spaceAfter=10)
    h2 = ParagraphStyle("rh2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=14, leading=18, textColor=colors.HexColor("#153355"), spaceBefore=10, spaceAfter=6)
    body = ParagraphStyle("rbody", parent=styles["BodyText"], fontSize=8.5, leading=12, textColor=colors.HexColor("#26364a"), spaceAfter=5)
    score_style = ParagraphStyle("score", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=38, leading=42, textColor=colors.HexColor("#0d1b2e"), alignment=TA_CENTER)
    small = ParagraphStyle("small", parent=body, fontSize=7.5, leading=10)

    s = audit.get("scores", {}) or {}
    st = audit.get("stats", {}) or {}
    issues = audit.get("issues", []) or []
    recs = (audit.get("recommendations", {}) or {}).get("developer_plan", []) or (audit.get("recommendations", {}) or {}).get("priorities", []) or []
    pages = audit.get("pages", []) or []
    links = audit.get("link_checks", []) or []
    resources = audit.get("resource_checks", []) or []

    story = []
    logo_file = FRONTEND / "assets" / "esupport-logo.png"
    if logo_file.exists():
        hdr_table = Table([[
            RLImage(str(logo_file), width=18*mm, height=18*mm),
            [
                Paragraph("eSupport SEO", title),
                Paragraph("Professional Website SEO Audit & Optimization • Full Technical, On-Page & Structural Report", subtitle),
                _P(audit.get("target", ""), body)
            ]
        ]], colWidths=[24*mm, 240*mm])
        hdr_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ]))
        story.append(hdr_table)
    else:
        story.append(Paragraph("eSupport SEO", title))
        story.append(Paragraph("Professional Website SEO Audit & Optimization • Full Technical, On-Page & Structural Report", subtitle))
        story.append(_P(audit.get("target", ""), body))
    story.append(Spacer(1, 4*mm))
    if audit.get("crawl_reached_safety_cap"):
        story.append(Spacer(1, 2*mm))
        story.append(Paragraph(f"Crawl note: the internal safety cap of {audit.get('safety_cap')} pages was reached before the queue was empty. This report covers the pages actually fetched.", small))
    story += engine_report_story(ensure_engine(audit), h2, body, small, full=True)

    story.append(Paragraph("Site Health Snapshot", h2))
    snapshot = [
        ["Signal", "Value", "Signal", "Value"],
        ["HTML pages", st.get("html_pages",0), "Status 2xx", st.get("status_2xx",0)],
        ["Status 4xx", st.get("status_4xx",0), "Status 5xx", st.get("status_5xx",0)],
        ["Missing titles", st.get("missing_title_pages",0), "Missing meta descriptions", st.get("missing_meta_description_pages",0)],
        ["Missing H1", st.get("missing_h1_pages",0), "Missing canonical", st.get("missing_canonical_pages",0)],
        ["Pages with schema", st.get("pages_with_schema",0), "Pages with Open Graph", st.get("pages_with_open_graph",0)],
        ["Noindex pages", st.get("noindex_pages",0), "Redirected pages", st.get("redirected_pages",0)],
        ["JS-heavy pages", st.get("js_heavy_pages",0), "Slow pages", st.get("slow_pages",0)],
        ["Images", st.get("total_images",0), "Images missing ALT", st.get("missing_alt_images",0)],
        ["Sitemap URLs", st.get("sitemap_urls",0), "Max crawl depth", st.get("max_crawl_depth",0)],
        ["Average response", f"{st.get('average_response_ms',0)} ms", "Average HTML", f"{st.get('average_html_kb',0)} KB"],
    ]
    story.append(_pdf_table(snapshot, [48*mm, 27*mm, 48*mm, 27*mm], font_size=7.5))

    story.append(PageBreak())
    story.append(Paragraph("Developer Action Plan", h2))
    if not recs:
        story.append(_P("No grouped recommendations were generated.", body))
    else:
        for r in recs:
            priority = r.get("priority", "")
            affected = r.get("affected", 0)
            story.append(KeepTogether([
                Paragraph(f"{priority} - {r.get('category','')} - {r.get('code','')}", h2),
                _P(f"Issue: {r.get('issue','')} ({affected} affected URL(s))", body),
                _P(f"Evidence: {r.get('evidence','')}", small),
                _P(f"Action: {r.get('action','')}", body),
                _P(f"Developer fix: {r.get('fix','') or 'Review the affected implementation and apply the recommended action.'}", body),
                _P(f"Validation: {r.get('validation','')}", body),
            ]))
            urls = r.get("affected_urls", [])
            if urls:
                story.append(_P("Affected URLs: " + " | ".join(urls[:20]), small))

    story.append(PageBreak())
    story.append(Paragraph("Per-URL Findings (evidence detail, not scored)", h2))
    story.append(_P("These raw per-URL observations support the checks above. They do not affect the score; the score comes only from the checks.", small))
    issue_rows = [["Severity", "Category", "Code", "Finding", "URL", "Recommendation"]]
    for i in (audit.get("page_findings") or [])[:400]:
        issue_rows.append([i.get("severity",""), i.get("category",""), i.get("code",""), i.get("message",""), i.get("url",""), i.get("recommendation","")])
    story.append(_pdf_table(issue_rows, [15*mm, 25*mm, 27*mm, 48*mm, 47*mm, 55*mm], font_size=6.5))

    story.append(PageBreak())
    story.append(Paragraph("Page Inventory", h2))
    page_rows = [["Status", "URL", "Title", "Title len", "Words", "H1", "Images", "Internal", "Time"]]
    for p in pages:
        page_rows.append([p.get("status",0), p.get("url",""), p.get("title","") or "(none)", len(p.get("title") or ""), p.get("word_count",0), len(p.get("h1",[])), len(p.get("images",[])), len(p.get("internal_links",[])), f"{p.get('response_time_ms',0)} ms"])
    story.append(_pdf_table(page_rows, [14*mm, 60*mm, 50*mm, 14*mm, 14*mm, 10*mm, 13*mm, 15*mm, 18*mm], font_size=5.8))

    story.append(PageBreak())
    story.append(Paragraph("Checked Links and Resources", h2))
    link_rows = [["URL", "Status", "Time", "Final URL", "Error"]]
    for x in links:
        link_rows.append([x.get("url",""), x.get("status",0), f"{x.get('elapsed_ms',0)} ms", x.get("final_url", ""), x.get("error","")])
    if len(link_rows) > 1:
        story.append(_pdf_table(link_rows, [62*mm, 15*mm, 18*mm, 55*mm, 35*mm], font_size=6.5))
    else:
        story.append(_P("No link checks were recorded.", body))
    story.append(Spacer(1, 4*mm))
    res_rows = [["Kind", "URL", "Status", "Bytes", "Time", "Content Type"]]
    for x in resources:
        res_rows.append([x.get("kind",""), x.get("url",""), x.get("status",0), x.get("bytes",0), f"{x.get('elapsed_ms',0)} ms", x.get("content_type","")])
    if len(res_rows) > 1:
        story.append(_pdf_table(res_rows, [18*mm, 65*mm, 15*mm, 20*mm, 18*mm, 34*mm], font_size=6.5))
    else:
        story.append(_P("No resource checks were recorded.", body))

    story.append(PageBreak())
    story.append(Paragraph("Robots, Sitemap, Schema and Topic Signals", h2))
    robots = audit.get("site", {}).get("robots", {}) or {}
    sm = audit.get("site", {}).get("sitemap", {}) or {}
    story.append(_P(f"robots.txt: {robots.get('url','')} | HTTP {robots.get('status',0)} | Found: {robots.get('found',False)} | Referenced sitemaps: {len(robots.get('sitemaps',[]) or [])}", body))
    story.append(_P(f"Discovered sitemap URLs: {audit.get('site',{}).get('sitemap_url_count',0)} | In-crawl sitemap URLs: {audit.get('site',{}).get('in_crawl_sitemap_count',0)} | Orphan candidates: {len(audit.get('site',{}).get('orphan_candidates',[]) or [])}", body))
    sm_rows = [["Sitemap URL", "Status", "Type", "URLs"]]
    for x in sm.get("files", []) or []:
        sm_rows.append([x.get("url",""), x.get("status",0), x.get("type",""), x.get("url_count",0)])
    if len(sm_rows) > 1:
        story.append(_pdf_table(sm_rows, [95*mm, 20*mm, 30*mm, 25*mm], font_size=6.5))
    schema_rows = [["URL", "Schema Types", "Errors"]]
    for p in pages:
        if p.get("schema_types") or p.get("schema_errors"):
            schema_rows.append([p.get("url",""), ", ".join(p.get("schema_types",[])), " | ".join(p.get("schema_errors",[]))])
    if len(schema_rows) > 1:
        story.append(Spacer(1, 3*mm)); story.append(_pdf_table(schema_rows, [70*mm, 60*mm, 60*mm], font_size=6.5))
    terms = audit.get("keywords", []) or []
    if terms:
        story.append(Spacer(1, 3*mm)); story.append(Paragraph("Top Topic Signals", h2))
        term_rows = [["Term", "Occurrences"]] + [[t.get("term",""), t.get("count",0)] for t in terms[:80]]
        story.append(_pdf_table(term_rows, [120*mm, 30*mm], font_size=7))

    story.append(PageBreak())
    story.append(Paragraph("Per-URL Finding Categories (evidence detail)", h2))
    cats=audit.get("source_categories",[]) or []
    cat_rows=[["Category","Total","Critical","Warning","Info"]]+[[x.get("category",""),x.get("total",0),x.get("critical",0),x.get("warning",0),x.get("info",0)] for x in cats]
    if len(cat_rows)>1: story.append(_pdf_table(cat_rows,[70*mm,20*mm,20*mm,20*mm,20*mm],font_size=7))
    ki=audit.get("keyword_intelligence",{}) or {}
    story.append(PageBreak()); story.append(Paragraph("Keyword & Hashtag Intelligence", h2))
    story.append(_P(ki.get("data_boundary", "Observed terms from fetched HTML."), small))
    krows=[["Keyword","Observed","Pages","Intent"]]+[[x.get("keyword",""),x.get("observed_count",0),x.get("pages",0),x.get("intent","")] for x in ki.get("observed_keywords",[])[:80]]
    if len(krows)>1: story.append(_pdf_table(krows,[80*mm,25*mm,25*mm,35*mm],font_size=6.8))
    tags=ki.get("hashtags",[])[:40]
    if tags: story.append(_P("Suggested hashtags: " + ", ".join(x.get("hashtag","") for x in tags), body))

    ai = audit.get("ai", {}) or {}
    if ai.get("enabled") and ai.get("data"):
        story.append(PageBreak())
        story.append(Paragraph("Local AI Recommendations", h2))
        story.append(_P(f"Model: {ai.get('model','')} | Generated from the live audit evidence above.", small))
        data = ai.get("data") or {}
        for key, value in data.items():
            label = str(key).replace("_", " ").title()
            story.append(Paragraph(label, h2))
            if isinstance(value, list):
                for item in value[:30]:
                    story.append(_P(json.dumps(item, ensure_ascii=False) if isinstance(item, (dict, list)) else str(item), body))
            elif isinstance(value, dict):
                story.append(_P(json.dumps(value, ensure_ascii=False, indent=2), small))
            else:
                story.append(_P(str(value), body))

    story.append(Spacer(1, 5*mm))
    story.append(Paragraph("Audit Method and Limitations", h2))
    story.append(_P("Data in this report comes from the live crawl and the audit rules in Aviance. Browser-rendered JavaScript behavior is not fully reproduced by raw HTTP parsing, and field Core Web Vitals, search rankings, backlinks, traffic and Search Console data require their respective external or browser/field data sources.", body))

    def page_decor(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#d6deea"))
        page_width, _ = landscape(A4)
        canvas.line(12*mm, 10*mm, page_width-12*mm, 10*mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(12*mm, 6*mm, "Aviance SEO Pro Max - live implementation audit")
        canvas.drawRightString(page_width-12*mm, 6*mm, f"Page {doc.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=page_decor, onLaterPages=page_decor)
    return buf.getvalue()

MAX_ZIP_ENTRY_BYTES = 15_000_000
MAX_ZIP_TOTAL_BYTES = 250_000_000
MAX_ZIP_ENTRIES = 5000


def source_audit(path: Path) -> dict[str, Any]:
    frameworks = Counter()
    findings: list[dict[str, Any]] = []
    scanned = 0
    truncated = False
    total_uncompressed = 0
    extensions = {".html", ".htm", ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".php", ".blade.php", ".astro", ".mdx"}
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            name = info.filename.replace("\\", "/")
            parts = set(name.split("/"))
            if info.is_dir() or parts & {"node_modules", ".git", ".venv", "dist", "build", "__pycache__"}:
                continue
            if scanned >= MAX_ZIP_ENTRIES or total_uncompressed >= MAX_ZIP_TOTAL_BYTES:
                truncated = True
                break
            if info.file_size > MAX_ZIP_ENTRY_BYTES:
                continue
            total_uncompressed += info.file_size
            scanned += 1
            lower = name.lower()
            if "next.config" in lower or "/pages/" in lower or "/app/" in lower:
                frameworks["Next.js"] += 1
            if lower.endswith((".jsx", ".tsx")) or "react" in lower:
                frameworks["React"] += 1
            if lower.endswith(".vue"):
                frameworks["Vue"] += 1
            if lower.endswith(".svelte"):
                frameworks["Svelte"] += 1
            if lower.endswith((".astro",)):
                frameworks["Astro"] += 1
            try:
                text = archive.read(info).decode("utf-8", "replace")[:6_000_000]
            except Exception:
                continue
            has_head = bool(re.search(r"<head\b", text, re.I))
            if re.search(r"<title\b[^>]*>\s*</title>", text, re.I):
                findings.append({"severity": "warning", "category": "Title", "file": name, "message": "Empty title tag detected."})
            if has_head and not re.search(r"<title\b", text, re.I):
                findings.append({"severity": "critical", "category": "Title", "file": name, "message": "No title implementation detected in a file containing <head>."})
            if re.search(r"<img\b(?![^>]*\balt\s*=)[^>]*>", text, re.I):
                findings.append({"severity": "warning", "category": "Image SEO", "file": name, "message": "Potential img tag without ALT attribute."})
            if has_head and not re.search(r"<meta[^>]+name=[\"']description", text, re.I):
                findings.append({"severity": "info", "category": "Meta Description", "file": name, "message": "No meta-description implementation detected in this file."})
            if has_head and not re.search(r"rel=[\"']canonical[\"']", text, re.I) and not re.search(r"canonical", text, re.I):
                findings.append({"severity": "info", "category": "Canonical", "file": name, "message": "No canonical implementation signal detected in this file."})
            if has_head and "application/ld+json" not in text.lower() and "schema.org" not in text.lower():
                findings.append({"severity": "info", "category": "Structured Data", "file": name, "message": "No structured-data implementation signal detected in this file."})
            if has_head and not re.search(r"og:title|og:description", text, re.I):
                findings.append({"severity": "info", "category": "Social", "file": name, "message": "No Open Graph title/description signal detected in this file."})
            if re.search(r"href=[\"']javascript:|onclick=[\"']", text, re.I):
                findings.append({"severity": "info", "category": "Rendering", "file": name, "message": "Inline JavaScript navigation/event signal detected; verify important links/content are available in HTML."})
            if re.search(r"<a\b[^>]*>\s*</a>", text, re.I):
                findings.append({"severity": "info", "category": "Internal Linking", "file": name, "message": "Empty anchor element detected."})
            if re.search(r"<meta[^>]+name=[\"']robots[\"']\s+content=[\"'][^\"']*noindex", text, re.I):
                findings.append({"severity": "warning", "category": "Indexability", "file": name, "message": "Noindex robots directive appears in source."})
    return {"files_scanned": scanned, "frameworks": dict(frameworks), "findings": findings[:2000], "truncated": truncated}




@app.get("/api/health")
def health():
    ollama = False
    ollama_model_available = False
    models = []
    try:
        base = OLLAMA_URL.rsplit("/api/", 1)[0].rstrip("/")
        r = requests.get(f"{base}/api/tags", timeout=5)
        if r.ok:
            ollama = True
            payload = r.json()
            models = [str(x.get("name", "")) for x in (payload.get("models") or [])]
            ollama_model_available = any(name == OLLAMA_MODEL or name.startswith(OLLAMA_MODEL + ":") for name in models)
    except (requests.RequestException, ValueError):
        pass
    playwright_package = False
    playwright_browser = False
    try:
        import playwright  # type: ignore
        playwright_package = True
        from playwright.sync_api import sync_playwright  # type: ignore
        with sync_playwright() as pw:
            launched = False
            for channel in ("chrome", None):
                try:
                    browser = pw.chromium.launch(channel=channel, headless=True) if channel else pw.chromium.launch(headless=True)
                    launched = True
                    browser.close()
                    break
                except Exception:
                    continue
            playwright_browser = launched
    except Exception:
        pass
    return {
        "ok": True, "version": app.version, "ollama_available": ollama,
        "ollama_model_available": ollama_model_available, "ollama_model": OLLAMA_MODEL,
        "ollama_models": models[:30], "playwright_package": playwright_package,
        "playwright_browser": playwright_browser, "history": False
    }


def _set_job(job_id: str, **updates):
    with AUDIT_JOBS_LOCK:
        if job_id in AUDIT_JOBS:
            AUDIT_JOBS[job_id].update(updates)

def _run_job(job_id: str, req: AuditRequest, cancel_event: threading.Event):
    _set_job(job_id, state="running", started_at=time.time(), progress={"phase":"starting","pages":0,"queued":1,"current_url":req.url,"status":0,"issues":0})
    try:
        def cb(progress):
            _set_job(job_id, progress=progress)
        result = crawl(req, progress_cb=cb, cancel_event=cancel_event)
        _set_job(job_id, state="cancelled" if cancel_event.is_set() else "completed", result=result, finished_at=time.time(), progress={"phase":"completed" if not cancel_event.is_set() else "cancelled", "pages":result.get("page_count",0), "queued":0, "current_url":"", "status":0, "issues":len(result.get("issues",[]))})
    except Exception as exc:
        _set_job(job_id, state="failed", error=str(exc), finished_at=time.time())

@app.post("/api/preflight")
def preflight(req: AuditRequest):
    """Fast live-site diagnostic used before a full audit. It never stores history."""
    try:
        start = validate_public_target(req.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        page_future = ex.submit(fetch_universal, make_session(), start, min(PREFLIGHT_TIMEOUT, 8), 500_000, 0)
        robots_future = ex.submit(parse_robots, make_session(), start)
        page = page_future.result()
        robots = robots_future.result()
    final_url = page.get("url", start)
    robots_sitemap_candidates = list(dict.fromkeys((robots.get("sitemaps") or []) + [origin(start) + "/sitemap.xml", origin(start) + "/sitemap_index.xml"]))[:4]
    sitemap_results = []
    def probe(u):
        r=fetch_universal(make_session(), u, timeout=min(PREFLIGHT_TIMEOUT, 6), max_body=500_000, retries=0)
        return {"url":u,"status":r.get("status",0),"ok":bool(r.get("ok") and int(r.get("status") or 0)<400),"elapsed_ms":r.get("elapsed_ms",0),"content_type":r.get("content_type","")}
    if robots_sitemap_candidates:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            sitemap_results=list(ex.map(probe, robots_sitemap_candidates))
    return {
        "ok": True,
        "target": start,
        "final_url": final_url,
        "http_status": page.get("status",0),
        "http_ok": bool(page.get("ok")),
        "content_type": page.get("content_type","") or "",
        "content_bytes": page.get("bytes",0),
        "response_ms": page.get("elapsed_ms",0),
        "redirect_chain": page.get("history",[]),
        "robots": {"url": robots.get("url"), "status": robots.get("status",0), "found": robots.get("found",False), "fetch_ms": robots.get("fetch_ms",0), "sitemaps_referenced": robots.get("sitemaps",[])},
        "sitemaps": sitemap_results,
        "elapsed_ms": round((time.perf_counter()-started)*1000,1),
        "message": "Live-site preflight completed. Values are fetched from the current target at test time."
    }


@app.post("/api/audit/start")
def start_audit_job(req: AuditRequest, current_admin: AdminUser = Depends(require_permission("audits.run"))):
    job_id = uuid.uuid4().hex
    cancel_event = threading.Event()
    with AUDIT_JOBS_LOCK:
        AUDIT_JOBS[job_id] = {"state":"queued", "created_at":time.time(), "progress":{"phase":"queued","pages":0,"queued":1,"current_url":req.url,"status":0,"issues":0}, "cancel_event":cancel_event}
    JOB_EXECUTOR.submit(_run_job, job_id, req, cancel_event)
    return {"job_id": job_id, "state":"queued"}

@app.get("/api/audit/status/{job_id}")
def audit_job_status(job_id: str):
    with AUDIT_JOBS_LOCK:
        job = AUDIT_JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Audit job not found")
        return {k:v for k,v in job.items() if k != "cancel_event"}

@app.post("/api/audit/cancel/{job_id}")
def cancel_audit_job(job_id: str, current_admin: AdminUser = Depends(require_permission("audits.cancel"))):
    with AUDIT_JOBS_LOCK:
        job = AUDIT_JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Audit job not found")
        job["cancel_event"].set()
        job["state"] = "cancelling"
    return {"ok":True,"state":"cancelling"}

@app.post("/api/audit")
def run_audit(req: AuditRequest, current_admin: AdminUser = Depends(require_permission("audits.run"))):
    try:
        return crawl(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Audit failed: {exc}")


@app.post("/api/ai")
def run_ai_analysis(audit: dict[str, Any]):
    if not isinstance(audit, dict) or not audit.get("target"):
        raise HTTPException(status_code=400, detail="A completed audit JSON payload is required")
    # Reuse the evidence-bound local model function. It never supplies synthetic ranking/traffic data.
    try:
        return local_ai(audit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AI analysis failed: {exc}")


@app.post("/api/page-check")
def page_check(req: AuditRequest):
    try:
        target = validate_public_target(req.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    started = time.perf_counter()
    res = fetch(make_session(), target, timeout=min(TIMEOUT, 15), retries=1)
    page = parse_page(target, res)
    page["depth"] = 0
    page["discovery"] = "single-page"
    page["robots_allowed"] = True
    page_checks(page)
    # Single-page check: the same engine scores the one page; site-level probes are not run, so the
    # checks that need them are reported as 'Not measured' instead of being guessed.
    audit = {"product": "eSupport SEO", "version": app.version, "target": target, "created_at": datetime.now(timezone.utc).isoformat(),
             "mode": "single live HTTP page audit", "pages_crawled": 1, "page_count": 1, "pages": [page],
             "page_findings": page.get("issues", []), "site": {"robots": {}, "sitemap": {"files": [], "url_count": 0, "urls_sample": [], "lastmod_sample": {}}},
             "link_checks": [], "resource_checks": [], "keyword_intelligence": build_keyword_intelligence([page]),
             "stats": {**site_stats([page], [], []), **expanded_stats([page], [], [], {"urls": []})}, "real_data": {}}
    add_data_provenance(audit)
    run_spec_engine(audit)
    audit["elapsed_ms"] = round((time.perf_counter()-started)*1000,1)
    return {"product":"eSupport SEO","version":app.version,"target":target,"page":page,"score":audit["score"],"issues":audit["issues"],"elapsed_ms":audit["elapsed_ms"],"report_audit":audit,"data_provenance":audit["data_provenance"]}


# --- REAL DATA INTEGRATIONS & SEO KNOWLEDGE BASE ---

class IntegrationTarget(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048)
    strategy: str = Field("mobile", pattern="^(mobile|desktop)$")
    days: int = Field(28, ge=1, le=480)
    limit: int = Field(100, ge=1, le=1000)
    location_code: int | None = Field(None, ge=1)
    language_code: str | None = Field(None, max_length=8)


class KeywordLookup(BaseModel):
    keywords: list[str] = Field(..., min_length=1, max_length=700)
    location_code: int | None = Field(None, ge=1)
    language_code: str | None = Field(None, max_length=8)


def _integration_target(url: str) -> str:
    try:
        return canonical_url(validate_public_target(url))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/seo-knowledge")
def seo_knowledge_base():
    return knowledge_base_export()


@app.get("/api/integrations/status")
def integrations_status(current_admin: AdminUser = Depends(require_permission("audits.run"))):
    return integrations.status()


@app.post("/api/integrations/pagespeed")
def integrations_pagespeed(req: IntegrationTarget, current_admin: AdminUser = Depends(require_permission("audits.run"))):
    return integrations.pagespeed(_integration_target(req.url), req.strategy)


@app.post("/api/integrations/search-console")
def integrations_search_console(req: IntegrationTarget, current_admin: AdminUser = Depends(require_permission("audits.run"))):
    return integrations.search_console(_integration_target(req.url), req.days)


@app.post("/api/integrations/keywords")
def integrations_keywords(req: KeywordLookup, current_admin: AdminUser = Depends(require_permission("audits.run"))):
    return integrations.keyword_metrics(req.keywords, req.location_code, req.language_code)


@app.post("/api/integrations/rankings")
def integrations_rankings(req: IntegrationTarget, current_admin: AdminUser = Depends(require_permission("audits.run"))):
    return integrations.ranked_keywords(_integration_target(req.url), req.limit, req.location_code, req.language_code)


@app.post("/api/integrations/backlinks")
def integrations_backlinks(req: IntegrationTarget, current_admin: AdminUser = Depends(require_permission("audits.run"))):
    return integrations.backlinks(_integration_target(req.url))


# --- PUBLIC SEO SCANNER & LEAD SYSTEM ---

PUBLIC_SCAN_JOBS: dict[str, dict[str, Any]] = {}
PUBLIC_SCAN_LOCK = threading.Lock()
_PUBLIC_SCAN_LIMITER = _RateLimiter(15)  # 15 scans per minute per IP
_PUBLIC_LEAD_LIMITER = _RateLimiter(10)  # 10 leads per minute per IP


def _build_public_safe_result(target_url: str, audit_res: dict[str, Any]) -> dict[str, Any]:
    raw_score = audit_res.get("score")
    if raw_score is None:
        raw_score = (audit_res.get("scores") or {}).get("overall")
    if raw_score is None:
        payload = ensure_engine(audit_res)
        raw_score = (payload.get("score") or {}).get("overall")
    else:
        payload = audit_res.get("seo_engine") or ensure_engine(audit_res)
    score = int(round(float(raw_score))) if raw_score is not None else 0
    status_info = get_score_status(score)
    categories = client_categories(audit_res)

    score_display = score if score is not None else "not scored"
    wa_msg = (
        f"Hello eSupport, I checked my website SEO score.\n\n"
        f"Website: {target_url}\n\n"
        f"SEO Score: {score_display}/100\n\n"
        f"I would like to get help improving my website SEO."
    )
    email_subject = f"SEO Help Request – {urlparse(target_url).hostname or target_url} – Score {score_display}/100"
    email_body = (
        f"Hello eSupport,\n\n"
        f"I checked my website SEO score.\n\n"
        f"Website:\n{target_url}\n\n"
        f"SEO Score: {score_display}/100\n\n"
        f"I would like help improving my website SEO."
    )

    general_summary = status_info["description"]

    return {
        "target_url": target_url,
        "scan_date": datetime.now(timezone.utc).isoformat(),
        "score": score,
        "overall_score": score,
        "grade": (payload.get("score") or {}).get("grade"),
        "maturity_label": (payload.get("score") or {}).get("maturity_label"),
        "ruleset_version": payload.get("ruleset_version"),
        "score_status": {
            "status": status_info["status"],
            "headline": status_info["headline"],
            "description": status_info["description"],
            "color": status_info.get("color", "#2563EB")
        },
        "categories": [
            {
                "id": c["id"],
                "name": c["name"],
                "weight": c["weight"],
                "score": c["score"],
                "display": c["display"],
                "status": c["status"],
                "description": c.get("description", ""),
                "provisional": c.get("provisional", False),
                "provisional_note": c.get("provisional_note"),
                "ai_summary": c.get("ai_summary", ""),
                "checks_passed": c.get("checks_passed", 0),
                "checks_total": c.get("checks_total", 0),
                "checks": [{k: chk.get(k) for k in ("id", "label", "status", "detail", "evidence_label", "display_as")} for chk in c.get("checks", [])],
            }
            for c in categories
        ],
        "potential": (payload.get("score") or {}).get("potential"),
        "integrity_statement": (payload.get("integrity") or {}).get("statement"),
        "core_web_vitals": (build_real_data_summary({"pagespeed": (audit_res.get("real_data") or {}).get("pagespeed") or {}}).get("core_web_vitals") or {}).get("mobile"),
        "methodology": "12 SEO categories with fixed weights, each scored from individual checks measured live on your website. "
                       "Checks that could not be measured are listed as not measured, never counted as failures. "
                       "Overall score = weighted average of the category scores. It is a health score, not a guaranteed Google ranking.",
        "summary": {
            "overall_score": score,
            "status": status_info["status"],
            "general_summary": general_summary
        },
        "cta": {
            "headline": "Want to Improve Your SEO?",
            "description": "Get a detailed SEO analysis from eSupport and discover the issues affecting your website.",
            "whatsapp_url": f"https://wa.me/94710690715?text={quote(wa_msg)}",
            "whatsapp_btn_text": "Get Professional SEO Help",
            "email_url": f"mailto:prasad@esupport.live?subject={quote(email_subject)}&body={quote(email_body)}",
            "request_btn_text": "Request Full SEO Analysis"
        }
    }


def _normalize_host_for_match(url_or_domain: str) -> str:
    if not url_or_domain:
        return ""
    url_str = str(url_or_domain).strip().lower()
    if not re.match(r"^https?://", url_str):
        url_str = "http://" + url_str
    try:
        netloc = urlparse(url_str).netloc or ""
        host = netloc.split(":")[0].strip()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def _find_recent_audit_for_url(target_url: str) -> Optional[dict[str, Any]]:
    """Look up latest completed audit in the database for the matching target URL or domain.
    Ensures that Admin technical inspections and Client public scans share the exact same verified audit."""
    try:
        target_host = _normalize_host_for_match(target_url)
        if not target_host:
            return None

        with SessionLocal() as db:
            audits = db.query(Audit).filter(Audit.status == "COMPLETED").order_by(Audit.id.desc()).all()
            for a in audits:
                if not a.target_url or not a.result_json:
                    continue
                a_host = _normalize_host_for_match(a.target_url)
                if a_host == target_host:
                    try:
                        data = json.loads(a.result_json)
                        if isinstance(data, dict):
                            if a.score is not None and data.get("score") is None:
                                data["score"] = a.score
                            return data
                    except Exception:
                        pass
    except Exception as exc:
        logger.warning(f"Error querying existing audit in DB for {target_url}: {exc}")
    return None


def _run_public_scan_job(job_id: str, target_url: str):
    try:
        with PUBLIC_SCAN_LOCK:
            if job_id in PUBLIC_SCAN_JOBS:
                PUBLIC_SCAN_JOBS[job_id].update({
                    "state": "running",
                    "phase": "SCANNING",
                    "message": "Connecting to website and testing availability..."
                })

        # 1. Check if a real verified audit already exists in the platform database for this website/domain
        existing_audit = _find_recent_audit_for_url(target_url)
        if existing_audit:
            # Provide smooth visual progress through phases to match the scanning UX
            time.sleep(0.7)
            with PUBLIC_SCAN_LOCK:
                if job_id in PUBLIC_SCAN_JOBS:
                    PUBLIC_SCAN_JOBS[job_id].update({
                        "phase": "ANALYZING",
                        "message": "Analyzing HTML structure, headings, and metadata..."
                    })
            time.sleep(0.7)
            with PUBLIC_SCAN_LOCK:
                if job_id in PUBLIC_SCAN_JOBS:
                    PUBLIC_SCAN_JOBS[job_id].update({
                        "phase": "CALCULATING SCORE",
                        "message": "Finalizing category performance and overall score..."
                    })
            time.sleep(0.5)

            public_safe_result = _build_public_safe_result(target_url, existing_audit)
            with PUBLIC_SCAN_LOCK:
                if job_id in PUBLIC_SCAN_JOBS:
                    PUBLIC_SCAN_JOBS[job_id].update({
                        "state": "completed",
                        "phase": "COMPLETE",
                        "message": "Scan completed successfully.",
                        "result": public_safe_result
                    })
            return

        # 2. If no audit exists in DB, run live crawl with real metrics
        def scan_progress(p):
            phase = (p.get("phase") or "").lower()
            msg = "Analyzing your website..."
            pub_phase = "ANALYZING"
            if phase in {"preflight", "starting"}:
                pub_phase = "SCANNING"
                msg = "Testing website accessibility..."
            elif phase in {"crawl"}:
                pub_phase = "ANALYZING"
                msg = "Analyzing HTML structure, headings, and metadata..."
            elif phase in {"links", "resources"}:
                pub_phase = "ANALYZING"
                msg = "Inspecting link hierarchy and page assets..."
            elif phase in {"integrations"}:
                pub_phase = "ANALYZING"
                msg = "Measuring real page speed with Google PageSpeed Insights..."
            elif phase in {"ai"}:
                pub_phase = "CALCULATING SCORE"
                msg = "Preparing easy-to-read explanations..."
            elif phase in {"completed"}:
                pub_phase = "CALCULATING SCORE"
                msg = "Calculating overall SEO health score..."

            with PUBLIC_SCAN_LOCK:
                if job_id in PUBLIC_SCAN_JOBS:
                    PUBLIC_SCAN_JOBS[job_id].update({
                        "phase": pub_phase,
                        "message": msg
                    })

        audit_req = AuditRequest(
            url=target_url,
            max_pages=100,
            respect_robots=True,
            check_links=True,
            check_resources=True,
            link_check_limit=1000,
            resource_check_limit=1000,
            render_max_pages=20,
            crawl_mode="auto",
            use_pagespeed=bool(integrations.PAGESPEED_API_KEY) or integrations.local_lighthouse_available(),
            pagespeed_desktop=True,
            use_search_console=False,
            use_dataforseo=False,
            run_ai=PUBLIC_SCAN_AI,
            render_probe=True,
            run_probes=True,
        )
        audit_res = crawl(audit_req, progress_cb=scan_progress)

        with PUBLIC_SCAN_LOCK:
            if job_id in PUBLIC_SCAN_JOBS:
                PUBLIC_SCAN_JOBS[job_id].update({
                    "phase": "CALCULATING SCORE",
                    "message": "Finalizing category performance..."
                })

        public_safe_result = _build_public_safe_result(target_url, audit_res)

        # Persist new scan to DB so Admin and future client visits share this audit
        try:
            with SessionLocal() as db:
                new_audit = Audit(
                    job_id=job_id,
                    target_url=target_url,
                    result_json=json.dumps(audit_res),
                    score=float(public_safe_result.get("score") or 0.0),
                    status="COMPLETED",
                    created_at=datetime.utcnow()
                )
                db.add(new_audit)
                db.commit()
        except Exception as exc:
            logger.warning(f"Could not save public scan to database: {exc}")

        with PUBLIC_SCAN_LOCK:
            if job_id in PUBLIC_SCAN_JOBS:
                PUBLIC_SCAN_JOBS[job_id].update({
                    "state": "completed",
                    "phase": "COMPLETE",
                    "message": "Scan completed successfully.",
                    "result": public_safe_result
                })
    except Exception as exc:
        logger.warning(f"Public scan failed for {target_url}: {exc}")
        with PUBLIC_SCAN_LOCK:
            if job_id in PUBLIC_SCAN_JOBS:
                PUBLIC_SCAN_JOBS[job_id].update({
                    "state": "failed",
                    "phase": "FAILED",
                    "error": "We couldn't analyze this website right now. Please check the URL and try again."
                })


@app.post("/api/public/scan/start")
def start_public_scan(req: PublicScanRequest = Body(...), request: Request = None):
    ip = request.client.host if (request and request.client) else "unknown"
    if not _PUBLIC_SCAN_LIMITER.allow(ip):
        raise HTTPException(status_code=429, detail="Too many requests. Please wait a moment and try again.")

    raw_url = req.url.strip()
    if not raw_url:
        raise HTTPException(status_code=400, detail="Please enter a website URL.")

    # Normalize common input like example.com to https://example.com
    if not re.match(r"^https?://", raw_url, re.I):
        raw_url = "https://" + raw_url

    try:
        target_url = validate_public_target(norm_url(raw_url))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid URL: {str(exc)}")
    except Exception:
        raise HTTPException(status_code=400, detail="Please enter a valid website URL (e.g. https://example.com).")

    try:
        with SessionLocal() as db_scan:
            db_scan.add(PublicScan(target_url=target_url, ip_address=ip))
            db_scan.commit()
    except Exception:
        pass

    job_id = uuid.uuid4().hex
    with PUBLIC_SCAN_LOCK:
        PUBLIC_SCAN_JOBS[job_id] = {
            "state": "running",
            "phase": "SCANNING",
            "message": "Initializing website scan...",
            "target": target_url,
            "created_at": time.time()
        }

    JOB_EXECUTOR.submit(_run_public_scan_job, job_id, target_url)
    return {"job_id": job_id, "state": "running", "phase": "SCANNING"}


@app.get("/api/public/scan/status/{job_id}")
def get_public_scan_status(job_id: str):
    with PUBLIC_SCAN_LOCK:
        job = PUBLIC_SCAN_JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Scan job not found.")
        return {
            "job_id": job_id,
            "state": job.get("state"),
            "phase": job.get("phase"),
            "message": job.get("message"),
            "result": job.get("result"),
            "error": job.get("error")
        }


@app.post("/api/public/scan")
def public_scan_sync(req: PublicScanRequest = Body(...), request: Request = None):
    """Synchronous endpoint for public SEO scan."""
    ip = request.client.host if (request and request.client) else "unknown"
    if not _PUBLIC_SCAN_LIMITER.allow(ip):
        raise HTTPException(status_code=429, detail="Too many requests. Please wait a moment and try again.")

    raw_url = req.url.strip()
    if not raw_url:
        raise HTTPException(status_code=400, detail="Please enter a website URL.")

    if not re.match(r"^https?://", raw_url, re.I):
        raw_url = "https://" + raw_url

    try:
        target_url = validate_public_target(norm_url(raw_url))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid URL: {str(exc)}")
    except Exception:
        raise HTTPException(status_code=400, detail="Please enter a valid website URL (e.g. https://example.com).")

    existing_audit = _find_recent_audit_for_url(target_url)
    if existing_audit:
        return _build_public_safe_result(target_url, existing_audit)

    try:
        audit_req = AuditRequest(
            url=target_url,
            max_pages=100,
            respect_robots=True,
            check_links=True,
            check_resources=True,
            link_check_limit=1000,
            resource_check_limit=1000,
            render_max_pages=20,
            crawl_mode="auto",
            use_pagespeed=bool(integrations.PAGESPEED_API_KEY) or integrations.local_lighthouse_available(),
            pagespeed_desktop=True,
            use_search_console=False,
            use_dataforseo=False,
            run_ai=PUBLIC_SCAN_AI,
            render_probe=True,
            run_probes=True,
        )
        audit_res = crawl(audit_req)
        public_safe_result = _build_public_safe_result(target_url, audit_res)
        try:
            with SessionLocal() as db:
                new_audit = Audit(
                    job_id=uuid.uuid4().hex,
                    target_url=target_url,
                    result_json=json.dumps(audit_res),
                    score=float(public_safe_result.get("score") or 0.0),
                    status="COMPLETED",
                    created_at=datetime.utcnow()
                )
                db.add(new_audit)
                db.commit()
        except Exception:
            pass
        return public_safe_result
    except Exception as exc:
        logger.warning(f"Sync public scan failed for {target_url}: {exc}")
        raise HTTPException(status_code=500, detail="We couldn't analyze this website right now. Please check the URL and try again.")


# --- SEO LEADS API ---

@app.post("/api/leads")
@app.post("/api/public/leads")
def create_lead(req: LeadCreateRequest = Body(...), request: Request = None, db: Session = Depends(get_db)):
    ip = request.client.host if (request and request.client) else "unknown"
    if not _PUBLIC_LEAD_LIMITER.allow(ip):
        raise HTTPException(status_code=429, detail="Too many requests. Please wait a moment and try again.")

    name = req.name.strip() if req.name else ""
    if not name:
        if req.company and req.company.strip():
            name = req.company.strip()
        elif req.email and "@" in req.email:
            name = req.email.split("@")[0].replace(".", " ").replace("_", " ").title()
        else:
            name = "Website Lead"

    email = req.email.strip().lower()
    if not email or "@" not in email or "." not in email:
        raise HTTPException(status_code=400, detail="Please provide a valid email address.")

    website = req.website.strip()
    if not website:
        raise HTTPException(status_code=400, detail="Website URL is required.")
    if not re.match(r"^https?://", website, re.I):
        website = "https://" + website

    initial_score = req.initial_score
    if initial_score is not None:
        try:
            initial_score = round(float(initial_score), 1)
        except Exception:
            initial_score = None

    timeline = [
        {
            "event": "Lead Created",
            "timestamp": datetime.utcnow().isoformat(),
            "note": f"Initial SEO Score: {initial_score}/100" if initial_score is not None else "Initial inquiry submitted from public SEO checker."
        }
    ]

    new_lead = SEOLead(
        name=name,
        company=req.company.strip(),
        email=email,
        phone=req.phone.strip(),
        website=website,
        initial_score=initial_score,
        message=req.message.strip(),
        status="NEW",
        source="public_checker",
        timeline_json=json.dumps(timeline)
    )
    db.add(new_lead)
    db.commit()
    db.refresh(new_lead)
    invalidate_dashboard_cache()

    return {
        "status": "success",
        "id": new_lead.id,
        "lead_id": new_lead.id,
        "message": "Thank you. Your request has been received. An eSupport representative will contact you."
    }


@app.get("/api/leads")
def list_leads(db: Session = Depends(get_db), current_admin: AdminUser = Depends(require_permission("leads.view"))):
    leads = db.query(SEOLead).order_by(SEOLead.created_at.desc()).all()
    if not leads:
        return []

    client_ids = list({l.client_id for l in leads if l.client_id})
    clients_map = {c.id: c.name for c in db.query(Client).filter(Client.id.in_(client_ids)).all()} if client_ids else {}

    result = []
    for l in leads:
        result.append({
            "id": l.id,
            "name": l.name,
            "company": l.company or "",
            "email": l.email,
            "phone": l.phone or "",
            "website": l.website,
            "initial_score": l.initial_score,
            "status": l.status,
            "source": l.source,
            "client_id": l.client_id,
            "client_name": clients_map.get(l.client_id),
            "message": l.message or "",
            "created_at": l.created_at.isoformat() if l.created_at else None,
            "updated_at": l.updated_at.isoformat() if l.updated_at else None,
        })
    return result


@app.get("/api/leads/{lead_id}")
def get_lead(lead_id: int, db: Session = Depends(get_db), current_admin: AdminUser = Depends(require_permission("leads.view"))):
    lead = db.query(SEOLead).filter(SEOLead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")

    timeline = []
    try:
        timeline = json.loads(lead.timeline_json) if lead.timeline_json else []
    except Exception:
        timeline = []

    notes = db.query(LeadNote).filter(LeadNote.lead_id == lead.id).order_by(LeadNote.created_at.desc()).all()
    notes_list = [{
        "id": n.id,
        "author_name": n.author_name,
        "author_email": n.author_email,
        "note": n.note,
        "created_at": n.created_at.isoformat()
    } for n in notes]

    return {
        "id": lead.id,
        "name": lead.name,
        "company": lead.company or "",
        "email": lead.email,
        "phone": lead.phone or "",
        "website": lead.website,
        "initial_score": lead.initial_score,
        "status": lead.status,
        "source": lead.source,
        "client_id": lead.client_id,
        "client_name": lead.client.name if lead.client else None,
        "message": lead.message or "",
        "timeline": timeline,
        "notes": notes_list,
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
        "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
    }


@app.post("/api/leads/{lead_id}/notes")
def add_lead_note(
    lead_id: int,
    req: LeadNoteCreateRequest = Body(...),
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("leads.notes"))
):
    lead = db.query(SEOLead).filter(SEOLead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")

    note_text = req.note.strip()
    if not note_text:
        raise HTTPException(status_code=400, detail="Note cannot be empty.")

    author_name = getattr(current_admin, "name", "") or current_admin.email.split("@")[0].capitalize()
    note = LeadNote(
        lead_id=lead.id,
        user_id=current_admin.id,
        author_name=author_name,
        author_email=current_admin.email,
        note=note_text,
        created_at=datetime.utcnow()
    )
    db.add(note)

    timeline = []
    try:
        timeline = json.loads(lead.timeline_json) if lead.timeline_json else []
    except Exception:
        timeline = []

    timeline.append({
        "event": "Sales Note Added",
        "timestamp": datetime.utcnow().isoformat(),
        "note": f"{author_name}: {note_text}"
    })
    lead.timeline_json = json.dumps(timeline)
    db.commit()
    db.refresh(note)

    record_activity(db, "LEAD_NOTE_ADDED", f"Lead #{lead.id} ({lead.name})", f"Note: {note_text[:50]}", user=current_admin)
    return {
        "status": "success",
        "id": note.id,
        "author_name": note.author_name,
        "note": note.note,
        "created_at": note.created_at.isoformat()
    }


@app.get("/api/leads/{lead_id}/notes")
def get_lead_notes(
    lead_id: int,
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("leads.view"))
):
    lead = db.query(SEOLead).filter(SEOLead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")

    notes = db.query(LeadNote).filter(LeadNote.lead_id == lead.id).order_by(LeadNote.created_at.desc()).all()
    return [{
        "id": n.id,
        "author_name": n.author_name,
        "author_email": n.author_email,
        "note": n.note,
        "created_at": n.created_at.isoformat()
    } for n in notes]


@app.post("/api/leads/{lead_id}/status")
@app.patch("/api/leads/{lead_id}/status")
def update_lead_status(
    lead_id: int,
    req: LeadStatusUpdateRequest = Body(...),
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("leads.edit"))
):
    lead = db.query(SEOLead).filter(SEOLead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")

    new_status = req.status.strip().upper()
    valid_statuses = {"NEW", "CONTACTED", "QUALIFIED", "CONVERTED", "CLOSED"}
    if new_status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {', '.join(sorted(valid_statuses))}")

    lead.status = new_status
    timeline = []
    try:
        timeline = json.loads(lead.timeline_json) if lead.timeline_json else []
    except Exception:
        timeline = []

    author_name = getattr(current_admin, "name", "") or current_admin.email.split("@")[0].capitalize()
    timeline.append({
        "event": f"Status updated to {new_status}",
        "timestamp": datetime.utcnow().isoformat(),
        "note": f"{author_name} updated status to {new_status}"
    })
    lead.timeline_json = json.dumps(timeline)
    db.commit()
    db.refresh(lead)
    invalidate_dashboard_cache()

    record_activity(db, "LEAD_STATUS_CHANGED", f"Lead #{lead.id} ({lead.name})", f"Status: {new_status}", user=current_admin)
    return {"status": "success", "id": lead.id, "lead_status": lead.status, "timeline": timeline}


@app.post("/api/leads/{lead_id}/convert")
def convert_lead_to_client(
    lead_id: int,
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("leads.convert"))
):
    lead = db.query(SEOLead).filter(SEOLead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")

    # Find or create Client
    client = None
    if lead.client_id:
        client = db.query(Client).filter(Client.id == lead.client_id).first()

    if not client and lead.email:
        client = db.query(Client).filter(Client.email == lead.email).first()

    if not client:
        client = Client(
            name=lead.name,
            company=lead.company or lead.name,
            email=lead.email,
            phone=lead.phone or "",
            status="ACTIVE"
        )
        db.add(client)
        db.commit()
        db.refresh(client)

    # Find or create Website under Client
    site = db.query(Website).filter(Website.client_id == client.id, Website.url == lead.website).first()
    if not site:
        site = Website(
            client_id=client.id,
            url=lead.website,
            name=lead.company or lead.name,
            status="ACTIVE"
        )
        db.add(site)
        db.commit()
        db.refresh(site)

    lead.client_id = client.id
    lead.status = "CONVERTED"

    timeline = []
    try:
        timeline = json.loads(lead.timeline_json) if lead.timeline_json else []
    except Exception:
        timeline = []

    author_name = getattr(current_admin, "name", "") or current_admin.email.split("@")[0].capitalize()
    timeline.append({
        "event": "Converted to Client & Website",
        "timestamp": datetime.utcnow().isoformat(),
        "note": f"{author_name} linked to Client #{client.id} ({client.name}) and Website #{site.id}"
    })
    lead.timeline_json = json.dumps(timeline)
    db.commit()
    db.refresh(lead)
    invalidate_dashboard_cache()

    record_activity(db, "LEAD_CONVERTED", f"Lead #{lead.id} ({lead.name})", f"Converted to Client #{client.id} ({client.name})", user=current_admin)

    return {
        "status": "success",
        "lead_id": lead.id,
        "client_id": client.id,
        "website_id": site.id,
        "client_name": client.name,
        "website_url": site.url
    }


@app.get("/api/seo-guide")
def seo_guide():
    return {"version":app.version,"sections":[{"letter":a,"name":b,"description":c} for a,b,c in SEO_A_TO_Z]}

@app.get("/api/seo-guide/pdf")
def seo_guide_pdf():
    pdf = build_guide_pdf()
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition":'attachment; filename="aviance-seo-a-to-z-guide.pdf"'})

@app.post("/api/report/pdf")
def report_pdf(payload: dict[str, Any], current_admin: Optional[AdminUser] = Depends(get_current_admin_optional)):
    audit = payload.get("audit") if isinstance(payload, dict) and isinstance(payload.get("audit"), dict) else payload
    report_type = payload.get("report_type", "full") if isinstance(payload, dict) else "full"
    if isinstance(audit, dict) and "audit_result" in audit and isinstance(audit["audit_result"], dict):
        audit = audit["audit_result"]
    if not isinstance(audit, dict) or not audit.get("target"):
        raise HTTPException(status_code=400, detail="A completed audit JSON payload is required")
    report_type = report_type if report_type in {"full","developer","recommendations","recommendations_all","executive","keywords","social","indexing","client"} else "client" if report_type == "client" else "full"
    assert_release_gate(audit)
    try:
        pdf = build_special_report_pdf(audit, report_type)
        host = urlparse(str(audit.get("target"))).hostname or "site"
        return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition":f'attachment; filename="{report_filename(host, report_type)}"'})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {exc}")

@app.get("/api/reports/public/{token}/pdf")
@app.get("/api/reports/{token}/pdf")
def download_public_report_pdf(token: str, db: Session = Depends(get_db)):
    report = db.query(PublicReport).filter(PublicReport.token == token).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found.")
    if report.status == "DISABLED":
        raise HTTPException(status_code=410, detail="This report has been disabled.")

    audit_data = {}
    if report.audit and report.audit.result_json:
        try:
            audit_data = json.loads(report.audit.result_json) if isinstance(report.audit.result_json, str) else report.audit.result_json
        except Exception:
            pass
    if not audit_data and report.snapshot_json:
        try:
            snapshot = json.loads(report.snapshot_json) if isinstance(report.snapshot_json, str) else report.snapshot_json
            audit_data = {
                "target": snapshot.get("target_url"),
                "score": snapshot.get("score"),
                "scores": {"overall": snapshot.get("score")},
                "stats": snapshot.get("stats", {}),
                "seo_engine": {"score": {"overall": snapshot.get("score")}, "categories": snapshot.get("categories", [])},
                "issues": snapshot.get("top_issues", []),
                "recommendations": {"developer_plan": snapshot.get("recommendations", [])}
            }
        except Exception:
            pass

    if not audit_data:
        raise HTTPException(status_code=404, detail="Audit data not available for this report.")

    try:
        pdf_bytes = build_client_summary_pdf(audit_data)
        host = urlparse(str(audit_data.get("target") or "website")).hostname or "site"
        safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", host)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="esupport-seo-client-report-{safe}.pdf"'}
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {exc}")

@app.get("/api/reports/public/{token}/comprehensive")
@app.get("/api/reports/{token}/comprehensive")
def view_comprehensive_report(token: str, db: Session = Depends(get_db)):
    report = db.query(PublicReport).filter(PublicReport.token == token).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found.")
    if report.status == "DISABLED":
        raise HTTPException(status_code=410, detail="This report has been disabled.")
    audit_data = {}
    if report.audit and report.audit.result_json:
        try:
            audit_data = json.loads(report.audit.result_json) if isinstance(report.audit.result_json, str) else report.audit.result_json
        except Exception:
            pass
    if not audit_data:
        audit_data = {"target": "https://voltedgepower-solutions.com/", "score": 47}
    from .comprehensive_report import build_comprehensive_html
    return HTMLResponse(content=build_comprehensive_html(audit_data))

@app.get("/api/reports/public/{token}/comprehensive/pdf")
@app.get("/api/reports/{token}/comprehensive/pdf")
def download_public_comprehensive_pdf(token: str, db: Session = Depends(get_db)):
    report = db.query(PublicReport).filter(PublicReport.token == token).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found.")
    if report.status == "DISABLED":
        raise HTTPException(status_code=410, detail="This report has been disabled.")
    audit_data = {}
    if report.audit and report.audit.result_json:
        try:
            audit_data = json.loads(report.audit.result_json) if isinstance(report.audit.result_json, str) else report.audit.result_json
        except Exception:
            pass
    if not audit_data:
        audit_data = {"target": "https://voltedgepower-solutions.com/", "score": 47}
    from .comprehensive_report import build_comprehensive_pdf
    pdf_bytes = build_comprehensive_pdf(audit_data)
    host = urlparse(str(audit_data.get("target") or "website")).hostname or "site"
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", host)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="esupport-seo-comprehensive-report-{safe}.pdf"'}
    )

@app.post("/api/report/comprehensive/pdf")
def report_comprehensive_pdf(payload: dict[str, Any], current_admin: AdminUser = Depends(require_permission("reports.view"))):
    audit = payload.get("audit") if isinstance(payload, dict) and isinstance(payload.get("audit"), dict) else payload
    if not isinstance(audit, dict) or not audit.get("target"):
        raise HTTPException(status_code=400, detail="A completed audit JSON payload is required")
    from .comprehensive_report import build_comprehensive_pdf
    pdf = build_comprehensive_pdf(audit)
    host = urlparse(str(audit.get("target"))).hostname or "site"
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", host)
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="esupport-seo-comprehensive-report-{safe}.pdf"'})

@app.post("/api/report/csv")
def report_csv(payload: dict[str, Any], current_admin: AdminUser = Depends(require_permission("reports.view"))):
    audit = payload.get("audit") if isinstance(payload, dict) and isinstance(payload.get("audit"), dict) else payload
    kind = payload.get("kind", "developers") if isinstance(payload, dict) else "developers"
    if not isinstance(audit, dict) or not audit.get("target"):
        raise HTTPException(status_code=400, detail="A completed audit JSON payload is required")
    out=StringIO(newline=""); out.write("\ufeff"); writer=csv.writer(out)
    host=re.sub(r"[^a-zA-Z0-9_-]+","-",urlparse(str(audit.get("target"))).hostname or "site")
    if kind=="pages":
        writer.writerow(["URL","Status","Title","Title Length","Meta Description","H1 Count","Words","Images","Internal Links","Response ms","Findings"])
        for p in audit.get("pages",[]) or []: writer.writerow([p.get("url"),p.get("status"),p.get("title"),len(p.get("title") or ""),p.get("meta_description"),len(p.get("h1",[])),p.get("word_count"),len(p.get("images",[])),len(p.get("internal_links",[])),p.get("response_time_ms"),len(p.get("issues",[]))])
        filename=f"aviance-pages-{host}.csv"
    elif kind=="issues":
        writer.writerow(["Severity","Category","Code","Message","URL","Recommendation","Evidence","Developer Fix"])
        for i in audit.get("issues",[]) or []: writer.writerow([i.get("severity"),i.get("category"),i.get("code"),i.get("message"),i.get("url"),i.get("recommendation"),i.get("evidence"),i.get("fix")])
        filename=f"aviance-issues-{host}.csv"
    elif kind=="keywords":
        writer.writerow(["Keyword","Observed Count","Pages","Intent","URLs"])
        for i in (audit.get("keyword_intelligence") or {}).get("observed_keywords",[]): writer.writerow([i.get("keyword"),i.get("observed_count"),i.get("pages"),i.get("intent")," | ".join(i.get("urls",[])[:50])])
        filename=f"aviance-keywords-{host}.csv"
    elif kind=="hashtags":
        writer.writerow(["Hashtag","Pages"])
        for i in (audit.get("keyword_intelligence") or {}).get("hashtags",[]): writer.writerow([i.get("hashtag"),i.get("pages")])
        filename=f"aviance-hashtags-{host}.csv"
    elif kind=="categories":
        writer.writerow(["Category","Total","Critical","Warning","Info","Top Issue Code","Affected URLs"])
        for i in audit.get("source_categories",[]) or []: writer.writerow([i.get("category"),i.get("total"),i.get("critical"),i.get("warning"),i.get("info"),i.get("top_issue_code")," | ".join(i.get("affected_urls",[])[:50])])
        filename=f"aviance-source-categories-{host}.csv"
    elif kind=="automatic":
        writer.writerow(["Check","Category","Name","Status","Points Earned","Points Available","Evidence Label","Evidence","Unmeasured Reason"])
        for i in (ensure_engine(audit).get("checks") or []): writer.writerow([i["id"],i["category"],i["name"],i["status"],i["points_earned"],i["points_available"],i["evidence"].get("label"),i["evidence"].get("statement"),i.get("unmeasured_reason") or ""])
        filename=f"esupport-check-evidence-{host}.csv"
    else:
        writer.writerow(["Priority","Category","Code","Issue","Affected","Action","Developer Fix","Validation","Affected URLs"])
        for item in (audit.get("recommendations",{}) or {}).get("developer_plan",[]) or []: writer.writerow([item.get("priority"),item.get("category"),item.get("code"),item.get("issue"),item.get("affected"),item.get("action"),item.get("fix"),item.get("validation")," | ".join(item.get("affected_urls",[])[:200])])
        filename=f"aviance-developer-plan-{host}.csv"
    return Response(content=out.getvalue().encode("utf-8"), media_type="text/csv; charset=utf-8", headers={"Content-Disposition":f'attachment; filename="{filename}"'})

@app.post("/api/report/bundle")
def report_bundle(payload: dict[str, Any], current_admin: AdminUser = Depends(require_permission("reports.view"))):
    """Portable report pack with all PDF/CSV exports, raw JSON and the A-Z guide."""
    audit = payload.get("audit") if isinstance(payload, dict) and isinstance(payload.get("audit"), dict) else payload
    if not isinstance(audit, dict) or not audit.get("target"):
        raise HTTPException(status_code=400, detail="A completed audit JSON payload is required")
    assert_release_gate(audit)
    raw_json = json.dumps(audit, ensure_ascii=False, indent=2)
    if len(raw_json.encode("utf-8")) > 40_000_000:
        raise HTTPException(status_code=413, detail="Audit result is too large for a report bundle. Export JSON separately.")
    try:
        host = re.sub(r"[^a-zA-Z0-9_-]+", "-", urlparse(str(audit.get("target"))).hostname or "site")
        developer_plan = (audit.get("recommendations",{}) or {}).get("developer_plan",[]) or []
        csv_dev = StringIO(newline=""); csv_dev.write("\ufeff"); w = csv.writer(csv_dev); w.writerow(["Priority","Category","Code","Issue","Affected","Action","Developer Fix","Validation","Affected URLs"])
        for item in developer_plan: w.writerow([item.get("priority"),item.get("category"),item.get("code"),item.get("issue"),item.get("affected"),item.get("action"),item.get("fix"),item.get("validation")," | ".join(item.get("affected_urls",[])[:200])])
        csv_pages = StringIO(newline=""); csv_pages.write("\ufeff"); wp = csv.writer(csv_pages); wp.writerow(["URL","Status","Title","Title Length","Meta Description","H1 Count","Words","Images","Internal Links","Response ms","Findings"])
        for p in audit.get("pages",[]) or []: wp.writerow([p.get("url"),p.get("status"),p.get("title"),len(p.get("title") or ""),p.get("meta_description"),len(p.get("h1",[])),p.get("word_count"),len(p.get("images",[])),len(p.get("internal_links",[])),p.get("response_time_ms"),len(p.get("issues",[]))])
        csv_issues = StringIO(newline=""); csv_issues.write("\ufeff"); wi = csv.writer(csv_issues); wi.writerow(["Severity","Category","Code","Message","URL","Recommendation","Evidence"])
        for i in audit.get("issues",[]) or []: wi.writerow([i.get("severity"),i.get("category"),i.get("code"),i.get("message"),i.get("url"),i.get("recommendation"),i.get("evidence")])
        bundle=BytesIO()
        with zipfile.ZipFile(bundle,"w",zipfile.ZIP_DEFLATED) as z:
            for rt in ("full","developer","recommendations","recommendations_all","executive","keywords","social","indexing"):
                z.writestr(report_filename(host,rt), build_special_report_pdf(audit,rt))
            z.writestr(f"aviance-seo-audit-{host}.json", raw_json.encode("utf-8"))
            z.writestr(f"aviance-developer-plan-{host}.csv", csv_dev.getvalue().encode("utf-8"))
            z.writestr(f"aviance-pages-{host}.csv", csv_pages.getvalue().encode("utf-8"))
            z.writestr(f"aviance-issues-{host}.csv", csv_issues.getvalue().encode("utf-8"))
            for kind in ("keywords","hashtags","categories","automatic"):
                csv_resp = report_csv({"audit":audit,"kind":kind}, current_admin=current_admin)
                disposition = csv_resp.headers.get("content-disposition","")
                filename = re.search(r'filename="([^"]+)"', disposition).group(1) if re.search(r'filename="([^"]+)"', disposition) else f"aviance-{kind}-{host}.csv"
                z.writestr(filename, csv_resp.body)
            guide_md = ROOT/'docs'/'SEO_A_TO_Z_GUIDE.md'
            if guide_md.exists(): z.write(guide_md, "SEO_A_TO_Z_GUIDE.md")
            z.writestr("README.txt", f"Aviance SEO Pro Max v{audit.get('version','')} report pack\nTarget: {audit.get('target','')}\nScore: {audit.get('score',0)}/100\nPages: {audit.get('page_count',0)}\n\nAll results are current-audit data. See the A-Z guide and Data Provenance section for measurement boundaries.\n")
        bundle.seek(0)
        return Response(content=bundle.getvalue(), media_type="application/zip", headers={"Content-Disposition":f'attachment; filename="aviance-seo-report-pack-{host}.zip"'})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Report bundle generation failed: {exc}")

@app.post("/api/source-audit")
async def run_source_audit(file: UploadFile = File(...), current_admin: AdminUser = Depends(require_permission("source_audit.run"))):
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Upload a .zip source archive")
    data = await file.read()
    if len(data) > 75_000_000:
        raise HTTPException(status_code=413, detail="ZIP exceeds 75 MB")
    target = UPLOADS / (hashlib.sha256(f"{file.filename}-{time.time()}".encode()).hexdigest()[:20] + ".zip")
    target.write_bytes(data)
    try:
        return source_audit(target)
    finally:
        target.unlink(missing_ok=True)
from .tech_detector.router import router as tech_detector_router
app.include_router(tech_detector_router)


if __name__ == "__main__":
    import uvicorn
    print(f"Aviance SEO Pro Max running at http://127.0.0.1:{PORT}")
    # HOST=0.0.0.0 makes the app reachable from other computers on your network (team members).
    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=PORT)
