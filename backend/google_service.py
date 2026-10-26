"""
Google Search Console, Analytics 4 & Performance Intelligence Engine (Phase 7)
Integrates authorized Google services, maintains per-client connection state,
strictly separates real-user Core Web Vitals from lab simulations, and exports multi-format reports.
"""

from __future__ import annotations

import io
import csv
import json
import logging
import math
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, Dict, List
from urllib.parse import urlparse

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, PageBreak
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas
from sqlalchemy.orm import Session

from . import integrations
from .database import Website, Client, SessionLocal

logger = logging.getLogger("aviance.google_service")


# -----------------------------------------------------------------------------
# PER-CLIENT CONNECTION STATUS VERIFIER
# -----------------------------------------------------------------------------

def check_google_connections(website: Website, db: Optional[Session] = None) -> Dict[str, Any]:
    """
    Test live connectivity for Google Search Console, Google Analytics 4,
    and Google PageSpeed Insights for a specific client website.
    Updates website.connection_status_json.
    """
    url = website.url
    domain = integrations.bare_domain(url)
    now_iso = datetime.now(timezone.utc).isoformat()

    # 1. Search Console Connection Check
    gsc_prop = website.gsc_property or ""
    gsc_status = "NOT_CONFIGURED"
    gsc_detail = "No Google service account configured."
    if integrations.gsc_configured():
        try:
            site = gsc_prop or integrations.gsc_match_property(url)
            if site:
                gsc_status = "CONNECTED"
                gsc_detail = f"Authorized on property '{site}'."
            else:
                email = integrations._gsc_info().get("client_email", "service account")
                gsc_status = "UNAUTHORIZED"
                gsc_detail = f"Property not found or unauthorized. Add {email} as a user in Search Console."
        except Exception as exc:
            gsc_status = "ERROR"
            gsc_detail = str(exc)

    # 2. GA4 Connection Check
    ga4_pid = website.ga4_property_id or integrations.GA4_PROPERTY_ID or ""
    ga4_status = "NOT_CONFIGURED"
    ga4_detail = "No GA4 property ID configured."
    if ga4_pid:
        if not integrations.gsc_configured():
            ga4_status = "REQUIRES_AUTH"
            ga4_detail = "GA4 property configured, but Google service account is missing."
        else:
            try:
                # Test query 1 day of traffic
                test_res = integrations.ga4(url, property_id=ga4_pid, days=3)
                if test_res.get("ok"):
                    ga4_status = "CONNECTED"
                    ga4_detail = f"Connected to GA4 Property #{ga4_pid}."
                else:
                    ga4_status = "UNAUTHORIZED" if "permission" in test_res.get("error", "").lower() else "ERROR"
                    ga4_detail = test_res.get("error", "Failed to query GA4 Data API.")
            except Exception as exc:
                ga4_status = "ERROR"
                ga4_detail = str(exc)

    # 3. PageSpeed & Core Web Vitals Status
    psi_status = "CONNECTED" if integrations.pagespeed_configured() else ("LOCAL_FALLBACK" if integrations.local_lighthouse_available() else "PUBLIC_QUOTA")
    psi_detail = (
        "Google PageSpeed Insights API Key active."
        if integrations.PAGESPEED_API_KEY
        else ("Local Lighthouse engine active." if integrations.local_lighthouse_available() else "Using Google PSI public quota.")
    )

    connection_data = {
        "website_id": website.id,
        "website_url": url,
        "target_domain": domain,
        "last_checked_at": now_iso,
        "search_console": {
            "status": gsc_status,
            "property": gsc_prop or (integrations.gsc_match_property(url) if gsc_status == "CONNECTED" else ""),
            "detail": gsc_detail,
            "is_connected": gsc_status == "CONNECTED"
        },
        "google_analytics_4": {
            "status": ga4_status,
            "property_id": ga4_pid,
            "detail": ga4_detail,
            "is_connected": ga4_status == "CONNECTED"
        },
        "pagespeed": {
            "status": psi_status,
            "detail": psi_detail,
            "is_connected": True
        },
        "bing_webmaster": {
            "status": "CONNECTED" if integrations.bing_configured() else "NOT_CONFIGURED",
            "detail": "Bing Webmaster Tools API Key active." if integrations.bing_configured() else "Set BING_API_KEY in .env.",
            "is_connected": integrations.bing_configured()
        },
        "ahrefs": {
            "status": "CONNECTED" if getattr(integrations, "ahrefs_configured", lambda: False)() else "NOT_CONFIGURED",
            "detail": "Ahrefs API v3 Token active." if getattr(integrations, "ahrefs_configured", lambda: False)() else "Set AHREFS_API_KEY in .env for official Domain Rating.",
            "is_connected": getattr(integrations, "ahrefs_configured", lambda: False)()
        },
        "openpagerank": {
            "status": "CONNECTED" if integrations.openpagerank_configured() else "NOT_CONFIGURED",
            "detail": "Open PageRank API active." if integrations.openpagerank_configured() else "Set OPENPAGERANK_API_KEY in .env.",
            "is_connected": integrations.openpagerank_configured()
        }
    }

    website.connection_status_json = json.dumps(connection_data)
    if db:
        try:
            db.commit()
        except Exception:
            db.rollback()

    return connection_data


# -----------------------------------------------------------------------------
# PERFORMANCE REPORT GENERATOR
# -----------------------------------------------------------------------------

def get_client_performance_report(
    website: Website,
    days: int = 28,
    db: Optional[Session] = None
) -> Dict[str, Any]:
    """
    Constructs comprehensive authorized performance telemetry for a client website:
    - Google Search Console: clicks, impressions, CTR, average position, top queries, top pages, devices, countries, date trends.
    - Google Analytics 4: sessions, users, engagement rate, average session duration, bounce rate, channels, landing pages.
    - Google PageSpeed & Core Web Vitals: real-user CrUX p75 field data vs Lighthouse lab scores.
    """
    url = website.url
    domain = integrations.bare_domain(url)
    connections = check_google_connections(website, db)

    # 1. Fetch Search Console
    gsc_prop = website.gsc_property or None
    gsc_res = integrations.search_console(url, days=days, property_url=gsc_prop)

    # 2. Fetch Google Analytics 4
    ga4_pid = website.ga4_property_id or None
    ga4_res = integrations.ga4(url, property_id=ga4_pid, days=days)

    # 3. Fetch PageSpeed & Core Web Vitals
    psi_mobile = integrations.pagespeed(url, strategy="mobile")
    psi_desktop = integrations.pagespeed(url, strategy="desktop")

    # Format CrUX Field Data (Real Users)
    field_mobile = psi_mobile.get("field") or {}
    field_desktop = psi_desktop.get("field") or {}

    field_summary = {
        "assessment": field_mobile.get("core_web_vitals_assessment") or field_desktop.get("core_web_vitals_assessment") or "insufficient data",
        "has_real_user_data": bool(field_mobile.get("metrics") or field_desktop.get("metrics")),
        "scope": field_mobile.get("scope") or "url",
        "mobile": field_mobile.get("metrics") or {},
        "desktop": field_desktop.get("metrics") or {}
    }

    # Format Lighthouse Lab Data (Simulated synthetic testing)
    lab_mobile = psi_mobile.get("lab") or {}
    lab_desktop = psi_desktop.get("lab") or {}
    lh_scores_mobile = psi_mobile.get("categories") or {}
    lh_scores_desktop = psi_desktop.get("categories") or {}

    lab_summary = {
        "mobile_score": lh_scores_mobile.get("performance"),
        "desktop_score": lh_scores_desktop.get("performance"),
        "mobile_lab": lab_mobile,
        "desktop_lab": lab_desktop,
        "categories_mobile": lh_scores_mobile,
        "categories_desktop": lh_scores_desktop
    }

    # Ranking disclaimer statement
    disclaimer = (
        "Google Search Console average position represents aggregated searcher impressions and geographic "
        "query distribution over time. It does not represent an exact live rank on any single user's device. "
        "Core Web Vitals field data represents real-user 75th percentile measurements over a 28-day collection period."
    )

    return {
        "ok": True,
        "website_id": website.id,
        "website_url": url,
        "target_domain": domain,
        "report_date": datetime.now(timezone.utc).isoformat(),
        "days": days,
        "disclaimer": disclaimer,
        "connections": connections,
        "search_console": {
            "is_connected": gsc_res.get("ok", False),
            "property": gsc_res.get("property"),
            "totals": gsc_res.get("totals") or {"clicks": 0, "impressions": 0, "ctr": 0.0, "position": 0.0},
            "top_queries": gsc_res.get("top_queries") or [],
            "top_pages": gsc_res.get("top_pages") or [],
            "devices": gsc_res.get("devices") or [],
            "countries": gsc_res.get("countries") or [],
            "dates": gsc_res.get("dates") or [],
            "error": gsc_res.get("error") if not gsc_res.get("ok") else None
        },
        "google_analytics_4": {
            "is_connected": ga4_res.get("ok", False),
            "property_id": ga4_res.get("property_id"),
            "totals": ga4_res.get("totals") or {
                "sessions": 0, "total_users": 0, "active_users": 0, "new_users": 0,
                "engagement_rate": 0.0, "average_session_duration": 0.0, "bounce_rate": 0.0
            },
            "channels": ga4_res.get("channels") or [],
            "top_pages": ga4_res.get("top_pages") or [],
            "countries": ga4_res.get("countries") or [],
            "error": ga4_res.get("error") if not ga4_res.get("ok") else None
        },
        "core_web_vitals_field": field_summary,
        "lighthouse_lab": lab_summary,
        "bing_webmaster": integrations.bing_webmaster(url),
        "ahrefs_domain_rating": integrations.ahrefs_domain_rating(url),
        "openpagerank": integrations.openpagerank(url),
    }


# -----------------------------------------------------------------------------
# MULTI-FORMAT EXPORTERS (CSV, EXCEL XML, VECTOR PDF)
# -----------------------------------------------------------------------------

def generate_performance_csv(report: Dict[str, Any]) -> str:
    """Generate structured RFC-4180 CSV export of Search Console and GA4 metrics."""
    out = io.StringIO()
    writer = csv.writer(out)

    target = report.get("target_domain", "")
    days = report.get("days", 28)
    gsc = report.get("search_console") or {}
    ga4 = report.get("google_analytics_4") or {}
    cwv = report.get("core_web_vitals_field") or {}
    lh = report.get("lighthouse_lab") or {}

    writer.writerow(["# GOOGLE SEARCH CONSOLE & ANALYTICS PERFORMANCE REPORT", target])
    writer.writerow(["Generated At", report.get("report_date", "")])
    writer.writerow(["Reporting Window", f"Last {days} Days"])
    writer.writerow(["Search Console Property", gsc.get("property") or "Not Connected"])
    writer.writerow(["GA4 Property ID", ga4.get("property_id") or "Not Connected"])
    writer.writerow([])

    # GSC Totals
    gsc_tot = gsc.get("totals") or {}
    writer.writerow(["# SEARCH CONSOLE EXECUTIVE TOTALS"])
    writer.writerow(["Clicks", gsc_tot.get("clicks", 0)])
    writer.writerow(["Impressions", gsc_tot.get("impressions", 0)])
    writer.writerow(["Click-Through Rate (CTR %)", f"{gsc_tot.get('ctr', 0)}%"])
    writer.writerow(["Average Search Position", gsc_tot.get("position", 0)])
    writer.writerow([])

    # GA4 Totals
    ga4_tot = ga4.get("totals") or {}
    writer.writerow(["# GOOGLE ANALYTICS 4 ENGAGEMENT TOTALS"])
    writer.writerow(["Sessions", ga4_tot.get("sessions", 0)])
    writer.writerow(["Total Users", ga4_tot.get("total_users", 0)])
    writer.writerow(["Active Users", ga4_tot.get("active_users", 0)])
    writer.writerow(["Engagement Rate (%)", f"{ga4_tot.get('engagement_rate', 0)}%"])
    writer.writerow(["Average Session Duration (s)", ga4_tot.get("average_session_duration", 0)])
    writer.writerow(["Bounce Rate (%)", f"{ga4_tot.get('bounce_rate', 0)}%"])
    writer.writerow([])

    # Core Web Vitals Field vs Lab
    writer.writerow(["# PERFORMANCE BENCHMARKS (FIELD VS LAB)"])
    writer.writerow(["Real-User Core Web Vitals Assessment", cwv.get("assessment", "insufficient data")])
    writer.writerow(["Lighthouse Mobile Performance Score", f"{lh.get('mobile_score', 'N/A')}/100"])
    writer.writerow(["Lighthouse Desktop Performance Score", f"{lh.get('desktop_score', 'N/A')}/100"])
    writer.writerow([])

    # Top Search Queries
    writer.writerow(["# TOP SEARCH QUERIES (GOOGLE SEARCH CONSOLE)"])
    writer.writerow(["Query", "Clicks", "Impressions", "CTR (%)", "Average Position"])
    for q in gsc.get("top_queries", [])[:100]:
        writer.writerow([q.get("query"), q.get("clicks"), q.get("impressions"), f"{q.get('ctr')}%", q.get("position")])
    writer.writerow([])

    # Traffic Acquisition Channels
    writer.writerow(["# TRAFFIC ACQUISITION CHANNELS (GA4)"])
    writer.writerow(["Channel Group", "Sessions", "Users"])
    for ch in ga4.get("channels", []):
        writer.writerow([ch.get("channel"), ch.get("sessions"), ch.get("users")])

    return out.getvalue()


def generate_performance_excel_xml(report: Dict[str, Any]) -> str:
    """Generate professional Microsoft Excel XML workbook with multiple worksheets."""
    target = report.get("target_domain", "")
    gsc = report.get("search_console") or {}
    ga4 = report.get("google_analytics_4") or {}
    cwv = report.get("core_web_vitals_field") or {}
    lh = report.get("lighthouse_lab") or {}

    def esc_xml(val: Any) -> str:
        s = str(val if val is not None else "")
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    xml = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<?mso-application progid="Excel.Sheet"?>',
        '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"',
        ' xmlns:o="urn:schemas-microsoft-com:office:office"',
        ' xmlns:x="urn:schemas-microsoft-com:office:excel"',
        ' xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"',
        ' xmlns:html="http://www.w3.org/TR/REC-html40">',
        ' <Styles>',
        '  <Style ss:ID="Header">',
        '   <Font ss:Bold="1" ss:Color="#FFFFFF"/>',
        '   <Interior ss:Color="#2563EB" ss:Pattern="Solid"/>',
        '   <Alignment ss:Horizontal="Center"/>',
        '  </Style>',
        '  <Style ss:ID="Bold"><Font ss:Bold="1"/></Style>',
        ' </Styles>',
    ]

    # Sheet 1: Executive Overview
    xml.append(' <Worksheet ss:Name="Overview">')
    xml.append('  <Table>')
    xml.append('   <Column ss:Width="240"/>')
    xml.append('   <Column ss:Width="260"/>')
    xml.append('   <Row ss:StyleID="Header"><Cell ss:MergeAcross="1"><Data ss:Type="String">Google Search Console &amp; Analytics Performance</Data></Cell></Row>')
    xml.append(f'   <Row><Cell ss:StyleID="Bold"><Data ss:Type="String">Target Domain</Data></Cell><Cell><Data ss:Type="String">{esc_xml(target)}</Data></Cell></Row>')
    xml.append(f'   <Row><Cell ss:StyleID="Bold"><Data ss:Type="String">Reporting Period</Data></Cell><Cell><Data ss:Type="String">Last {report.get("days", 28)} Days</Data></Cell></Row>')
    gsc_tot = gsc.get("totals") or {}
    xml.append(f'   <Row><Cell ss:StyleID="Bold"><Data ss:Type="String">Search Console Clicks</Data></Cell><Cell><Data ss:Type="Number">{gsc_tot.get("clicks", 0)}</Data></Cell></Row>')
    xml.append(f'   <Row><Cell ss:StyleID="Bold"><Data ss:Type="String">Search Console Impressions</Data></Cell><Cell><Data ss:Type="Number">{gsc_tot.get("impressions", 0)}</Data></Cell></Row>')
    xml.append(f'   <Row><Cell ss:StyleID="Bold"><Data ss:Type="String">Search Console Average CTR</Data></Cell><Cell><Data ss:Type="String">{esc_xml(gsc_tot.get("ctr", 0))}%</Data></Cell></Row>')
    xml.append(f'   <Row><Cell ss:StyleID="Bold"><Data ss:Type="String">Average Position</Data></Cell><Cell><Data ss:Type="Number">{gsc_tot.get("position", 0)}</Data></Cell></Row>')
    ga4_tot = ga4.get("totals") or {}
    xml.append(f'   <Row><Cell ss:StyleID="Bold"><Data ss:Type="String">GA4 Sessions</Data></Cell><Cell><Data ss:Type="Number">{ga4_tot.get("sessions", 0)}</Data></Cell></Row>')
    xml.append(f'   <Row><Cell ss:StyleID="Bold"><Data ss:Type="String">GA4 Total Users</Data></Cell><Cell><Data ss:Type="Number">{ga4_tot.get("total_users", 0)}</Data></Cell></Row>')
    xml.append(f'   <Row><Cell ss:StyleID="Bold"><Data ss:Type="String">GA4 Engagement Rate</Data></Cell><Cell><Data ss:Type="String">{esc_xml(ga4_tot.get("engagement_rate", 0))}%</Data></Cell></Row>')
    xml.append('  </Table>')
    xml.append(' </Worksheet>')

    # Sheet 2: GSC Queries
    xml.append(' <Worksheet ss:Name="Search Queries">')
    xml.append('  <Table>')
    xml.append('   <Row ss:StyleID="Header">')
    for col in ["Search Query", "Clicks", "Impressions", "CTR (%)", "Avg Position"]:
        xml.append(f'    <Cell><Data ss:Type="String">{col}</Data></Cell>')
    xml.append('   </Row>')
    for q in gsc.get("top_queries", []):
        xml.append('   <Row>')
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(q.get("query"))}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="Number">{q.get("clicks") or 0}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="Number">{q.get("impressions") or 0}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(q.get("ctr"))}%</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="Number">{q.get("position") or 0}</Data></Cell>')
        xml.append('   </Row>')
    xml.append('  </Table>')
    xml.append(' </Worksheet>')

    # Sheet 3: GA4 Channels
    xml.append(' <Worksheet ss:Name="Traffic Channels">')
    xml.append('  <Table>')
    xml.append('   <Row ss:StyleID="Header">')
    for col in ["Channel Group", "Sessions", "Users"]:
        xml.append(f'    <Cell><Data ss:Type="String">{col}</Data></Cell>')
    xml.append('   </Row>')
    for ch in ga4.get("channels", []):
        xml.append('   <Row>')
        xml.append(f'    <Cell><Data ss:Type="String">{esc_xml(ch.get("channel"))}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="Number">{ch.get("sessions") or 0}</Data></Cell>')
        xml.append(f'    <Cell><Data ss:Type="Number">{ch.get("users") or 0}</Data></Cell>')
        xml.append('   </Row>')
    xml.append('  </Table>')
    xml.append(' </Worksheet>')

    xml.append('</Workbook>')
    return "\n".join(xml)


class PerformanceReportCanvas(canvas.Canvas):
    """Two-pass ReportLab canvas for running headers, footers, and page numbers."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pages: List[Any] = []

    def showPage(self):
        self.pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total_pages = len(self.pages)
        for p in self.pages:
            self.__dict__.update(p)
            self.draw_header_footer(total_pages)
            super().showPage()
        super().save()

    def draw_header_footer(self, total_pages: int):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748B"))

        if self._pageNumber > 1:
            self.drawString(14 * mm, 287 * mm, "Google Search Console & Analytics Performance Report • eSupport SEO Platform")
            self.drawRightString(196 * mm, 287 * mm, datetime.now(timezone.utc).strftime("%B %d, %Y"))
            self.setStrokeColor(colors.HexColor("#E2E8F0"))
            self.setLineWidth(0.5)
            self.line(14 * mm, 285 * mm, 196 * mm, 285 * mm)

        # Footer
        self.setStrokeColor(colors.HexColor("#E2E8F0"))
        self.setLineWidth(0.5)
        self.line(14 * mm, 12 * mm, 196 * mm, 12 * mm)
        self.drawString(14 * mm, 8 * mm, "Enterprise Confidential • Authorized Google Telemetry • eSupport SEO v10.4.7")
        self.drawRightString(196 * mm, 8 * mm, f"Page {self._pageNumber} of {total_pages}")
        self.restoreState()


def generate_performance_pdf(report: Dict[str, Any]) -> bytes:
    """Generate executive-ready ReportLab vector PDF performance report."""
    target = report.get("target_domain", "")
    days = report.get("days", 28)
    gsc = report.get("search_console") or {}
    ga4 = report.get("google_analytics_4") or {}
    cwv = report.get("core_web_vitals_field") or {}
    lh = report.get("lighthouse_lab") or {}

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=15 * mm,
        bottomMargin=16 * mm
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "PerfTitle", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=colors.HexColor("#0F172A")
    )
    subtitle_style = ParagraphStyle(
        "PerfSubtitle", parent=styles["Normal"], fontName="Helvetica", fontSize=9, leading=13, textColor=colors.HexColor("#64748B")
    )
    section_title = ParagraphStyle(
        "PerfSection", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=12, leading=16, textColor=colors.HexColor("#1E293B"), spaceBefore=14, spaceAfter=6
    )
    body_style = ParagraphStyle(
        "PerfBody", parent=styles["Normal"], fontName="Helvetica", fontSize=8.5, leading=12, textColor=colors.HexColor("#334155")
    )
    disclaimer_style = ParagraphStyle(
        "PerfDisclaimer", parent=styles["Normal"], fontName="Helvetica-Oblique", fontSize=8, leading=11, textColor=colors.HexColor("#1E40AF")
    )

    story: List[Any] = []

    # Title Banner
    story.append(Paragraph("Google Performance & Core Web Vitals Report", title_style))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(
        f"Domain: <b>{target}</b> | Window: Last <b>{days} Days</b> | Generated: {datetime.now(timezone.utc).strftime('%B %d, %Y')}",
        subtitle_style
    ))
    story.append(Spacer(1, 4 * mm))

    # Executive Scoreboard KPI Table
    gsc_tot = gsc.get("totals") or {}
    ga4_tot = ga4.get("totals") or {}

    clicks_str = f"{gsc_tot.get('clicks', 0):,}" if gsc.get("is_connected") else "Not Connected"
    impr_str = f"{gsc_tot.get('impressions', 0):,}" if gsc.get("is_connected") else "Not Connected"
    sessions_str = f"{ga4_tot.get('sessions', 0):,}" if ga4.get("is_connected") else "Not Connected"
    eng_str = f"{ga4_tot.get('engagement_rate', 0)}%" if ga4.get("is_connected") else "Not Connected"

    kpi_data = [
        [
            Paragraph("<b>SEARCH CLICKS</b>", subtitle_style),
            Paragraph("<b>SEARCH IMPRESSIONS</b>", subtitle_style),
            Paragraph("<b>GA4 SESSIONS</b>", subtitle_style),
            Paragraph("<b>ENGAGEMENT RATE</b>", subtitle_style)
        ],
        [
            Paragraph(f"<font size=14 color='#2563EB'><b>{clicks_str}</b></font>", title_style),
            Paragraph(f"<font size=14 color='#10B981'><b>{impr_str}</b></font>", title_style),
            Paragraph(f"<font size=14 color='#06B6D4'><b>{sessions_str}</b></font>", title_style),
            Paragraph(f"<font size=14 color='#8B5CF6'><b>{eng_str}</b></font>", title_style)
        ],
        [
            Paragraph(f"CTR: {gsc_tot.get('ctr', 0)}%", subtitle_style),
            Paragraph(f"Avg Position: {gsc_tot.get('position', 0)}", subtitle_style),
            Paragraph(f"Users: {ga4_tot.get('total_users', 0):,}", subtitle_style),
            Paragraph(f"Bounce Rate: {ga4_tot.get('bounce_rate', 0)}%", subtitle_style)
        ]
    ]

    kpi_table = Table(kpi_data, colWidths=[45 * mm, 45 * mm, 45 * mm, 47 * mm])
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(kpi_table)
    story.append(Spacer(1, 4 * mm))

    # Disclaimer Box
    disc_data = [[Paragraph(f"<b>Data Measurement Boundaries:</b> {report.get('disclaimer', '')}", disclaimer_style)]]
    disc_table = Table(disc_data, colWidths=[182 * mm])
    disc_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EFF6FF")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#BFDBFE")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(disc_table)
    story.append(Spacer(1, 4 * mm))

    # Real-User Core Web Vitals (CrUX Field Data) vs Lighthouse Lab
    story.append(Paragraph("Core Web Vitals (Real User Field Data vs Lab Simulation)", section_title))
    assessment = cwv.get("assessment", "insufficient data").upper()
    ass_color = "#10B981" if assessment == "PASSED" else ("#EF4444" if assessment == "FAILED" else "#F59E0B")

    story.append(Paragraph(
        f"75th Percentile Real-User CWV Assessment: <font color='{ass_color}'><b>{assessment}</b></font> | "
        f"Lighthouse Mobile Lab Score: <b>{lh.get('mobile_score', 'N/A')}/100</b> | Desktop Lab: <b>{lh.get('desktop_score', 'N/A')}/100</b>",
        body_style
    ))
    story.append(Spacer(1, 3 * mm))

    # Top Search Queries Table
    story.append(Paragraph("Top Google Search Queries", section_title))
    queries = gsc.get("top_queries", [])
    if queries:
        q_rows = [[
            Paragraph("<b>Query</b>", subtitle_style),
            Paragraph("<b>Clicks</b>", subtitle_style),
            Paragraph("<b>Impressions</b>", subtitle_style),
            Paragraph("<b>CTR</b>", subtitle_style),
            Paragraph("<b>Avg Position</b>", subtitle_style)
        ]]
        for q in queries[:10]:
            q_rows.append([
                Paragraph(f"<b>{q.get('query', '')}</b>", body_style),
                Paragraph(f"{q.get('clicks', 0):,}", body_style),
                Paragraph(f"{q.get('impressions', 0):,}", body_style),
                Paragraph(f"{q.get('ctr', 0)}%", body_style),
                Paragraph(f"{q.get('position', 0):.1f}", body_style)
            ])
        q_tbl = Table(q_rows, colWidths=[70 * mm, 25 * mm, 30 * mm, 25 * mm, 32 * mm])
        q_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F5F9")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(q_tbl)
    else:
        story.append(Paragraph("<i>No authorized Google Search Console queries recorded for this property.</i>", body_style))

    doc.build(story, canvasmaker=PerformanceReportCanvas)
    return buf.getvalue()

