"""Deterministic repairs to salary estimates already in the database.

A clamp change creates a new `salary.version()`, making the replay decision visible. An
operator may deliberately grandfather the prior version to avoid re-paying DeepSeek for
the whole catalogue when the affected rows can be recomputed exactly. That choice leaves
already-published rows carrying the number the old clamp allowed until a deterministic
repair is applied.

This module closes that gap for repairs that need no model call: the answer is a pure
function of the row, so it can be recomputed for free, as many times as you like.

The one repair here today is the internship ceiling. The 2026-08-18 estimator audit
(`docs/SALARY_ESTIMATOR_AUDIT.html`) found 58 of 153 live internship listings priced above
the HK$15,000 cap the enricher's own prompt sets for them — the worst a 2027
investment-banking summer analyst at HK$41,500-83,500, 5.6x the cap.

Every repair here must be **idempotent and down-only**: it runs on a schedule against a
database it does not own, so running it twice must change nothing the second time, and it
must never be able to raise a published salary.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field

from hk_jobs.salary_clamp import (
    FRONT_OFFICE_TIER,
    INTERNSHIP_MAX_MONTHLY_HKD,
    SINGLE_VALUE_MIN_FRACTION,
    _title_grade_ceiling,
    clamp_salary,
    is_internship,
    salary_rule_resolution,
)

logger = logging.getLogger(__name__)


@dataclass
class RepairSummary:
    """What a repair pass found and (if applying) wrote."""

    examined: int = 0
    matched: int = 0
    repaired: int = 0
    #: Rows whose title matched but whose stored seniority is not "junior" — reported
    #: and SKIPPED, never written. A compound listing ("Manager / Intern") is the real
    #: case this catches; a growing list is the signal that the title pattern has started
    #: catching full-time roles.
    suspicious: list[str] = field(default_factory=list)
    #: Rows whose title matched but which carry a figure the EMPLOYER stated — reported
    #: and SKIPPED. A disclosed number outranks every estimate, including this repair's.
    disclosed: list[str] = field(default_factory=list)
    #: Rows an Ultimate Admin has hand-corrected (`manually_edited_at` set) — reported
    #: and SKIPPED. A human who overruled the pipeline outranks every rule in this file.
    pinned: list[str] = field(default_factory=list)
    #: (title, old_max, new_max), largest reduction first — for the run log.
    examples: list[tuple[str, int, int]] = field(default_factory=list)
    #: Secondary copies brought into line with their primary listing during a full replay.
    aligned: int = 0


def _capped(est_min: int | None, est_max: int | None) -> tuple[int | None, int | None]:
    """The internship ceiling alone, with `salary_clamp`'s own single-value rule.

    Deliberately not a call to `clamp_salary`: this runs against rows written by many
    older clamp versions, and re-running the *whole* clamp would also apply every other
    ceiling that has moved since, silently rewriting thousands of estimates nobody
    reviewed. One repair, one class of change.
    """
    if est_max is None or est_max <= INTERNSHIP_MAX_MONTHLY_HKD:
        return est_min, est_max
    new_max = INTERNSHIP_MAX_MONTHLY_HKD
    new_min = est_min
    if new_min is None or new_min >= new_max:
        new_min = round(new_max * SINGLE_VALUE_MIN_FRACTION)
    return new_min, new_max


def repair_internship_salaries(
    db_path: str,
    *,
    dry_run: bool = True,
    live_board_only: bool = True,
) -> RepairSummary:
    """Clamp published internship estimates down to the internship ceiling.

    Idempotent: a second run finds nothing to change. Down-only: `_capped` can only lower
    a maximum, so a repeat run — or a bug in the title pattern — can never inflate a
    published salary.
    """
    summary = RepairSummary()
    board = "AND j.is_active = 1 AND j.is_primary = 1" if live_board_only else ""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"""SELECT j.title, e.source, e.source_id, e.seniority,
                       e.salary_estimated_min AS mn, e.salary_estimated_max AS mx,
                       e.salary_estimated_confidence AS conf,
                       e.salary_hkd_max AS disclosed_max,
                       e.manually_edited_at AS pinned_at
                  FROM jobs j JOIN job_enrichments e
                    ON j.source = e.source AND j.source_id = e.source_id
                 WHERE e.salary_estimated_max IS NOT NULL {board}""",
        ).fetchall()
        summary.examined = len(rows)

        pending: list[tuple[int | None, int, str, str]] = []
        for row in rows:
            if not is_internship(row["title"]):
                continue
            summary.matched += 1
            # An Ultimate Admin's correction is the last word. `enrichment.py` and
            # `salary_audit.py` already exclude a pinned row unconditionally; this
            # repair did not, so a hand-corrected salary was re-clamped every night
            # and survived only because `pipeline_publish` replays the admin_edits
            # ledger afterwards. The pin held by being undone downstream rather than
            # respected here, which also meant this repair was never idempotent on it.
            if row["pinned_at"] is not None:
                summary.pinned.append(f"[pinned] {row['title']}")
                continue
            # Two independent signals must agree before this rewrites a published
            # salary. The title is one; the stored seniority is the other, and it comes
            # from a separate field of the model's answer rather than from the words
            # being matched here.
            #
            # Found the night this shipped: "Weath Management Manager / Wealth Management
            # Intern" is ONE listing advertising two roles, stored as `mid`. The title
            # matches, but capping it at the internship ceiling would be wrong for the
            # Manager half. A compound title like that is exactly the case a title-only
            # rule cannot read, so it is reported and skipped rather than written.
            #
            # Skipping costs almost nothing: when the cap first shipped, all 168 matched
            # live rows independently carried `junior`, so this gate changes the outcome
            # only for the genuinely ambiguous handful.
            if row["seniority"] not in (None, "junior"):
                summary.suspicious.append(f"[{row['seniority']}] {row['title']}")
                continue
            # A figure the EMPLOYER stated is extraction, not estimation, and outranks
            # both this repair and the model that wrote the estimate. Two signals mark
            # one: a disclosed `salary_hkd_max`, or `confidence = "high"`, which the
            # enricher sets precisely when it found the number in the posting's text.
            #
            # Found live 2026-08-19, after this repair had already run unattended:
            # "Business Analyst/ Junior/Trainee Analyst (NOT IT/Data)" disclosed
            # HK$25,000-32,000 and was rewritten to the internship cap. Nine rows had
            # been overwritten that way. Only the board's COALESCE onto the disclosed
            # column kept it off the page — the stored estimate was simply lost.
            #
            # If the disclosed figure itself looks wrong, the bug is in the parser and
            # rewriting the estimate would hide it. So: report, never write.
            if row["disclosed_max"] is not None or row["conf"] == "high":
                summary.disclosed.append(f"[disclosed] {row['title']}")
                continue
            new_min, new_max = _capped(row["mn"], row["mx"])
            if (new_min, new_max) == (row["mn"], row["mx"]):
                continue
            pending.append((new_min, new_max, row["source"], row["source_id"]))
            summary.examples.append((row["title"], row["mx"], new_max))

        summary.repaired = len(pending)
        summary.examples.sort(key=lambda e: e[1], reverse=True)
        del summary.examples[10:]

        if summary.pinned:
            logger.info(
                "%d rows were hand-corrected by an admin and were left alone: %s",
                len(summary.pinned), "; ".join(summary.pinned[:5]),
            )

        if summary.disclosed:
            logger.info(
                "%d internship-matched rows carry an employer-stated figure and were "
                "left alone: %s",
                len(summary.disclosed), "; ".join(summary.disclosed[:5]),
            )

        if summary.suspicious:
            logger.warning(
                "%d internship-matched rows are not stored as 'junior' — review before "
                "trusting this write: %s",
                len(summary.suspicious), "; ".join(summary.suspicious[:5]),
            )

        if pending and not dry_run:
            with conn:
                conn.executemany(
                    """UPDATE job_enrichments
                          SET salary_estimated_min = ?, salary_estimated_max = ?
                        WHERE source = ? AND source_id = ?""",
                    pending,
                )
            logger.info("Repaired %d internship salary estimates", summary.repaired)
    finally:
        conn.close()
    return summary


def repair_grade_ceiling_salaries(
    db_path: str,
    *,
    dry_run: bool = True,
    live_board_only: bool = True,
) -> RepairSummary:
    """Re-apply the title-grade ceiling to estimates already published.

    Found 2026-08-19: 62 live rows sat ABOVE the ceiling their own title implies, and
    rows enriched on the SAME DAY sat both at and above it — so this was never simply
    "written before the ceiling shipped". `clamp_salary`'s floor raise adopted a matched
    role band outright and then re-applied only the GLOBAL cap, handing back a maximum
    the grade ceiling had already lowered. That is fixed in `salary_clamp` now; this
    closes the gap for rows written while it was broken.

    Front-office desks are exempt, exactly as `clamp_salary` exempts them — a flat
    "Vice President = HK$80,000" is a support-function rule, and revenue desks run their
    own ladder several times higher. The two exemptions must stay identical, which is
    why both read `FRONT_OFFICE_TIER` rather than spelling the string twice.

    Idempotent and down-only: `_title_grade_ceiling` is a pure function of the company
    slug and the title, so a second run finds nothing, and the ceiling can only lower.
    """
    summary = RepairSummary()
    board = "AND j.is_active = 1 AND j.is_primary = 1" if live_board_only else ""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"""SELECT j.title, j.company_slug, e.source, e.source_id, e.salary_tier,
                       e.salary_estimated_min AS mn, e.salary_estimated_max AS mx,
                       e.salary_estimated_confidence AS conf,
                       e.salary_hkd_max AS disclosed_max,
                       e.manually_edited_at AS pinned_at
                  FROM jobs j JOIN job_enrichments e
                    ON j.source = e.source AND j.source_id = e.source_id
                 WHERE e.salary_estimated_max IS NOT NULL {board}""",
        ).fetchall()
        summary.examined = len(rows)

        pending: list[tuple[int | None, int, str, str]] = []
        for row in rows:
            if row["salary_tier"] == FRONT_OFFICE_TIER:
                continue
            ceiling = _title_grade_ceiling(row["company_slug"], row["title"])
            if ceiling is None or row["mx"] is None or row["mx"] <= ceiling:
                continue
            summary.matched += 1
            # An Ultimate Admin's correction outranks this ceiling, same as above.
            if row["pinned_at"] is not None:
                summary.pinned.append(f"[pinned] {row['title']}")
                continue
            # Same rule as the internship repair: a figure the EMPLOYER stated is
            # extraction, not estimation, and outranks this repair's own ceiling.
            if row["disclosed_max"] is not None or row["conf"] == "high":
                summary.disclosed.append(f"[disclosed] {row['title']}")
                continue
            new_min = row["mn"]
            if new_min is None or new_min >= ceiling:
                new_min = round(ceiling * SINGLE_VALUE_MIN_FRACTION)
            pending.append((new_min, ceiling, row["source"], row["source_id"]))
            summary.examples.append((row["title"], row["mx"], ceiling))

        summary.repaired = len(pending)
        summary.examples.sort(key=lambda e: e[1], reverse=True)
        del summary.examples[10:]

        if summary.disclosed:
            logger.info(
                "%d grade-ceiling rows carry an employer-stated figure and were left "
                "alone: %s", len(summary.disclosed), "; ".join(summary.disclosed[:5]),
            )

        if pending and not dry_run:
            with conn:
                conn.executemany(
                    """UPDATE job_enrichments
                          SET salary_estimated_min = ?, salary_estimated_max = ?
                        WHERE source = ? AND source_id = ?""",
                    pending,
                )
            logger.info("Repaired %d grade-ceiling salary estimates", summary.repaired)
    finally:
        conn.close()
    return summary


def replay_salary_rules(
    db_path: str,
    *,
    dry_run: bool = True,
    active_only: bool = True,
    rule_names: frozenset[str] | None = None,
) -> RepairSummary:
    """Re-apply the current deterministic clamp to stored estimates for free.

    This is deliberately different from a new model enrichment. The pre-clamp model
    output is not stored, so it only replays a *terminal*, employer/title-specific rule
    that can safely replace a previously finalised range. Re-running coordinate floors
    against an already-clamped figure would manufacture promotions on a second pass.
    It neither calls DeepSeek nor changes ``prompt_version``. ``rule_names``
    makes a replay deliberately narrow when a newly reviewed anchor should be
    applied without also replaying every other terminal rule.
    Employer-disclosed figures and Ultimate Admin edits remain untouchable.

    Active cross-post copies are included, not hidden behind ``is_primary``. Once their
    primary listing has a safe deterministic result, unprotected secondary estimates are
    aligned to it so a later source-priority change cannot resurrect a stale range.
    """
    summary = RepairSummary()
    active = "AND j.is_active = 1" if active_only else ""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"""SELECT j.title, j.company_slug, j.source_tier, j.is_primary,
                       j.cross_posted, j.apply_url, e.source, e.source_id,
                       e.seniority, e.salary_tier, e.salary_role, e.salary_grade,
                       e.salary_estimated_min AS mn, e.salary_estimated_max AS mx,
                       e.salary_estimated_confidence AS conf,
                       e.salary_hkd_max AS disclosed_max,
                       e.manually_edited_at AS pinned_at
                  FROM jobs j JOIN job_enrichments e
                    ON j.source = e.source AND j.source_id = e.source_id
                 WHERE e.salary_estimated_max IS NOT NULL {active}"""
        ).fetchall()
        summary.examined = len(rows)

        targets: dict[tuple[str, str], tuple[int | None, int | None]] = {}
        protected: set[tuple[str, str]] = set()
        rows_by_key = {(row["source"], row["source_id"]): row for row in rows}
        for row in rows:
            key = (row["source"], row["source_id"])
            if row["pinned_at"] is not None:
                protected.add(key)
                summary.pinned.append(f"[pinned] {row['title']}")
                continue
            if row["disclosed_max"] is not None or row["conf"] == "high":
                protected.add(key)
                summary.disclosed.append(f"[disclosed] {row['title']}")
                continue
            # Require an explicit terminal rule. The standard coordinate ladder is an
            # enrichment-time transform: replaying it against the stored final result
            # is not mathematically idempotent (a source-tier multiplier may already
            # have been applied). Exact employer/title rules are safe because they own
            # both endpoints and deliberately supersede the prior range.
            terminal = salary_rule_resolution(
                row["company_slug"],
                row["title"],
                role=row["salary_role"],
                internship=is_internship(row["title"]),
            ).winner
            if terminal is None:
                continue
            if rule_names is not None and terminal.rule not in rule_names:
                continue
            summary.matched += 1
            targets[key] = clamp_salary(
                row["salary_tier"], row["seniority"], row["mn"], row["mx"],
                role=row["salary_role"], grade=row["salary_grade"],
                company_slug=row["company_slug"], title=row["title"],
                source_tier=row["source_tier"],
            )

        groups: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            if row["cross_posted"] and row["apply_url"]:
                groups.setdefault(row["apply_url"], []).append(row)
        for members in groups.values():
            primary = next((row for row in members if row["is_primary"]), None)
            if primary is None:
                continue
            primary_key = (primary["source"], primary["source_id"])
            if primary_key in protected or primary_key not in targets:
                continue
            canonical = targets[primary_key]
            for row in members:
                key = (row["source"], row["source_id"])
                if key == primary_key or key in protected:
                    continue
                if targets.get(key) != canonical:
                    targets[key] = canonical
                    summary.aligned += 1

        pending: list[tuple[int | None, int | None, str, str]] = []
        for key, target in targets.items():
            row = rows_by_key[key]
            before = (row["mn"], row["mx"])
            if target == before:
                continue
            pending.append((target[0], target[1], *key))
            summary.examples.append((row["title"], row["mx"], target[1] or 0))
        summary.repaired = len(pending)
        summary.examples.sort(key=lambda example: abs(example[1] - example[2]), reverse=True)
        del summary.examples[10:]

        if pending and not dry_run:
            with conn:
                conn.executemany(
                    """UPDATE job_enrichments
                          SET salary_estimated_min = ?, salary_estimated_max = ?
                        WHERE source = ? AND source_id = ?""",
                    pending,
                )
    finally:
        conn.close()
    return summary
