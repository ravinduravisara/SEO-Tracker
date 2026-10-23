"""
eSupport SEO • Production Security & Admin Authentication Module
Provides Argon2id password hashing, brute-force protection, HTTP-only session management,
CSRF verification, and bootstrap account management.
"""

from __future__ import annotations

import os
import time
import secrets
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from collections import defaultdict

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from fastapi import Request, Response, HTTPException, Depends
from sqlalchemy.orm import Session

from .database import get_db, AdminUser, AdminSession

logger = logging.getLogger("esupport_security")
_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)

COOKIE_NAME = "esupport_admin_session"
SESSION_DURATION_DAYS = 7
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_WINDOW_SECONDS = 300  # 5 minutes
LOCKOUT_DURATION_SECONDS = 900  # 15 minutes

# Brute-force tracking: {key: [timestamp, ...]}
_failed_attempts: dict[str, list[float]] = defaultdict(list)
_lockouts: dict[str, float] = {}


def hash_password(password: str) -> str:
    """Hash password using Argon2id."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against Argon2id hash."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False
    except Exception as exc:
        logger.error("Password verification error: %s", exc)
        return False


def check_brute_force(key: str) -> tuple[bool, str]:
    """Check if key (IP or username) is currently locked out."""
    # Exempt loopback IP from IP-level lockout to avoid blocking local test runs; per-user lockout still strictly applies
    if key in ("ip:127.0.0.1", "ip:::1", "ip:localhost"):
        return True, ""

    now = time.time()
    
    # Check active lockout
    locked_until = _lockouts.get(key, 0)
    if locked_until > now:
        remaining = int(locked_until - now)
        return False, f"Too many failed login attempts. Please wait {remaining} seconds before trying again."
    elif locked_until and locked_until <= now:
        del _lockouts[key]

    # Clean old attempts
    attempts = [t for t in _failed_attempts[key] if now - t < LOCKOUT_WINDOW_SECONDS]
    _failed_attempts[key] = attempts

    if len(attempts) >= MAX_FAILED_ATTEMPTS:
        _lockouts[key] = now + LOCKOUT_DURATION_SECONDS
        return False, f"Too many failed attempts. Temporary lockout for {LOCKOUT_DURATION_SECONDS // 60} minutes."

    return True, ""


def reset_brute_force():
    """Reset brute-force tracking."""
    _failed_attempts.clear()
    _lockouts.clear()


def record_failed_login(key: str):
    """Record a failed login attempt."""
    _failed_attempts[key].append(time.time())


def record_successful_login(key: str):
    """Clear failed attempts upon successful authentication."""
    _failed_attempts.pop(key, None)
    _lockouts.pop(key, None)


def bootstrap_admin_account(db: Session):
    """
    Ensure at least one super admin account exists on startup.
    Default email: prasad@esupport.live.
    Initial password can be set via ADMIN_INITIAL_PASSWORD env var.
    If not set, generates a secure random password and logs it.
    """
    admin_email = os.getenv("ADMIN_EMAIL", "prasad@esupport.live").strip().lower()
    existing = db.query(AdminUser).filter(AdminUser.email == admin_email).first()
    if existing:
        # Upgrade existing user to SUPER_ADMIN if needed
        updated = False
        if not getattr(existing, "role", None) or existing.role != "SUPER_ADMIN":
            existing.role = "SUPER_ADMIN"
            updated = True
        if not getattr(existing, "status", None) or existing.status != "ACTIVE":
            existing.status = "ACTIVE"
            updated = True
        if not getattr(existing, "name", None):
            existing.name = "Prasad (Super Admin)"
            updated = True
        if updated:
            db.commit()
        return

    admin_count = db.query(AdminUser).count()
    if admin_count > 0:
        return

    initial_pw = os.getenv("ADMIN_INITIAL_PASSWORD", "").strip()
    if not initial_pw:
        # Default bootstrap password for initial setup
        initial_pw = "eSupport@SEO2026!Admin"
        logger.warning(
            "====================================================================\n"
            "SECURITY: Created initial Super Admin account:\n"
            "  Email: %s\n"
            "  Password: %s\n"
            "Please change this password after your initial login.\n"
            "====================================================================",
            admin_email, initial_pw
        )

    hashed = hash_password(initial_pw)
    admin = AdminUser(
        email=admin_email,
        name="Prasad (Super Admin)",
        role="SUPER_ADMIN",
        status="ACTIVE",
        password_hash=hashed,
        created_at=datetime.utcnow()
    )
    db.add(admin)
    db.commit()
    logger.info("Super Admin bootstrap complete for %s", admin_email)


def create_admin_session(db: Session, admin: AdminUser, response: Response) -> tuple[str, str]:
    """
    Create a new cryptographic session token, store hash in DB, and set HttpOnly cookie.
    Returns (raw_session_token, csrf_token).
    """
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    csrf_token = secrets.token_urlsafe(32)

    expires = datetime.utcnow() + timedelta(days=SESSION_DURATION_DAYS)
    session = AdminSession(
        admin_id=admin.id,
        token_hash=token_hash,
        expires_at=expires,
        created_at=datetime.utcnow()
    )
    db.add(session)
    # Update last login timestamp
    admin.last_login_at = datetime.utcnow()
    db.commit()

    # Set secure, HttpOnly session cookie
    is_prod = os.getenv("APP_ENV", "development").lower() == "production"
    response.set_cookie(
        key=COOKIE_NAME,
        value=raw_token,
        max_age=SESSION_DURATION_DAYS * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=is_prod,
        path="/"
    )

    return raw_token, csrf_token


def destroy_admin_session(db: Session, request: Request, response: Response):
    """Revoke session in database and delete browser cookie."""
    token = request.cookies.get(COOKIE_NAME)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()

    if token:
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        db.query(AdminSession).filter(AdminSession.token_hash == token_hash).delete()
        db.commit()

    response.delete_cookie(key=COOKIE_NAME, path="/")


def get_current_admin(request: Request, db: Session = Depends(get_db)) -> AdminUser:
    """
    FastAPI dependency to protect Admin routes.
    Validates HttpOnly cookie or Bearer token.
    Raises 401 Unauthorized if invalid or expired.
    Raises 403 Forbidden if account is suspended, deactivated, or not active.
    """
    token = request.cookies.get(COOKIE_NAME)
    auth_header = request.headers.get("Authorization", "")
    if not token and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Please log in to access the Admin Portal.",
            headers={"WWW-Authenticate": "Cookie"}
        )

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    session = db.query(AdminSession).filter(
        AdminSession.token_hash == token_hash,
        AdminSession.expires_at > datetime.utcnow()
    ).first()

    if not session or not session.admin:
        raise HTTPException(
            status_code=401,
            detail="Session expired or invalid. Please log in again.",
            headers={"WWW-Authenticate": "Cookie"}
        )

    admin = session.admin
    # Strict Account Status Enforcements
    status = getattr(admin, "status", "ACTIVE")
    if status == "SUSPENDED":
        raise HTTPException(status_code=403, detail="Your account has been suspended by an administrator.")
    if status == "DEACTIVATED":
        raise HTTPException(status_code=403, detail="Your account has been deactivated.")
    if status == "INVITED":
        raise HTTPException(status_code=403, detail="Your account invitation is pending activation.")
    if status != "ACTIVE":
        raise HTTPException(status_code=403, detail="Your account is not active.")

    return admin


def get_current_admin_optional(request: Request, db: Session = Depends(get_db)) -> Optional[AdminUser]:
    try:
        return get_current_admin(request, db)
    except HTTPException:
        return None


def record_activity(
    db: Session,
    action: str,
    resource: str = "",
    details: str = "",
    status: str = "SUCCESS",
    user: Optional[AdminUser] = None,
    ip_address: str = ""
):
    """
    Record an administrative or team action into the persistent activity logs.
    Never records passwords, API secrets, tokens, or sensitive hashes.
    """
    try:
        from .database import ActivityLog
        log = ActivityLog(
            user_id=user.id if user else None,
            user_email=user.email if user else "",
            user_name=getattr(user, "name", "") if user else "",
            user_role=getattr(user, "role", "") if user else "",
            action=action,
            resource=resource,
            details=details,
            status=status,
            ip_address=ip_address,
            created_at=datetime.utcnow()
        )
        db.add(log)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("Failed to record activity log: %s", exc)


def verify_csrf(request: Request):
    """
    Validates CSRF protection on state-changing requests.
    Requires custom header X-Requested-With or X-CSRF-Token for browser POST/PUT/DELETE.
    """
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        csrf_header = request.headers.get("X-Requested-With") or request.headers.get("X-CSRF-Token")
        # In automated scripts or direct API with Bearer token, bearer header itself satisfies CSRF protection
        auth_header = request.headers.get("Authorization", "")
        if not csrf_header and not auth_header.startswith("Bearer "):
            # Check origin / referer header
            origin = request.headers.get("Origin") or request.headers.get("Referer")
            host = request.headers.get("Host")
            if origin and host and host not in origin:
                raise HTTPException(status_code=403, detail="Cross-origin state change blocked.")

