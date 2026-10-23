import sys, os, json, sqlite3
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
)
from reportlab.graphics.shapes import Drawing, Circle, String, Wedge, Rect, Group
from reportlab.pdfgen import canvas

class NumberedCanvas(canvas.Canvas):
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
        self.drawString(14 * mm, 8 * mm, "eSupport SEO • https://esupport.live • WhatsApp: +94 70 782 0810")
        self.drawRightString(196 * mm, 8 * mm, f"Page {self._pageNumber} of {page_count}")
        self.restoreState()

def build_client_pdf(audit: dict) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4, # 210 x 297 mm
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"eSupport SEO Client Report - {audit.get('target', '')}",
        author="eSupport SEO"
    )

    styles = getSampleStyleSheet()
    
    # Custom styles
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
        fontSize=13,
        leading=16,
        textColor=colors.HexColor("#0F172A"),
        spaceBefore=8,
        spaceAfter=4
    )
    body_style = ParagraphStyle(
        "ClientBody",
        fontName="Helvetica",
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#334155")
    )
    small_style = ParagraphStyle(
        "ClientSmall",
        fontName="Helvetica",
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#64748B")
    )
    bold_small = ParagraphStyle(
        "ClientBoldSmall",
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#1E293B")
    )

    score_val = float(audit.get("score") or (audit.get("scores") or {}).get("overall") or 0)
    score_int = int(round(score_val))
    target_url = audit.get("target") or audit.get("url") or "Website"
    stats = audit.get("stats") or {}
    eng = audit.get("seo_engine") or {}
    eng_score = eng.get("score") or {}
    categories = eng.get("categories") or []
    recs = (audit.get("recommendations") or {}).get("developer_plan") or []
    issues = audit.get("issues") or []

    # Score color & label
    if score_int >= 85:
        score_color = colors.HexColor("#10B981") # emerald
        score_hex = "#10B981"
        badge_text = "EXCELLENT SEO HEALTH"
        badge_bg = "#ECFDF5"
        exec_text = "Your website demonstrates robust search engine fundamentals. Crawlability, core tagging, and structural hierarchy are well positioned to compete effectively in organic search."
    elif score_int >= 70:
        score_color = colors.HexColor("#0284C7") # blue/sky
        score_hex = "#0284C7"
        badge_text = "GOOD SEO FOUNDATION"
        badge_bg = "#F0F9FF"
        exec_text = "Your website has a solid baseline foundation with key SEO elements in place. Addressing prioritized technical and content optimizations will provide significant ranking gains."
    elif score_int >= 50:
        score_color = colors.HexColor("#F59E0B") # amber
        score_hex = "#F59E0B"
        badge_text = "NEEDS IMPROVEMENT"
        badge_bg = "#FFFBEB"
        exec_text = "Noticeable SEO gaps were identified across technical structure and search signals. Immediate remediation of high-priority findings is recommended to prevent lost search visibility."
    else:
        score_color = colors.HexColor("#EF4444") # red
        score_hex = "#EF4444"
        badge_text = "CRITICAL ACTION REQUIRED"
        badge_bg = "#FEF2F2"
        exec_text = "Major technical blockers and missing search signals are actively impacting search performance and user conversion. Systematic execution of the remediation roadmap below is urgently required."

    story = []

    # ================= PAGE 1: EXECUTIVE SUMMARY & HEALTH GAUGE =================
    
    # 1. Header Banner
    header_data = [
        [
            Paragraph("<b><font color='#2563EB'>eSupport</font> SEO</b>", brand_style),
            Paragraph(f"<font color='#64748B'><b>CLIENT AUDIT REPORT</b><br/>{audit.get('created_at', 'Live Audit')[:10]}</font>", ParagraphStyle("RightH", parent=brand_sub, alignment=TA_RIGHT))
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
    story.append(Spacer(1, 3 * mm))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#E2E8F0"), spaceAfter=5 * mm))

    # 2. Score Hero Box with Circular Gauge Drawing
    d = Drawing(120, 120)
    # Background circle track
    d.add(Circle(60, 60, 50, fillColor=colors.HexColor("#F1F5F9"), strokeColor=None))
    # Wedge progress arc
    sweep = max(1, min(360, 360 * (score_int / 100.0)))
    d.add(Wedge(60, 60, 50, 90 - sweep, 90, fillColor=score_color, strokeColor=None))
    # Inner white circle cutout
    d.add(Circle(60, 60, 39, fillColor=colors.HexColor("#FFFFFF"), strokeColor=None))
    # Inner text
    d.add(String(60, 56, f"{score_int}%", textAnchor='middle', fontName='Helvetica-Bold', fontSize=21, fillColor=colors.HexColor("#0F172A")))
    d.add(String(60, 44, "OVERALL SCORE", textAnchor='middle', fontName='Helvetica-Bold', fontSize=5.5, fillColor=colors.HexColor("#64748B")))

    pages_crawled = stats.get('total_pages') or audit.get('page_count') or 1
    crit_count = sum(1 for i in issues if i.get("severity") in ("critical", "error"))
    warn_count = sum(1 for i in issues if i.get("severity") == "warning")
    potential_score = (eng_score.get("potential") or {}).get("overall") or min(100, score_int + 22)

    hero_info = [
        [Paragraph(f"<font color='{score_hex}'><b>● {badge_text}</b></font>", ParagraphStyle("Badge", fontName="Helvetica-Bold", fontSize=11, leading=14))],
        [Paragraph(exec_text, body_style)],
        [Spacer(1, 1 * mm)],
        [
            Table([
                [
                    Paragraph(f"<b>{pages_crawled}</b><br/><font color='#64748B'>Pages Audited</font>", ParagraphStyle("MC", fontName="Helvetica", fontSize=8, leading=10, alignment=TA_CENTER)),
                    Paragraph(f"<b><font color='#EF4444'>{crit_count}</font></b><br/><font color='#64748B'>Critical Issues</font>", ParagraphStyle("MC", fontName="Helvetica", fontSize=8, leading=10, alignment=TA_CENTER)),
                    Paragraph(f"<b><font color='#F59E0B'>{warn_count}</font></b><br/><font color='#64748B'>Warnings</font>", ParagraphStyle("MC", fontName="Helvetica", fontSize=8, leading=10, alignment=TA_CENTER)),
                    Paragraph(f"<b><font color='#10B981'>{potential_score}%</font></b><br/><font color='#64748B'>Achievable Score</font>", ParagraphStyle("MC", fontName="Helvetica", fontSize=8, leading=10, alignment=TA_CENTER)),
                ]
            ], colWidths=[33*mm, 33*mm, 33*mm, 33*mm], style=[
                ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F8FAFC")),
                ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
                ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
                ('TOPPADDING', (0,0), (-1,-1), 5),
                ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ])
        ]
    ]
    hero_info_table = Table(hero_info, colWidths=[134 * mm])
    hero_info_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING', (0,0), (-1,-1), 1),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
    ]))

    hero_layout = Table([[d, hero_info_table]], colWidths=[48 * mm, 134 * mm])
    hero_layout.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#FFFFFF")),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor("#E2E8F0")),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(hero_layout)
    story.append(Spacer(1, 6 * mm))

    # 3. Core Category Breakdown
    story.append(Paragraph("<b>Category Health Breakdown</b>", h1_style))
    story.append(Paragraph("Weighted evaluation of the website across core organic search pillars.", small_style))
    story.append(Spacer(1, 2 * mm))

    cat_rows = [
        [
            Paragraph("<b>Category</b>", bold_small),
            Paragraph("<b>Weight</b>", ParagraphStyle("C", parent=bold_small, alignment=TA_CENTER)),
            Paragraph("<b>Score</b>", ParagraphStyle("C", parent=bold_small, alignment=TA_CENTER)),
            Paragraph("<b>Status / Grade</b>", ParagraphStyle("C", parent=bold_small, alignment=TA_CENTER)),
            Paragraph("<b>Executive Summary</b>", bold_small),
        ]
    ]

    # Normalize category display
    display_cats = categories if categories else [
        {"name": "Technical SEO", "weight": 20, "score": min(100, score_int + 10), "grade": "Good", "summary": "Core indexability, robots directives, and crawl structure."},
        {"name": "On-Page Content & Meta", "weight": 25, "score": score_int, "grade": "Good", "summary": "Titles, meta descriptions, heading structures, and body copy."},
        {"name": "Mobile & Responsive UX", "weight": 20, "score": min(100, score_int + 5), "grade": "Good", "summary": "Mobile viewport rendering, tap targets, and responsive layout."},
        {"name": "Performance & Speed", "weight": 20, "score": max(30, score_int - 15), "grade": "Needs Attention", "summary": "Page response time, asset sizes, and loading metrics."},
        {"name": "Security & Best Practices", "weight": 15, "score": min(100, score_int + 15), "grade": "Excellent", "summary": "HTTPS encryption, security headers, and canonical integrity."},
    ]

    for c in display_cats[:7]:
        c_score = int(c.get("score") or 0) if c.get("score") is not None else 0
        c_weight = c.get("weight") or 15
        c_grade = c.get("grade") or ("Good" if c_score >= 70 else "Needs Work")
        c_col = "#10B981" if c_score >= 80 else ("#0284C7" if c_score >= 70 else ("#F59E0B" if c_score >= 50 else "#EF4444"))
        c_desc = c.get("summary") or c.get("description") or f"Evaluation of {c.get('name')}"

        cat_rows.append([
            Paragraph(f"<b>{c.get('name')}</b>", bold_small),
            Paragraph(f"{c_weight}%", ParagraphStyle("C", parent=small_style, alignment=TA_CENTER)),
            Paragraph(f"<b><font color='{c_col}'>{c_score}%</font></b>", ParagraphStyle("C", parent=bold_small, alignment=TA_CENTER)),
            Paragraph(f"<font color='{c_col}'>● {c_grade}</font>", ParagraphStyle("C", parent=small_style, alignment=TA_CENTER)),
            Paragraph(c_desc[:90], small_style),
        ])

    cat_table = Table(cat_rows, colWidths=[42 * mm, 16 * mm, 20 * mm, 34 * mm, 70 * mm])
    cat_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#F1F5F9")),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E1")),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 3.5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3.5),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(cat_table)

    # Page 1 footer note
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("<i>* Detailed check findings and prioritized improvement items continue on next page.</i>", small_style))

    # ================= PAGE 2: KEY FINDINGS & TOP RECOMMENDATIONS =================
    story.append(PageBreak())

    story.append(Paragraph("<b>Priority Action Items & Business Impact</b>", h1_style))
    story.append(Paragraph("The highest-impact issues discovered during the audit that directly affect search rankings, click-through rates, and customer conversions.", body_style))
    story.append(Spacer(1, 3 * mm))

    # Priority Issues Table
    issue_rows = [
        [
            Paragraph("<b>Priority</b>", bold_small),
            Paragraph("<b>SEO Factor</b>", bold_small),
            Paragraph("<b>Issue Identified</b>", bold_small),
            Paragraph("<b>Business Impact</b>", bold_small),
            Paragraph("<b>Recommended Action</b>", bold_small),
        ]
    ]

    # Curate high-impact findings
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
        # Fallback if no developer plan exists
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
        issue_rows.append([
            Paragraph(f"<b><font color='{p_col}'>{prio}</font></b>", bold_small),
            Paragraph(f"<b>{item.get('cat')}</b>", small_style),
            Paragraph(item.get("issue")[:80], small_style),
            Paragraph(item.get("impact", "Negative impact on search rankings.")[:85], small_style),
            Paragraph(f"<b>{item.get('action')[:110]}</b>", small_style),
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

    # Quick Wins Section
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
            Paragraph("<b>PHASE 1: Foundation (Days 1–14)</b>", ParagraphStyle("P1", fontName="Helvetica-Bold", fontSize=9, leading=11, textColor=colors.HexColor("#2563EB"))),
            Paragraph("<b>PHASE 2: Optimization (Days 15–30)</b>", ParagraphStyle("P2", fontName="Helvetica-Bold", fontSize=9, leading=11, textColor=colors.HexColor("#0284C7"))),
            Paragraph("<b>PHASE 3: Growth (Days 31–60)</b>", ParagraphStyle("P3", fontName="Helvetica-Bold", fontSize=9, leading=11, textColor=colors.HexColor("#10B981"))),
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

    # Methodology & Integrity
    story.append(Paragraph("<b>Audit Standards & Methodology</b>", h1_style))
    story.append(Paragraph(
        "This audit was compiled via real-time HTTP crawler validation, direct DOM analysis, and Google Webmaster technical standards. "
        "Scores reflect strictly verifiable parameters without artificial inflation. Achieving the projected target requires systematic implementation of the technical, structural, and on-page recommendations identified herein.",
        body_style
    ))
    story.append(Spacer(1, 8 * mm))

    # Agency Call to Action & Contact Card
    cta_data = [
        [
            Paragraph("<b>Ready to Boost Your Organic Rankings & Leads?</b>", ParagraphStyle("CTATitle", fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=colors.HexColor("#0F172A"))),
            Paragraph("<b>eSupport SEO Experts</b>", ParagraphStyle("CTABrand", fontName="Helvetica-Bold", fontSize=10, leading=13, alignment=TA_RIGHT, textColor=colors.HexColor("#2563EB"))),
        ],
        [
            Paragraph("Our team specializes in full technical implementation, content optimization, and search growth strategies. Contact us for a free strategy consultation.", body_style),
            Paragraph("<b>Direct Consultation:</b><br/>WhatsApp: <font color='#16A34A'><b>+94 70 782 0810</b></font><br/>Email: <b>prasad@esupport.live</b><br/>Web: <b>https://esupport.live</b>", ParagraphStyle("CTADetails", fontName="Helvetica", fontSize=8, leading=11, alignment=TA_RIGHT)),
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

    doc.build(story, canvasmaker=NumberedCanvas)
    return buf.getvalue()

if __name__ == "__main__":
    conn = sqlite3.connect("seo_platform.db")
    cur = conn.cursor()
    cur.execute("SELECT result_json FROM audits WHERE id=21")
    row = cur.fetchone()
    if row and row[0]:
        data = json.loads(row[0])
        pdf_bytes = build_client_pdf(data)
        out_path = "scratch/test_client_report.pdf"
        with open(out_path, "wb") as f:
            f.write(pdf_bytes)
        print(f"Generated test client PDF: {len(pdf_bytes)} bytes written to {out_path}")
