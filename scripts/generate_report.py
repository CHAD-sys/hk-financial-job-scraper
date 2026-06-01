"""
Generate a PDF report of all enriched HK financial sector jobs, organised by category.
Output: outputs/HK_Jobs_By_Category.pdf
"""

import json
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    HRFlowable,
    NextPageTemplate,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.doctemplate import PageTemplate
from reportlab.platypus.frames import Frame

# ── colours ──────────────────────────────────────────────────────────────────
NAVY    = colors.HexColor("#1A3A5C")
BLUE    = colors.HexColor("#2C6FAC")
LBLUE   = colors.HexColor("#D6E8F7")
WHITE   = colors.white
GREY    = colors.HexColor("#F5F5F5")
DGREY   = colors.HexColor("#666666")

SENIORITY_COLOURS = {
    "lead":   colors.HexColor("#C0392B"),  # red
    "senior": colors.HexColor("#2C6FAC"),  # blue
    "mid":    colors.HexColor("#27AE60"),  # green
    "junior": colors.HexColor("#95A5A6"),  # grey
}

CATEGORY_ORDER = ["Finance", "Operations", "Sales", "Engineering", "HR", "Other"]

# ── helpers ───────────────────────────────────────────────────────────────────

def fmt_date(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso).strftime("%d %b %Y")
    except ValueError:
        return iso[:10]


def fmt_skills(raw: str | None, max_len: int = 55) -> str:
    if not raw:
        return "—"
    try:
        skills = json.loads(raw)
    except Exception:
        return raw[:max_len]
    joined = ", ".join(skills)
    return joined[:max_len] + "…" if len(joined) > max_len else joined


def load_jobs(db_path: str) -> dict[str, list[dict]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT j.company, j.title, j.posted_at, j.locations,
               e.seniority, e.required_skills, e.remote_type,
               e.job_category, e.years_experience_required
          FROM jobs j
          JOIN job_enrichments e ON j.source=e.source AND j.source_id=e.source_id
         ORDER BY e.job_category, e.seniority DESC, j.company, j.title
    """).fetchall()
    conn.close()

    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_cat[r["job_category"] or "Other"].append(dict(r))
    return by_cat


def count_by(jobs_flat: list[dict], key: str) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for j in jobs_flat:
        counts[j.get(key) or "Unknown"] += 1
    return dict(sorted(counts.items(), key=lambda x: -x[1]))


# ── PDF builder ───────────────────────────────────────────────────────────────

class ReportBuilder:
    def __init__(self, out_path: str) -> None:
        self.out_path = out_path
        self.styles = getSampleStyleSheet()
        self._build_styles()
        self.today = date.today().strftime("%d %b %Y")
        self.story: list = []
        self._page_num = 0

    def _build_styles(self) -> None:
        s = self.styles
        def add(name, **kw):
            s.add(ParagraphStyle(name=name, **kw))

        add("ReportTitle",  fontSize=28, textColor=WHITE,  alignment=TA_CENTER, leading=36, fontName="Helvetica-Bold")
        add("ReportSub",    fontSize=14, textColor=LBLUE,  alignment=TA_CENTER, leading=20, fontName="Helvetica")
        add("ReportMeta",   fontSize=11, textColor=LBLUE,  alignment=TA_CENTER, leading=16, fontName="Helvetica")
        add("SectionHead",  fontSize=16, textColor=NAVY,   leading=22, fontName="Helvetica-Bold", spaceAfter=4)
        add("StatLabel",    fontSize=10, textColor=DGREY,  leading=14, fontName="Helvetica")
        add("StatValue",    fontSize=10, textColor=NAVY,   leading=14, fontName="Helvetica-Bold")
        add("TocEntry",     fontSize=11, textColor=NAVY,   leading=18, fontName="Helvetica")
        add("Footer",       fontSize=8,  textColor=DGREY,  alignment=TA_CENTER, fontName="Helvetica")
        add("CellNormal",   fontSize=8,  textColor=colors.black, leading=11, fontName="Helvetica")
        add("CellBold",     fontSize=8,  textColor=NAVY,   leading=11, fontName="Helvetica-Bold")
        add("CellSmall",    fontSize=7,  textColor=DGREY,  leading=10, fontName="Helvetica")

    # ── page callbacks ────────────────────────────────────────────────────────

    def _on_page(self, canvas, doc) -> None:
        self._page_num += 1
        w, h = A4
        canvas.saveState()
        # footer bar
        canvas.setFillColor(NAVY)
        canvas.rect(0, 0, w, 20*mm, fill=1, stroke=0)
        canvas.setFillColor(WHITE)
        canvas.setFont("Helvetica", 8)
        canvas.drawCentredString(w/2, 7*mm, f"Generated: {self.today}  •  HK Financial Sector Jobs Report")
        canvas.drawRightString(w - 15*mm, 7*mm, f"Page {self._page_num}")
        canvas.restoreState()

    def _on_title_page(self, canvas, doc) -> None:
        w, h = A4
        canvas.saveState()
        canvas.setFillColor(NAVY)
        canvas.rect(0, 0, w, h, fill=1, stroke=0)
        canvas.restoreState()

    # ── pages ─────────────────────────────────────────────────────────────────

    def add_title_page(self, total_jobs: int, n_companies: int) -> None:
        s = self.styles
        self.story += [
            Spacer(1, 6*cm),
            Paragraph("Hong Kong Financial Sector", s["ReportTitle"]),
            Paragraph("Jobs Report", s["ReportTitle"]),
            Spacer(1, 1*cm),
            HRFlowable(width="60%", thickness=1, color=BLUE, hAlign="CENTER"),
            Spacer(1, 1*cm),
            Paragraph(f"Total positions: {total_jobs:,}", s["ReportMeta"]),
            Paragraph(f"Companies covered: {n_companies}", s["ReportMeta"]),
            Paragraph(f"Report date: {self.today}", s["ReportMeta"]),
            Spacer(1, 2*cm),
            Paragraph("Powered by AI enrichment via DeepSeek · Data from Workday, Eightfold & JobsDB", s["ReportSub"]),
            PageBreak(),
        ]

    def add_summary_page(self, by_cat: dict[str, list[dict]]) -> None:
        s = self.styles
        all_jobs = [j for jobs in by_cat.values() for j in jobs]

        self.story.append(Paragraph("Executive Summary", s["SectionHead"]))
        self.story.append(HRFlowable(width="100%", thickness=2, color=BLUE))
        self.story.append(Spacer(1, 0.5*cm))

        # ── stats tables side by side ──────────────────────────────────────
        def mini_table(title: str, data: dict[str, int]) -> Table:
            rows = [[Paragraph(title, s["CellBold"]), ""]]
            for k, v in list(data.items())[:12]:
                rows.append([Paragraph(k, s["CellNormal"]),
                              Paragraph(str(v), s["StatValue"])])
            t = Table(rows, colWidths=[7*cm, 2*cm])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0,0), (-1,0), NAVY),
                ("TEXTCOLOR",  (0,0), (-1,0), WHITE),
                ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
                ("FONTSIZE",   (0,0), (-1,-1), 9),
                ("ROWBACKGROUNDS", (0,1), (-1,-1), [WHITE, GREY]),
                ("GRID", (0,0), (-1,-1), 0.3, colors.lightgrey),
                ("BOTTOMPADDING", (0,0), (-1,-1), 4),
                ("TOPPADDING",    (0,0), (-1,-1), 4),
            ]))
            return t

        cat_counts  = {c: len(by_cat.get(c, [])) for c in CATEGORY_ORDER if c in by_cat}
        sen_counts  = count_by(all_jobs, "seniority")
        co_counts   = count_by(all_jobs, "company")
        rem_counts  = count_by(all_jobs, "remote_type")

        side = Table(
            [[mini_table("Jobs by Category", cat_counts),
              mini_table("Jobs by Seniority", sen_counts)],
             [mini_table("Top Companies", dict(list(co_counts.items())[:12])),
              mini_table("Remote Type", rem_counts)]],
            colWidths=[9.5*cm, 9.5*cm],
            rowHeights=None,
        )
        side.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING",  (0,0), (-1,-1), 4),
            ("RIGHTPADDING", (0,0), (-1,-1), 4),
            ("BOTTOMPADDING",(0,0), (-1,-1), 8),
        ]))
        self.story.append(side)
        self.story.append(PageBreak())

    def add_toc(self, by_cat: dict[str, list[dict]]) -> None:
        s = self.styles
        self.story.append(Paragraph("Table of Contents", s["SectionHead"]))
        self.story.append(HRFlowable(width="100%", thickness=2, color=BLUE))
        self.story.append(Spacer(1, 0.4*cm))
        for i, cat in enumerate(CATEGORY_ORDER, start=1):
            if cat in by_cat:
                n = len(by_cat[cat])
                self.story.append(
                    Paragraph(f"{i}.&nbsp;&nbsp;{cat}&nbsp;&nbsp;<font color='#2C6FAC'>{n} jobs</font>", s["TocEntry"])
                )
        self.story.append(PageBreak())

    def add_category_section(self, category: str, jobs: list[dict]) -> None:
        s = self.styles
        print(f"Processing {category} category ({len(jobs)} jobs)...")

        self.story.append(Paragraph(f"{category} — {len(jobs):,} positions", s["SectionHead"]))
        self.story.append(HRFlowable(width="100%", thickness=2, color=BLUE))
        self.story.append(Spacer(1, 0.3*cm))

        # Table header
        headers = ["Company", "Job Title", "Seniority", "Key Skills", "Remote", "Posted"]
        col_w   = [4.0*cm, 6.5*cm, 1.7*cm, 5.0*cm, 1.6*cm, 2.0*cm]

        table_data = [[Paragraph(h, s["CellBold"]) for h in headers]]

        for j in jobs:
            sen = (j.get("seniority") or "").lower()
            sen_col = SENIORITY_COLOURS.get(sen, colors.black)
            sen_para = Paragraph(
                f'<font color="{sen_col.hexval()}">{sen.capitalize()}</font>',
                s["CellNormal"],
            )
            loc_raw = j.get("locations") or "[]"
            try:
                locs = json.loads(loc_raw)
                loc_str = locs[0].split(",")[0] if locs else "HK"
            except Exception:
                loc_str = "HK"

            table_data.append([
                Paragraph(j["company"][:35],         s["CellBold"]),
                Paragraph(j["title"][:70],           s["CellNormal"]),
                sen_para,
                Paragraph(fmt_skills(j.get("required_skills")), s["CellSmall"]),
                Paragraph((j.get("remote_type") or "—")[:8],   s["CellSmall"]),
                Paragraph(fmt_date(j.get("posted_at")),         s["CellSmall"]),
            ])

        t = Table(table_data, colWidths=col_w, repeatRows=1)
        t.setStyle(TableStyle([
            # Header row
            ("BACKGROUND",   (0,0), (-1,0), NAVY),
            ("TEXTCOLOR",    (0,0), (-1,0), WHITE),
            ("FONTNAME",     (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE",     (0,0), (-1,0), 8),
            # Data rows
            ("FONTSIZE",     (0,1), (-1,-1), 8),
            ("ROWBACKGROUNDS",(0,1),(-1,-1), [WHITE, GREY]),
            ("GRID",         (0,0), (-1,-1), 0.25, colors.lightgrey),
            ("VALIGN",       (0,0), (-1,-1), "TOP"),
            ("TOPPADDING",   (0,0), (-1,-1), 3),
            ("BOTTOMPADDING",(0,0), (-1,-1), 3),
            ("LEFTPADDING",  (0,0), (-1,-1), 4),
            ("RIGHTPADDING", (0,0), (-1,-1), 4),
        ]))

        self.story.append(t)
        self.story.append(PageBreak())

    # ── build ─────────────────────────────────────────────────────────────────

    def build(self, by_cat: dict[str, list[dict]]) -> int:
        all_jobs = [j for jobs in by_cat.values() for j in jobs]
        n_companies = len({j["company"] for j in all_jobs})

        doc = SimpleDocTemplate(
            self.out_path,
            pagesize=A4,
            leftMargin=1.5*cm, rightMargin=1.5*cm,
            topMargin=2*cm,    bottomMargin=2.5*cm,
        )

        self.add_title_page(len(all_jobs), n_companies)
        self.add_summary_page(by_cat)
        self.add_toc(by_cat)
        for cat in CATEGORY_ORDER:
            if cat in by_cat:
                self.add_category_section(cat, by_cat[cat])

        # Title page uses dark background; rest use normal callback
        doc.build(
            self.story,
            onFirstPage=self._on_title_page,
            onLaterPages=self._on_page,
        )
        return self._page_num


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    db   = Path(__file__).parent.parent / "data" / "jobs.db"
    out  = Path(__file__).parent.parent / "outputs" / "HK_Jobs_By_Category.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)

    print("Loading jobs from database…")
    by_cat = load_jobs(str(db))
    total  = sum(len(v) for v in by_cat.values())
    print(f"Found {total} enriched jobs across {len(by_cat)} categories\n")

    builder = ReportBuilder(str(out))
    pages   = builder.build(by_cat)

    size_kb = out.stat().st_size // 1024
    print(f"\n✅ PDF created: {out}  ({pages} pages, {size_kb} KB)")


if __name__ == "__main__":
    main()
