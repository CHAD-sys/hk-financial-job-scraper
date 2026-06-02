"""
Generate a full-data PDF report of all 1,063 enriched HK financial sector jobs.
Output: outputs/HK_Jobs_Full_Data_Report.pdf
"""

import json
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

from reportlab.graphics.charts.barcharts import HorizontalBarChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    HRFlowable, PageBreak, Paragraph, SimpleDocTemplate,
    Spacer, Table, TableStyle, KeepTogether,
)

# ── palette ───────────────────────────────────────────────────────────────────
NAVY  = colors.HexColor("#1A3A5C")
BLUE  = colors.HexColor("#2C6FAC")
LBLUE = colors.HexColor("#D6E8F7")
TEAL  = colors.HexColor("#1ABC9C")
WHITE = colors.white
GREY  = colors.HexColor("#F5F5F5")
LGREY = colors.HexColor("#CCCCCC")
DGREY = colors.HexColor("#555555")

SEN_COL = {
    "lead":   colors.HexColor("#C0392B"),
    "senior": colors.HexColor("#2C6FAC"),
    "mid":    colors.HexColor("#27AE60"),
    "junior": colors.HexColor("#95A5A6"),
}
SEN_BG = {
    "lead":   colors.HexColor("#FADBD8"),
    "senior": colors.HexColor("#D6E8F7"),
    "mid":    colors.HexColor("#D5F5E3"),
    "junior": colors.HexColor("#F2F3F4"),
}

CAT_PALETTE = [
    colors.HexColor("#2C6FAC"), colors.HexColor("#1ABC9C"),
    colors.HexColor("#E67E22"), colors.HexColor("#8E44AD"),
    colors.HexColor("#C0392B"), colors.HexColor("#27AE60"),
]

CATEGORY_ORDER = ["Finance", "Operations", "Sales", "Engineering", "HR", "Other"]
REMOTE_LABEL = {"on-site": "[Office]", "hybrid": "[Hybrid]", "remote": "[Remote]"}

# ── data helpers ──────────────────────────────────────────────────────────────

def load_jobs(db_path: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT j.company, j.title, j.source, j.posted_at, j.locations,
               e.seniority, e.required_skills, e.years_experience_required,
               e.remote_type, e.salary_hkd_min, e.salary_hkd_max,
               e.job_category
          FROM jobs j
          JOIN job_enrichments e ON j.source=e.source AND j.source_id=e.source_id
         ORDER BY e.job_category, e.seniority DESC, j.company, j.title
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def by_category(jobs: list[dict]) -> dict[str, list[dict]]:
    d: dict[str, list[dict]] = defaultdict(list)
    for j in jobs:
        d[j["job_category"] or "Other"].append(j)
    return d


def fmt_date(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso).strftime("%d %b %Y")
    except Exception:
        return iso[:10]


def fmt_skills(raw: str | None, maxlen: int = 60) -> str:
    if not raw:
        return "—"
    try:
        sk = json.loads(raw)
    except Exception:
        return (raw or "")[:maxlen]
    joined = ", ".join(sk)
    return joined[:maxlen] + "…" if len(joined) > maxlen else joined


def fmt_salary(mn, mx) -> str:
    if mn and mx:
        return f"{mn//1000}K–{mx//1000}K HKD"
    if mn:
        return f">{mn//1000}K HKD"
    if mx:
        return f"<{mx//1000}K HKD"
    return "N/A"


def fmt_exp(yrs) -> str:
    if yrs is None:
        return "—"
    return f"{yrs}+ yrs"


def fmt_source(src: str) -> str:
    return {"eightfold": "Eightfold", "workday": "Workday", "jobsdb": "JobsDB"}.get(src, src)


def top_skills(jobs: list[dict], n: int = 20) -> list[tuple[str, int]]:
    c: Counter = Counter()
    for j in jobs:
        try:
            for sk in json.loads(j.get("required_skills") or "[]"):
                c[sk.lower().strip()] += 1
        except Exception:
            pass
    return c.most_common(n)


# ── chart helpers ─────────────────────────────────────────────────────────────

def bar_chart(data: dict[str, int], width=17*cm, height=5*cm, title="") -> Drawing:
    labels = list(data.keys())[:12]
    values = [data[l] for l in labels]
    max_v  = max(values) if values else 1

    d = Drawing(width, height + 20)
    bar_h   = (height - 10) / len(labels)
    bar_gap = bar_h * 0.2
    bar_w_max = width - 6*cm

    for i, (lbl, val) in enumerate(zip(labels, values)):
        y = height - (i + 1) * bar_h + bar_gap / 2
        bw = bar_w_max * val / max_v
        d.add(Rect(3.5*cm, y, bw, bar_h - bar_gap,
                   fillColor=CAT_PALETTE[i % len(CAT_PALETTE)], strokeColor=None))
        d.add(String(3.3*cm, y + (bar_h - bar_gap) / 3, lbl,
                     fontSize=7, textAnchor="end", fillColor=NAVY))
        d.add(String(3.5*cm + bw + 2, y + (bar_h - bar_gap) / 3, str(val),
                     fontSize=7, fillColor=DGREY))
    return d


def pie_chart(data: dict[str, int], width=8*cm, height=6*cm) -> Drawing:
    d = Drawing(width, height)
    pie = Pie()
    pie.x, pie.y = 1.5*cm, 0.5*cm
    pie.width = pie.height = min(width, height) - 1*cm
    pie.data   = list(data.values())
    pie.labels = [f"{k}\n{v}" for k, v in data.items()]
    pie.slices.strokeWidth = 0.5
    pie.slices.strokeColor = WHITE
    pie.sideLabels = True
    pie.sideLabelsOffset = 0.05
    for i, col in enumerate(CAT_PALETTE[:len(data)]):
        pie.slices[i].fillColor = col
    pie.slices.fontSize = 7
    d.add(pie)
    return d


# ── PDF class ─────────────────────────────────────────────────────────────────

class FullReport:
    def __init__(self, out: str) -> None:
        self.out   = out
        self.story: list = []
        self.today = date.today().strftime("%d %b %Y")
        self._page = 0
        s = getSampleStyleSheet()
        self.S = s

        def add(name, **kw):
            s.add(ParagraphStyle(name=name, **kw))

        add("RTitle",   fontSize=30, textColor=WHITE,  alignment=TA_CENTER, leading=38, fontName="Helvetica-Bold")
        add("RSub",     fontSize=13, textColor=LBLUE,  alignment=TA_CENTER, leading=20, fontName="Helvetica")
        add("RMeta",    fontSize=10, textColor=LBLUE,  alignment=TA_CENTER, leading=16, fontName="Helvetica")
        add("SecHead",  fontSize=15, textColor=NAVY,   leading=22, fontName="Helvetica-Bold", spaceAfter=2)
        add("AppHead",  fontSize=12, textColor=NAVY,   leading=18, fontName="Helvetica-Bold", spaceBefore=8, spaceAfter=2)
        add("TocLine",  fontSize=11, textColor=NAVY,   leading=18, fontName="Helvetica")
        add("Cell",     fontSize=7.5,textColor=colors.black, leading=10, fontName="Helvetica")
        add("CellB",    fontSize=7.5,textColor=NAVY,   leading=10, fontName="Helvetica-Bold")
        add("CellS",    fontSize=6.5,textColor=DGREY,  leading=9,  fontName="Helvetica")
        add("CellSen",  fontSize=7.5,leading=10, fontName="Helvetica-Bold", alignment=TA_CENTER)
        add("StatH",    fontSize=9,  textColor=NAVY,   leading=13, fontName="Helvetica-Bold")
        add("StatV",    fontSize=9,  textColor=DGREY,  leading=13, fontName="Helvetica")

    # ── callbacks ─────────────────────────────────────────────────────────────

    def _cb_title(self, c, doc):
        w, h = A4
        c.saveState()
        c.setFillColor(NAVY)
        c.rect(0, 0, w, h, fill=1, stroke=0)
        # decorative stripe
        c.setFillColor(BLUE)
        c.rect(0, h * 0.35, w, 4, fill=1, stroke=0)
        c.restoreState()

    def _cb_page(self, c, doc):
        self._page += 1
        w, h = A4
        c.saveState()
        c.setFillColor(NAVY)
        c.rect(0, 0, w, 18*mm, fill=1, stroke=0)
        c.setFillColor(TEAL)
        c.rect(0, 17.5*mm, w, 1.5*mm, fill=1, stroke=0)
        c.setFillColor(WHITE)
        c.setFont("Helvetica", 7.5)
        c.drawCentredString(w / 2, 6*mm,
            f"HK Financial Sector Jobs Report  •  Generated: {self.today}  •  deepseek-chat enrichment")
        c.drawRightString(w - 12*mm, 6*mm, f"Page {self._page}")
        # top rule
        c.setStrokeColor(LBLUE)
        c.setLineWidth(0.5)
        c.line(12*mm, h - 12*mm, w - 12*mm, h - 12*mm)
        c.restoreState()

    # ── pages ─────────────────────────────────────────────────────────────────

    def title_page(self, n_jobs: int, n_co: int) -> None:
        S = self.S
        self.story += [
            Spacer(1, 5.5*cm),
            Paragraph("Hong Kong Financial Sector", S["RTitle"]),
            Paragraph("Jobs Intelligence Report", S["RTitle"]),
            Spacer(1, 0.8*cm),
            HRFlowable(width="55%", thickness=1.5, color=TEAL, hAlign="CENTER"),
            Spacer(1, 0.8*cm),
            Paragraph(f"<b>{n_jobs:,}</b> active positions  ·  <b>{n_co}</b> companies", S["RSub"]),
            Paragraph(f"Report date: {self.today}", S["RMeta"]),
            Spacer(1, 1.5*cm),
            Paragraph("Enriched via DeepSeek AI  ·  Sources: Workday · Eightfold · JobsDB", S["RSub"]),
            PageBreak(),
        ]

    def summary_page(self, jobs: list[dict], by_cat: dict) -> None:
        S = self.S

        # ── stat boxes row ────────────────────────────────────────────────────
        with_sal  = sum(1 for j in jobs if j["salary_hkd_min"])
        with_sk   = sum(1 for j in jobs
                        if j["required_skills"] and j["required_skills"] != "[]")
        with_exp  = sum(1 for j in jobs if j["years_experience_required"])

        def box(label, value, sub=""):
            return Table(
                [[Paragraph(value, ParagraphStyle("bv", fontSize=18, fontName="Helvetica-Bold",
                                                  textColor=NAVY, alignment=TA_CENTER))],
                 [Paragraph(label, ParagraphStyle("bl", fontSize=8, fontName="Helvetica",
                                                  textColor=DGREY, alignment=TA_CENTER))],
                 [Paragraph(sub,   ParagraphStyle("bs", fontSize=7, fontName="Helvetica",
                                                  textColor=LGREY, alignment=TA_CENTER))]],
                colWidths=[4.3*cm],
                style=[("BOX",(0,0),(-1,-1),0.5,LGREY),
                       ("BACKGROUND",(0,0),(-1,-1),GREY),
                       ("TOPPADDING",(0,0),(-1,-1),6),
                       ("BOTTOMPADDING",(0,0),(-1,-1),6)],
            )

        sen_counts = Counter(j["seniority"] for j in jobs)
        rem_counts = Counter(j["remote_type"] or "unknown" for j in jobs)
        src_counts = Counter(fmt_source(j["source"]) for j in jobs)
        cat_counts = {c: len(by_cat.get(c,[])) for c in CATEGORY_ORDER if c in by_cat}

        boxes = Table([[
            box("Total Jobs",       f"{len(jobs):,}"),
            box("Companies",        str(len({j['company'] for j in jobs}))),
            box("With Skills",      f"{with_sk:,}",  f"{with_sk*100//len(jobs)}% coverage"),
            box("With Salary",      str(with_sal),   f"{with_sal*100//len(jobs)}% coverage"),
        ]], colWidths=[4.4*cm]*4,
           style=[("LEFTPADDING",(0,0),(-1,-1),3),("RIGHTPADDING",(0,0),(-1,-1),3)])

        self.story += [
            Paragraph("Executive Summary", S["SecHead"]),
            HRFlowable(width="100%", thickness=2, color=BLUE),
            Spacer(1, 0.3*cm),
            boxes,
            Spacer(1, 0.5*cm),
        ]

        # ── side-by-side charts ────────────────────────────────────────────────
        def stat_table(title, data: dict):
            rows = [[Paragraph(title, S["StatH"]), Paragraph("Count", S["StatH"])]]
            for k, v in list(data.items())[:12]:
                rows.append([Paragraph(str(k), S["StatV"]), Paragraph(str(v), S["StatV"])])
            t = Table(rows, colWidths=[5.8*cm, 1.8*cm])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0,0),(-1,0), NAVY),
                ("TEXTCOLOR",  (0,0),(-1,0), WHITE),
                ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,GREY]),
                ("GRID",(0,0),(-1,-1),0.3,LGREY),
                ("TOPPADDING",(0,0),(-1,-1),3),
                ("BOTTOMPADDING",(0,0),(-1,-1),3),
                ("FONTSIZE",(0,0),(-1,-1),8),
            ]))
            return t

        co_counts = Counter(j["company"] for j in jobs)

        side = Table([[
            stat_table("Category", cat_counts),
            stat_table("Seniority", dict(sen_counts.most_common())),
            stat_table("Source", src_counts),
            stat_table("Remote Type", dict(rem_counts.most_common())),
        ]], colWidths=[7.8*cm]*2 + [4.8*cm]*2,
            style=[("VALIGN",(0,0),(-1,-1),"TOP"),
                   ("LEFTPADDING",(0,0),(-1,-1),3),
                   ("RIGHTPADDING",(0,0),(-1,-1),3)])

        self.story.append(side)
        self.story.append(Spacer(1, 0.4*cm))

        # ── top companies table ────────────────────────────────────────────────
        self.story.append(Paragraph("Top Companies by Job Count", S["AppHead"]))
        top_co = co_counts.most_common(15)
        co_rows = [[Paragraph("Company", S["StatH"]),
                    Paragraph("Jobs", S["StatH"]),
                    Paragraph("Top Category", S["StatH"]),
                    Paragraph("Sources", S["StatH"])]]
        for co, cnt in top_co:
            co_jobs = [j for j in jobs if j["company"] == co]
            top_cat = Counter(j["job_category"] for j in co_jobs).most_common(1)[0][0]
            srcs    = ", ".join(sorted({fmt_source(j["source"]) for j in co_jobs}))
            co_rows.append([
                Paragraph(co, S["StatV"]),
                Paragraph(str(cnt), S["StatV"]),
                Paragraph(top_cat, S["StatV"]),
                Paragraph(srcs, S["StatV"]),
            ])
        co_tbl = Table(co_rows, colWidths=[8*cm, 2*cm, 4*cm, 4.8*cm])
        co_tbl.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),NAVY),
            ("TEXTCOLOR", (0,0),(-1,0),WHITE),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,GREY]),
            ("GRID",(0,0),(-1,-1),0.3,LGREY),
            ("TOPPADDING",(0,0),(-1,-1),3),
            ("BOTTOMPADDING",(0,0),(-1,-1),3),
            ("FONTSIZE",(0,0),(-1,-1),8),
        ]))
        self.story.append(co_tbl)
        self.story.append(PageBreak())

    def toc_page(self, by_cat: dict) -> None:
        S = self.S
        self.story.append(Paragraph("Contents", S["SecHead"]))
        self.story.append(HRFlowable(width="100%", thickness=2, color=BLUE))
        self.story.append(Spacer(1, 0.4*cm))
        self.story.append(Paragraph("Part A — Jobs by Category", S["AppHead"]))
        for i, cat in enumerate(CATEGORY_ORDER, 1):
            if cat in by_cat:
                n = len(by_cat[cat])
                self.story.append(
                    Paragraph(f"&nbsp;&nbsp;{i}. {cat} — <font color='#2C6FAC'>{n} jobs</font>", S["TocLine"]))
        self.story.append(Spacer(1, 0.3*cm))
        self.story.append(Paragraph("Part B — Data Appendix", S["AppHead"]))
        for item in ["Top 20 Skills", "Experience by Seniority", "Salary by Category",
                     "Remote Type by Company"]:
            self.story.append(Paragraph(f"&nbsp;&nbsp;· {item}", S["TocLine"]))
        self.story.append(PageBreak())

    def category_section(self, cat: str, jobs: list[dict]) -> None:
        S = self.S
        print(f"Processing {cat} category ({len(jobs)} jobs)...")

        self.story.append(Paragraph(f"{cat}  —  {len(jobs):,} positions", S["SecHead"]))
        self.story.append(HRFlowable(width="100%", thickness=2, color=BLUE))
        self.story.append(Spacer(1, 0.2*cm))

        cols = ["Company", "Job Title", "Level", "Required Skills", "Remote", "Salary", "Exp", "Source"]
        cw   = [3.5*cm, 5.8*cm, 1.5*cm, 5.2*cm, 1.5*cm, 2.5*cm, 1.2*cm, 1.6*cm]

        header = [Paragraph(h, ParagraphStyle("th", fontSize=7.5, fontName="Helvetica-Bold",
                                               textColor=WHITE, alignment=TA_CENTER))
                  for h in cols]
        rows = [header]

        for j in jobs:
            sen = (j.get("seniority") or "mid").lower()
            sc  = SEN_COL.get(sen, colors.black)
            sb  = SEN_BG.get(sen, WHITE)
            rem = j.get("remote_type") or ""
            rem_label = REMOTE_LABEL.get(rem, rem[:8] if rem else "—")

            rows.append([
                Paragraph(j["company"][:30],                                     S["CellB"]),
                Paragraph(j["title"][:75],                                       S["Cell"]),
                Paragraph(f'<font color="{sc.hexval()}">{sen.capitalize()}</font>', S["CellSen"]),
                Paragraph(fmt_skills(j.get("required_skills"), 65),              S["CellS"]),
                Paragraph(rem_label,                                              S["CellS"]),
                Paragraph(fmt_salary(j.get("salary_hkd_min"), j.get("salary_hkd_max")), S["CellS"]),
                Paragraph(fmt_exp(j.get("years_experience_required")),           S["CellS"]),
                Paragraph(fmt_source(j.get("source","")),                        S["CellS"]),
            ])

        t = Table(rows, colWidths=cw, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND",     (0,0),(-1,0), NAVY),
            ("ROWBACKGROUNDS", (0,1),(-1,-1), [WHITE, GREY]),
            ("GRID",           (0,0),(-1,-1), 0.25, LGREY),
            ("VALIGN",         (0,0),(-1,-1), "TOP"),
            ("TOPPADDING",     (0,0),(-1,-1), 2),
            ("BOTTOMPADDING",  (0,0),(-1,-1), 2),
            ("LEFTPADDING",    (0,0),(-1,-1), 3),
            ("RIGHTPADDING",   (0,0),(-1,-1), 3),
            ("ALIGN",          (2,0),(2,-1),  "CENTER"),   # seniority centred
            ("ALIGN",          (4,0),(6,-1),  "CENTER"),   # remote/salary/exp centred
        ]))

        self.story.append(t)
        self.story.append(PageBreak())

    def appendix(self, jobs: list[dict]) -> None:
        S = self.S
        self.story.append(Paragraph("Part B — Data Appendix", S["SecHead"]))
        self.story.append(HRFlowable(width="100%", thickness=2, color=BLUE))
        self.story.append(Spacer(1, 0.4*cm))

        # ── top skills ────────────────────────────────────────────────────────
        self.story.append(Paragraph("Top 20 In-Demand Skills", S["AppHead"]))
        sk_data = top_skills(jobs, 20)
        sk_rows = [[Paragraph("Skill", S["StatH"]), Paragraph("Frequency", S["StatH"]),
                    Paragraph("Skill", S["StatH"]), Paragraph("Frequency", S["StatH"])]]
        half = len(sk_data) // 2
        for i in range(half):
            l_sk, l_n = sk_data[i]
            r_sk, r_n = sk_data[i + half] if i + half < len(sk_data) else ("", "")
            sk_rows.append([
                Paragraph(l_sk.title(), S["StatV"]), Paragraph(str(l_n), S["StatV"]),
                Paragraph(r_sk.title() if r_sk else "", S["StatV"]),
                Paragraph(str(r_n) if r_n else "", S["StatV"]),
            ])
        sk_tbl = Table(sk_rows, colWidths=[6.5*cm, 2.5*cm, 6.5*cm, 2.5*cm])
        sk_tbl.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),NAVY),("TEXTCOLOR",(0,0),(-1,0),WHITE),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,GREY]),
            ("GRID",(0,0),(-1,-1),0.3,LGREY),
            ("FONTSIZE",(0,0),(-1,-1),8),
            ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
        ]))
        self.story.append(sk_tbl)
        self.story.append(Spacer(1, 0.5*cm))

        # ── experience by seniority ───────────────────────────────────────────
        self.story.append(Paragraph("Years of Experience Required by Seniority", S["AppHead"]))
        exp_rows = [[Paragraph("Seniority", S["StatH"]),
                     Paragraph("Jobs with Exp Data", S["StatH"]),
                     Paragraph("Avg Years Required", S["StatH"]),
                     Paragraph("Range", S["StatH"])]]
        for sen in ["junior","mid","senior","lead"]:
            sen_jobs = [j for j in jobs if (j.get("seniority") or "").lower() == sen
                        and j.get("years_experience_required")]
            if sen_jobs:
                yrs = [j["years_experience_required"] for j in sen_jobs]
                avg = sum(yrs) / len(yrs)
                rng = f"{min(yrs)}–{max(yrs)} yrs"
            else:
                avg, rng = 0, "—"
            exp_rows.append([
                Paragraph(sen.capitalize(), S["StatV"]),
                Paragraph(str(len(sen_jobs)), S["StatV"]),
                Paragraph(f"{avg:.1f} yrs" if avg else "—", S["StatV"]),
                Paragraph(rng, S["StatV"]),
            ])
        exp_tbl = Table(exp_rows, colWidths=[4*cm, 5*cm, 5*cm, 4.8*cm])
        exp_tbl.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),NAVY),("TEXTCOLOR",(0,0),(-1,0),WHITE),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,GREY]),
            ("GRID",(0,0),(-1,-1),0.3,LGREY),
            ("FONTSIZE",(0,0),(-1,-1),8),
            ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ]))
        self.story.append(exp_tbl)
        self.story.append(Spacer(1, 0.5*cm))

        # ── salary by category ────────────────────────────────────────────────
        self.story.append(Paragraph("Salary Ranges by Category (where disclosed)", S["AppHead"]))
        sal_rows = [[Paragraph("Category", S["StatH"]),
                     Paragraph("Jobs", S["StatH"]),
                     Paragraph("With Salary", S["StatH"]),
                     Paragraph("Avg Min (HKD)", S["StatH"]),
                     Paragraph("Avg Max (HKD)", S["StatH"])]]
        for cat in CATEGORY_ORDER:
            cat_jobs = [j for j in jobs if (j.get("job_category") or "Other") == cat]
            sal_jobs = [j for j in cat_jobs if j.get("salary_hkd_min")]
            avg_min  = int(sum(j["salary_hkd_min"] for j in sal_jobs) / len(sal_jobs)) if sal_jobs else None
            avg_max  = int(sum(j["salary_hkd_max"] for j in sal_jobs if j.get("salary_hkd_max")) /
                           max(1, sum(1 for j in sal_jobs if j.get("salary_hkd_max"))))  if sal_jobs else None
            sal_rows.append([
                Paragraph(cat, S["StatV"]),
                Paragraph(str(len(cat_jobs)), S["StatV"]),
                Paragraph(str(len(sal_jobs)), S["StatV"]),
                Paragraph(f"{avg_min:,}" if avg_min else "—", S["StatV"]),
                Paragraph(f"{avg_max:,}" if avg_max else "—", S["StatV"]),
            ])
        sal_tbl = Table(sal_rows, colWidths=[3.8*cm, 2*cm, 3*cm, 4.5*cm, 4.5*cm])
        sal_tbl.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),NAVY),("TEXTCOLOR",(0,0),(-1,0),WHITE),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,GREY]),
            ("GRID",(0,0),(-1,-1),0.3,LGREY),
            ("FONTSIZE",(0,0),(-1,-1),8),
            ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ]))
        self.story.append(sal_tbl)
        self.story.append(Spacer(1, 0.5*cm))

        # ── remote type by company (top 15) ───────────────────────────────────
        self.story.append(Paragraph("Remote Type Distribution — Top 15 Companies", S["AppHead"]))
        co_set = [co for co, _ in Counter(j["company"] for j in jobs).most_common(15)]
        rem_types = ["on-site", "hybrid", "remote"]
        hdr = [Paragraph("Company", S["StatH"])] + [Paragraph(r.capitalize(), S["StatH"]) for r in rem_types]
        rem_rows = [hdr]
        for co in co_set:
            co_j = [j for j in jobs if j["company"] == co]
            rc = Counter(j.get("remote_type") or "on-site" for j in co_j)
            rem_rows.append([Paragraph(co, S["StatV"])] +
                            [Paragraph(str(rc.get(r, 0)), S["StatV"]) for r in rem_types])
        rem_tbl = Table(rem_rows, colWidths=[8*cm, 3*cm, 3*cm, 3*cm])
        rem_tbl.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),NAVY),("TEXTCOLOR",(0,0),(-1,0),WHITE),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,GREY]),
            ("GRID",(0,0),(-1,-1),0.3,LGREY),
            ("FONTSIZE",(0,0),(-1,-1),8),
            ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ]))
        self.story.append(rem_tbl)

    # ── build ─────────────────────────────────────────────────────────────────

    def build(self, jobs: list[dict]) -> int:
        by_cat = by_category(jobs)
        n_co   = len({j["company"] for j in jobs})

        doc = SimpleDocTemplate(
            self.out,
            pagesize=A4,
            leftMargin=1.2*cm, rightMargin=1.2*cm,
            topMargin=1.8*cm,  bottomMargin=2.2*cm,
        )

        self.title_page(len(jobs), n_co)
        self.summary_page(jobs, by_cat)
        self.toc_page(by_cat)
        for cat in CATEGORY_ORDER:
            if cat in by_cat:
                self.category_section(cat, by_cat[cat])
        self.appendix(jobs)

        doc.build(self.story,
                  onFirstPage=self._cb_title,
                  onLaterPages=self._cb_page)
        return self._page


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    db  = Path(__file__).parent.parent / "data" / "jobs.db"
    out = Path(__file__).parent.parent / "outputs" / "HK_Jobs_Full_Data_Report.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)

    print("Loading jobs from database…")
    jobs = load_jobs(str(db))
    print(f"Found {len(jobs)} enriched jobs\n")

    report = FullReport(str(out))
    pages  = report.build(jobs)

    size_kb = out.stat().st_size // 1024
    print(f"\n✅ PDF created: {out}")
    print(f"   {pages} pages · {size_kb} KB")


if __name__ == "__main__":
    main()
