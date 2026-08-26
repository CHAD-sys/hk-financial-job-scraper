"""Validated employer-disclosed salary facts used by exact salary overlays."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path


_ROOT = Path(__file__).resolve().parent.parent
_PATH = _ROOT / "salary_guidlines" / "disclosed_salary_evidence.json"
_ANCHORS_PATH = _ROOT / "salary_guidlines" / "hk_salary_anchors.json"
_REQUIRED = {
    "key", "company_slug", "title", "band_monthly_hkd", "currency", "period",
    "source", "captured_on", "evidence_type", "scope",
}


def _load() -> dict[str, dict]:
    payload = json.loads(_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("records"), list):
        raise ValueError("Invalid disclosed-salary evidence registry")
    records: dict[str, dict] = {}
    for record in payload["records"]:
        if not isinstance(record, dict) or _REQUIRED - set(record):
            raise ValueError("Disclosed-salary evidence record is missing required fields")
        key = record["key"]
        band = record["band_monthly_hkd"]
        if not isinstance(key, str) or key in records:
            raise ValueError(f"Duplicate or invalid disclosed evidence key: {key!r}")
        if (
            not isinstance(band, list) or len(band) != 2
            or not all(isinstance(value, int) and value > 0 for value in band)
            or band[0] > band[1]
        ):
            raise ValueError(f"Invalid disclosed salary band for {key!r}")
        if record["currency"] != "HKD" or record["period"] != "monthly":
            raise ValueError(f"Disclosed evidence {key!r} is not monthly HKD")
        date.fromisoformat(record["captured_on"])
        records[key] = record
    return records


RECORDS = _load()


def validate_overlay_alignment() -> tuple[str, ...]:
    """Ensure every disclosed overlay names an exact, matching evidence record."""
    anchors = json.loads(_ANCHORS_PATH.read_text(encoding="utf-8"))
    overlays = anchors.get("employer_salary_overlays_monthly_hkd", {}).get("rules", [])
    errors: list[str] = []
    referenced: set[str] = set()
    for overlay in overlays:
        evidence_key = overlay.get("disclosed_evidence_key")
        if evidence_key is None:
            continue
        referenced.add(evidence_key)
        record = RECORDS.get(evidence_key)
        if record is None:
            errors.append(f"overlay {overlay.get('key')!r} references missing evidence {evidence_key!r}")
            continue
        if overlay.get("key") != evidence_key:
            errors.append(f"overlay {overlay.get('key')!r} must use evidence key {evidence_key!r}")
        for field in ("company_slug", "band_monthly_hkd"):
            if overlay.get(field) != record[field]:
                errors.append(f"overlay {evidence_key!r} differs from disclosed evidence field {field}")
    for key in RECORDS.keys() - referenced:
        errors.append(f"disclosed evidence {key!r} is not linked to an overlay")
    return tuple(errors)
