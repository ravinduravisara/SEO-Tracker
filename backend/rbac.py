"""
eSupport SEO • Centralized Role-Based Access Control (RBAC) Module
Provides role definitions, fine-grained permission mapping, permission checks,
and FastAPI dependencies to enforce authorization at the backend.
"""

from __future__ import annotations

from typing import Set, Dict, List
from fastapi import HTTPException, Depends

# Role Constants
ROLE_SUPER_ADMIN = "SUPER_ADMIN"
ROLE_ADMIN = "ADMIN"
ROLE_SALES = "SALES"
ROLE_SEO_ANALYST = "SEO_ANALYST"

VALID_ROLES: List[str] = [
    ROLE_SUPER_ADMIN,
    ROLE_ADMIN,
    ROLE_SALES,
    ROLE_SEO_ANALYST,
]

# User Account Statuses
STATUS_INVITED = "INVITED"
STATUS_ACTIVE = "ACTIVE"
STATUS_SUSPENDED = "SUSPENDED"
STATUS_DEACTIVATED = "DEACTIVATED"

VALID_STATUSES: List[str] = [
    STATUS_INVITED,
    STATUS_ACTIVE,
    STATUS_SUSPENDED,
    STATUS_DEACTIVATED,
]

# Role to Permissions Mapping
ROLE_PERMISSIONS: Dict[str, Set[str]] = {
    ROLE_SUPER_ADMIN: {
        "dashboard.view", "dashboard.full",
        "clients.view", "clients.create", "clients.edit", "clients.delete",
        "websites.view", "websites.create", "websites.edit", "websites.delete",
        "scanner.view", "scanner.history", "scanner.analytics",
        "leads.view", "leads.create", "leads.edit", "leads.contact", "leads.convert", "leads.notes",
        "audits.view", "audits.run", "audits.cancel", "audits.delete",
        "issues.view", "recommendations.view", "keywords.view", "pages.view",
        "reports.view", "reports.generate", "reports.publish", "reports.disable", "reports.email",
        "public_reports.view", "public_reports.publish", "public_reports.disable",
        "technical_report.view", "source_audit.run", "guide.view",
        "notifications.view", "activity_logs.view",
        "admin_users.view", "admin_users.create", "admin_users.edit", "admin_users.disable",
        "admin_users.change_role", "admin_users.reset_access", "admin_users.delete",
        "security.view", "security.manage",
        "settings.view", "settings.manage",
        "integrations.view", "integrations.manage",
        "system_health.view",
        "tech_detector.view", "tech_detector.scan",
    },
    ROLE_ADMIN: {
        "dashboard.view", "dashboard.operational",
        "clients.view", "clients.create", "clients.edit",
        "websites.view", "websites.create", "websites.edit",
        "scanner.view", "scanner.history", "scanner.analytics",
        "leads.view", "leads.create", "leads.edit", "leads.contact", "leads.convert", "leads.notes",
        "audits.view", "audits.run", "audits.cancel",
        "issues.view", "recommendations.view", "keywords.view", "pages.view",
        "reports.view", "reports.generate", "reports.publish", "reports.disable", "reports.email",
        "public_reports.view", "public_reports.publish", "public_reports.disable",
        "technical_report.view", "source_audit.run", "guide.view",
        "notifications.view", "activity_logs.view",
        "system_health.view",
        "tech_detector.view", "tech_detector.scan",
        # Team management, limited to SALES and SEO_ANALYST members (see MANAGEABLE_ROLES).
        "admin_users.view", "admin_users.create", "admin_users.edit", "admin_users.disable",
        "admin_users.change_role", "admin_users.reset_access",
    },
    ROLE_SALES: {
        "dashboard.view", "dashboard.sales",
        "clients.view", "clients.create", "clients.edit",
        "websites.view", "websites.create",
        "scanner.view", "scanner.history", "scanner.analytics",
        "leads.view", "leads.create", "leads.edit", "leads.contact", "leads.convert", "leads.notes",
        "public_reports.view",
        "notifications.view",
        "guide.view",
    },
    ROLE_SEO_ANALYST: {
        "dashboard.view", "dashboard.analyst",
        "clients.view",
        "websites.view", "websites.create",
        "scanner.view", "scanner.history",
        "audits.view", "audits.run", "audits.cancel",
        "issues.view", "recommendations.view", "keywords.view", "pages.view",
        "reports.view", "reports.generate",
        "public_reports.view",
        "technical_report.view", "source_audit.run", "guide.view",
        "notifications.view",
    },
}


# Which roles each role may invite, edit, suspend or reset. Super Admin manages everyone.
MANAGEABLE_ROLES: Dict[str, Set[str]] = {
    ROLE_SUPER_ADMIN: set(VALID_ROLES),
    ROLE_ADMIN: {ROLE_SALES, ROLE_SEO_ANALYST},
}


def can_manage_role(manager_role: str, target_role: str) -> bool:
    """True when a user with manager_role may create or manage an account with target_role."""
    return target_role in MANAGEABLE_ROLES.get(manager_role, set())


def has_permission(role: str, permission: str) -> bool:
    """Check if the given role possesses the specified permission."""
    if role == ROLE_SUPER_ADMIN:
        return True
    perms = ROLE_PERMISSIONS.get(role, set())
    return permission in perms


def get_role_permissions(role: str) -> List[str]:
    """Return all granted permissions for a role as a sorted list."""
    if role == ROLE_SUPER_ADMIN:
        all_perms: Set[str] = set()
        for p in ROLE_PERMISSIONS.values():
            all_perms.update(p)
        return sorted(list(all_perms))
    return sorted(list(ROLE_PERMISSIONS.get(role, set())))


def require_permission(permission: str):
    """
    FastAPI dependency factory enforcing that the authenticated user possesses
    the requested permission. Returns the authenticated user or raises 403 Forbidden.
    """
    from .security import get_current_admin  # lazy import to avoid circular dependency

    def dependency(current_user=Depends(get_current_admin)):
        # Verify account status
        status = getattr(current_user, "status", STATUS_ACTIVE)
        if status == STATUS_SUSPENDED:
            raise HTTPException(
                status_code=403,
                detail="Your account has been suspended by an administrator."
            )
        if status == STATUS_DEACTIVATED:
            raise HTTPException(
                status_code=403,
                detail="Your account has been deactivated."
            )
        if status == STATUS_INVITED:
            raise HTTPException(
                status_code=403,
                detail="Your account invitation has not been completed."
            )
        if status != STATUS_ACTIVE:
            raise HTTPException(
                status_code=403,
                detail="Your account is not active."
            )

        role = getattr(current_user, "role", ROLE_ADMIN)
        if not has_permission(role, permission):
            raise HTTPException(
                status_code=403,
                detail=f"Access forbidden: requires permission '{permission}'."
            )
        return current_user

    return dependency


def require_roles(*roles: str):
    """
    FastAPI dependency factory enforcing that the authenticated user has one of the specified roles.
    SUPER_ADMIN always satisfies the requirement.
    """
    from .security import get_current_admin

    def dependency(current_user=Depends(get_current_admin)):
        status = getattr(current_user, "status", STATUS_ACTIVE)
        if status != STATUS_ACTIVE:
            raise HTTPException(
                status_code=403,
                detail="Account is inactive or suspended."
            )
        user_role = getattr(current_user, "role", ROLE_ADMIN)
        if user_role == ROLE_SUPER_ADMIN or user_role in roles:
            return current_user

        raise HTTPException(
            status_code=403,
            detail=f"Access forbidden: requires one of roles [{', '.join(roles)}]."
        )

    return dependency
