"""
An admin's direct edit path onto a job's row and its enrichment — the one place
this backend lets a human overwrite what the pipeline computed, title through
the AI's salary estimate. Gated by `_require_admin` (main.py).

This was Ultimate-Admin-only until 2026-08-20. It was widened to every admin
because a wrong salary is this board's most visible defect and one account
should not be the queue for fixing it. The gate is the only thing that moved:
the allowlist, the audit trail and the pinning below are unchanged, and
`admin_edits.seeker_id` already recorded *which* human edited, so widening who
may write does not weaken who can be held to it.

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
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

#: Columns on `jobs` a human may hand-correct.
JOB_FIELDS = frozenset(
    {
        "title",
        "company",
        "locations",
        "employment_type",
        "department",
        "seniority",
        "remote_type",
        "salary_min",
        "salary_max",
        "salary_currency",
        "description_clean",
        "description_raw",
        "apply_url",
        "is_active",
        # ADR 0032: the admin-only Hidden state. 1 removes the Role from the
        # public board (and every board-side count and the recommendation
        # feeds) without closing it; 0 restores it. Reversible, audited here
        # like any other field.
        "admin_hidden",
        "source_tier",
        "category",
    }
)

#: Columns on `job_enrichments` a human may hand-correct.
ENRICHMENT_FIELDS = frozenset(
    {
        "seniority",
        "remote_type",
        "required_skills",
        "salary_hkd_min",
        "salary_hkd_max",
        "job_category",
        "salary_estimated_min",
        "salary_estimated_max",
        "salary_estimated_confidence",
        "years_experience_required",
        "description_summary",
        "title_en",
    }
)

#: Stored as a JSON array in both tables; the API sends/receives a plain list.
_JSON_FIELDS = frozenset({"locations", "required_skills"})

#: `jobs.seniority`/`jobs.remote_type` and `job_enrichments.seniority`/
#: `job_enrichments.remote_type` are genuinely different columns (raw scraped
#: value vs. the AI-derived one the board actually filters by) — the SELECT
#: below aliases the enrichment side to keep them apart in one flat dict.
_ENRICHMENT_ALIASES = {"seniority": "e_seniority", "remote_type": "e_remote_type"}

_ADMIN_EDITS_DDL = """
CREATE TABLE IF NOT EXISTS admin_edits (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    source    TEXT NOT NULL,
    source_id TEXT NOT NULL,
    seeker_id TEXT NOT NULL,
    field     TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    edited_at TEXT NOT NULL
)
"""


#: Phase 36. Mirrors hk_jobs/migrations.py — same reason ensure_schema() below
#: mirrors phase 33: the Railway web service ships webapp/backend only, so a
#: long-lived volume can predate a phase this feature needs.
_SALARY_CORRECTIONS_DDL = """
CREATE TABLE IF NOT EXISTS admin_salary_corrections (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source        TEXT NOT NULL,
    source_id     TEXT NOT NULL,
    title         TEXT,
    company       TEXT,
    company_slug  TEXT,
    source_tier   TEXT,
    sector        TEXT,
    seniority     TEXT,
    job_category  TEXT,
    old_min       INTEGER,
    old_max       INTEGER,
    new_min       INTEGER,
    new_max       INTEGER,
    seeker_id     TEXT NOT NULL,
    corrected_at  TEXT NOT NULL
)
"""

#: The two enrichment columns whose change makes an edit a SALARY correction.
#: `salary_hkd_*` is deliberately absent: those hold what the EMPLOYER disclosed,
#: and correcting a transcription of someone else's published figure is not
#: evidence about what the market pays.
_SALARY_ESTIMATE_FIELDS = ("salary_estimated_min", "salary_estimated_max")


class JobNotFound(Exception):
    """Raised when (source, source_id) has no row in `jobs`."""


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Install the editor's phase-33 schema on deployments with an older volume.

    The Railway web service uploads only ``webapp/backend``; it does not ship
    ``hk_jobs/migrations.py``.  A long-lived production volume can therefore
    predate the editor even when the current backend code is live.  Keeping this
    tiny, idempotent compatibility check beside the only feature that needs the
    schema prevents an authorized request from failing with a 500.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(job_enrichments)").fetchall()}
    if not columns:
        raise RuntimeError("job_enrichments table is missing; run the base database migrations")

    job_columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}

    with conn:
        if "manually_edited_at" not in columns:
            conn.execute("ALTER TABLE job_enrichments ADD COLUMN manually_edited_at TEXT")
        # ADR 0032 / migrations.py phase 41 — same reason as the line above: a
        # long-lived Railway volume can predate the phase this feature needs.
        if "admin_hidden" not in job_columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN admin_hidden INTEGER NOT NULL DEFAULT 0")
        conn.execute(_ADMIN_EDITS_DDL)
        conn.execute(_SALARY_CORRECTIONS_DDL)


def _to_storage(field: str, value: Any) -> Any:
    """The DB's own representation of a value the API received."""
    if field in _JSON_FIELDS:
        return json.dumps(value if value is not None else [])
    if field in ("is_active", "admin_hidden"):
        return 1 if value else 0
    return value


def _to_text(value: Any) -> str | None:
    """Audit-log representation — always a string (or None), never a list/bool."""
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _from_audit(field: str, value: str | None) -> Any:
    """Recover a typed database value from an ``admin_edits.new_value`` cell."""
    if value is None:
        return None
    if field in _JSON_FIELDS:
        return json.dumps(json.loads(value), ensure_ascii=False)
    if field == "is_active":
        return 1 if value.lower() in {"1", "true"} else 0
    if field in {
        "salary_min",
        "salary_max",
        "salary_hkd_min",
        "salary_hkd_max",
        "salary_estimated_min",
        "salary_estimated_max",
        "years_experience_required",
    }:
        return int(float(value))
    if field in {"salary_estimated_confidence"}:
        try:
            return float(value)
        except ValueError:
            return value
    return value


def reapply_recorded_edits(conn: sqlite3.Connection) -> int:
    """Reapply each field's latest admin correction after an import.

    This deliberately writes no new audit rows: the original edit remains the
    audit event, while publication merely ensures pipeline data cannot erase it.
    Must be called inside the publisher's transaction.
    """
    has_audit = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='admin_edits'"
    ).fetchone()
    if not has_audit:
        return 0
    rows = conn.execute(
        """
        SELECT e.source, e.source_id, e.field, e.new_value, e.edited_at
        FROM admin_edits e
        JOIN (
            SELECT source, source_id, field, MAX(id) AS latest_id
            FROM admin_edits GROUP BY source, source_id, field
        ) latest ON latest.latest_id=e.id
        JOIN jobs j ON j.source=e.source AND j.source_id=e.source_id
        ORDER BY e.id
        """
    ).fetchall()
    applied = 0
    for source, source_id, qualified, value, edited_at in rows:
        prefix, _, field = qualified.partition(".")
        allowlist = JOB_FIELDS if prefix == "job" else ENRICHMENT_FIELDS
        if field not in allowlist:
            continue
        stored = _from_audit(field, value)
        if prefix == "job":
            conn.execute(
                f'UPDATE jobs SET "{field}"=? WHERE source=? AND source_id=?',
                (stored, source, source_id),
            )
        else:
            conn.execute(
                f"""
                INSERT INTO job_enrichments(source,source_id,"{field}",manually_edited_at)
                VALUES (?,?,?,?) ON CONFLICT(source,source_id) DO UPDATE SET
                    "{field}"=excluded."{field}",
                    manually_edited_at=excluded.manually_edited_at
                """,
                (source, source_id, stored, edited_at),
            )
        applied += 1
    return applied


def get_job_for_edit(conn: sqlite3.Connection, source: str, source_id: str) -> dict[str, Any]:
    """
    The full row plus its enrichment (LEFT JOIN — a job need not have one yet).

    Addressable, not board-visible: an inactive or non-primary copy must still
    be reachable here — those are exactly the rows a correction is often
    needed on, and job_read.Visibility.BOARD would hide them.
    """
    ensure_schema(conn)
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
        audit_rows.append(
            (
                source,
                source_id,
                seeker_id,
                f"job.{field}",
                _to_text(old_value),
                _to_text(new_value),
                moment,
            )
        )

    changed_enrichment: dict[str, Any] = {}
    for field, new_value in enrichment_changes.items():
        current_key = _ENRICHMENT_ALIASES.get(field, field)
        old_value = current.get(current_key)
        if _to_storage(field, new_value) == old_value:
            continue
        changed_enrichment[field] = new_value
        audit_rows.append(
            (
                source,
                source_id,
                seeker_id,
                f"enrichment.{field}",
                _to_text(old_value),
                _to_text(new_value),
                moment,
            )
        )

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

        _record_salary_correction(
            conn, source, source_id, seeker_id,
            current=current, changed=changed_enrichment, at=moment,
        )

    return get_job_for_edit(conn, source, source_id)


def _record_salary_correction(
    conn: sqlite3.Connection,
    source: str,
    source_id: str,
    seeker_id: str,
    *,
    current: dict[str, Any],
    changed: dict[str, Any],
    at: str,
) -> None:
    """
    Keep an admin's salary correction as calibration evidence, not just as audit.

    One row per EDIT, not per field: an admin who moves min and max together has
    made one judgement about what the Role pays, and splitting it across two rows
    would make a range impossible to read back. Called inside `apply_edit`'s
    transaction, so a correction and the write it describes land together or not
    at all.

    Silent no-op when neither estimate field moved — an admin fixing a job title
    is not evidence about pay. Also a no-op on a database predating phase 36;
    `ensure_schema` has normally created the table by now, and losing one
    observation is not worth failing a correction the admin has already made.

    The Role's shape is snapshotted from `current` — the record as it was BEFORE
    this edit — so the evidence describes the Role the estimator actually saw.
    """
    if not any(field in changed for field in _SALARY_ESTIMATE_FIELDS):
        return

    def _before(field: str) -> Any:
        return current.get(field)

    def _after(field: str) -> Any:
        return changed[field] if field in changed else current.get(field)

    # Seniority: prefer the AI column the board filters on, fall back to the
    # scraped one. Sector is deliberately NOT recomputed here — job_read owns
    # that derivation and importing it for one string would tie the write path
    # to the read path. `category`/`job_category` carry the useful signal.
    seniority = current.get("e_seniority") or current.get("seniority")

    try:
        conn.execute(
            """
            INSERT INTO admin_salary_corrections (
                source, source_id, title, company, company_slug, source_tier,
                sector, seniority, job_category, old_min, old_max,
                new_min, new_max, seeker_id, corrected_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source, source_id,
                current.get("title"), current.get("company"),
                current.get("company_slug"), current.get("source_tier"),
                current.get("category"), seniority, current.get("job_category"),
                _before("salary_estimated_min"), _before("salary_estimated_max"),
                _after("salary_estimated_min"), _after("salary_estimated_max"),
                seeker_id, at,
            ),
        )
    except sqlite3.OperationalError:  # table absent on a pre-phase-36 database
        logger.warning(
            "admin_salary_corrections is missing; correction for %s/%s not recorded "
            "as calibration evidence (the edit itself and its audit row are unaffected)",
            source, source_id,
        )
