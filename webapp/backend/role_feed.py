"""Deep module for the Roles FinEx suggests to one Seeker.

The interface is two outcome-oriented operations. Callers provide the local jobs.db
connection and, for a signed-in request, an opaque Seeker id. Everything else—
Seeker signal reads, Role-reference resolution, candidate policy, resume evidence,
ranking, feedback projection and impression attribution—stays inside this module.

Storage ownership remains unchanged: Listing facts are read from jobs.db through
``job_read`` and Seeker-owned signals are read/written through ``seekers_store``.
The databases are never attached or joined.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

import job_read
import recommendations
import resume_intelligence
import seekers_store
from job_read import CatalogueAudience, JobFilters, JobSummary, Sort, Visibility
from pydantic import BaseModel, Field

_CANDIDATE_WINDOW = 1_000
#: The evidence-directed leg. Separate from the recency window because it is a
#: different question — "what matches this person", not "what is new" — and
#: because it is only ever paid for by a Seeker who has given us evidence.
_TARGETED_WINDOW = 600
_MAX_FEED_PAGES = 10


class RoleFeedItem(BaseModel):
    job: JobSummary
    score: float
    reasons: tuple[str, ...] = ()
    feedback: tuple[str, ...] = ()


class RoleFeed(BaseModel):
    personalized: bool
    personalization_enabled: bool
    model_version: str
    signal_count: int
    saved_role_count: int
    activity_count: int
    eligible_count: int
    page: int
    page_size: int
    total_pages: int
    generated_at: str
    batch_id: str | None
    items: tuple[RoleFeedItem, ...] = ()


class ResumeMatchItem(BaseModel):
    job: JobSummary
    match_score: int
    reasons: tuple[str, ...]


class ResumeMatches(BaseModel):
    has_resume: bool
    resume_uploaded_at: str | None
    model_version: str
    items: tuple[ResumeMatchItem, ...] = Field(default_factory=tuple)


def _candidates(
    conn: sqlite3.Connection,
    *,
    evidence: "resume_intelligence.ResumeEvidence | None" = None,
) -> list[JobSummary]:
    """The one bounded candidate policy for seeker suggestions — two legs.

    **Recency**, newest-first, exactly as before. It is what a Seeker with no
    evidence yet gets, and it keeps a feed that already has evidence open to
    things just posted.

    **Evidence-directed**, and this is the new half. The recency leg is a
    1,000-Role slice of an 1,813-Role board: 45% of what a Seeker could be
    shown was unreachable, and which 45% depended on nothing but posting date.
    A Morgan Stanley quant's ideal role posted three weeks ago simply was not
    a candidate — not ranked low, not a candidate. Widening the slice is the
    obvious fix and the wrong one: it costs linearly and still misses anything
    past the new edge.

    So instead we ask the board directly for the Roles this Seeker's evidence
    points at — their rarest skills, in the catalogue's own spelling, across
    the WHOLE board with no recency bound (see
    `resume_intelligence.retrieval_terms`). Retrieval becomes a function of
    relevance rather than of date, and the union stays bounded.

    Ordering within the union does not matter: every candidate is scored, and
    the score decides. This returns a POOL, not a ranking.
    """
    pool = job_read.list_jobs(
        conn,
        JobFilters(),
        sort=Sort.NEWEST,
        page=1,
        page_size=_CANDIDATE_WINDOW,
        visibility=Visibility.BOARD,
        audience=CatalogueAudience.MEMBER,
    ).jobs

    terms = resume_intelligence.retrieval_terms(evidence) if evidence else ()
    if not terms:
        return pool

    targeted = job_read.list_jobs(
        conn,
        JobFilters(skills=terms),
        sort=Sort.NEWEST,
        page=1,
        page_size=_TARGETED_WINDOW,
        visibility=Visibility.BOARD,
        audience=CatalogueAudience.MEMBER,
    ).jobs

    seen = {(role.source, role.source_id) for role in pool}
    pool.extend(
        role for role in targeted if (role.source, role.source_id) not in seen
    )
    return pool


def _refs(rows: list[dict]) -> list[tuple[str, str]]:
    return [(str(row["source"]), str(row["source_id"])) for row in rows]


@dataclass(frozen=True)
class SeekerRanking:
    """The shared core result behind every ranked-Role surface.

    `ranked` is None when the Seeker has no first-party relevance evidence at
    all yet (no saved Roles, no settled search, no "More like this", no clicks,
    no resume) — every caller (the in-app feed, Alerts) must treat that as
    "nothing to show", never fall back to a market-wide default.
    """

    ranked: recommendations.RecommendationResult | None
    saved_role_count: int
    activity_count: int


def rank_for_seeker(
    conn: sqlite3.Connection,
    *,
    seeker_id: str,
    page: int,
    page_size: int,
    now: datetime,
) -> SeekerRanking:
    """Assemble one Seeker's first-party signals, fetch the candidate pool, and rank.

    Pulled out of `roles_for_seeker` so a second surface (Alerts, alerts.py)
    can get the identical ranking — same signals, same candidate policy, same
    `RankedRole.matched` semantics — without a second, drifting copy of this
    assembly. What each surface does with the result (paginate and attribute
    impressions for the in-app feed; threshold and email for Alerts) stays in
    that surface, not here.
    """
    store = seekers_store.get_store()
    saved_rows = store.list_saved_roles(seeker_id)
    saved_order = _refs(saved_rows)
    saved_refs = set(saved_order)
    activity = store.list_discovery_events(seeker_id)
    feedback_rows = store.list_recommendation_feedback(seeker_id)
    more_like_order = _refs([row for row in feedback_rows if row["action"] == "more_like"])
    dismissed_refs = set(_refs([row for row in feedback_rows if row["action"] == "not_interested"]))
    clicked_order = _refs(store.list_clicked_recommendation_refs(seeker_id))
    resume_row = store.get_resume(seeker_id, include_document=True)
    resume_evidence = (
        resume_intelligence.evidence_from_storage(
            resume_row["text_content"], resume_row["analysis"]
        )
        if resume_row
        else None
    )

    has_relevance_evidence = bool(
        saved_rows or activity or more_like_order or clicked_order or resume_evidence
    )
    if not has_relevance_evidence:
        return SeekerRanking(ranked=None, saved_role_count=0, activity_count=0)

    candidates = _candidates(conn, evidence=resume_evidence)
    saved_roles = job_read.jobs_by_refs(conn, saved_order, visibility=Visibility.ADDRESSABLE)
    more_like_roles = job_read.jobs_by_refs(
        conn, more_like_order, visibility=Visibility.ADDRESSABLE
    )
    clicked_roles = job_read.jobs_by_refs(conn, clicked_order, visibility=Visibility.ADDRESSABLE)
    ranked = recommendations.rank_roles(
        candidates,
        saved_roles=saved_roles,
        discovery_events=activity,
        more_like_roles=more_like_roles,
        clicked_roles=clicked_roles,
        saved_refs=saved_refs,
        dismissed_refs=dismissed_refs,
        hidden_employer_keys=set(),
        resume_evidence=resume_evidence,
        page=page,
        page_size=page_size,
        now=now,
    )
    return SeekerRanking(
        ranked=ranked, saved_role_count=len(saved_roles), activity_count=len(activity)
    )


def roles_for_seeker(
    conn: sqlite3.Connection,
    *,
    seeker_id: str | None,
    page: int,
    page_size: int,
    now: datetime | None = None,
) -> RoleFeed:
    """Return and attribute one evidence-based Role feed for a signed-in Seeker.

    An anonymous visitor, or a Seeker with no settled first-party signal, gets
    an empty feed. A generic market sample would be another catalogue-browsing
    path and would not be relevant to that person's research.
    """
    generated_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    safe_page = max(1, min(int(page), _MAX_FEED_PAGES))
    safe_page_size = max(1, min(int(page_size), 24))
    store = seekers_store.get_store() if seeker_id else None

    if not seeker_id:
        return RoleFeed(
            personalized=False,
            personalization_enabled=False,
            model_version=recommendations.MODEL_VERSION,
            signal_count=0,
            saved_role_count=0,
            activity_count=0,
            eligible_count=0,
            page=safe_page,
            page_size=safe_page_size,
            total_pages=0,
            generated_at=generated_at.isoformat(),
            batch_id=None,
        )

    result = rank_for_seeker(
        conn, seeker_id=seeker_id, page=safe_page, page_size=safe_page_size, now=generated_at
    )
    if result.ranked is None:
        return RoleFeed(
            personalized=False,
            personalization_enabled=True,
            model_version=recommendations.MODEL_VERSION,
            signal_count=0,
            saved_role_count=0,
            activity_count=0,
            eligible_count=0,
            page=safe_page,
            page_size=safe_page_size,
            total_pages=0,
            generated_at=generated_at.isoformat(),
            batch_id=None,
        )
    ranked = result.ranked

    feedback_rows = store.list_recommendation_feedback(seeker_id) if store else []
    feedback_by_ref: dict[tuple[str, str], list[str]] = {}
    for row in feedback_rows:
        feedback_by_ref.setdefault((str(row["source"]), str(row["source_id"])), []).append(
            str(row["action"])
        )

    items = tuple(
        RoleFeedItem(
            job=item.job,
            score=item.score,
            reasons=item.reasons,
            feedback=tuple(feedback_by_ref.get((item.job.source, item.job.source_id), ())),
        )
        for item in ranked.items
    )

    batch_id = None
    if store and seeker_id and items:
        batch_id = store.record_recommendation_impressions(
            seeker_id,
            (
                {
                    "source": item.job.source,
                    "source_id": item.job.source_id,
                    "score": item.score,
                    "reasons": item.reasons,
                    "position": position,
                }
                for position, item in enumerate(items, start=1)
            ),
            model_version=recommendations.MODEL_VERSION,
            now=generated_at,
        )

    return RoleFeed(
        personalized=ranked.personalized,
        personalization_enabled=bool(seeker_id),
        model_version=recommendations.MODEL_VERSION,
        signal_count=ranked.signal_count,
        saved_role_count=result.saved_role_count,
        activity_count=result.activity_count,
        eligible_count=ranked.eligible_count,
        page=safe_page,
        page_size=safe_page_size,
        total_pages=min(
            _MAX_FEED_PAGES,
            (ranked.eligible_count + safe_page_size - 1) // safe_page_size,
        ),
        generated_at=generated_at.isoformat(),
        batch_id=batch_id,
        items=items,
    )


def resume_matches_for_seeker(
    conn: sqlite3.Connection,
    *,
    seeker_id: str,
    limit: int,
) -> ResumeMatches:
    """Return the current Roles with strongest observable resume alignment."""
    safe_limit = max(1, min(int(limit), 12))
    row = seekers_store.get_store().get_resume(seeker_id, include_document=True)
    if row is None:
        return ResumeMatches(
            has_resume=False,
            resume_uploaded_at=None,
            model_version=resume_intelligence.MATCH_MODEL_VERSION,
        )

    evidence = resume_intelligence.evidence_from_storage(row["text_content"], row["analysis"])
    matches = resume_intelligence.rank_resume_matches(
        _candidates(conn, evidence=evidence), evidence, limit=safe_limit
    )
    return ResumeMatches(
        has_resume=True,
        resume_uploaded_at=str(row["uploaded_at"]),
        model_version=resume_intelligence.MATCH_MODEL_VERSION,
        items=tuple(
            ResumeMatchItem(
                job=item.job,
                match_score=item.score,
                reasons=item.reasons,
            )
            for item in matches
        ),
    )
