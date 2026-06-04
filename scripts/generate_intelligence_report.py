"""
Generate a comprehensive PDF: architecture overview + all 1,592 jobs.
Output: outputs/HK_Job_Market_Intelligence_Report.pdf
"""

import json
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    HRFlowable, KeepTogether, PageBreak, Paragraph,
    SimpleDocTemplate, Spacer, Table, TableStyle,
)

# ── Palette ────────────────────────────────────────────────────────────────────
NAVY   = colors.HexColor("#1A3A5C")
BLUE   = colors.HexColor("#185FA5")
LBLUE  = colors.HexColor("#D6E8F7")
TEAL   = colors.HexColor("#1ABC9C")
WHITE  = colors.white
GREY   = colors.HexColor("#F5F5F5")
LGREY  = colors.HexColor("#CCCCCC")
DGREY  = colors.HexColor("#555555")
SEN_COL = {
    "lead":   colors.HexColor("#C0392B"),
    "senior": colors.HexColor("#185FA5"),
    "mid":    colors.HexColor("#27AE60"),
    "junior": colors.HexColor("#888888"),
}

TODAY   = date.today().strftime("%d %b %Y")
DB_PATH = Path(__file__).parent.parent / "data" / "jobs.db"
OUT_DIR = Path(__file__).parent.parent / "outputs"

COMPANY_ORDER_KEY = lambda name: name  # alphabetical within section


# ── Data helpers ───────────────────────────────────────────────────────────────

def load_data():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT j.company, j.company_slug, j.title, j.url, j.posted_at,
               j.source, j.description_clean,
               e.seniority, e.job_category, e.remote_type,
               e.required_skills, e.salary_hkd_min, e.salary_hkd_max
          FROM jobs j
          LEFT JOIN job_enrichments e
            ON j.source=e.source AND j.source_id=e.source_id
         WHERE j.is_active=1
         ORDER BY j.company, e.seniority DESC, j.title
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def group_by_company(jobs):
    d = defaultdict(list)
    for j in jobs:
        d[j["company"]].append(j)
    return dict(sorted(d.items(), key=lambda x: -len(x[1])))  # biggest first


def fmt_date(iso):
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso).strftime("%d %b %Y")
    except Exception:
        return iso[:10]


def fmt_skills(raw, n=3):
    if not raw:
        return "—"
    try:
        sk = json.loads(raw)
    except Exception:
        return raw[:40]
    if not sk:
        return "—"
    shown = ", ".join(sk[:n])
    return shown + (f" +{len(sk)-n}" if len(sk) > n else "")


def fmt_salary(mn, mx):
    if mn and mx:
        return f"{mn//1000}K–{mx//1000}K"
    if mn:
        return f">{mn//1000}K"
    return "N/A"


def top_skills(jobs, n=10):
    c = Counter()
    for j in jobs:
        try:
            for s in json.loads(j.get("required_skills") or "[]"):
                c[s.lower().strip()] += 1
        except Exception:
            pass
    return c.most_common(n)


SOURCE_LABEL = {
    "jobsdb":    "JobsDB",
    "workday":   "Workday",
    "eightfold": "Eightfold",
}


# ── Style builder ──────────────────────────────────────────────────────────────

def build_styles():
    s = getSampleStyleSheet()

    def add(name, **kw):
        s.add(ParagraphStyle(name=name, **kw))

    add("CoverTitle",    fontSize=32, textColor=WHITE,  alignment=TA_CENTER, leading=42, fontName="Helvetica-Bold")
    add("CoverSub",      fontSize=15, textColor=LBLUE,  alignment=TA_CENTER, leading=22, fontName="Helvetica")
    add("CoverMeta",     fontSize=11, textColor=LBLUE,  alignment=TA_CENTER, leading=16, fontName="Helvetica")
    add("SecBanner",     fontSize=18, textColor=WHITE,  alignment=TA_LEFT,   leading=26, fontName="Helvetica-Bold")
    add("SecHead",       fontSize=15, textColor=NAVY,   leading=22,           fontName="Helvetica-Bold", spaceAfter=4)
    add("SubHead",       fontSize=12, textColor=NAVY,   leading=18,           fontName="Helvetica-Bold", spaceBefore=8, spaceAfter=2)
    add("RBodyText",     fontSize=10, textColor=DGREY,  leading=15,           fontName="Helvetica")
    add("CoHead",        fontSize=12, textColor=WHITE,  leading=18,           fontName="Helvetica-Bold")
    add("CoSub",         fontSize=8,  textColor=LBLUE,  leading=12,           fontName="Helvetica")
    add("Cell",          fontSize=7.5,textColor=colors.black, leading=10,    fontName="Helvetica")
    add("CellB",         fontSize=7.5,textColor=NAVY,   leading=10,           fontName="Helvetica-Bold")
    add("CellS",         fontSize=6.5,textColor=DGREY,  leading=9,            fontName="Helvetica")
    add("StatBig",       fontSize=36, textColor=NAVY,   alignment=TA_CENTER, leading=42, fontName="Helvetica-Bold")
    add("StatLabel",     fontSize=9,  textColor=DGREY,  alignment=TA_CENTER, leading=13, fontName="Helvetica")
    add("StepTitle",     fontSize=13, textColor=NAVY,   leading=18,           fontName="Helvetica-Bold")
    add("StepText",      fontSize=10, textColor=DGREY,  leading=15,           fontName="Helvetica")
    add("BoxTitle",      fontSize=11, textColor=NAVY,   leading=16,           fontName="Helvetica-Bold")
    add("BoxText",       fontSize=9,  textColor=DGREY,  leading=14,           fontName="Helvetica")
    add("TocLine",       fontSize=10, textColor=NAVY,   leading=16,           fontName="Helvetica")
    return s


# ── Page callbacks ─────────────────────────────────────────────────────────────

class ReportDoc(SimpleDocTemplate):
    def __init__(self, path, total_pages_ref):
        super().__init__(
            path, pagesize=A4,
            leftMargin=1.5*cm, rightMargin=1.5*cm,
            topMargin=2*cm, bottomMargin=2.5*cm,
        )
        self._pn = 0
        self._total = total_pages_ref  # mutable list [N]

    def _cover_cb(self, canvas, doc):
        w, h = A4
        canvas.saveState()
        canvas.setFillColor(BLUE)
        canvas.rect(0, 0, w, h, fill=1, stroke=0)
        canvas.setFillColor(TEAL)
        canvas.rect(0, h * 0.38, w, 3, fill=1, stroke=0)
        canvas.restoreState()

    def _page_cb(self, canvas, doc):
        self._pn += 1
        w, h = A4
        canvas.saveState()
        canvas.setFillColor(NAVY)
        canvas.rect(0, 0, w, 19*mm, fill=1, stroke=0)
        canvas.setFillColor(TEAL)
        canvas.rect(0, 18.5*mm, w, 1.5*mm, fill=1, stroke=0)
        canvas.setFillColor(WHITE)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawCentredString(
            w / 2, 6.5*mm,
            f"HK Job Board Scraper  ·  Confidential  ·  {TODAY}"
        )
        canvas.drawRightString(w - 15*mm, 6.5*mm, f"Page {self._pn}")
        canvas.setStrokeColor(LBLUE)
        canvas.setLineWidth(0.4)
        canvas.line(15*mm, h - 12*mm, w - 15*mm, h - 12*mm)
        canvas.restoreState()

    def build(self, story):
        super().build(story, onFirstPage=self._cover_cb, onLaterPages=self._page_cb)


# ── Story builder ──────────────────────────────────────────────────────────────

class StoryBuilder:
    def __init__(self, S, jobs, by_co):
        self.S = S
        self.jobs = jobs
        self.by_co = by_co
        self.story = []

    # ── helpers ────────────────────────────────────────────────────────────────

    def _banner(self, text, bg=BLUE):
        tbl = Table(
            [[Paragraph(text, self.S["SecBanner"])]],
            colWidths=[17.7*cm],
        )
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), bg),
            ("LEFTPADDING", (0,0), (-1,-1), 12),
            ("TOPPADDING", (0,0), (-1,-1), 10),
            ("BOTTOMPADDING", (0,0), (-1,-1), 10),
        ]))
        return tbl

    def _stat_box(self, value, label):
        tbl = Table([
            [Paragraph(value, self.S["StatBig"])],
            [Paragraph(label, self.S["StatLabel"])],
        ], colWidths=[4.2*cm])
        tbl.setStyle(TableStyle([
            ("BOX", (0,0), (-1,-1), 0.5, LGREY),
            ("BACKGROUND", (0,0), (-1,-1), GREY),
            ("TOPPADDING", (0,0), (-1,-1), 8),
            ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ]))
        return tbl

    def _mini_table(self, title, rows, col_w=None):
        S = self.S
        header = [[Paragraph(title, ParagraphStyle("_mh", fontSize=8, fontName="Helvetica-Bold",
                                                    textColor=WHITE))]]
        data_rows = [[Paragraph(str(k), S["CellB"]), Paragraph(str(v), S["Cell"])]
                     for k, v in rows]
        col_w = col_w or [7*cm, 2.5*cm]
        t = Table(header + data_rows, colWidths=col_w)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), NAVY),
            ("SPAN", (0,0), (-1,0)),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [WHITE, GREY]),
            ("GRID", (0,0), (-1,-1), 0.3, LGREY),
            ("TOPPADDING", (0,0), (-1,-1), 3),
            ("BOTTOMPADDING", (0,0), (-1,-1), 3),
            ("LEFTPADDING", (0,0), (-1,-1), 5),
        ]))
        return t

    def _step_block(self, icon, title, body, tag):
        S = self.S
        inner = Table([
            [Paragraph(icon, ParagraphStyle("_ic", fontSize=28, textColor=BLUE, alignment=TA_CENTER)),
             Table([
                 [Paragraph(title, S["StepTitle"])],
                 [Paragraph(body,  S["StepText"])],
                 [Paragraph(tag,   ParagraphStyle("_tg", fontSize=8, textColor=TEAL,
                                                   fontName="Helvetica-Bold"))],
             ], colWidths=[13*cm])],
        ], colWidths=[2.5*cm, 13*cm])
        inner.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("LEFTPADDING", (0,0), (-1,-1), 6),
        ]))
        outer = Table([[inner]], colWidths=[16.5*cm])
        outer.setStyle(TableStyle([
            ("BOX", (0,0), (-1,-1), 0.8, BLUE),
            ("BACKGROUND", (0,0), (-1,-1), GREY),
            ("TOPPADDING", (0,0), (-1,-1), 10),
            ("BOTTOMPADDING", (0,0), (-1,-1), 10),
            ("LEFTPADDING", (0,0), (-1,-1), 8),
        ]))
        return outer

    def _source_box(self, title, subtitle, companies):
        S = self.S
        co_text = ", ".join(companies[:6])
        if len(companies) > 6:
            co_text += f" +{len(companies)-6} more"
        t = Table([
            [Paragraph(title,    S["BoxTitle"])],
            [Paragraph(subtitle, S["BoxText"])],
            [Paragraph(co_text,  ParagraphStyle("_co", fontSize=8, textColor=DGREY,
                                                 fontName="Helvetica"))],
        ], colWidths=[5.3*cm])
        t.setStyle(TableStyle([
            ("BOX", (0,0), (-1,-1), 0.8, BLUE),
            ("BACKGROUND", (0,0), (0,0), LBLUE),
            ("TOPPADDING", (0,0), (-1,-1), 6),
            ("BOTTOMPADDING", (0,0), (-1,-1), 6),
            ("LEFTPADDING", (0,0), (-1,-1), 8),
        ]))
        return t

    # ── pages ──────────────────────────────────────────────────────────────────

    def cover(self):
        S = self.S
        n = len(self.jobs)
        self.story += [
            Spacer(1, 5.5*cm),
            Paragraph("Hong Kong Financial Sector", S["CoverTitle"]),
            Paragraph("Job Market Intelligence Report", S["CoverTitle"]),
            Spacer(1, 0.8*cm),
            HRFlowable(width="50%", thickness=1.5, color=TEAL, hAlign="CENTER"),
            Spacer(1, 0.8*cm),
            Paragraph(f"<b>{n:,}</b> active job listings across <b>27</b> financial companies", S["CoverSub"]),
            Spacer(1, 0.3*cm),
            Paragraph("AI-enriched  ·  99.9% description coverage  ·  Daily updates", S["CoverMeta"]),
            Spacer(1, 0.3*cm),
            Paragraph(f"Report date: {TODAY}", S["CoverMeta"]),
            Spacer(1, 1.5*cm),
            Paragraph("Powered by HK Job Board Scraper", S["CoverSub"]),
            PageBreak(),
        ]
        print("Generating cover page...")

    def architecture(self):
        S = self.S
        jobs = self.jobs
        by_src = Counter(j["source"] for j in jobs)
        by_sen = Counter((j.get("seniority") or "unknown").lower() for j in jobs)
        by_cat = Counter(j.get("job_category") or "Other" for j in jobs)
        by_co  = Counter(j["company"] for j in jobs)
        skills = top_skills(jobs, 10)

        print("Generating architecture section...")

        # ── What Is This? ───────────────────────────────────────────────────
        self.story.append(self._banner("Section 1 — How This Works"))
        self.story.append(Spacer(1, 0.4*cm))
        self.story.append(Paragraph("We track who's hiring in Hong Kong finance — automatically, every day.", S["SecHead"]))
        self.story.append(Spacer(1, 0.4*cm))

        steps = [
            ("🔍", "Step 1: Collect",
             "Every morning at 2 AM, our system visits 27 company job pages automatically "
             "and collects all available job listings — up to 5 pages per company.",
             "27 companies  ·  3 job platforms  ·  1,592 jobs"),
            ("📄", "Step 2: Read",
             "For each job found, we fetch the full job description — what the company is "
             "actually looking for in a candidate. We use direct API connections where available "
             "(Workday, Eightfold, JobsDB GraphQL) so this step takes under 2 minutes.",
             "99.9% of jobs have full descriptions"),
            ("🤖", "Step 3: Understand",
             "We use DeepSeek AI to read each description and extract structured data: "
             "seniority level, required skills, job category, and remote type. "
             "Every job is enriched — even those with short or cryptic titles.",
             "All 1,592 jobs enriched  ·  avg 5.0 skills per job"),
        ]
        for icon, title, body, tag in steps:
            self.story.append(self._step_block(icon, title, body, tag))
            self.story.append(Spacer(1, 0.4*cm))
        self.story.append(PageBreak())

        # ── Where Does Data Come From? ───────────────────────────────────────
        self.story.append(self._banner("Where Does the Data Come From?"))
        self.story.append(Spacer(1, 0.5*cm))

        jobsdb_cos   = sorted([j["company"] for j in jobs if j["source"] == "jobsdb"],
                               key=lambda x: -by_co[x])
        jobsdb_cos   = list(dict.fromkeys(jobsdb_cos))
        workday_cos  = sorted(list(dict.fromkeys(
            j["company"] for j in jobs if j["source"] == "workday")))
        ef_cos       = sorted(list(dict.fromkeys(
            j["company"] for j in jobs if j["source"] == "eightfold")))

        boxes = Table([[
            self._source_box(
                f"JobsDB  ({by_src['jobsdb']:,} jobs)",
                "Hong Kong's most popular job board. Our smart browser "
                "automatically visits each company's listing page and reads "
                "all jobs — just like a human, but faster. Uses Cloudflare bypass.",
                jobsdb_cos,
            ),
            self._source_box(
                f"Workday  ({by_src['workday']:,} jobs)",
                "AIA, Prudential, FWD, and Sun Life use Workday — a corporate "
                "HR platform. We call its JSON API directly: no browser needed, "
                "results in seconds.",
                workday_cos,
            ),
            self._source_box(
                f"Eightfold  ({by_src['eightfold']:,} jobs)",
                "HSBC uses Eightfold AI for recruitment. Same approach — "
                "direct API call, very fast. HSBC's Eightfold also includes "
                "Hang Seng Bank roles.",
                ef_cos,
            ),
        ]], colWidths=[5.7*cm, 5.7*cm, 5.7*cm])
        boxes.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING", (0,0), (-1,-1), 4),
            ("RIGHTPADDING", (0,0), (-1,-1), 4),
        ]))
        self.story.append(boxes)
        self.story.append(PageBreak())

        # ── By The Numbers ───────────────────────────────────────────────────
        self.story.append(self._banner("By The Numbers"))
        self.story.append(Spacer(1, 0.5*cm))

        stat_row = Table([[
            self._stat_box("1,592", "Active job listings"),
            self._stat_box("27",    "Companies tracked"),
            self._stat_box("~15",   "Minutes to update"),
            self._stat_box("99.9%", "Description coverage"),
        ]], colWidths=[4.4*cm]*4,
           style=[("LEFTPADDING",(0,0),(-1,-1),3),("RIGHTPADDING",(0,0),(-1,-1),3)])
        self.story.append(stat_row)
        self.story.append(Spacer(1, 0.5*cm))

        # Stats side-by-side
        sen_items  = [(k.capitalize(), v) for k, v in
                      sorted(by_sen.items(), key=lambda x: -x[1]) if k != "unknown"]
        cat_items  = [(k, v) for k, v in
                      sorted(by_cat.items(), key=lambda x: -x[1])]
        co_items   = [(co, cnt) for co, cnt in by_co.most_common(15)]
        skill_items = [(s.title(), n) for s, n in skills]

        side = Table([[
            self._mini_table("Jobs by Category",   cat_items,  [7*cm, 2.5*cm]),
            self._mini_table("Jobs by Seniority",  sen_items,  [6*cm, 2.5*cm]),
            self._mini_table("Top Skills",         skill_items,[8*cm, 2.5*cm]),
        ]], colWidths=[9.5*cm, 8.8*cm, 10.5*cm],
           style=[("VALIGN",(0,0),(-1,-1),"TOP"),
                  ("LEFTPADDING",(0,0),(-1,-1),3),
                  ("RIGHTPADDING",(0,0),(-1,-1),3)])
        self.story.append(side)
        self.story.append(Spacer(1, 0.4*cm))
        self.story.append(self._mini_table("Top 15 Companies by Job Count", co_items, [11*cm, 3*cm]))
        self.story.append(PageBreak())

    def jobs_section(self):
        S = self.S
        total = len(self.by_co)
        print("Generating jobs section...")

        self.story.append(self._banner("Section 2 — All Jobs (Complete Database)"))
        self.story.append(Spacer(1, 0.3*cm))
        self.story.append(Paragraph(
            f"All {len(self.jobs):,} active jobs across {total} companies, "
            "sorted by company then seniority. Seniority is colour-coded: "
            "<font color='#C0392B'>Lead</font>  "
            "<font color='#185FA5'>Senior</font>  "
            "<font color='#27AE60'>Mid</font>  "
            "<font color='#888888'>Junior</font>",
            S["RBodyText"],
        ))
        self.story.append(Spacer(1, 0.3*cm))

        col_w = [5.0*cm, 1.6*cm, 2.0*cm, 5.5*cm, 1.5*cm, 2.0*cm]
        HEADERS = ["Job Title", "Level", "Category", "Key Skills", "Remote", "Posted"]

        for idx, (company, jobs) in enumerate(self.by_co.items(), 1):
            src = SOURCE_LABEL.get(jobs[0]["source"], jobs[0]["source"])
            print(f"  Processing company {idx}/{total}: {company} ({len(jobs)} jobs)...")

            # Company header block
            hdr = Table([[
                Paragraph(f"{company}  —  {len(jobs)} jobs", S["CoHead"]),
                Paragraph(f"{src}  ·  Updated: {TODAY}", S["CoSub"]),
            ]], colWidths=[12*cm, 5.5*cm])
            hdr.setStyle(TableStyle([
                ("BACKGROUND", (0,0), (-1,-1), NAVY),
                ("LEFTPADDING", (0,0), (-1,-1), 10),
                ("TOPPADDING", (0,0), (-1,-1), 8),
                ("BOTTOMPADDING", (0,0), (-1,-1), 8),
                ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ]))
            self.story.append(KeepTogether([hdr, Spacer(1, 1*mm)]))

            # Job table
            header_row = [
                Paragraph(h, ParagraphStyle("_th", fontSize=7.5, fontName="Helvetica-Bold",
                                             textColor=WHITE, alignment=TA_CENTER))
                for h in HEADERS
            ]
            table_data = [header_row]

            for j in jobs:
                sen = (j.get("seniority") or "mid").lower()
                sc  = SEN_COL.get(sen, colors.black)
                rem = (j.get("remote_type") or "on-site").replace("on-site", "Office")
                rem = rem.replace("hybrid", "Hybrid").replace("remote", "Remote")

                table_data.append([
                    Paragraph(j["title"][:48],                              S["CellB"]),
                    Paragraph(f'<font color="{sc.hexval()}">{sen.capitalize()}</font>',
                              ParagraphStyle("_sen", fontSize=7, fontName="Helvetica-Bold",
                                             leading=10, alignment=TA_CENTER)),
                    Paragraph((j.get("job_category") or "Other")[:14],     S["CellS"]),
                    Paragraph(fmt_skills(j.get("required_skills"), 3),     S["CellS"]),
                    Paragraph(rem[:8],                                       S["CellS"]),
                    Paragraph(fmt_date(j.get("posted_at")),                 S["CellS"]),
                ])

            t = Table(table_data, colWidths=col_w, repeatRows=1)
            t.setStyle(TableStyle([
                ("BACKGROUND",      (0,0),(-1,0), NAVY),
                ("ROWBACKGROUNDS",  (0,1),(-1,-1), [WHITE, GREY]),
                ("GRID",            (0,0),(-1,-1), 0.25, LGREY),
                ("VALIGN",          (0,0),(-1,-1), "TOP"),
                ("TOPPADDING",      (0,0),(-1,-1), 2),
                ("BOTTOMPADDING",   (0,0),(-1,-1), 2),
                ("LEFTPADDING",     (0,0),(-1,-1), 3),
                ("RIGHTPADDING",    (0,0),(-1,-1), 3),
                ("ALIGN",           (1,0),(1,-1),  "CENTER"),
                ("ALIGN",           (4,0),(5,-1),  "CENTER"),
            ]))
            self.story.append(t)
            self.story.append(Spacer(1, 0.5*cm))

    def build(self, out_path):
        self.cover()
        self.architecture()
        self.jobs_section()

        doc = SimpleDocTemplate(
            out_path, pagesize=A4,
            leftMargin=1.5*cm, rightMargin=1.5*cm,
            topMargin=2*cm, bottomMargin=2.5*cm,
        )

        _page = [0]

        def on_first(canvas, doc):
            w, h = A4
            canvas.saveState()
            canvas.setFillColor(BLUE)
            canvas.rect(0, 0, w, h, fill=1, stroke=0)
            canvas.setFillColor(TEAL)
            canvas.rect(0, h * 0.38, w, 3, fill=1, stroke=0)
            canvas.restoreState()

        def on_later(canvas, doc):
            _page[0] += 1
            w, h = A4
            canvas.saveState()
            canvas.setFillColor(NAVY)
            canvas.rect(0, 0, w, 19*mm, fill=1, stroke=0)
            canvas.setFillColor(TEAL)
            canvas.rect(0, 18.5*mm, w, 1.5*mm, fill=1, stroke=0)
            canvas.setFillColor(WHITE)
            canvas.setFont("Helvetica", 7.5)
            canvas.drawCentredString(w/2, 6.5*mm,
                f"HK Job Board Scraper  ·  Confidential  ·  {TODAY}")
            canvas.drawRightString(w-15*mm, 6.5*mm, f"Page {_page[0]}")
            canvas.setStrokeColor(LBLUE)
            canvas.setLineWidth(0.4)
            canvas.line(15*mm, h-12*mm, w-15*mm, h-12*mm)
            canvas.restoreState()

        doc.build(self.story, onFirstPage=on_first, onLaterPages=on_later)
        return _page[0]


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "HK_Job_Market_Intelligence_Report.pdf"

    print("Loading data from database...")
    jobs   = load_data()
    by_co  = group_by_company(jobs)
    print(f"Loaded {len(jobs):,} active jobs across {len(by_co)} companies\n")

    S = build_styles()
    builder = StoryBuilder(S, jobs, by_co)
    pages = builder.build(str(out))

    size_kb = out.stat().st_size // 1024
    print(f"\n✅ PDF complete: {pages} pages, {size_kb} KB")
    print(f"   Saved to: {out}")


if __name__ == "__main__":
    main()
