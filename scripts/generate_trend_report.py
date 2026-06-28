#!/usr/bin/env python3
"""
HK Financial Jobs — Trend & Historical Intelligence Report
Reads job_history + company_metrics from data/jobs.db and generates a PDF.
"""

import sqlite3, os
from datetime import datetime, timedelta
from collections import defaultdict, Counter
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer,
    Table, TableStyle, PageBreak, HRFlowable, KeepTogether, NextPageTemplate
)

DB_PATH  = "data/jobs.db"
OUT_PATH = "data/HK_Jobs_Trend_Report_2026.pdf"
TODAY    = datetime.now().strftime("%B %d, %Y")

# ── Colors ──────────────────────────────────────────────────────────────────
NAVY    = colors.HexColor('#15406B'); NAVY2 = colors.HexColor('#1E5A9C')
BLUE    = colors.HexColor('#2E7DD1'); MIDBLUE = colors.HexColor('#BFDBFE')
GREEN   = colors.HexColor('#15803D'); LTGREEN = colors.HexColor('#DCFCE7')
RED     = colors.HexColor('#B91C1C'); LTRED = colors.HexColor('#FEE2E2')
AMBER   = colors.HexColor('#B45309'); LTAMBER = colors.HexColor('#FEF3C7')
GREY    = colors.HexColor('#64748B'); LTGREY = colors.HexColor('#F1F5F9')
GREY200 = colors.HexColor('#E2E8F0'); WHITE = colors.white
INK     = colors.HexColor('#0F172A')

# ── Sector detection (by company name) ──────────────────────────────────────
def detect_sector(name):
    c = (name or '').lower()
    if any(b in c for b in ['goldman','morgan stanley','deutsche','barclays',
                            'jpmorgan chase','bank of america']):
        return 'Investment Bank'
    if any(i in c for i in ['manulife','axa','aia','prudential','fwd','sun life',
                            'zurich','generali','china life','china pacific',
                            'ping an','chubb','swiss re','samsung life','allianz',
                            'nippon','metlife','taiping','munich re','tokio marine']):
        return 'Insurance'
    if any(a in c for a in ['blackrock','value partners','macquarie','fidelity',
                            'state street','invesco','bnp paribas asset','man group',
                            'schroders','northern trust','asset management','pimco',
                            'kkr','franklin','amundi','t. rowe','apollo','brookfield',
                            'carlyle','gic','temasek']):
        return 'Asset Management'
    return 'Banking'

# ── Style helpers ───────────────────────────────────────────────────────────
def ps(name, **kw):
    base = kw.pop('parent', 'Normal')
    return ParagraphStyle(name, parent=getSampleStyleSheet()[base], **kw)

def P(txt, style):
    return Paragraph(str(txt) if txt is not None else '', style)

PW, PH = letter
LM = RM = 0.5*inch
TM = BM = 0.5*inch
CW = PW - LM - RM

def make_header_footer(title_right=''):
    def _hf(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(NAVY); canvas.setLineWidth(1.5)
        canvas.line(LM, PH-TM+10, PW-RM, PH-TM+10)
        canvas.setFont('Helvetica-Bold', 7.5); canvas.setFillColor(NAVY)
        canvas.drawString(LM, PH-TM+14, 'HK FINANCIAL SECTOR · TREND & HISTORICAL INTELLIGENCE 2026')
        canvas.setFont('Helvetica', 7.5); canvas.setFillColor(GREY)
        canvas.drawRightString(PW-RM, PH-TM+14, title_right)
        canvas.setStrokeColor(GREY200); canvas.setLineWidth(0.5)
        canvas.line(LM, BM-4, PW-RM, BM-4)
        canvas.setFont('Helvetica', 7); canvas.setFillColor(GREY)
        canvas.drawString(LM, BM-14, f'Confidential · Finex Members Only · Generated {TODAY}')
        canvas.drawCentredString(PW/2, BM-14, 'Source: job_history + company_metrics')
        canvas.drawRightString(PW-RM, BM-14, f'Page {doc.page}')
        canvas.restoreState()
    return _hf

def cover_bg(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(NAVY); canvas.rect(0,0,PW,PH,fill=1,stroke=0)
    canvas.setFillColor(BLUE); canvas.rect(0,0,PW,6,fill=1,stroke=0)
    canvas.restoreState()

BASE_TS = [
    ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
    ('BACKGROUND',(0,0),(-1,0),NAVY),
    ('TEXTCOLOR',(0,0),(-1,0),WHITE),
    ('FONTSIZE',(0,0),(-1,-1),7.5),
    ('GRID',(0,0),(-1,-1),0.3,GREY200),
    ('ROWBACKGROUNDS',(0,1),(-1,-1),[WHITE,LTGREY]),
    ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4),
    ('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),
    ('VALIGN',(0,0),(-1,-1),'TOP'),
]
def make_table(rows, widths, extra=None):
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle(list(BASE_TS) + (extra or [])))
    return t

def fmt_pct(v):
    return f'{v:+.1f}%' if v is not None else '—'
def fmt_num(v, dp=0):
    if v is None: return '—'
    return f'{v:,.{dp}f}'

# ── Load data ───────────────────────────────────────────────────────────────
def load():
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    hist = [dict(r) for r in conn.execute(
        "SELECT company_id, company_name, job_count, scraped_date, trend_direction, "
        "trend_percent, jobs_added, jobs_removed FROM job_history ORDER BY scraped_date, company_name")]
    metrics = [dict(r) for r in conn.execute(
        "SELECT company_id, company_name, avg_jobs_7d, avg_jobs_30d, growth_rate_7d, "
        "growth_rate_30d, current_trend FROM company_metrics")]
    conn.close()
    return hist, metrics

# ── Build ───────────────────────────────────────────────────────────────────
def build(hist, metrics):
    story = []
    h1 = ps('H1', fontSize=16, textColor=NAVY, fontName='Helvetica-Bold', spaceAfter=4, spaceBefore=6)
    h2 = ps('H2', fontSize=11, textColor=NAVY2, fontName='Helvetica-Bold', spaceAfter=3, spaceBefore=8)
    body = ps('BD', fontSize=8.5, textColor=INK, leading=13)
    tbl_hdr = ps('TH', fontSize=7.5, textColor=WHITE, fontName='Helvetica-Bold', alignment=TA_CENTER)
    cell = ps('TC', fontSize=7.5, textColor=INK, leading=11)
    cellc = ps('TCC', fontSize=7.5, textColor=INK, alignment=TA_CENTER, leading=11)
    boldc = ps('TB', fontSize=7.5, textColor=NAVY, fontName='Helvetica-Bold', alignment=TA_CENTER, leading=11)
    def TH(t): return P(t, tbl_hdr)
    def C(t): return P(t, cellc)
    def L(t): return P(t, cell)
    def B(t): return P(t, boldc)

    # per-day totals
    by_date = defaultdict(lambda: {'companies':0,'jobs':0})
    for r in hist:
        by_date[r['scraped_date']]['companies'] += 1
        by_date[r['scraped_date']]['jobs'] += r['job_count']
    dates = sorted(by_date)
    first_date, last_date = dates[0], dates[-1]
    n_snaps = len(dates)
    first_total = by_date[first_date]['jobs']
    last_total  = by_date[last_date]['jobs']
    net_growth = (last_total-first_total)/first_total*100 if first_total else 0
    check_back = (datetime.fromisoformat(first_date) + timedelta(days=30)).strftime('%B %d, %Y')

    # ── COVER ────────────────────────────────────────────────────────────────
    cov = Table([
        [P('Hong Kong Financial Sector', ps('ct',fontSize=28,textColor=WHITE,fontName='Helvetica-Bold',alignment=TA_CENTER,leading=34))],
        [P('Trend &amp; Historical Intelligence Report', ps('cs',fontSize=14,textColor=MIDBLUE,alignment=TA_CENTER,leading=20))],
        [Spacer(1,8)],
        [P(f'{n_snaps} daily snapshots · {first_date} → {last_date}', ps('cd',fontSize=10,textColor=MIDBLUE,alignment=TA_CENTER))],
        [P(f'Generated {TODAY}', ps('cd2',fontSize=9,textColor=GREY,alignment=TA_CENTER))],
    ], colWidths=[CW])
    cov.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),NAVY),
        ('TOPPADDING',(0,0),(0,0),90),('BOTTOMPADDING',(0,-1),(0,-1),90)]))
    story.append(cov)
    story.append(NextPageTemplate('main'))
    story.append(PageBreak())

    # ── DATA QUALITY BANNER ──────────────────────────────────────────────────
    story.append(P('Data Quality &amp; Methodology', h1))
    story.append(HRFlowable(width='100%', thickness=1.5, color=NAVY))
    story.append(Spacer(1,4))
    note = (
        f'<b>Trend data begins {first_date}</b> and spans <b>{n_snaps} daily snapshots</b> '
        f'through {last_date}. Trends become statistically meaningful after 7+ snapshots, so '
        f'this report is usable but still <b>early-stage</b>. For meaningful 30-day analysis, '
        f'check back after <b>{check_back}</b>.'
    )
    story.append(P(note, body))
    story.append(Spacer(1,4))
    caveat = (
        '<b>Read with care — three known distortions in the raw history:</b><br/>'
        '1. <b>Coverage expansion:</b> the tracked roster grew from 28 to 65 companies on 2026-06-21, '
        'so totals before/after that date are not like-for-like — much of the apparent market growth is '
        'simply more companies being tracked, not net new hiring.<br/>'
        '2. <b>Scrape-failure swings:</b> some single-day drops (e.g. 2026-06-19) reflect Cloudflare / '
        'network failures, not real market contraction.<br/>'
        '3. <b>Recovery artifacts:</b> a company that returned 0 on a failed day then recovered shows an '
        'inflated "+100%" growth rate. Treat extreme single-week growth figures as directional only.'
    )
    box = Table([[P(caveat, ps('cav',fontSize=8,textColor=INK,leading=12))]], colWidths=[CW])
    box.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),LTAMBER),('BOX',(0,0),(-1,-1),0.7,AMBER),
        ('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7),
        ('LEFTPADDING',(0,0),(-1,-1),9),('RIGHTPADDING',(0,0),(-1,-1),9)]))
    story.append(box)
    story.append(Spacer(1,10))

    # ── SECTION 1: MARKET OVERVIEW OVER TIME ─────────────────────────────────
    story.append(P('Section 1 · Market Overview Over Time', h1))
    story.append(HRFlowable(width='100%', thickness=1, color=NAVY))
    story.append(Spacer(1,4))
    rows = [[TH('Date'),TH('Companies'),TH('Total Jobs'),TH('Δ vs Prev Day'),TH('Δ %')]]
    prev = None; deltas = []
    for d in dates:
        tj = by_date[d]['jobs']; co = by_date[d]['companies']
        if prev is None:
            dtxt, dptxt = '—','—'
        else:
            delta = tj - prev; pct = delta/prev*100 if prev else 0
            deltas.append((d, delta))
            dtxt = f'{delta:+,}'; dptxt = f'{pct:+.1f}%'
        rows.append([C(d), C(str(co)), B(f'{tj:,}'), C(dtxt), C(dptxt)])
        prev = tj
    story.append(make_table(rows, [1.3*inch,1.2*inch,1.4*inch,1.5*inch,CW-5.4*inch]))
    story.append(Spacer(1,6))
    if deltas:
        gain = max(deltas, key=lambda x:x[1]); drop = min(deltas, key=lambda x:x[1])
        story.append(P(
            f'<b>Biggest single-day gain:</b> {gain[1]:+,} jobs on {gain[0]} &nbsp;·&nbsp; '
            f'<b>Biggest single-day drop:</b> {drop[1]:+,} jobs on {drop[0]}', body))
    story.append(P(
        f'<b>Net change first → latest snapshot:</b> {first_total:,} ({first_date}) → '
        f'{last_total:,} ({last_date}) = <b>{net_growth:+.1f}%</b> '
        f'<font color="#B45309">(distorted by the 28→65 company expansion — not pure hiring growth)</font>', body))
    story.append(PageBreak())

    # ── SECTION 2: COMPANY GROWTH RANKINGS ───────────────────────────────────
    story.append(P('Section 2 · Company Growth Rankings', h1))
    story.append(HRFlowable(width='100%', thickness=1, color=NAVY))
    story.append(Spacer(1,4))
    # current jobs = latest snapshot job_count per company
    latest_jobs = {}
    for r in hist:
        latest_jobs[r['company_id']] = r['job_count']  # ordered by date asc → ends on latest
    m_sorted = sorted(metrics, key=lambda m: (m['growth_rate_7d'] is None, -(m['growth_rate_7d'] or -1e9)))
    rows = [[TH('Company'),TH('Sector'),TH('Current'),TH('7d Avg'),TH('30d Avg'),
             TH('Growth 7d'),TH('Growth 30d'),TH('Trend')]]
    for m in m_sorted:
        rows.append([
            L(m['company_name']), L(detect_sector(m['company_name'])),
            C(str(latest_jobs.get(m['company_id'],'—'))),
            C(fmt_num(m['avg_jobs_7d'],1)), C(fmt_num(m['avg_jobs_30d'],1)),
            C(fmt_pct(m['growth_rate_7d'])), C(fmt_pct(m['growth_rate_30d'])),
            C((m['current_trend'] or '—').title()),
        ])
    story.append(make_table(rows, [1.85*inch,1.15*inch,0.6*inch,0.7*inch,0.7*inch,0.8*inch,0.85*inch,0.85*inch]))
    trend_ct = Counter((m['current_trend'] or 'unknown') for m in metrics)
    story.append(Spacer(1,5))
    story.append(P('  ·  '.join(f'<b>{k.title()}:</b> {v}' for k,v in trend_ct.most_common()), body))
    story.append(PageBreak())

    # ── SECTION 3: HIRING VELOCITY ───────────────────────────────────────────
    story.append(P('Section 3 · Hiring Velocity — Top Movers', h1))
    story.append(HRFlowable(width='100%', thickness=1, color=NAVY))
    story.append(Spacer(1,4))
    # absolute increase = latest - earliest per company (from history)
    first_jobs = {}; last_jobs = {}
    for r in hist:
        cid = r['company_id']
        if cid not in first_jobs: first_jobs[cid] = r['job_count']
        last_jobs[cid] = r['job_count']
    names = {r['company_id']: r['company_name'] for r in hist}
    abs_delta = sorted(((names[c], last_jobs[c]-first_jobs[c], first_jobs[c], last_jobs[c])
                        for c in last_jobs), key=lambda x:-x[1])
    story.append(P('Top 10 by Absolute Job-Count Increase (first → latest snapshot)', h2))
    rows=[[TH('Company'),TH('First'),TH('Latest'),TH('Δ Jobs')]]
    for nm,d,f,l in abs_delta[:10]:
        rows.append([L(nm),C(str(f)),C(str(l)),B(f'{d:+}')])
    story.append(make_table(rows,[3.0*inch,1.2*inch,1.2*inch,CW-5.4*inch]))
    story.append(Spacer(1,8))
    pos = [m for m in metrics if m['growth_rate_7d'] is not None]
    top_pct = sorted(pos, key=lambda m:-m['growth_rate_7d'])[:10]
    story.append(P('Top 10 by 7-Day Growth Rate', h2))
    rows=[[TH('Company'),TH('Sector'),TH('Growth 7d'),TH('Trend')]]
    for m in top_pct:
        rows.append([L(m['company_name']),L(detect_sector(m['company_name'])),
                     B(fmt_pct(m['growth_rate_7d'])),C((m['current_trend'] or '—').title())])
    story.append(make_table(rows,[2.6*inch,1.6*inch,1.2*inch,CW-5.4*inch]))
    story.append(Spacer(1,8))
    bottom = sorted(pos, key=lambda m:m['growth_rate_7d'])[:10]
    story.append(P('Bottom 10 by 7-Day Growth Rate (biggest declines — potential freezes/layoffs)', h2))
    rows=[[TH('Company'),TH('Sector'),TH('Growth 7d'),TH('Trend')]]
    for m in bottom:
        rows.append([L(m['company_name']),L(detect_sector(m['company_name'])),
                     P(fmt_pct(m['growth_rate_7d']), ps('rd',fontSize=7.5,textColor=RED,fontName='Helvetica-Bold',alignment=TA_CENTER)),
                     C((m['current_trend'] or '—').title())])
    story.append(make_table(rows,[2.6*inch,1.6*inch,1.2*inch,CW-5.4*inch]))
    story.append(PageBreak())

    # ── SECTION 4: TREND DIRECTION SUMMARY ───────────────────────────────────
    story.append(P('Section 4 · Trend Direction Summary', h1))
    story.append(HRFlowable(width='100%', thickness=1, color=NAVY))
    story.append(Spacer(1,4))
    rows=[[TH('Trend Direction'),TH('Companies'),TH('% of Tracked')]]
    tot_m = len(metrics) or 1
    for k,v in Counter((m['current_trend'] or 'unknown') for m in metrics).most_common():
        rows.append([C(k.title()),C(str(v)),C(f'{v/tot_m*100:.1f}%')])
    story.append(make_table(rows,[2.5*inch,2*inch,CW-4.5*inch]))
    story.append(Spacer(1,8))
    story.append(P('Average 7-Day Growth Rate by Sector', h2))
    sec_growth = defaultdict(list)
    for m in metrics:
        if m['growth_rate_7d'] is not None:
            sec_growth[detect_sector(m['company_name'])].append(m['growth_rate_7d'])
    sec_rows = sorted(((s, sum(v)/len(v), len(v)) for s,v in sec_growth.items()), key=lambda x:-x[1])
    rows=[[TH('Sector'),TH('Companies'),TH('Avg 7d Growth')]]
    for s,avg,n in sec_rows:
        rows.append([L(s),C(str(n)),B(fmt_pct(avg))])
    story.append(make_table(rows,[2.5*inch,2*inch,CW-4.5*inch]))
    if sec_rows:
        story.append(Spacer(1,5))
        story.append(P(f'<b>Fastest-growing sector (7d):</b> {sec_rows[0][0]} at {fmt_pct(sec_rows[0][1])} average.', body))
    story.append(PageBreak())

    # ── SECTION 5: PER-COMPANY HISTORY (≥3 data points) ──────────────────────
    story.append(P('Section 5 · Per-Company History', h1))
    story.append(HRFlowable(width='100%', thickness=1, color=NAVY))
    story.append(Spacer(1,4))
    story.append(P('Only companies with at least 3 daily snapshots are shown — single-day points are not trends.', body))
    story.append(Spacer(1,6))
    by_co = defaultdict(list)
    for r in hist:
        by_co[r['company_name']].append(r)
    shown = 0
    for co in sorted(by_co):
        recs = sorted(by_co[co], key=lambda r:r['scraped_date'])
        if len(recs) < 3:
            continue
        shown += 1
        co_hdr = Table([[P(f'{co}', ps('co',fontSize=9,textColor=NAVY,fontName='Helvetica-Bold')),
                         P(f'{len(recs)} snapshots · {detect_sector(co)}', ps('cox',fontSize=8,textColor=GREY,alignment=TA_RIGHT))]],
                       colWidths=[CW*0.65,CW*0.35])
        co_hdr.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),LTGREY),('LINEBELOW',(0,0),(-1,-1),1,NAVY2),
            ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4),
            ('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7)]))
        rows=[[TH('Date'),TH('Jobs'),TH('Trend'),TH('Δ vs Prev Day')]]
        prev=None
        for r in recs:
            if prev is None: dtxt='—'
            else:
                dl=r['job_count']-prev; dtxt=f'{dl:+}'
            rows.append([C(r['scraped_date']),C(str(r['job_count'])),
                         C((r['trend_direction'] or '—').title()),C(dtxt)])
            prev=r['job_count']
        tbl=make_table(rows,[1.6*inch,1.3*inch,1.6*inch,CW-4.5*inch])
        story.append(KeepTogether([co_hdr, Spacer(1,2), tbl, Spacer(1,8)]))
    story.append(Spacer(1,4))
    story.append(P(f'<i>{shown} companies have ≥3 snapshots and are shown above.</i>', ps('f',fontSize=8,textColor=GREY)))
    return story

def main():
    print("Loading trend data…")
    hist, metrics = load()
    print(f"  job_history rows: {len(hist)} · company_metrics rows: {len(metrics)}")
    if not hist:
        print("No job_history data — nothing to build."); return
    story = build(hist, metrics)
    print("Assembling document…")
    doc = BaseDocTemplate(OUT_PATH, pagesize=letter,
        leftMargin=LM, rightMargin=RM, topMargin=TM+0.3*inch, bottomMargin=BM+0.25*inch)
    cover_frame = Frame(0,0,PW,PH,id='cover',leftPadding=LM,rightPadding=RM,topPadding=TM,bottomPadding=BM)
    main_frame  = Frame(LM,BM+0.25*inch,CW,PH-TM-BM-0.55*inch,id='main',
                        leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)
    doc.addPageTemplates([
        PageTemplate(id='cover',frames=[cover_frame],onPage=cover_bg),
        PageTemplate(id='main',frames=[main_frame],onPage=make_header_footer('Trend Report · 15 snapshots')),
    ])
    doc.build(story)
    size = os.path.getsize(OUT_PATH)/1024/1024
    print(f"\n✅ Trend report saved: {OUT_PATH} ({size:.2f} MB)")

if __name__ == '__main__':
    main()
