#!/usr/bin/env python3
"""Extract finite, function-specific HK monthly base bands from Randstad 2025.

Usage: python3 scripts/import_randstad_2025.py path/to/official.pdf
The checked-in JSON is the reviewable source artifact used by the anchor build.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "salary_guidlines" / "randstad_2025_finance.json"
SOURCE_URL = "https://www.randstad.com.hk/s3fs-media/hk/public/2025-01/Randstad-Hong-Kong-SAR-2025-Job-Market-Outlook-Salary-Guide.pdf?VersionId=Nbc9a4xsKw0jkw6VdMPz4ygnUr6zj93H"
RANGE = re.compile(r"(?<!\d)(\d{1,3},\d{3})\s*-\s*(\d{1,3},\d{3})")
NUMBER = re.compile(r"\$?(\d{1,3},\d{3})")
YEARS = ("1–3 years", "3–6 years", "7–10 years")
SKIP_TITLE = re.compile(
    r"^(department head|team head|associate / AVP|VP / senior associate|"
    r"director or above|senior relationship manager / relationship manager|"
    r"assistant relationship manager / relationship support officer|"
    r"private equity associate / senior associate|chief |head of |"
    r"financial planning & analysis / management reporting)",
    re.I,
)
SECTIONS = {
    (16, "L"): [
        ("retail banking", "retail_banking"),
        ("global market treasury", "front_office"),
        ("corporate banking", "commercial_corporate_banking"),
        ("commercial banking", "commercial_corporate_banking"),
        ("financial institutional banking", "commercial_corporate_banking"),
    ],
    (16, "R"): [
        ("transaction banking", "commercial_corporate_banking"),
        ("structured finance / project finance / syndication finance", "front_office"),
        ("private banking & wealth management", "front_office"),
        ("private equity", "front_office"),
        ("asset management (fixed income, equities)", "front_office"),
        ("investment banking", "front_office"),
    ],
    (17, "L"): [("compliance", "middle_office")],
    (17, "R"): [("risk management", "middle_office")],
    (18, "L"): [("operations", "back_office_operations")],
    (18, "R"): [("finance accounting & audit", "corporate_finance_accounting")],
}
INSURANCE_SECTIONS = {
    (29, "L"): ("bancassurance", "alternative distribution", "actuarial", "claims"),
    (29, "R"): ("customer service", "policy admin", "underwriting", "product"),
    (30, "L"): ("accounting & finance", "internal audit", "transformation", "financial risk management"),
}


def _slug(value: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", value.lower())).strip("_")


def _lines(pdf, page_number: int, side: str) -> list[str]:
    box = (50, 145, 945, 950) if side == "L" else (945, 145, 1850, 950)
    return pdf.pages[page_number - 1].crop(box).extract_text().splitlines()


def extract(pdf_path: Path) -> dict:
    roles: list[dict] = []
    with pdfplumber.open(pdf_path) as pdf:
        for (page, side), headings in SECTIONS.items():
            section, tier = headings[0]
            for line in _lines(pdf, page, side):
                heading = next((item for item in headings if line.startswith(item[0]) and not RANGE.search(line)), None)
                if heading:
                    section, tier = heading
                    continue
                matches = list(RANGE.finditer(line))
                if not matches:
                    continue
                title = line[: matches[0].start()].strip()
                # Missing early experience columns shift later bands to the left.
                # Only first-column rows can be mapped safely by text extraction.
                if title.endswith("-") or SKIP_TITLE.search(title):
                    continue
                bands = {}
                for grade, match in zip(YEARS, matches[:3]):
                    low, high = (int(piece.replace(",", "")) for piece in match.groups())
                    if low < high <= 200_000:
                        bands[grade] = [low, high]
                if len(bands) < 2:
                    continue
                roles.append({
                    "tier": tier,
                    "role": _slug(section + " " + title),
                    "section": section,
                    "native_title": title,
                    "page": page,
                    "bands": bands,
                })

        for (page, side), headings in INSURANCE_SECTIONS.items():
            section = headings[0]
            for line in _lines(pdf, page, side):
                if line in headings:
                    section = line
                    continue
                if line.startswith(headings[0] + " low middle high"):
                    continue
                numbers = list(NUMBER.finditer(line))
                if len(numbers) != 3:
                    continue
                title = line[:numbers[0].start()].strip()
                low, middle, high = (int(match.group(1).replace(",", "")) for match in numbers)
                if not title or not 0 < low < middle < high <= 200_000:
                    continue
                roles.append({
                    "tier": "insurance",
                    "role": _slug("insurance " + section),
                    "section": section,
                    "native_title": title,
                    "page": page,
                    "bands": {title.title(): [low, high]},
                })

    # Merge insurance titles into one function-specific catalog.
    merged: dict[tuple[str, str], dict] = {}
    for entry in roles:
        key = (entry["tier"], entry["role"])
        if key not in merged:
            merged[key] = entry
        else:
            if entry["bands"].keys() & merged[key]["bands"].keys():
                raise ValueError(f"Duplicate Randstad coordinate: {key} {entry['bands']}")
            merged[key]["bands"].update(entry["bands"])
    return {
        "source_url": SOURCE_URL,
        "period": "monthly",
        "basis": "basic salary, excluding AWS and fixed/variable bonus",
        "year": 2025,
        "roles": sorted(merged.values(), key=lambda item: (item["tier"], item["role"])),
    }


if __name__ == "__main__":
    data = extract(Path(sys.argv[1]))
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(len(data["roles"]), "roles;", sum(len(role["bands"]) for role in data["roles"]), "cells")
