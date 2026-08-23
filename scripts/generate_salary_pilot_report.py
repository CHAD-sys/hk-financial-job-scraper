"""Render the salary-evaluation batches into a reviewable PDF.

The evaluation result files are deliberately separate from production data. This
report joins the model responses to the frozen cohort manifest and links each
role back to its public FinEx Careers teaser page.
"""

from __future__ import annotations

import json
import unicodedata
from argparse import ArgumentParser
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer

ROOT = Path(__file__).resolve().parents[1]
EVALUATION_DIR = ROOT / "data" / "salary_evaluation_2026-08-22"
BOARD_BASE = "https://www.finexcareers.com"


def _escape(value: object) -> str:
    # The report deliberately uses ReportLab's built-in Helvetica. Normalise
    # source text to characters it can render instead of leaving black boxes
    # for copied job-title glyphs or invisible formatting characters.
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.replace("■", " - ").replace("•", "; ").replace("▪", "; ")
    text = text.encode("ascii", "ignore").decode("ascii")
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _salary(result: dict, status: str, error: str = "") -> str:
    if status != "ok":
        reason = "Model response truncated" if "TruncatedAnswer" in error else "Model request failed"
        return f'<font color="#B42318">Not available</font><br/><font color="#667085">{reason}</font>'
    low = result.get("salary_estimated_min")
    high = result.get("salary_estimated_max")
    if low is None or high is None:
        return "Not estimated"
    confidence = result.get("salary_estimated_confidence", "-").title()
    return f"HK${low:,.0f}-<br/>HK${high:,.0f}<br/><font color='#667085'>{confidence}</font>"


def _job_url(row: dict) -> str:
    source = quote(str(row["source"]), safe="")
    source_id = quote(str(row["source_id"]), safe="")
    return f"{BOARD_BASE}/jobs/{source}/{source_id}"


def _load_rows(batch: str) -> tuple[list[dict], dict[str, int]]:
    manifest = json.loads((EVALUATION_DIR / "manifest.json").read_text(encoding="utf-8"))
    batches = ("pilot_400", "continuation_600") if batch == "all_1000" else (batch,)
    roles = [row for row in manifest["roles"] if row["batch"] in batches]
    records: dict[tuple[str, str], dict] = {}
    for name in batches:
        for line in (EVALUATION_DIR / f"{name}_results.jsonl").read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            records[(record["source"], record["source_id"])] = record
    if len(roles) != len(records):
        raise ValueError(f"Manifest/results mismatch: {len(roles)} roles, {len(records)} records")

    rows = []
    for role in roles:
        record = records[(role["source"], role["source_id"])]
        rows.append({
            **role,
            "result": record.get("result", {}),
            "status": record["status"],
            "error": record.get("error", ""),
        })
    summary = {
        "attempted": len(rows),
        "successful": sum(row["status"] == "ok" for row in rows),
        "unavailable": sum(row["status"] != "ok" for row in rows),
    }
    return sorted(rows, key=lambda row: (row["company"].casefold(), row["title"].casefold())), summary


def _page_number(canvas, doc) -> None:
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#D0D5DD"))
    canvas.line(doc.leftMargin, 13 * mm, landscape(doc.pagesize)[0] - doc.rightMargin, 13 * mm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#667085"))
    canvas.drawString(doc.leftMargin, 8 * mm, "FinEx Careers - Salary estimation evaluation")
    canvas.drawRightString(
        landscape(doc.pagesize)[0] - doc.rightMargin,
        8 * mm,
        f"Page {doc.page}",
    )
    canvas.restoreState()


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument(
        "--batch", choices=("pilot_400", "continuation_600", "all_1000"), required=True
    )
    args = parser.parse_args()
    rows, summary = _load_rows(args.batch)
    batch_label = {
        "pilot_400": "Pilot 400",
        "continuation_600": "Continuation 600",
        "all_1000": "Full 1,000-role evaluation",
    }[args.batch]
    output = ROOT / "output" / "pdf" / f"salary-estimation-{args.batch}-results.pdf"
    output.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "ReportTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=18,
        leading=22, textColor=colors.HexColor("#101828"), spaceAfter=5,
    )
    subtitle = ParagraphStyle(
        "ReportSubtitle", parent=styles["Normal"], fontName="Helvetica", fontSize=8.5,
        leading=11, textColor=colors.HexColor("#475467"), spaceAfter=10,
    )
    header = ParagraphStyle(
        "TableHeader", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=7,
        leading=8, textColor=colors.white, alignment=TA_CENTER,
    )
    cell = ParagraphStyle(
        "TableCell", parent=styles["Normal"], fontName="Helvetica", fontSize=6.5,
        leading=8.1, textColor=colors.HexColor("#1D2939"),
    )
    link = ParagraphStyle(
        "TableLink", parent=cell, textColor=colors.HexColor("#175CD3"), alignment=TA_CENTER,
    )
    doc = SimpleDocTemplate(
        str(output), pagesize=landscape((297 * mm, 210 * mm)),
        leftMargin=11 * mm, rightMargin=11 * mm, topMargin=12 * mm, bottomMargin=18 * mm,
        title=f"Salary estimation {batch_label}",
        author="FinEx Careers",
    )
    story = [
        Paragraph(f"Salary estimation {batch_label} - {summary['successful']} completed estimates", title),
        Paragraph(
            f"Cohort: {summary['attempted']} recent, unedited roles. This appendix includes every role: "
            f"{summary['successful']} completed estimates and {summary['unavailable']} unavailable model results. "
            "Amounts are monthly HKD AI estimates for evaluation, not published salary disclosures. "
            f"Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}.",
            subtitle,
        ),
    ]
    table_rows = [[
        Paragraph("#", header),
        Paragraph("Role and company", header),
        Paragraph("Estimated monthly salary / result", header),
        Paragraph("Enrichment profile", header),
        Paragraph("Selected skills", header),
        Paragraph("Job board", header),
    ]]
    for index, row in enumerate(rows, start=1):
        result = row["result"]
        if row["status"] == "ok":
            years = result.get("years_experience")
            profile = "<br/>".join(filter(None, [
                f"{_escape(result.get('seniority', '-')).title()} | "
                f"{f'{years} yrs' if years is not None else 'Experience not stated'}",
                _escape(result.get("job_category", "-")),
                _escape(result.get("remote_type", "-")),
            ]))
            skills = result.get("skills") or []
            skill_text = "; ".join(_escape(skill) for skill in skills[:3]) or "-"
        else:
            profile = "<font color='#667085'>No completed enrichment</font>"
            skill_text = "<font color='#667085'>Not available</font>"
        role = f"<b>{_escape(row['title'])}</b><br/><font color='#667085'>{_escape(row['company'])}</font>"
        url = _job_url(row)
        table_rows.append([
            Paragraph(str(index), cell),
            Paragraph(role, cell),
            Paragraph(_salary(result, row["status"], row["error"]), cell),
            Paragraph(profile, cell),
            Paragraph(skill_text, cell),
            Paragraph(f'<link href="{url}">Open role</link>', link),
        ])
    table = LongTable(
        table_rows,
        colWidths=[10 * mm, 58 * mm, 28 * mm, 33 * mm, 91 * mm, 23 * mm],
        repeatRows=1,
        hAlign="LEFT",
    )
    table.setStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#12355B")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D0D5DD")),
        ("LEFTPADDING", (0, 0), (-1, -1), 3.2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3.2),
        ("TOPPADDING", (0, 0), (-1, 0), 4.5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 4.5),
        ("TOPPADDING", (0, 1), (-1, -1), 3.6),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 3.6),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F9FAFB")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#FFFFFF"), colors.HexColor("#F8FAFC")]),
    ])
    story.extend([Spacer(1, 2 * mm), table])
    doc.build(story, onFirstPage=_page_number, onLaterPages=_page_number)
    print(output)


if __name__ == "__main__":
    main()
