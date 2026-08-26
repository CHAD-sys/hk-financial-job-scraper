"""
What admins have decided the anchors got wrong, fed back to the estimator.

WHY THIS EXISTS
---------------
`salary_guidlines/hk_salary_anchors.json` is calibrated from three published
salary guides. It is very good and it is not complete: it prices 471 (tier, role,
grade) cells, and Hong Kong finance has more shapes of job than that. When the
estimator lands on the wrong cell — or the right cell prices this employer badly
— an admin corrects the number by hand, and until now that judgement stopped at
the row it was made on. The next similar posting got the same wrong answer.

`admin_salary_corrections` (phase 36) keeps those judgements. This module turns
them into something the model can read: for the Role being enriched, the handful
of past corrections about roles of the same shape, stated as evidence.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
**It does not write to the anchors file.** Those bands are a weighted merge of
three sources (60/25/15 by band midpoint, see `meta.source`). Folding single
observations into them would corrupt a calibration nobody could then reconstruct,
and one admin's view of one posting is not a salary survey. Corrections sit
beside the anchors and are offered as evidence; the anchors stay the baseline.

**It does not feed `salary_anchors.fingerprint()`.** Published rule tables do
participate in that digest, because changing a shared rule must create a visible
staleness decision. Individual corrections remain different: if this live
database evidence were included, every hand-correction would mark all ~13,000
stored estimates stale and re-pay DeepSeek for the lot — roughly $40 a time,
triggered by an admin fixing one salary.

The consequence is deliberate and worth stating plainly: corrections change what
FUTURE enrichments are told, not what is already stored. A correction already
protects its own row forever (`manually_edited_at`); this is about the next
posting that looks like it.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass

logger = logging.getLogger(__name__)

#: How many corrections to put in front of the model for one Role. Small on
#: purpose: this is evidence, not a second anchor table, and every line costs
#: input tokens on every enrichment call for the rest of the run.
MAX_EVIDENCE_LINES = 5

#: Corrections older than this stop being offered. A judgement about what a role
#: paid two years ago is not evidence about what it pays now, and the table is
#: append-only, so without a horizon it would grow into the prompt forever.
MAX_AGE_DAYS = 365

#: Words carrying no signal about what KIND of job a title names. Dropped before
#: overlap scoring so "Senior Analyst, Credit" and "Analyst - Credit Risk" are
#: recognised as the same shape rather than sharing only a seniority word.
_STOPWORDS = frozenset({
    "senior", "junior", "assistant", "associate", "vice", "president", "avp",
    "vp", "svp", "evp", "director", "manager", "head", "lead", "officer",
    "executive", "specialist", "and", "the", "of", "for", "to", "in", "at",
    "hong", "kong", "hk", "greater", "china", "apac", "asia", "pacific",
})

_WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Correction:
    """One admin's judgement about what one Role should have been priced at."""

    title: str
    company: str
    seniority: str | None
    category: str | None
    old_min: int | None
    old_max: int | None
    new_min: int | None
    new_max: int | None

    @property
    def has_range(self) -> bool:
        return self.new_min is not None or self.new_max is not None


def _shape(title: str | None) -> frozenset[str]:
    """The content words of a title, lowercased, stopwords removed."""
    if not title:
        return frozenset()
    return frozenset(_WORD.findall(title.lower())) - _STOPWORDS


def load(conn: sqlite3.Connection, *, max_age_days: int = MAX_AGE_DAYS) -> list[Correction]:
    """
    Every usable correction, newest first. `[]` on any problem.

    Returns `[]` rather than raising for a database predating phase 36, and for
    anything else that goes wrong reading it: this is an enhancement to an
    estimate, and failing an entire nightly enrichment run because a calibration
    hint could not be loaded would be a far worse outcome than estimating without
    the hint.

    Only the LATEST correction per Role is kept. An admin who corrects the same
    posting twice has changed their mind, not produced two observations, and the
    superseded figure must not be offered as evidence for anything.
    """
    try:
        rows = conn.execute(
            """
            SELECT c.title, c.company, c.seniority, c.job_category,
                   c.old_min, c.old_max, c.new_min, c.new_max
              FROM admin_salary_corrections c
              JOIN (
                SELECT source, source_id, MAX(id) AS latest
                  FROM admin_salary_corrections
                 GROUP BY source, source_id
              ) newest
                ON newest.latest = c.id
             WHERE c.corrected_at >= datetime('now', ?)
             ORDER BY c.id DESC
            """,
            (f"-{int(max_age_days)} days",),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.debug("Salary corrections unavailable (%s); estimating without them.", exc)
        return []

    corrections = [
        Correction(
            title=row[0] or "",
            company=row[1] or "",
            seniority=row[2],
            category=row[3],
            old_min=row[4],
            old_max=row[5],
            new_min=row[6],
            new_max=row[7],
        )
        for row in rows
    ]
    return [c for c in corrections if c.has_range]


def _relevance(
    correction: Correction, *, title_shape: frozenset[str], seniority: str | None,
) -> int:
    """
    How much this correction says about the Role being enriched.

    Title-word overlap, with one bonus point for a matching seniority. Seniority
    alone is worth nothing here — "every mid-level role" is not a shape, and
    scoring it as one would fill the evidence block with unrelated jobs that
    happen to share a rung.
    """
    overlap = len(_shape(correction.title) & title_shape)
    if overlap == 0:
        return 0
    if seniority and correction.seniority and correction.seniority == seniority:
        overlap += 1
    return overlap


def evidence_for(
    corrections: list[Correction],
    *,
    title: str,
    seniority: str | None = None,
    limit: int = MAX_EVIDENCE_LINES,
) -> str:
    """
    The prompt block for one Role, or `""` when nothing is relevant.

    Empty is the common case and the important one: a Role with no similar
    correction must produce a prompt byte-identical to the one it produced before
    this module existed. Returning a "no corrections available" line instead
    would put a useless sentence in front of the model on every call, and cost
    input tokens on all ~6,000 of them to say nothing.
    """
    if not corrections:
        return ""

    title_shape = _shape(title)
    if not title_shape:
        return ""

    scored = [
        (score, c)
        for c in corrections
        if (score := _relevance(c, title_shape=title_shape, seniority=seniority)) > 0
    ]
    if not scored:
        return ""

    scored.sort(key=lambda pair: pair[0], reverse=True)
    lines = [_line(correction) for _, correction in scored[:limit]]

    return (
        "\nHUMAN CORRECTIONS — our team reviewed these similar roles and replaced "
        "the estimate with the figure below. Treat them as ground truth about "
        "what this kind of role pays in Hong Kong, and prefer them over the "
        "anchor table where they disagree:\n" + "\n".join(lines) + "\n"
    )


def _line(c: Correction) -> str:
    """One correction, as one line. `was ...` is included when it is known."""
    corrected = _range(c.new_min, c.new_max)
    previously = _range(c.old_min, c.old_max)
    who = f"{c.title.strip()} at {c.company.strip()}" if c.company.strip() else c.title.strip()
    tail = f" (estimator had said {previously})" if previously else ""
    return f"- {who}: {corrected}/month{tail}"


def _range(low: int | None, high: int | None) -> str:
    if low and high:
        return f"HK${low:,}-{high:,}"
    if low:
        return f"HK${low:,}+"
    if high:
        return f"up to HK${high:,}"
    return ""
