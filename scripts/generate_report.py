#!/usr/bin/env python3
"""
HK Financial Job Market Intelligence Report
Reads from data/jobs.db and generates a professional PDF.
"""

import sqlite3, json, os
from datetime import datetime
from collections import defaultdict, Counter
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer,
    Table, TableStyle, PageBreak, HRFlowable, KeepTogether,
    NextPageTemplate
)

# ── Config ──────────────────────────────────────────────────────────────────
DB_PATH  = "data/jobs.db"
OUT_PATH = "data/HK_Financial_Jobs_Report_2026.pdf"
TODAY    = datetime.now().strftime("%B %d, %Y")

# ── Colors ───────────────────────────────────────────────────────────────────
NAVY      = colors.HexColor('#15406B')
NAVY2     = colors.HexColor('#1E5A9C')
BLUE      = colors.HexColor('#2E7DD1')
LTBLUE    = colors.HexColor('#EFF6FF')
MIDBLUE   = colors.HexColor('#BFDBFE')
GREEN     = colors.HexColor('#15803D')
LTGREEN   = colors.HexColor('#DCFCE7')
RED       = colors.HexColor('#B91C1C')
LTRED     = colors.HexColor('#FEE2E2')
AMBER     = colors.HexColor('#B45309')
LTAMBER   = colors.HexColor('#FEF3C7')
PURPLE    = colors.HexColor('#6D28D9')
LTPURPLE  = colors.HexColor('#EDE9FE')
TEAL      = colors.HexColor('#0F766E')
LTTEAL    = colors.HexColor('#CCFBF1')
GREY      = colors.HexColor('#64748B')
LTGREY    = colors.HexColor('#F1F5F9')
GREY200   = colors.HexColor('#E2E8F0')
WHITE     = colors.white
INK       = colors.HexColor('#0F172A')

# Sector color map
SECTOR_COLORS = {
    'Banking':         (NAVY,   LTBLUE),
    'Insurance':       (TEAL,   LTTEAL),
    'Asset Management':(PURPLE, LTPURPLE),
    'Investment Bank': (AMBER,  LTAMBER),
    'Internship':      (GREEN,  LTGREEN),
    'Other':           (GREY,   LTGREY),
}

# Seniority colors
SEN_COLORS = {
    'lead':   RED,
    'senior': NAVY2,
    'mid':    TEAL,
    'junior': GREEN,
}

# ── DB helpers ───────────────────────────────────────────────────────────────
def load_jobs():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT
            j.source, j.source_id, j.company, j.title,
            j.url, j.posted_at, j.locations AS location,
            e.seniority, e.job_category, e.remote_type,
            e.required_skills, e.salary_hkd_min, e.salary_hkd_max,
            e.years_experience_required,
            j.description_clean
        FROM jobs j
        LEFT JOIN job_enrichments e
               ON j.source = e.source AND j.source_id = e.source_id
        WHERE j.is_active = 1
        ORDER BY j.company, e.seniority, j.title
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    # Parse JSON fields
    for r in rows:
        try:
            r['location'] = json.loads(r['location'] or '[]')
        except Exception:
            r['location'] = []
        try:
            r['required_skills'] = json.loads(r['required_skills'] or '[]')
        except Exception:
            r['required_skills'] = []

    return rows

def detect_sector(row):
    """Map company + category to a display sector."""
    cat  = (row.get('job_category') or '').lower()
    comp = (row.get('company') or '').lower()

    # Internship detection
    title = (row.get('title') or '').lower()
    if any(k in title for k in ['intern', 'internship', 'graduate trainee',
                                  'graduate program', 'summer analyst',
                                  'summer associate']):
        return 'Internship'

    # Investment banks
    inv_banks = ['goldman', 'morgan stanley', 'deutsche', 'barclays',
                 'jpmorgan chase', 'bank of america', 'ubs']
    if any(b in comp for b in inv_banks):
        return 'Investment Bank'

    # Insurance
    ins = ['manulife','axa','aia','prudential','fwd','sun life','zurich',
           'generali','china life','china pacific','ping an','chubb',
           'swiss re','samsung life','allianz','nippon','metlife']
    if any(i in comp for i in ins):
        return 'Insurance'

    # Asset management
    am = ['blackrock','value partners','macquarie','fidelity','state street',
          'invesco','bnp paribas am','man group','schroders','northern trust',
          'jpm am','pimco','kkr','franklin','amundi']
    if any(a in comp for a in am):
        return 'Asset Management'

    # Banking (catch-all for remaining)
    return 'Banking'

# ── Style helpers ─────────────────────────────────────────────────────────────
def ps(name, **kw):
    base = kw.pop('parent', 'Normal')
    s = getSampleStyleSheet()
    return ParagraphStyle(name, parent=s[base], **kw)

def P(txt, style):
    return Paragraph(str(txt) if txt else '', style)

# ── Page templates ────────────────────────────────────────────────────────────
PW, PH = letter
LM = RM = 0.5*inch
TM = BM = 0.5*inch
CW = PW - LM - RM

def make_header_footer(title_right=''):
    def _hf(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(NAVY)
        canvas.setLineWidth(1.5)
        canvas.line(LM, PH-TM+10, PW-RM, PH-TM+10)
        canvas.setFont('Helvetica-Bold', 7.5)
        canvas.setFillColor(NAVY)
        canvas.drawString(LM, PH-TM+14, 'HK FINANCIAL SECTOR · JOB MARKET INTELLIGENCE REPORT 2026')
        canvas.setFont('Helvetica', 7.5)
        canvas.setFillColor(GREY)
        canvas.drawRightString(PW-RM, PH-TM+14, title_right)
        canvas.setStrokeColor(GREY200)
        canvas.setLineWidth(0.5)
        canvas.line(LM, BM-4, PW-RM, BM-4)
        canvas.setFont('Helvetica', 7)
        canvas.setFillColor(GREY)
        canvas.drawString(LM, BM-14, f'Confidential · Finex Members Only · Generated {TODAY}')
        canvas.drawCentredString(PW/2, BM-14, 'Source: HK Job Board Scraper')
        canvas.drawRightString(PW-RM, BM-14, f'Page {doc.page}')
        canvas.restoreState()
    return _hf

def cover_bg(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, 0, PW, PH, fill=1, stroke=0)
    canvas.setFillColor(NAVY2)
    canvas.rect(0, PH-8, PW, 8, fill=1, stroke=0)
    canvas.setFillColor(BLUE)
    canvas.rect(0, 0, PW, 6, fill=1, stroke=0)
    canvas.restoreState()

# ── Table style helpers ───────────────────────────────────────────────────────
BASE_TS = [
    ('FONTNAME',      (0,0),(-1,0),  'Helvetica-Bold'),
    ('BACKGROUND',    (0,0),(-1,0),  NAVY),
    ('TEXTCOLOR',     (0,0),(-1,0),  WHITE),
    ('FONTSIZE',      (0,0),(-1,-1), 7.5),
    ('GRID',          (0,0),(-1,-1), 0.3, GREY200),
    ('ROWBACKGROUNDS',(0,1),(-1,-1), [WHITE, LTGREY]),
    ('TOPPADDING',    (0,0),(-1,-1), 4),
    ('BOTTOMPADDING', (0,0),(-1,-1), 4),
    ('LEFTPADDING',   (0,0),(-1,-1), 5),
    ('RIGHTPADDING',  (0,0),(-1,-1), 5),
    ('VALIGN',        (0,0),(-1,-1), 'TOP'),
]

def make_table(rows, widths, extra=None):
    t = Table(rows, colWidths=widths, repeatRows=1)
    cmds = list(BASE_TS)
    if extra:
        cmds += extra
    t.setStyle(TableStyle(cmds))
    return t

# ── Seniority badge ───────────────────────────────────────────────────────────
def seniority_para(seniority):
    s = (seniority or 'mid').lower()
    c = SEN_COLORS.get(s, GREY)
    style = ps(f'sen_{s}', fontSize=7, textColor=WHITE,
               fontName='Helvetica-Bold', alignment=TA_CENTER,
               backColor=c, borderPad=2)
    return P(s.upper(), style)

# ── Skills string ─────────────────────────────────────────────────────────────
def skills_str(skills, max_skills=5):
    if not skills:
        return '—'
    shown = skills[:max_skills]
    rest  = len(skills) - max_skills
    s = ' · '.join(shown)
    if rest > 0:
        s += f' +{rest}'
    return s

# ── Salary string ─────────────────────────────────────────────────────────────
def salary_str(mn, mx):
    if mn and mx:
        return f'HK${mn:,}–{mx:,}'
    if mn:
        return f'HK${mn:,}+'
    return '—'

# ── Location string ───────────────────────────────────────────────────────────
def loc_str(locs):
    if not locs:
        return 'HK'
    return ', '.join(locs[:2])

# ── Date string ───────────────────────────────────────────────────────────────
def date_str(d):
    if not d:
        return '—'
    try:
        dt = datetime.fromisoformat(str(d)[:10])
        return dt.strftime('%d %b %Y')
    except Exception:
        return str(d)[:10]

# ── Build story ───────────────────────────────────────────────────────────────
def build_story(jobs):
    story = []

    # ── Styles ────────────────────────────────────────────────────────────────
    cover_title  = ps('CT', fontSize=32, textColor=WHITE,
                      fontName='Helvetica-Bold', alignment=TA_CENTER, leading=38)
    cover_sub    = ps('CS', fontSize=14, textColor=MIDBLUE,
                      alignment=TA_CENTER, leading=20)
    cover_date   = ps('CD', fontSize=9,  textColor=GREY,  alignment=TA_CENTER)
    h1           = ps('H1', fontSize=18, textColor=NAVY,
                      fontName='Helvetica-Bold', spaceAfter=4, spaceBefore=8)
    h2           = ps('H2', fontSize=11, textColor=NAVY2,
                      fontName='Helvetica-Bold', spaceAfter=3, spaceBefore=6)
    body         = ps('BD', fontSize=8.5, textColor=INK, leading=13)
    small        = ps('SM', fontSize=7.5, textColor=GREY, leading=11)
    cap          = ps('CA', fontSize=7.5, textColor=GREY,
                      alignment=TA_CENTER, spaceBefore=2)
    tbl_hdr      = ps('TH', fontSize=7.5, textColor=WHITE,
                      fontName='Helvetica-Bold', alignment=TA_CENTER)
    tbl_cell     = ps('TC', fontSize=7.5, textColor=INK, leading=11)
    tbl_cell_c   = ps('TCC',fontSize=7.5, textColor=INK,
                      alignment=TA_CENTER, leading=11)
    tbl_bold     = ps('TB', fontSize=7.5, textColor=NAVY,
                      fontName='Helvetica-Bold', leading=11)

    def PH(t): return P(t, tbl_hdr)
    def PC(t): return P(t, tbl_cell_c)
    def PL(t): return P(t, tbl_cell)
    def PB(t): return P(t, tbl_bold)

    # ── COVER ─────────────────────────────────────────────────────────────────
    from reportlab.graphics.shapes import Drawing, Rect, String, Line
    from reportlab.graphics import renderPDF

    cov = Table([
        [P('Hong Kong Financial Sector', cover_title)],
        [P('Job Market Intelligence Report', cover_sub)],
        [Spacer(1, 10)],
        [P(f'Generated {TODAY}', cover_date)],
    ], colWidths=[CW])
    cov.setStyle(TableStyle([
        ('BACKGROUND',    (0,0),(-1,-1), NAVY),
        ('TOPPADDING',    (0,0),(0,0),   80),
        ('BOTTOMPADDING', (0,-1),(0,-1), 80),
        ('TOPPADDING',    (0,1),(0,1),   10),
        ('BOTTOMPADDING', (0,1),(0,1),   10),
    ]))
    story.append(cov)

    # Sector stats on cover
    by_sector = defaultdict(list)
    for j in jobs:
        by_sector[detect_sector(j)].append(j)

    sector_order = ['Banking','Insurance','Asset Management',
                    'Investment Bank','Internship','Other']
    stats_data = [[]]
    for sec in sector_order:
        jj = by_sector.get(sec, [])
        if not jj:
            continue
        c, bg = SECTOR_COLORS.get(sec, (GREY, LTGREY))
        cell = Table([
            [P(str(len(jj)), ps(f'sn_{sec}', fontSize=22,
               fontName='Helvetica-Bold', textColor=c, alignment=TA_CENTER))],
            [P(sec, ps(f'sl_{sec}', fontSize=7.5,
               textColor=GREY, alignment=TA_CENTER))],
        ], colWidths=[1.1*inch])
        cell.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,-1), WHITE),
            ('TOPPADDING',(0,0),(-1,-1), 6),
            ('BOTTOMPADDING',(0,0),(-1,-1), 6),
            ('ROUNDEDCORNERS',[4,4,4,4]),
        ]))
        stats_data[0].append(cell)

    n = len(stats_data[0])
    if n:
        col_w = CW / n
        stats = Table(stats_data, colWidths=[col_w]*n)
        stats.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,-1), colors.HexColor('#1E3A5F')),
            ('GRID',(0,0),(-1,-1), 1, NAVY),
            ('TOPPADDING',(0,0),(-1,-1), 8),
            ('BOTTOMPADDING',(0,0),(-1,-1), 8),
        ]))
        story.append(Spacer(1, 20))
        story.append(stats)

    story.append(NextPageTemplate('main'))
    story.append(PageBreak())

    # ── EXECUTIVE SUMMARY ─────────────────────────────────────────────────────
    story.append(P('Executive Summary', h1))
    story.append(HRFlowable(width='100%', thickness=1.5, color=NAVY))
    story.append(Spacer(1, 6))

    # Key metrics table
    total = len(jobs)
    sen_counts = Counter(j.get('seniority','mid') or 'mid' for j in jobs)
    remote_counts = Counter(j.get('remote_type','on-site') or 'on-site' for j in jobs)
    skill_all = []
    for j in jobs:
        skill_all.extend(j.get('required_skills') or [])
    top_skills = Counter(skill_all).most_common(10)

    metrics = [
        [PH('Metric'), PH('Value')],
        [PL('Total Active Job Listings'), PB(f'{total:,}')],
        [PL('Companies Tracked'), PB('62')],
        [PL('Job Platforms'), PL('JobsDB · Workday · Eightfold')],
        [PL('Description Coverage'), PB('100%')],
        [PL('AI Enrichment Coverage'), PB('100%')],
        [PL('Report Generated'), PL(TODAY)],
    ]
    story.append(make_table(metrics, [3*inch, CW-3*inch]))
    story.append(Spacer(1, 10))

    # Seniority + remote side by side
    sen_rows = [[PH('Seniority'), PH('Jobs'), PH('%')]]
    for lv in ['lead','senior','mid','junior']:
        n = sen_counts.get(lv, 0)
        pct = f'{n/total*100:.1f}%'
        sen_rows.append([PC(lv.title()), PC(str(n)), PC(pct)])

    rem_rows = [[PH('Work Type'), PH('Jobs'), PH('%')]]
    for rt in ['on-site','hybrid','remote']:
        n = remote_counts.get(rt, 0)
        pct = f'{n/total*100:.1f}%'
        rem_rows.append([PC(rt.title()), PC(str(n)), PC(pct)])

    half = (CW-10)/2
    side = Table([[
        make_table(sen_rows, [half*0.5, half*0.25, half*0.25]),
        make_table(rem_rows, [half*0.5, half*0.25, half*0.25]),
    ]], colWidths=[half+5, half+5])
    side.setStyle(TableStyle([
        ('LEFTPADDING',(0,0),(-1,-1),0),
        ('RIGHTPADDING',(0,0),(-1,-1),0),
        ('TOPPADDING',(0,0),(-1,-1),0),
        ('BOTTOMPADDING',(0,0),(-1,-1),0),
        ('VALIGN',(0,0),(-1,-1),'TOP'),
    ]))
    story.append(side)
    story.append(Spacer(1, 10))

    # Top skills
    story.append(P('Top 10 Most In-Demand Skills', h2))
    skill_rows = [[PH('Rank'), PH('Skill'), PH('Job Count'), PH('% of All Jobs')]]
    for i, (sk, cnt) in enumerate(top_skills, 1):
        skill_rows.append([
            PC(str(i)), PL(sk), PC(str(cnt)), PC(f'{cnt/total*100:.1f}%')
        ])
    story.append(make_table(skill_rows,
        [0.4*inch, 3.5*inch, 1.2*inch, 1.2*inch]))
    story.append(Spacer(1, 10))

    # Sector summary
    story.append(P('Jobs by Sector & Company', h2))
    sec_rows = [[PH('Sector'), PH('Companies'), PH('Total Jobs'), PH('% of Market')]]
    for sec in sector_order:
        jj = by_sector.get(sec, [])
        if not jj:
            continue
        cos = len(set(j['company'] for j in jj))
        sec_rows.append([
            PL(sec), PC(str(cos)), PC(str(len(jj))),
            PC(f'{len(jj)/total*100:.1f}%')
        ])
    story.append(make_table(sec_rows,
        [2*inch, 1.5*inch, 1.5*inch, 1.5*inch]))

    story.append(PageBreak())

    # ── SECTOR SECTIONS ───────────────────────────────────────────────────────
    for sec in sector_order:
        jj = by_sector.get(sec, [])
        if not jj:
            continue

        sec_color, sec_bg = SECTOR_COLORS.get(sec, (GREY, LTGREY))

        # Section header
        hdr = Table([[P(f'{sec.upper()}  ·  {len(jj)} POSITIONS',
                        ps(f'sh_{sec}', fontSize=13, textColor=WHITE,
                           fontName='Helvetica-Bold'))]],
                    colWidths=[CW])
        hdr.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,-1), sec_color),
            ('TOPPADDING',(0,0),(-1,-1), 10),
            ('BOTTOMPADDING',(0,0),(-1,-1), 10),
            ('LEFTPADDING',(0,0),(-1,-1), 14),
        ]))
        story.append(KeepTogether([hdr, Spacer(1, 6)]))

        # Sector stats bar
        sec_sen = Counter(j.get('seniority','mid') or 'mid' for j in jj)
        stats_txt = '  ·  '.join(
            f'{lv.title()}: {sec_sen.get(lv,0)}'
            for lv in ['lead','senior','mid','junior'] if sec_sen.get(lv,0)
        )
        story.append(P(stats_txt, small))
        story.append(Spacer(1, 6))

        # Group by company within sector
        by_company = defaultdict(list)
        for j in jj:
            by_company[j['company']].append(j)

        for company in sorted(by_company.keys()):
            cjobs = by_company[company]

            # Company sub-header
            co_hdr = Table([[
                P(f'{company}', ps(f'co_{company}',
                   fontSize=9, textColor=sec_color,
                   fontName='Helvetica-Bold')),
                P(f'{len(cjobs)} positions',
                  ps(f'co_cnt_{company}', fontSize=8,
                     textColor=GREY, alignment=TA_RIGHT)),
            ]], colWidths=[CW*0.7, CW*0.3])
            co_hdr.setStyle(TableStyle([
                ('BACKGROUND',(0,0),(-1,-1), sec_bg),
                ('TOPPADDING',(0,0),(-1,-1), 5),
                ('BOTTOMPADDING',(0,0),(-1,-1), 5),
                ('LEFTPADDING',(0,0),(-1,-1), 8),
                ('RIGHTPADDING',(0,0),(-1,-1), 8),
                ('LINEBELOW',(0,0),(-1,-1), 1, sec_color),
            ]))

            # Job rows
            job_rows = [[
                PH('Job Title'),
                PH('Seniority'),
                PH('Location'),
                PH('Remote'),
                PH('Skills'),
                PH('Salary'),
                PH('Exp (yrs)'),
                PH('Posted'),
            ]]
            _SEN = ['lead','senior','mid','junior','']
            for j in sorted(cjobs,
                            key=lambda x: (
                                _SEN.index(x.get('seniority','') or '') if (x.get('seniority','') or '') in _SEN else len(_SEN),
                                x.get('title',''))):
                job_rows.append([
                    PL(j.get('title','—') or '—'),
                    seniority_para(j.get('seniority')),
                    PC(loc_str(j.get('location',[])) or 'HK'),
                    PC((j.get('remote_type') or 'on-site').replace('-',' ').title()),
                    PL(skills_str(j.get('required_skills',[])) or '—'),
                    PC(salary_str(j.get('salary_hkd_min'),
                                  j.get('salary_hkd_max'))),
                    PC(str(j.get('years_experience_required') or '—')),
                    PC(date_str(j.get('posted_at'))),
                ])

            job_tbl = make_table(job_rows, [
                2.2*inch,  # title
                0.65*inch, # seniority
                0.75*inch, # location
                0.65*inch, # remote
                1.6*inch,  # skills
                1.0*inch,  # salary
                0.55*inch, # exp
                0.75*inch, # posted
            ])

            story.append(KeepTogether([co_hdr, Spacer(1,2), job_tbl,
                                       Spacer(1, 8)]))

        story.append(PageBreak())

    # ── APPENDIX: Full skills taxonomy ───────────────────────────────────────
    story.append(P('Appendix A · Full Skills Demand Index', h1))
    story.append(HRFlowable(width='100%', thickness=1, color=NAVY))
    story.append(Spacer(1, 6))
    story.append(P(
        'All skills extracted by AI enrichment across all 2,742 active '
        'job listings, ranked by frequency.', body))
    story.append(Spacer(1, 6))

    all_skills = Counter(skill_all).most_common()
    # 3-column layout
    chunk = (len(all_skills) + 2) // 3
    cols = [all_skills[i*chunk:(i+1)*chunk] for i in range(3)]
    max_rows = max(len(c) for c in cols)

    sk_rows = [[PH('Skill'), PH('Count'), PH('Skill'), PH('Count'),
                PH('Skill'), PH('Count')]]
    for i in range(max_rows):
        row = []
        for col in cols:
            if i < len(col):
                sk, cnt = col[i]
                row += [PL(sk), PC(str(cnt))]
            else:
                row += [PL(''), PC('')]
        sk_rows.append(row)

    col_w = CW / 6
    story.append(make_table(sk_rows, [col_w*1.8, col_w*0.2]*3))
    story.append(PageBreak())

    # ── APPENDIX B: Company directory ────────────────────────────────────────
    story.append(P('Appendix B · Company Directory', h1))
    story.append(HRFlowable(width='100%', thickness=1, color=NAVY))
    story.append(Spacer(1, 6))

    co_rows = [[PH('#'), PH('Company'), PH('Sector'), PH('Total Jobs'),
                PH('Lead'), PH('Senior'), PH('Mid'), PH('Junior'),
                PH('On-site'), PH('Hybrid'), PH('Remote')]]

    all_cos = sorted(set(j['company'] for j in jobs))
    for i, co in enumerate(all_cos, 1):
        cj = [j for j in jobs if j['company'] == co]
        sen = Counter(j.get('seniority','mid') or 'mid' for j in cj)
        rem = Counter(j.get('remote_type','on-site') or 'on-site' for j in cj)
        sec = detect_sector(cj[0]) if cj else 'Other'
        co_rows.append([
            PC(str(i)), PL(co), PL(sec), PB(str(len(cj))),
            PC(str(sen.get('lead',0))),
            PC(str(sen.get('senior',0))),
            PC(str(sen.get('mid',0))),
            PC(str(sen.get('junior',0))),
            PC(str(rem.get('on-site',0))),
            PC(str(rem.get('hybrid',0))),
            PC(str(rem.get('remote',0))),
        ])

    story.append(make_table(co_rows, [
        0.3*inch, 2.0*inch, 1.2*inch, 0.65*inch,
        0.5*inch, 0.55*inch, 0.5*inch, 0.6*inch,
        0.6*inch, 0.55*inch, 0.55*inch,
    ]))

    return story


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("Loading jobs from DB…")
    jobs = load_jobs()
    print(f"  Loaded {len(jobs)} active jobs")

    print("Building PDF story…")
    story = build_story(jobs)

    print("Assembling document…")
    doc = BaseDocTemplate(
        OUT_PATH,
        pagesize=letter,
        leftMargin=LM, rightMargin=RM,
        topMargin=TM+0.3*inch, bottomMargin=BM+0.25*inch,
    )
    cover_frame = Frame(0, 0, PW, PH, id='cover',
                        leftPadding=LM, rightPadding=RM,
                        topPadding=TM, bottomPadding=BM)
    main_frame  = Frame(LM, BM+0.25*inch, CW,
                        PH-TM-BM-0.55*inch, id='main',
                        leftPadding=0, rightPadding=0,
                        topPadding=0, bottomPadding=0)
    doc.addPageTemplates([
        PageTemplate(id='cover', frames=[cover_frame], onPage=cover_bg),
        PageTemplate(id='main',  frames=[main_frame],
                     onPage=make_header_footer('62 Companies · 2,742 Active Listings')),
    ])

    doc.build(story)
    size = os.path.getsize(OUT_PATH) / 1024 / 1024
    print(f"\n✅ Report saved: {OUT_PATH} ({size:.1f} MB)")
    print(f"   Covers {len(jobs)} jobs across all sectors")

if __name__ == '__main__':
    main()
