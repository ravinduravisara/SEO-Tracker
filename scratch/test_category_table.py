import io
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.graphics.shapes import Drawing, Circle, Wedge, String
from reportlab.lib.units import mm

def make_score_circle(score: int, size: int = 24):
    d = Drawing(size, size)
    cx = size / 2.0
    cy = size / 2.0
    r = (size / 2.0) - 1.5
    inner_r = r - 3.2

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

    d.add(Circle(cx, cy, r, fillColor=colors.HexColor('#F1F5F9'), strokeColor=None))
    sweep = max(4, min(360, 360 * (score / 100.0)))
    d.add(Wedge(cx, cy, r, 90 - sweep, 90, fillColor=col, strokeColor=None))
    d.add(Circle(cx, cy, inner_r, fillColor=colors.HexColor('#FFFFFF'), strokeColor=None))
    font_sz = 6.0 if score < 100 else 5.0
    d.add(String(cx, cy - 2.0, f'{score}%', textAnchor='middle', fontName='Helvetica-Bold', fontSize=font_sz, fillColor=colors.HexColor('#0F172A')))
    return d

buf = io.BytesIO()
doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=14*mm, rightMargin=14*mm, topMargin=15*mm, bottomMargin=15*mm)

styles = getSampleStyleSheet()
bold_small = ParagraphStyle('B', fontName='Helvetica-Bold', fontSize=8, leading=10, textColor=colors.HexColor('#1E293B'))
small_style = ParagraphStyle('S', fontName='Helvetica', fontSize=7.5, leading=9.5, textColor=colors.HexColor('#64748B'))

categories = [
    ('Technical SEO', 15, 94, 'Excellent', '14 of 15 passed (4 pts unmeasured)'),
    ('On-Page SEO', 12, 86, 'Very Good', '4 of 11 passed (8 pts unmeasured)'),
    ('Content SEO', 12, 85, 'Very Good', '6 of 8 passed (21 pts unmeasured)'),
    ('Keyword Optimization', 8, 43, 'Poor', '0 of 5 passed (20 pts unmeasured)'),
    ('Internal Linking', 6, 85, 'Very Good', '4 of 6 passed'),
    ('Image SEO', 5, 48, 'Poor', '0 of 7 passed'),
    ('Structured Data', 6, 53, 'Needs Improvement', '2 of 8 passed'),
    ('Mobile SEO', 6, 88, 'Very Good', '3 of 4 passed (25 pts unmeasured)'),
    ('Page Experience', 8, 65, 'Needs Improvement', '2 of 2 passed (70 pts unmeasured)'),
    ('Local SEO', 8, 86, 'Very Good', '7 of 10 passed (10 pts unmeasured)'),
    ('E-commerce SEO', 8, 21, 'Critical', '2 of 8 passed'),
    ('Conversion SEO', 6, 89, 'Very Good', '6 of 8 passed (8 pts unmeasured)'),
]

rows = [[
    Paragraph('<b>Category</b>', bold_small),
    Paragraph('<b>Weight</b>', ParagraphStyle('C', parent=bold_small, alignment=TA_CENTER)),
    Paragraph('<b>Score</b>', ParagraphStyle('C', parent=bold_small, alignment=TA_CENTER)),
    Paragraph('<b>Grade</b>', ParagraphStyle('C', parent=bold_small, alignment=TA_CENTER)),
    Paragraph('<b>Audit Verification & Observations</b>', bold_small),
]]

for name, weight, score, grade, obs in categories:
    col = '#10B981' if score >= 85 else ('#0284C7' if score >= 70 else ('#F59E0B' if score >= 50 else '#EF4444'))
    circle = make_score_circle(score, size=24)
    rows.append([
        Paragraph(f'<b>{name}</b>', bold_small),
        Paragraph(f'{weight}%', ParagraphStyle('C', parent=small_style, alignment=TA_CENTER)),
        circle,
        Paragraph(f'<font color="{col}"><b>{grade}</b></font>', ParagraphStyle('C', parent=small_style, alignment=TA_CENTER)),
        Paragraph(obs, small_style),
    ])

t = Table(rows, colWidths=[44*mm, 15*mm, 20*mm, 30*mm, 73*mm])
t.setStyle(TableStyle([
    ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F1F5F9')),
    ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
    ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
    ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ('ALIGN', (2,1), (2,-1), 'CENTER'),
    ('TOPPADDING', (0,0), (-1,-1), 2.5),
    ('BOTTOMPADDING', (0,0), (-1,-1), 2.5),
    ('LEFTPADDING', (0,0), (-1,-1), 4),
    ('RIGHTPADDING', (0,0), (-1,-1), 4),
]))

doc.build([t])
print('Built table with 12 rows, total PDF bytes:', len(buf.getvalue()))
