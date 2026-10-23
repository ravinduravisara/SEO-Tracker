"""
eSupport SEO • Database Seeder Module
Provides realistic, comprehensive demo and initial seed data for:
  - Admin Users (SUPER_ADMIN, ADMIN, SALES, SEO_ANALYST)
  - Team Invitations
  - Clients & Websites
  - Real Audits & Spec-Compliant Scoring (ruleset 1.0.0)
  - Public Client Reports with live tokens and frozen snapshots
  - CRM Leads & Discussion Notes across pipeline stages
  - Platform Activity Logs & Public Scans

Supports both MySQL (from .env DATABASE_URL) and SQLite.
Can be executed as:
    python -m backend.seed [--reset] [--verbose]
    python scripts/seed_db.py [--reset] [--verbose]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import secrets
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.orm import Session
from backend.database import (
    SessionLocal,
    Base,
    engine,
    AdminUser,
    AdminSession,
    TeamInvitation,
    ActivityLog,
    Client,
    Website,
    Audit,
    PublicReport,
    SEOLead,
    LeadNote,
    PublicScan,
    init_db
)
from backend.security import hash_password
from backend.rbac import ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_SALES, ROLE_SEO_ANALYST, STATUS_ACTIVE
from backend.seo_engine import run_engine, RULESET_VERSION
from backend.report_service import build_client_report_snapshot

logger = logging.getLogger("esupport_seeder")
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


# =====================================================================
# 1. ADMIN USERS SEED DATA
# =====================================================================
DEMO_ADMIN_USERS = [
    {
        "email": "prasad@esupport.live",
        "name": "Prasad (Super Admin)",
        "role": ROLE_SUPER_ADMIN,
        "password": "eSupport@SEO2026!Admin",
        "status": STATUS_ACTIVE,
    },
    {
        "email": "alice.admin@esupport.live",
        "name": "Alice Admin",
        "role": ROLE_ADMIN,
        "password": "AdminPassword2026!",
        "status": STATUS_ACTIVE,
    },
    {
        "email": "sam.sales@esupport.live",
        "name": "Sam Sales",
        "role": ROLE_SALES,
        "password": "SalesPassword2026!",
        "status": STATUS_ACTIVE,
    },
    {
        "email": "arthur.analyst@esupport.live",
        "name": "Arthur Analyst",
        "role": ROLE_SEO_ANALYST,
        "password": "AnalystPassword2026!",
        "status": STATUS_ACTIVE,
    },
]


def seed_admin_users(db: Session, force: bool = False, verbose: bool = True) -> int:
    """Seed default admin users across all 4 RBAC roles."""
    created_count = 0
    for u in DEMO_ADMIN_USERS:
        existing = db.query(AdminUser).filter(AdminUser.email == u["email"]).first()
        if not existing:
            user = AdminUser(
                email=u["email"],
                name=u["name"],
                role=u["role"],
                status=u["status"],
                password_hash=hash_password(u["password"]),
                last_login_at=datetime.utcnow() - timedelta(hours=2),
                created_at=datetime.utcnow() - timedelta(days=30),
            )
            db.add(user)
            created_count += 1
            if verbose:
                logger.info(f"  [+] Created User: {u['email']} ({u['role']})")
        elif force:
            existing.name = u["name"]
            existing.role = u["role"]
            existing.status = u["status"]
            existing.password_hash = hash_password(u["password"])
            if verbose:
                logger.info(f"  [*] Updated User: {u['email']} ({u['role']})")
    db.commit()
    return created_count


# =====================================================================
# 2. TEAM INVITATIONS SEED DATA
# =====================================================================
DEMO_INVITATIONS = [
    {
        "email": "devops@esupport.live",
        "name": "DevOps Lead",
        "role": ROLE_ADMIN,
        "raw_token": "inv_demo_devops_token_2026",
    },
    {
        "email": "content@esupport.live",
        "name": "Content Specialist",
        "role": ROLE_SEO_ANALYST,
        "raw_token": "inv_demo_content_token_2026",
    },
]


def seed_team_invitations(db: Session, force: bool = False, verbose: bool = True) -> int:
    """Seed sample pending invitations."""
    inviter = db.query(AdminUser).filter(AdminUser.role == ROLE_SUPER_ADMIN).first()
    inviter_id = inviter.id if inviter else None

    created_count = 0
    for inv in DEMO_INVITATIONS:
        existing = db.query(TeamInvitation).filter(TeamInvitation.email == inv["email"]).first()
        if not existing:
            token_hash = hashlib.sha256(inv["raw_token"].encode("utf-8")).hexdigest()
            item = TeamInvitation(
                email=inv["email"],
                name=inv["name"],
                role=inv["role"],
                token_hash=token_hash,
                expires_at=datetime.utcnow() + timedelta(days=7),
                invited_by_id=inviter_id,
                created_at=datetime.utcnow() - timedelta(days=1),
            )
            db.add(item)
            created_count += 1
            if verbose:
                logger.info(f"  [+] Created Invitation for: {inv['email']} ({inv['role']})")
    db.commit()
    return created_count


# =====================================================================
# 3. CLIENTS & WEBSITES SEED DATA
# =====================================================================
DEMO_CLIENTS_AND_SITES = [
    {
        "client": {
            "name": "Nattandiya Electricals",
            "company": "Nattandiya Electricals (Pvt) Ltd",
            "email": "nattandiyaelectricals@gmail.com",
            "phone": "+94 76 003 9961",
            "status": "ACTIVE",
        },
        "website": {
            "url": "https://nattandiyaelectricals.lk/",
            "name": "Nattandiya Electricals Online",
            "status": "ACTIVE",
        },
        "target_url": "https://nattandiyaelectricals.lk/",
        "report_token": "rpt_nattandiya_2026",
    },
    {
        "client": {
            "name": "VideoClay Global",
            "company": "VideoClay Inc",
            "email": "hello@videoclay.com",
            "phone": "+94 77 865 8921",
            "status": "ACTIVE",
        },
        "website": {
            "url": "https://www.videoclay.com/",
            "name": "VideoClay Marketplace",
            "status": "ACTIVE",
        },
        "target_url": "https://www.videoclay.com/",
        "report_token": "rpt_videoclay_2026",
    },
    {
        "client": {
            "name": "Curve Ahangama",
            "company": "Curve Boutique Surf Resort & Cafe",
            "email": "stay@curveahangama.com",
            "phone": "+94 77 123 4567",
            "status": "ACTIVE",
        },
        "website": {
            "url": "https://curveahangama.com/",
            "name": "Curve Ahangama Hotel",
            "status": "ACTIVE",
        },
        "target_url": "https://curveahangama.com/",
        "report_token": "rpt_curve_2026",
    },
    {
        "client": {
            "name": "Meta Computers",
            "company": "Meta Computers Retail LK",
            "email": "sales@metacomputers.lk",
            "phone": "+94 11 234 5678",
            "status": "ACTIVE",
        },
        "website": {
            "url": "https://metacomputers.lk/",
            "name": "Meta Computers PC Store",
            "status": "ACTIVE",
        },
        "target_url": "https://metacomputers.lk/",
        "report_token": "rpt_metacomputers_2026",
    },
    {
        "client": {
            "name": "Apex Dynamics Ltd",
            "company": "Apex Dynamics Ltd",
            "email": "jane@apexdynamics.example",
            "phone": "+94 11 765 4321",
            "status": "ACTIVE",
        },
        "website": {
            "url": "https://apexdynamics.example/",
            "name": "Apex Dynamics Enterprise Solutions",
            "status": "ACTIVE",
        },
        "target_url": "https://apexdynamics.example/",
        "report_token": "rpt_apexdynamics_2026",
    },
]


def seed_clients_and_websites(db: Session, force: bool = False, verbose: bool = True) -> tuple[int, int]:
    """Seed clients and their associated websites."""
    clients_created = 0
    websites_created = 0

    for item in DEMO_CLIENTS_AND_SITES:
        c_data = item["client"]
        w_data = item["website"]

        client = db.query(Client).filter(Client.email == c_data["email"]).first()
        if not client:
            client = Client(
                name=c_data["name"],
                company=c_data["company"],
                email=c_data["email"],
                phone=c_data["phone"],
                status=c_data["status"],
                created_at=datetime.utcnow() - timedelta(days=20),
            )
            db.add(client)
            db.flush()
            clients_created += 1
            if verbose:
                logger.info(f"  [+] Created Client: {client.name} (id={client.id})")
        elif force:
            client.name = c_data["name"]
            client.company = c_data["company"]
            client.phone = c_data["phone"]
            client.status = c_data["status"]

        website = db.query(Website).filter(Website.url == w_data["url"]).first()
        if not website:
            website = Website(
                client_id=client.id,
                url=w_data["url"],
                name=w_data["name"],
                status=w_data["status"],
                created_at=datetime.utcnow() - timedelta(days=20),
            )
            db.add(website)
            db.flush()
            websites_created += 1
            if verbose:
                logger.info(f"  [+] Created Website: {website.url} (client_id={client.id})")
        else:
            if website.client_id != client.id:
                website.client_id = client.id

    db.commit()
    return clients_created, websites_created


# =====================================================================
# 4. AUDITS & SPEC-COMPLIANT REPORTS SEED DATA
# =====================================================================
def _build_synthetic_audit(target_url: str, profile: str = "general") -> dict[str, Any]:
    """Construct an authentic, spec-compliant audit dataset with realistic pages."""
    domain = urlparse(target_url).netloc
    
    if "nattandiya" in target_url:
        pages = [
            {
                "url": f"{target_url}",
                "status": 200,
                "title": "Buy Electrical Items Online | Nattandiya Electricals",
                "meta_description": "Buy Electrical Items Online In Sri Lanka from Nattandiya Electricals. Switches, sockets, cables, breakers and lighting with islandwide cash on delivery.",
                "h1": [],
                "heading_order": [{"tag": "h6", "text": "Site Navigation"}, {"tag": "h4", "text": "+94 76 00 399 61"}],
                "word_count": 6988,
                "editorial_word_count": 45,
                "viewport": "width=device-width, initial-scale=1.0, maximum-scale=1",
                "canonical": f"{target_url}",
                "og": {"og:title": "Buy Electrical Items Online | Nattandiya Electricals", "og:description": "Online store", "og:image": f"{target_url}logo.png", "og:url": target_url, "og:locale": "en_US"},
                "images": [{"src": f"{target_url}slider1.jpg", "alt": "bacola"}, {"src": f"{target_url}slider2.jpg", "alt": "rgdfrg"}]
            },
            {
                "url": f"{target_url}shop/",
                "status": 200,
                "title": "Buy Electrical Items & Home Appliances Online In Sri Lanka | Nattandiya Electricals",
                "meta_description": "Browse our full catalogue of electrical items and home appliances in Sri Lanka with prices.",
                "h1": [],
                "heading_order": [{"tag": "h6", "text": "Site Navigation"}],
                "word_count": 1126,
                "editorial_word_count": 0,
                "canonical": f"{target_url}shop/",
                "og": {"og:title": "Shop", "og:url": f"{target_url}shop/product-1/"}
            },
            {
                "url": f"{target_url}product-category/switches-sockets/",
                "status": 200,
                "title": "Switches & Sockets - Nattandiya Electricals",
                "meta_description": "Switches and sockets in Sri Lanka.",
                "h1": [],
                "word_count": 800,
                "editorial_word_count": 0,
                "canonical": f"{target_url}product-category/switches-sockets/",
                "og": {"og:title": "Switches", "og:url": f"{target_url}shop/switch-1/"}
            },
            {
                "url": f"{target_url}product-category/geyzer/",
                "status": 200,
                "title": "Geyzer (Bathroom Water Heater) - Nattandiya Electricals",
                "meta_description": "Delmege geysers in Sri Lanka with warranty and islandwide delivery.",
                "h1": [],
                "word_count": 450,
                "editorial_word_count": 59,
                "canonical": f"{target_url}product-category/geyzer/"
            },
            {
                "url": f"{target_url}product-category/uncategorized/",
                "status": 200,
                "title": "Uncategorized - Nattandiya Electricals",
                "meta_description": "",
                "h1": [],
                "word_count": 300,
                "editorial_word_count": 0,
                "canonical": f"{target_url}product-category/uncategorized/"
            },
            {
                "url": f"{target_url}brand/kevilton/",
                "status": 200,
                "title": "Kevilton Archives - Nattandiya Electricals",
                "meta_description": "Kevilton brand electrical items.",
                "h1": [],
                "word_count": 600,
                "editorial_word_count": 129,
                "canonical": f"{target_url}brand/kevilton/"
            },
            {
                "url": f"{target_url}shop/1-gang-1-way-switch-kevilton-nature/",
                "status": 200,
                "title": "Best 1 Gang 1 Way Switch - Kevilton Nature",
                "meta_description": "Kevilton Nature 1 gang 1 way switch with SLS 1000 standard and lifetime warranty.",
                "h1": ["1 Gang 1 Way Switch Kevilton Nature"],
                "heading_order": [{"tag": "h1", "text": "1 Gang 1 Way Switch"}, {"tag": "h2", "text": "Description"}],
                "word_count": 65,
                "editorial_word_count": 65,
                "prose_word_count": 0,
                "canonical": f"{target_url}shop/1-gang-1-way-switch-kevilton-nature/",
                "commerce_signals": {"has_availability": True, "has_reviews": False}
            },
            {
                "url": f"{target_url}shop/rcd-alpha-2-pole-40a-30m/",
                "status": 200,
                "title": "Best RCD Alpha 2 Pole 40A",
                "meta_description": "RCD Alpha 2 pole 40A 30mA protection device IEC 60898.",
                "h1": ["RCD Alpha 2 Pole 40A 30mA"],
                "word_count": 60,
                "editorial_word_count": 60,
                "prose_word_count": 0,
                "canonical": f"{target_url}shop/rcd-alpha-2-pole-40a-30m/",
                "commerce_signals": {"has_availability": True, "has_reviews": False}
            },
            {
                "url": f"{target_url}about-us/",
                "status": 200,
                "title": "Nattandiya Electricals | Buy Quality Electrical Items In Sri Lanka",
                "meta_description": "About Nattandiya Electricals Kuliyapitiya Road showroom.",
                "h1": [],
                "word_count": 580,
                "editorial_word_count": 580,
                "canonical": f"{target_url}about-us/"
            },
            {
                "url": f"{target_url}contact/",
                "status": 200,
                "title": "Contact Us - Nattandiya Electricals",
                "meta_description": "Contact Nattandiya Electricals.",
                "h1": ["Get In Touch"],
                "word_count": 350,
                "editorial_word_count": 200,
                "canonical": f"{target_url}contact/",
                "links": [
                    {"u": "tel:6031112298", "t": "+94 76 00 399 61 Call us (mobile /whatsapp)", "z": "body"},
                    {"u": "mailto:nattandiyaelectricals@gmail.com", "t": "email us", "z": "body"}
                ]
            },
            {
                "url": f"{target_url}blog/",
                "status": 200,
                "title": "Blog - Nattandiya Electricals",
                "meta_description": "",
                "h1": [],
                "word_count": 400,
                "editorial_word_count": 100,
                "canonical": f"{target_url}blog/"
            },
            {
                "url": f"{target_url}things-to-know-before-getting-a-quotation/",
                "status": 200,
                "title": "8 Key Points to Know Before Getting a Quotation for Your Wiring",
                "meta_description": "Wiring quotation checklist.",
                "h1": ["Point 1", "Point 2", "Point 3", "Point 4", "Point 5", "Point 6", "Point 7", "Point 8"],
                "word_count": 950,
                "editorial_word_count": 950,
                "canonical": f"{target_url}things-to-know-before-getting-a-quotation/"
            },
            {
                "url": f"{target_url}privacy-policy/",
                "status": 200,
                "title": "Privacy Policy - Nattandiya Electricals",
                "meta_description": "",
                "h1": ["Privacy Policy"],
                "word_count": 800,
                "editorial_word_count": 600,
                "canonical": f"{target_url}privacy-policy/"
            }
        ]
        sitemap_set = [f"{target_url}cart/", f"{target_url}checkout/", f"{target_url}my-account/"]
    elif "videoclay" in target_url:
        pages = [
            {
                "url": f"{target_url}",
                "status": 200,
                "title": "VideoClay - Drag & Drop Video Templates, MOGRTs & Audio. No Plugins",
                "meta_description": "After Effects templates, Premiere Pro MOGRTs, motion graphics and music with no plugins required.",
                "h1": ["Drag. Drop. Done."],
                "word_count": 700,
                "editorial_word_count": 550,
                "viewport": "width=device-width, initial-scale=1.0",
                "canonical": "https://videoclay.com/",
                "og": {"og:title": "VideoClay", "og:image": f"{target_url}images/videoclay_logo.svg", "og:url": "https://videoclay.com/", "og:locale": "en_US"}
            },
            {
                "url": f"{target_url}after-effects",
                "status": 200,
                "title": "After Effects - VideoClay",
                "meta_description": "Browse After Effects templates and lower thirds.",
                "h1": ["After Effects"],
                "word_count": 35,
                "editorial_word_count": 35,
                "canonical": f"{target_url}after-effects",
                "og": {"og:title": "After Effects", "og:url": f"{target_url}after-effects"}
            },
            {
                "url": f"{target_url}mogrt",
                "status": 200,
                "title": "MOGRT - VideoClay",
                "meta_description": "Premiere Pro MOGRT templates for motion graphics.",
                "h1": ["MOGRT"],
                "word_count": 30,
                "editorial_word_count": 30,
                "canonical": f"{target_url}mogrt"
            },
            {
                "url": f"{target_url}pricing",
                "status": 200,
                "title": "Pricing",
                "meta_description": "Unlimited downloads for $5/mo billed $60/yr.",
                "h1": ["Unlock your creative potential"],
                "word_count": 700,
                "editorial_word_count": 600,
                "canonical": "https://videoclay.com/pricing"
            },
            {
                "url": f"{target_url}learn",
                "status": 200,
                "title": "Videoclay Tutorials",
                "meta_description": "Learn After Effects and Premiere Pro editing tutorials.",
                "h1": ["Learn Video Editing", "Featured Tutorials"],
                "word_count": 450,
                "editorial_word_count": 400,
                "canonical": f"{target_url}learn"
            }
        ]
        sitemap_set = []
    else:
        # Standard high-quality corporate / local site
        pages = [
            {
                "url": f"{target_url}",
                "status": 200,
                "title": f"{domain.capitalize()} | Premium Solutions & Experience",
                "meta_description": f"Official website of {domain}. Explore our curated products, local services and expert guides.",
                "h1": [f"Welcome to {domain.capitalize()}"],
                "word_count": 920,
                "editorial_word_count": 820,
                "viewport": "width=device-width, initial-scale=1.0",
                "canonical": target_url,
                "og": {"og:title": domain.capitalize(), "og:url": target_url, "og:locale": "en_US"}
            },
            {
                "url": f"{target_url}services/",
                "status": 200,
                "title": f"Services & Offerings - {domain.capitalize()}",
                "meta_description": f"Complete service catalog and pricing details for {domain}.",
                "h1": ["Our Services"],
                "word_count": 680,
                "editorial_word_count": 600,
                "canonical": f"{target_url}services/"
            },
            {
                "url": f"{target_url}about/",
                "status": 200,
                "title": f"About Us - {domain.capitalize()}",
                "meta_description": f"Learn about the history, expertise and mission of {domain}.",
                "h1": ["About Our Company"],
                "word_count": 750,
                "editorial_word_count": 700,
                "canonical": f"{target_url}about/"
            },
            {
                "url": f"{target_url}contact/",
                "status": 200,
                "title": f"Contact Us - {domain.capitalize()}",
                "meta_description": f"Get in touch with the team at {domain}.",
                "h1": ["Contact Us"],
                "word_count": 320,
                "editorial_word_count": 280,
                "canonical": f"{target_url}contact/",
                "links": [{"u": f"mailto:info@{domain}", "t": f"info@{domain}", "z": "body"}]
            }
        ]
        sitemap_set = []

    return {
        "target": target_url,
        "product": "esupport_seo_crawler",
        "version": "10.4",
        "page_count": len(pages),
        "pages_crawled": len(pages),
        "pages": pages,
        "sitemap": {
            "detected": f"{target_url}sitemap_index.xml",
            "urls": [p["url"] for p in pages],
            "files": [{"url": f"{target_url}sitemap_index.xml", "status": 200}]
        },
        "sitemap_set": sitemap_set,
        "robots": {
            "found": True,
            "url": f"{target_url}robots.txt",
            "content": f"User-agent: *\nDisallow: /wp-admin/\nAllow: /wp-admin/admin-ajax.php\nSitemap: {target_url}sitemap_index.xml",
            "googlebot_allows_root": True,
            "sitemaps": [f"{target_url}sitemap_index.xml"]
        },
        "probes": {
            "probes": [{"control": True, "url": f"{target_url}non-existent-probe-check", "status": 404, "final_url": f"{target_url}non-existent-probe-check"}]
        },
        "stats": {
            "broken_links": 0,
            "load_time": 1.2,
        }
    }


def seed_audits_and_reports(db: Session, force: bool = False, verbose: bool = True) -> tuple[int, int]:
    """Seed high-fidelity audits and public client reports."""
    audits_seeded = 0
    reports_seeded = 0

    for item in DEMO_CLIENTS_AND_SITES:
        target_url = item["target_url"]
        report_token = item["report_token"]
        c_data = item["client"]

        client = db.query(Client).filter(Client.email == c_data["email"]).first()
        website = db.query(Website).filter(Website.url == item["website"]["url"]).first()

        # Find any existing audit for this target URL
        audit = db.query(Audit).filter(Audit.target_url == target_url).order_by(Audit.id.desc()).first()

        if audit and audit.result_json:
            try:
                audit_dict = json.loads(audit.result_json)
            except Exception:
                audit_dict = _build_synthetic_audit(target_url)
        else:
            audit_dict = _build_synthetic_audit(target_url)

        # Ensure spec engine computes exact score
        engine_payload = run_engine(audit_dict)
        score_val = engine_payload.get("score", {}).get("overall", 65.0)
        audit_dict["seo_engine"] = engine_payload
        audit_dict["score"] = score_val

        if not audit:
            audit = Audit(
                client_id=client.id if client else None,
                website_id=website.id if website else None,
                job_id=f"job_seed_{secrets.token_hex(6)}",
                status="COMPLETED",
                target_url=target_url,
                result_json=json.dumps(audit_dict),
                score=float(score_val),
                progress_json=json.dumps({"phase": "complete", "percent": 100}),
                created_at=datetime.utcnow() - timedelta(days=2),
                completed_at=datetime.utcnow() - timedelta(days=2),
            )
            db.add(audit)
            db.flush()
            audits_seeded += 1
            if verbose:
                logger.info(f"  [+] Created Audit for {target_url}: Score {score_val} ({engine_payload.get('score', {}).get('grade')})")
        else:
            # Update client & website relations and calibrated score
            audit.client_id = client.id if client else audit.client_id
            audit.website_id = website.id if website else audit.website_id
            audit.score = float(score_val)
            audit.result_json = json.dumps(audit_dict)
            if verbose:
                logger.info(f"  [*] Updated Audit #{audit.id} for {target_url}: Score {score_val} ({engine_payload.get('score', {}).get('grade')})")

        # Now build frozen client report snapshot
        snapshot = build_client_report_snapshot(
            audit=audit_dict,
            client_name=c_data["name"],
            company=c_data["company"],
            token=report_token,
        )

        pub_rep = db.query(PublicReport).filter(PublicReport.token == report_token).first()
        if not pub_rep:
            pub_rep = PublicReport(
                client_id=client.id if client else None,
                website_id=website.id if website else None,
                audit_id=audit.id,
                token=report_token,
                status="PUBLISHED",
                snapshot_json=json.dumps(snapshot),
                created_at=datetime.utcnow() - timedelta(days=2),
                published_at=datetime.utcnow() - timedelta(days=2),
            )
            db.add(pub_rep)
            reports_seeded += 1
            if verbose:
                logger.info(f"  [+] Created Public Report: token={report_token} (URL: /report/{report_token})")
        else:
            pub_rep.client_id = client.id if client else pub_rep.client_id
            pub_rep.website_id = website.id if website else pub_rep.website_id
            pub_rep.audit_id = audit.id
            pub_rep.status = "PUBLISHED"
            pub_rep.snapshot_json = json.dumps(snapshot)
            if verbose:
                logger.info(f"  [*] Updated Public Report: token={report_token}")

    db.commit()
    return audits_seeded, reports_seeded


# =====================================================================
# 5. SALES LEADS & CRM NOTES SEED DATA
# =====================================================================
DEMO_LEADS = [
    {
        "name": "Kasun Perera",
        "company": "Lanka Solar Mart",
        "email": "kasun@lankasolarmart.lk",
        "phone": "+94 77 456 7890",
        "website": "https://lankasolarmart.lk",
        "initial_score": 54.0,
        "status": "NEW",
        "source": "public_checker",
        "message": "Hi, we recently launched our e-commerce site for solar inverters and panels. Need help ranking on Google Sri Lanka.",
        "timeline": [
            {"event": "Lead Created", "timestamp": (datetime.utcnow() - timedelta(hours=3)).isoformat(), "note": "Initial SEO Score: 54.0/100"}
        ],
        "notes": []
    },
    {
        "name": "Nuwan Senanayake",
        "company": "Ceylon Fresh Teas",
        "email": "nuwan@ceylonfreshtea.example",
        "phone": "+94 71 888 9900",
        "website": "https://ceylonfreshtea.example",
        "initial_score": 48.0,
        "status": "NEW",
        "source": "public_checker",
        "message": "Interested in exporting tea to Europe and Australia. Low international visibility right now.",
        "timeline": [
            {"event": "Lead Created", "timestamp": (datetime.utcnow() - timedelta(hours=8)).isoformat(), "note": "Initial SEO Score: 48.0/100"}
        ],
        "notes": []
    },
    {
        "name": "Dilshan Fernando",
        "company": "Ceylon Spices Direct",
        "email": "dilshan@ceylonspices.example",
        "phone": "+94 76 555 4321",
        "website": "https://ceylonspices.example",
        "initial_score": 62.0,
        "status": "CONTACTED",
        "source": "whatsapp_inbound",
        "message": "We have 40+ products with wholesale prices. Looking for an SEO retainer plan.",
        "timeline": [
            {"event": "Lead Created", "timestamp": (datetime.utcnow() - timedelta(days=2)).isoformat(), "note": "Contacted via WhatsApp"},
            {"event": "Sales Outreach", "timestamp": (datetime.utcnow() - timedelta(days=1)).isoformat(), "note": "Sam sent executive audit summary and scheduled discovery call"}
        ],
        "notes": [
            {"author_name": "Sam Sales", "author_email": "sam.sales@esupport.live", "note": "Called Dilshan. Very keen on e-commerce product schema and international keywords. Follow-up call set for Thursday 3 PM."}
        ]
    },
    {
        "name": "Chaminda Silva",
        "company": "Nattandiya Electricals",
        "email": "nattandiyaelectricals@gmail.com",
        "phone": "+94 76 003 9961",
        "website": "https://nattandiyaelectricals.lk/",
        "initial_score": 66.0,
        "status": "QUALIFIED",
        "source": "audit_consultation",
        "message": "Need developer guidance on fixing wrong contact phone link, missing H1s, and writing category copy.",
        "timeline": [
            {"event": "Lead Created", "timestamp": (datetime.utcnow() - timedelta(days=5)).isoformat(), "note": "Initial SEO Score: 66/100 (Needs Improvement)"},
            {"event": "Audit Delivered", "timestamp": (datetime.utcnow() - timedelta(days=4)).isoformat(), "note": "Full 30-section audit report delivered with potential score +21 pts"},
            {"event": "Qualified", "timestamp": (datetime.utcnow() - timedelta(days=2)).isoformat(), "note": "Client approved proposal for Quick Wins + Category Content revamp"}
        ],
        "notes": [
            {"author_name": "Arthur Analyst", "author_email": "arthur.analyst@esupport.live", "note": "Audit shows 1,090 products already indexed cleanly by Rank Math. Immediate wins: fix tel link (15m), H1 headings (1.5h), and move Delivery terms out of Privacy Policy."},
            {"author_name": "Sam Sales", "author_email": "sam.sales@esupport.live", "note": "Presented 1-4 Week SEO Roadmap. Store owner Chaminda agrees to start Phase 1 this week."}
        ]
    },
    {
        "name": "Dinesh Jayawardena",
        "company": "Meta Computers",
        "email": "sales@metacomputers.lk",
        "phone": "+94 11 234 5678",
        "website": "https://metacomputers.lk/",
        "initial_score": 85.0,
        "status": "CONVERTED",
        "source": "referral",
        "message": "Existing customer upgrading to ongoing monthly technical SEO & PageSpeed optimization.",
        "timeline": [
            {"event": "Lead Created", "timestamp": (datetime.utcnow() - timedelta(days=15)).isoformat(), "note": "Referred by partner agency"},
            {"event": "Converted", "timestamp": (datetime.utcnow() - timedelta(days=10)).isoformat(), "note": "Contract signed for 6-month SEO retainer"}
        ],
        "notes": [
            {"author_name": "Prasad (Super Admin)", "author_email": "prasad@esupport.live", "note": "Client converted to active monthly retainer. Assigned Arthur as lead analyst."}
        ]
    },
    {
        "name": "Suresh Mendis",
        "company": "Galle Villa Rentals",
        "email": "suresh@gallevillas.example",
        "phone": "+94 77 999 1122",
        "website": "https://gallevillas.example",
        "initial_score": 41.0,
        "status": "CLOSED",
        "source": "public_checker",
        "message": "Inquiry about hotel booking SEO.",
        "timeline": [
            {"event": "Lead Created", "timestamp": (datetime.utcnow() - timedelta(days=20)).isoformat(), "note": "Initial scan score: 41.0"},
            {"event": "Closed", "timestamp": (datetime.utcnow() - timedelta(days=7)).isoformat(), "note": "Client decided to postpone marketing till next season"}
        ],
        "notes": [
            {"author_name": "Sam Sales", "author_email": "sam.sales@esupport.live", "note": "Postponed marketing campaign until Q4 2026. Lead closed for now."}
        ]
    }
]


def seed_sales_leads_and_notes(db: Session, force: bool = False, verbose: bool = True) -> tuple[int, int]:
    """Seed CRM leads and discussion notes across the sales pipeline."""
    leads_created = 0
    notes_created = 0

    sales_user = db.query(AdminUser).filter(AdminUser.role == ROLE_SALES).first()
    sales_uid = sales_user.id if sales_user else None

    for item in DEMO_LEADS:
        lead = db.query(SEOLead).filter(SEOLead.email == item["email"]).first()
        if not lead:
            # Link converted leads to client if applicable
            client_id = None
            if item["status"] == "CONVERTED":
                c = db.query(Client).filter(Client.name.like(f"%{item['company']}%")).first()
                if c:
                    client_id = c.id

            lead = SEOLead(
                name=item["name"],
                company=item["company"],
                email=item["email"],
                phone=item["phone"],
                website=item["website"],
                initial_score=item["initial_score"],
                message=item["message"],
                status=item["status"],
                source=item["source"],
                client_id=client_id,
                timeline_json=json.dumps(item["timeline"]),
                created_at=datetime.utcnow() - timedelta(days=10),
            )
            db.add(lead)
            db.flush()
            leads_created += 1
            if verbose:
                logger.info(f"  [+] Created Lead: {lead.name} ({lead.status})")

            # Add notes
            for n in item.get("notes", []):
                note = LeadNote(
                    lead_id=lead.id,
                    user_id=sales_uid,
                    author_name=n["author_name"],
                    author_email=n["author_email"],
                    note=n["note"],
                    created_at=datetime.utcnow() - timedelta(days=1),
                )
                db.add(note)
                notes_created += 1
        elif force:
            lead.status = item["status"]
            lead.initial_score = item["initial_score"]

    db.commit()
    return leads_created, notes_created


# =====================================================================
# 6. ACTIVITY LOGS SEED DATA
# =====================================================================
DEMO_ACTIVITIES = [
    ("USER_LOGIN", "Authentication", "Super Admin signed in from office network", "prasad@esupport.live", "SUPER_ADMIN"),
    ("AUDIT_COMPLETED", "Audit (https://nattandiyaelectricals.lk/)", "Full site audit completed with score 66/100 (Needs Improvement)", "arthur.analyst@esupport.live", "SEO_ANALYST"),
    ("REPORT_PUBLISHED", "Public Report (rpt_nattandiya_2026)", "Published interactive client snapshot with 1-4 Week Roadmap", "arthur.analyst@esupport.live", "SEO_ANALYST"),
    ("AUDIT_COMPLETED", "Audit (https://www.videoclay.com/)", "Marketplace audit completed with score 63/100", "arthur.analyst@esupport.live", "SEO_ANALYST"),
    ("REPORT_PUBLISHED", "Public Report (rpt_videoclay_2026)", "Client snapshot published for VideoClay", "arthur.analyst@esupport.live", "SEO_ANALYST"),
    ("LEAD_STATUS_CHANGED", "Lead (Chaminda Silva)", "Lead updated from CONTACTED to QUALIFIED", "sam.sales@esupport.live", "SALES"),
    ("LEAD_NOTE_ADDED", "Lead (Chaminda Silva)", "Added notes regarding quick wins and 1-4 week roadmap approval", "sam.sales@esupport.live", "SALES"),
    ("CLIENT_CREATED", "Client (Nattandiya Electricals)", "New client profile created and linked to website", "prasad@esupport.live", "SUPER_ADMIN"),
    ("USER_INVITED", "Team (devops@esupport.live)", "One-time invitation token dispatched for ADMIN role", "prasad@esupport.live", "SUPER_ADMIN"),
    ("LEAD_CONVERTED", "Lead (Dinesh Jayawardena)", "Lead converted to active client Meta Computers Retail", "sam.sales@esupport.live", "SALES"),
]


def seed_activity_logs(db: Session, force: bool = False, verbose: bool = True) -> int:
    """Seed recent audit trail and user activity records."""
    logs_created = 0
    count = db.query(ActivityLog).count()
    if count >= len(DEMO_ACTIVITIES) and not force:
        return 0

    for action, resource, details, email, role in DEMO_ACTIVITIES:
        user = db.query(AdminUser).filter(AdminUser.email == email).first()
        log = ActivityLog(
            user_id=user.id if user else None,
            user_email=email,
            user_name=user.name if user else email,
            user_role=role,
            action=action,
            resource=resource,
            details=details,
            status="SUCCESS",
            ip_address="127.0.0.1",
            created_at=datetime.utcnow() - timedelta(hours=secrets.randbelow(48) + 1),
        )
        db.add(log)
        logs_created += 1
    db.commit()
    return logs_created


# =====================================================================
# 7. PUBLIC SCANS SEED DATA
# =====================================================================
DEMO_PUBLIC_SCANS = [
    ("https://nattandiyaelectricals.lk/", 66.0),
    ("https://www.videoclay.com/", 63.0),
    ("https://metacomputers.lk/", 85.0),
    ("https://curveahangama.com/", 78.0),
    ("https://lankasolarmart.lk/", 54.0),
    ("https://ceylonspices.example/", 62.0),
    ("https://gallevillas.example/", 41.0),
    ("https://ceylonfreshtea.example/", 48.0),
    ("https://serendibnews.net/", 60.0),
    ("https://holidaytuktuk.com/", 74.0),
    ("https://shwoah.com/", 67.0),
    ("https://voltedgepower-solutions.com/", 47.0),
]


def seed_public_scans(db: Session, force: bool = False, verbose: bool = True) -> int:
    """Seed historical scan counts for the landing page scanner stats."""
    created = 0
    existing_count = db.query(PublicScan).count()
    if existing_count >= len(DEMO_PUBLIC_SCANS) and not force:
        return 0

    for url, score in DEMO_PUBLIC_SCANS:
        scan = PublicScan(
            target_url=url,
            score=score,
            ip_address=f"192.168.1.{secrets.randbelow(200) + 10}",
            created_at=datetime.utcnow() - timedelta(days=secrets.randbelow(14)),
        )
        db.add(scan)
        created += 1
    db.commit()
    return created


# =====================================================================
# ORCHESTRATOR
# =====================================================================
def seed_all(db: Optional[Session] = None, reset: bool = False, verbose: bool = True) -> dict[str, Any]:
    """
    Run complete database seeding pipeline.
    If reset=True, clears demo records first while keeping schema intact.
    """
    close_db_when_done = False
    if db is None:
        init_db()
        db = SessionLocal()
        close_db_when_done = True

    try:
        if verbose:
            print("\n=======================================================")
            print("  eSupport SEO Platform • Comprehensive Database Seeder")
            print("=======================================================")
            print(f"Target Database: {db.bind.url}")
            print(f"Mode: {'RESET & SEED' if reset else 'SAFE APPEND / UPDATE'}\n")

        if reset:
            if verbose:
                logger.warning("Reset mode selected: clearing demo data tables...")
            db.query(LeadNote).delete()
            db.query(SEOLead).delete()
            db.query(PublicReport).delete()
            db.query(Audit).delete()
            db.query(Website).delete()
            db.query(Client).delete()
            db.query(TeamInvitation).delete()
            db.query(ActivityLog).delete()
            db.commit()

        u_count = seed_admin_users(db, force=reset, verbose=verbose)
        inv_count = seed_team_invitations(db, force=reset, verbose=verbose)
        c_count, w_count = seed_clients_and_websites(db, force=reset, verbose=verbose)
        a_count, r_count = seed_audits_and_reports(db, force=reset, verbose=verbose)
        l_count, n_count = seed_sales_leads_and_notes(db, force=reset, verbose=verbose)
        act_count = seed_activity_logs(db, force=reset, verbose=verbose)
        scan_count = seed_public_scans(db, force=reset, verbose=verbose)

        summary = {
            "admin_users": u_count,
            "team_invitations": inv_count,
            "clients": c_count,
            "websites": w_count,
            "audits": a_count,
            "public_reports": r_count,
            "seo_leads": l_count,
            "lead_notes": n_count,
            "activity_logs": act_count,
            "public_scans": scan_count,
        }

        if verbose:
            print("\n-------------------------------------------------------")
            print("  Seeding Complete Summary:")
            print("-------------------------------------------------------")
            for k, v in summary.items():
                print(f"  {k:<20}: {v:>4} seeded/updated")
            print("-------------------------------------------------------")
            print("  Ready Credentials:")
            print("    Super Admin : prasad@esupport.live     (eSupport@SEO2026!Admin)")
            print("    Admin       : alice.admin@esupport.live (AdminPassword2026!)")
            print("    Sales       : sam.sales@esupport.live   (SalesPassword2026!)")
            print("    SEO Analyst : arthur.analyst@esupport.live (AnalystPassword2026!)")
            print("\n  Public Reports Active:")
            print("    Nattandiya  : http://localhost:8000/report/rpt_nattandiya_2026 (Score 66)")
            print("    VideoClay   : http://localhost:8000/report/rpt_videoclay_2026   (Score 63)")
            print("    Meta PC     : http://localhost:8000/report/rpt_metacomputers_2026 (Score 85)")
            print("=======================================================\n")

        return summary
    finally:
        if close_db_when_done:
            db.close()


def main():
    parser = argparse.ArgumentParser(description="Seed eSupport SEO database with realistic demo and production data.")
    parser.add_argument("--reset", "-r", action="store_true", help="Clear existing records before seeding.")
    parser.add_argument("--quiet", "-q", action="store_true", help="Disable verbose logging.")
    args = parser.parse_args()

    seed_all(reset=args.reset, verbose=not args.quiet)


if __name__ == "__main__":
    main()
