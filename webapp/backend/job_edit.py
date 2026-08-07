"""
Ultimate Admin's direct edit path onto a job's row and its enrichment — the
one place this backend lets a human overwrite what the pipeline computed,
title through the AI's salary estimate. Gated by `_require_super_admin`
(main.py); every other admin sees the dashboard but never this.

Two things about the write itself, both load-bearing:

1. **An allowlist, not every column.** `source`, `source_id`, `dedup_hash`,
   `url`, `company_slug` and the timestamps are identity/structural: editing
   `source_id` would silently orphan the row's own `job_enrichments` (joined
   on `source, source_id`) and break the `jobs` primary key. Everything a
   human would plausibly want to hand-correct is in JOB_FIELDS/ENRICHMENT_
   FIELDS; nothing else is reachable through this module regardless of what
   a request sends.

2. **Every enrichment write sets `manually_edited_at`.** That column (phase 33,
   hk_jobs/migrations.py) is what makes the correction stick: `hk_jobs/
   enrichment.py`'s re-enrichment pass and `hk_jobs/salary_audit.py`'s
   outlier re-judgment both exclude a row once it is set — unconditionally,
   including under `--re-enrich` and `--full`. Without it, a hand-corrected
   salary is exactly the shape of "outlier" the audit pass looks for, and
   would be sent right back to the model that just got overruled.

Every change is logged to `admin_edits` (source, source_id, who, field, old
value, new value, when) before being written — accountability for a write
this permissive, same reasoning as `salary_audit_log` and seekers.db's
`events` table.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

#: Columns on `jobs` a human may hand-correct.
JOB_FIELDS = frozenset({
    "title", "company", "locations", "employment_type", "department",
    "seniority", "remote_type", "salary_min", "salary_max", "salary_currency",
    "description_clean", "description_raw", "apply_url", "is_active",
    "source_tier", "category",
})

#: Columns on `job_enrichments` a human may hand-correct.
ENRICHMENT_FIELDS = frozenset({
    "seniority", "remote_type", "required_skills", "salary_hkd_min",
    "salary_hkd_max", "job_category", "salary_estimated_min",
    "salary_estimated_max", "salary_estimated_confidence",
    "years_experience_required", "description_summary", "title_en",
})

#: Stored as a JSON array in both tables; the API sends/receives a plain list.
_JSON_FIELDS = frozenset({"locations", "required_skills"})

#: `jobs.seniority`/`jobs.remote_type` and `job_enrichments.seniority`/
#: `job_enrichments.remote_type` are genuinely different columns (raw scraped
#: value vs. the AI-derived one the board actually filters by) — the SELECT
#: below aliases the enrichment side to keep them apart in one flat dict.
_ENRICHMENT_ALIASES = {"seniority": "e_seniority", "remote_type": "e_remote_type"}


class JobNotFound(Exception):
    """Raised when (source, source_id) has no row in `jobs`."""


def _to_storage(field: str, value: Any) -> Any:
    """The DB's own representation of a value the API received."""
    if field in _JSON_FIELDS:
        return json.dumps(value if value is not None else [])
    if field == "is_active":
        return 1 if value else 0
    return value


def _to_text(value: Any) -> str | None:
    """Audit-log representation — always a string (or None), never a list/bool."""
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def get_job_for_edit(conn: sqlite3.Connection, source: str, source_id: str) -> dict[str, Any]:
    """
    The full row plus its enrichment (LEFT JOIN — a job need not have one yet).

    Addressable, not board-visible: an inactive or non-primary copy must still
    be reachable here — those are exactly the rows a correction is often
    needed on, and job_read.Visibility.BOARD would hide them.
    """
    row = conn.execute(
        """
        SELECT j.*,
               e.seniority   AS e_seniority,
               e.remote_type AS e_remote_type,
               e.required_skills, e.salary_hkd_min, e.salary_hkd_max,
               e.job_category, e.salary_estimated_min, e.salary_estimated_max,
               e.salary_estimated_confidence, e.years_experience_required,
               e.description_summary, e.title_en, e.manually_edited_at
          FROM jobs j
          LEFT JOIN job_enrichments e ON j.source = e.source AND j.source_id = e.source_id
         WHERE j.source = ? AND j.source_id = ?
        """,
        (source, source_id),
    ).fetchone()
    if row is None:
        raise JobNotFound(f"{source}/{source_id}")
    return dict(row)


def apply_edit(
    conn: sqlite3.Connection,
    source: str,
    source_id: str,
    seeker_id: str,
    *,
    job_changes: dict[str, Any] | None = None,
    enrichment_changes: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Apply a partial set of changes and return the updated record.

    Raises ValueError for any key outside JOB_FIELDS/ENRICHMENT_FIELDS — the
    allowlist is enforced HERE, not trusted to the route layer. Raises
    JobNotFound (via get_job_for_edit) for an unknown (source, source_id).
    Writing nothing (both dicts empty/None) is a no-op that still returns the
    current record, not an error.
    """
    job_changes = job_changes or {}
    enrichment_changes = enrichment_changes or {}

    unknown_job = set(job_changes) - JOB_FIELDS
    unknown_enrichment = set(enrichment_changes) - ENRICHMENT_FIELDS
    if unknown_job or unknown_enrichment:
        bad = sorted(unknown_job | unknown_enrichment)
        raise ValueError(f"not an editable field: {', '.join(bad)}")

    current = get_job_for_edit(conn, source, source_id)
    moment = (now or datetime.now(timezone.utc)).isoformat()
    audit_rows: list[tuple[str, str, str, str, str | None, str | None, str]] = []

    # Filtered down to genuinely-changed fields BEFORE any SQL is built — a
    # caller that resends the current value for an untouched field (a form
    # posting its whole state, not a diff) must not write it, and must not
    # set manually_edited_at on a row nothing about actually changed.
    changed_job: dict[str, Any] = {}
    for field, new_value in job_changes.items():
        old_value = current.get(field)
        if _to_storage(field, new_value) == old_value:
            continue
        changed_job[field] = new_value
        audit_rows.append((source, source_id, seeker_id, f"job.{field}",
                            _to_text(old_value), _to_text(new_value), moment))

    changed_enrichment: dict[str, Any] = {}
    for field, new_value in enrichment_changes.items():
        current_key = _ENRICHMENT_ALIASES.get(field, field)
        old_value = current.get(current_key)
        if _to_storage(field, new_value) == old_value:
            continue
        changed_enrichment[field] = new_value
        audit_rows.append((source, source_id, seeker_id, f"enrichment.{field}",
                            _to_text(old_value), _to_text(new_value), moment))

    if not audit_rows:
        return current  # nothing actually changed

    with conn:
        if changed_job:
            set_clause = ", ".join(f"{f} = ?" for f in changed_job)
            values = [_to_storage(f, v) for f, v in changed_job.items()]
            conn.execute(
                f"UPDATE jobs SET {set_clause} WHERE source = ? AND source_id = ?",
                (*values, source, source_id),
            )

        if changed_enrichment:
            cols = list(changed_enrichment)
            placeholders = ", ".join("?" * len(cols))
            col_list = ", ".join(cols)
            update_clause = ", ".join(f"{c} = excluded.{c}" for c in cols)
            values = [_to_storage(f, v) for f, v in changed_enrichment.items()]
            conn.execute(
                f"""
                INSERT INTO job_enrichments (source, source_id, {col_list}, manually_edited_at)
                VALUES (?, ?, {placeholders}, ?)
                ON CONFLICT (source, source_id) DO UPDATE SET
                    {update_clause}, manually_edited_at = excluded.manually_edited_at
                """,
                (source, source_id, *values, moment),
            )

        conn.executemany(
            "INSERT INTO admin_edits (source, source_id, seeker_id, field, "
            "old_value, new_value, edited_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            audit_rows,
        )

    return get_job_for_edit(conn, source, source_id)
