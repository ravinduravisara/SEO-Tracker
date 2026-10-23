import io
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.graphics.shapes import Drawing, Circle, Wedge, String
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

def make_score_circle(score: int, size: int = 22):
    d = Drawing(size, size)
    cx = size / 2.0
    cy = size / 2.0
    r = (size / 2.0) - 1.2
    inner_r = r - 2.8

    if score >= 90:
        col = colors.HexColor('#10B981')
    elif score >= 80:
        col = colors.HexColor('#059669')
    elif score >= 70:
        col = colors.HexColor('#0284C7')
    elif score >= 50:
        col = colors.HexColor('#F59E0B')
    else:
        col = colors.HexColor('#EF4444')

    # Background track ring
    d.add(Circle(cx, cy, r, fillColor=colors.HexColor('#F1F5F9'), strokeColor=colors.HexColor('#E2E8F0'), strokeWidth=0.5))
    # Arc wedge
    sweep = max(4, min(360, 360 * (score / 100.0)))
    d.add(Wedge(cx, cy, r, 90 - sweep, 90, fillColor=col, strokeColor=None))
    # Inner cutout
    d.add(Circle(cx, cy, inner_r, fillColor=colors.HexColor('#FFFFFF'), strokeColor=None))
    # Text in center
    font_sz = 5.8 if score < 100 else 4.8
    d.add(String(cx, cy - 2.0, f'{score}%', textAnchor='middle', fontName='Helvetica-Bold', fontSize=font_sz, fillColor=colors.HexColor('#0F172A')))
    return d

buf = io.BytesIO()
doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=14*mm, rightMargin=14*mm, topMargin=15*mm, bottomMargin=15*mm)

styles = getSampleStyleSheet()
brand_style = ParagraphStyle("BH", fontName="Helvetica-Bold", fontSize=17, leading=20, textColor=colors.HexColor("#0F172A"))
brand_sub = ParagraphStyle("BS", fontName="Helvetica", fontSize=8, leading=10, textColor=colors.HexColor("#64748B"))
h1_style = ParagraphStyle("H1", fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=colors.HexColor("#0F172A"), spaceBefore=4, spaceAfter=2)
body_style = ParagraphStyle("B", fontName="Helvetica", fontSize=8, leading=11, textColor=colors.HexColor("#334155"))
small_style = ParagraphStyle("S", fontName="Helvetica", fontSize=7, leading=9, textColor=colors.HexColor("#64748B"))
bold_small = ParagraphStyle("BSM", fontName="Helvetica-Bold", fontSize=7.5, leading=9.5, textColor=colors.HexColor("#1E293B"))

story = []

# Header
header_data = [
    [
        Paragraph("<b><font color='#2563EB'>eSupport</font> SEO</b>", brand_style),
        Paragraph("<font color='#64748B'><b>CLIENT AUDIT REPORT</b><br/>2026-10-11</font>", ParagraphStyle("RH", parent=brand_sub, alignment=TA_RIGHT))
    ],
    [
        Paragraph("Professional Technical & Organic Search Health Assessment", brand_sub),
        Paragraph("Target: <font color='#0F172A'><b>https://example.com/</b></font>", ParagraphStyle("RH2", parent=brand_sub, alignment=TA_RIGHT))
    ]
]
header_table = Table(header_data, colWidths=[105*mm, 77*mm])
header_table.setStyle(TableStyle([
    ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ('BOTTOMPADDING', (0,0), (-1,-1), 1),
    ('TOPPADDING', (0,0), (-1,-1), 0),
    ('LEFTPADDING', (0,0), (-1,-1), 0),
    ('RIGHTPADDING', (0,0), (-1,-1), 0),
]))
story.append(header_table)
story.append(Spacer(1, 2*mm))
story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#E2E8F0"), spaceAfter=4*mm))

# Overall Hero Gauge (90x90 pt)
score_int = 73
score_color = colors.HexColor("#0284C7")
d = Drawing(92, 92)
d.add(Circle(46, 46, 40, fillColor=colors.HexColor("#F1F5F9"), strokeColor=None))
sweep = max(1, min(360, 360 * (score_int / 100.0)))
d.add(Wedge(46, 46, 40, 90 - sweep, 90, fillColor=score_color, strokeColor=None))
d.add(Circle(46, 46, 31, fillColor=colors.HexColor("#FFFFFF"), strokeColor=None))
d.add(String(46, 43, f"{score_int}%", textAnchor='middle', fontName='Helvetica-Bold', fontSize=18, fillColor=colors.HexColor("#0F172A")))
d.add(String(46, 33, "OVERALL SCORE", textAnchor='middle', fontName='Helvetica-Bold', fontSize=4.8, fillColor=colors.HexColor("#64748B")))

hero_info = [
    [Paragraph("<font color='#0284C7'><b>● GOOD SEO FOUNDATION</b></font>", ParagraphStyle("Badge", fontName="Helvetica-Bold", fontSize=10, leading=13))],
    [Paragraph("Your website has a solid baseline foundation with key SEO elements in place. Addressing prioritized technical and content optimizations will provide significant ranking gains.", body_style)],
    [Spacer(1, 1*mm)],
    [
        # 3 KPI cards (Achievable Score REMOVED!)
        Table([
            [
                Paragraph("<b>100</b><br/><font color='#64748B'>Pages Audited</font>", ParagraphStyle("MC", fontName="Helvetica", fontSize=7.5, leading=9.5, alignment=TA_CENTER)),
                Paragraph("<b><font color='#EF4444'>4</font></b><br/><font color='#64748B'>Critical Issues</font>", ParagraphStyle("MC", fontName="Helvetica", fontSize=7.5, leading=9.5, alignment=TA_CENTER)),
                Paragraph("<b><font color='#F59E0B'>12</font></b><br/><font color='#64748B'>Warnings</font>", ParagraphStyle("MC", fontName="Helvetica", fontSize=7.5, leading=9.5, alignment=TA_CENTER)),
            ]
        ], colWidths=[44.6*mm, 44.7*mm, 44.7*mm], style=[
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F8FAFC")),
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
            ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ])
    ]
]
hero_info_table = Table(hero_info, colWidths=[136*mm])
hero_info_table.setStyle(TableStyle([
    ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ('LEFTPADDING', (0,0), (-1,-1), 0),
    ('RIGHTPADDING', (0,0), (-1,-1), 0),
    ('TOPPADDING', (0,0), (-1,-1), 0),
    ('BOTTOMPADDING', (0,0), (-1,-1), 0),
]))
hero_layout = Table([[d, hero_info_table]], colWidths=[46*mm, 136*mm])
hero_layout.setStyle(TableStyle([
    ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#FFFFFF")),
    ('BOX', (0,0), (-1,-1), 1, colors.HexColor("#E2E8F0")),
    ('TOPPADDING', (0,0), (-1,-1), 5),
    ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ('LEFTPADDING', (0,0), (-1,-1), 3),
    ('RIGHTPADDING', (0,0), (-1,-1), 3),
]))
story.append(hero_layout)
story.append(Spacer(1, 4*mm))

# Category Breakdown Heading
story.append(Paragraph("<b>Category Health Breakdown</b>", h1_style))
story.append(Paragraph("Full 12-pillar organic search audit. Scores reflect verified live crawl signals and ranking readiness.", small_style))
story.append(Spacer(1, 2*mm))

categories = [
    ('Technical SEO', 15, 94, 'Excellent', '14 of 15 passed (4 pts unmeasured)', 'Core indexability, robots directives, SSL security'),
    ('On-Page SEO', 12, 86, 'Very Good', '4 of 11 passed (8 pts unmeasured)', 'Page titles, meta descriptions, H1 hierarchy'),
    ('Content SEO', 12, 85, 'Very Good', '6 of 8 passed (21 pts unmeasured)', 'Topical depth, content quality, word count'),
    ('Keyword Optimization', 8, 43, 'Poor', '0 of 5 passed (20 pts unmeasured)', 'Search intent mapping, keyword distribution'),
    ('Internal Linking', 6, 85, 'Very Good', '4 of 6 passed', 'Site architecture, anchor tags, link flow'),
    ('Image SEO', 5, 48, 'Poor', '0 of 7 passed', 'Alt attributes, WebP compression, asset sizes'),
    ('Structured Data', 6, 53, 'Needs Improvement', '2 of 8 passed', 'Schema.org JSON-LD, Open Graph social tags'),
    ('Mobile SEO', 6, 88, 'Very Good', '3 of 4 passed (25 pts unmeasured)', 'Responsive design, viewport, mobile usability'),
    ('Page Experience', 8, 65, 'Needs Improvement', '2 of 2 passed (70 pts unmeasured)', 'Core Web Vitals, speed, render stability'),
    ('Local SEO', 8, 86, 'Very Good', '7 of 10 passed (10 pts unmeasured)', 'NAP consistency, local intent, business signals'),
    ('E-commerce SEO', 8, 21, 'Critical', '2 of 8 passed', 'Product catalogue markup, conversion intent'),
    ('Conversion SEO', 6, 89, 'Very Good', '6 of 8 passed (8 pts unmeasured)', 'CTAs, contact routing, WhatsApp lead capture'),
]

rows = [[
    Paragraph('<b>Category Pillar</b>', bold_small),
    Paragraph('<b>Weight</b>', ParagraphStyle('C', parent=bold_small, alignment=TA_CENTER)),
    Paragraph('<b>Score</b>', ParagraphStyle('C', parent=bold_small, alignment=TA_CENTER)),
    Paragraph('<b>Status Grade</b>', ParagraphStyle('C', parent=bold_small, alignment=TA_CENTER)),
    Paragraph('<b>Audit Verification & Observations</b>', bold_small),
]]

for name, weight, score, grade, checks, summary in categories:
    col = '#10B981' if score >= 85 else ('#0284C7' if score >= 70 else ('#F59E0B' if score >= 50 else '#EF4444'))
    circle = make_score_circle(score, size=21)
    rows.append([
        Paragraph(f'<b>{name}</b>', bold_small),
        Paragraph(f'{weight}%', ParagraphStyle('C', parent=small_style, alignment=TA_CENTER)),
        circle,
        Paragraph(f'<font color="{col}"><b>● {grade}</b></font>', ParagraphStyle('C', parent=small_style, alignment=TA_CENTER)),
        Paragraph(f"<b>{checks}</b><br/><font color='#64748B'>{summary}</font>", small_style),
    ])

# Total row
rows.append([
    Paragraph('<b>Total Audit Score</b>', bold_small),
    Paragraph('<b>100%</b>', ParagraphStyle('C', parent=bold_small, alignment=TA_CENTER)),
    make_score_circle(score_int, size=21),
    Paragraph(f'<font color="{score_color.hexval()}"><b>● GOOD FOUNDATION</b></font>', ParagraphStyle('C', parent=bold_small, alignment=TA_CENTER)),
    Paragraph('<b>7,312 / 10,000 weighted points earned. Systematic optimization unblocks maximum search rank.</b>', bold_small),
])

cat_table = Table(rows, colWidths=[43*mm, 15*mm, 20*mm, 32*mm, 72*mm])
cat_table.setStyle(TableStyle([
    ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F1F5F9')),
    ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor('#F8FAFC')),
    ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
    ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
    ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ('ALIGN', (2,1), (2,-1), 'CENTER'),
    ('TOPPADDING', (0,0), (-1,-1), 2),
    ('BOTTOMPADDING', (0,0), (-1,-1), 2),
    ('LEFTPADDING', (0,0), (-1,-1), 3),
    ('RIGHTPADDING', (0,0), (-1,-1), 3),
]))
story.append(cat_table)

# Page 2
story.append(PageBreak())
story.append(Paragraph("<b>Page 2 Content Test</b>", h1_style))

# Canvas counting
class PageCounter(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.page_count = 0
    def showPage(self):
        self.page_count += 1
        super().showPage()

pc = PageCounter
doc.build(story)
print("Build complete! Total bytes:", len(buf.getvalue()))
