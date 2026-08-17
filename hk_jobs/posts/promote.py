"""
LP-3 promotion: run the extractor over pending linkedin_posts rows and
promote the ones that clear the gate into the canonical `jobs` table.

Promotion gate (PLAN_LINKEDIN_POSTS.md decision #8): concrete title +
HK-plausible location + stored confidence. Both must hold — a post with no
identifiable title, or one whose location can't be pinned to Hong Kong, stays
in linkedin_posts (extraction_status='rejected') and is never surfaced.

Confidential employers (decision #7): NEVER guess. If the extractor found no
named employer, company is set to "Confidential via {recruiter}" and the slug
is recruiter-based (confidential-{recruiter-slug}) — this means dedup_hash()
can only ever collapse a recruiter's own reposts of the SAME text, never
different confidential mandates, and never a real board listing. Named
employers get a best-effort slug from the company name so dedup_hash() CAN
match an existing board listing and trigger cross_posted (the "hidden"
signal) — but this is best-effort only: there's no runtime lookup from a
free-text employer name to an existing companies.yaml slug in this codebase
(confirmed: no such utility exists, only offline one-off resolver scripts
like scripts/resolve_indeed_slugs.py). A naive slugify that happens not to
match an existing slug just means this particular post-job doesn't get
flagged cross_posted — it's still promoted and shown, just without the dedup
credit. Never a promotion-blocking failure.

The "hidden" flag itself is NOT a stored column — it falls out of calling
JobStore.reconcile_cross_posted() after promotion: source='linkedin_posts'
AND cross_posted=False on the resulting Job means genuinely no cross-source
match was found (PLAN_LINKEDIN_POSTS.md §4, §7).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Callable

from hk_jobs.posts.extractor import (
    PROMPT_VERSION,
    ExtractionResult,
    ExtractorAuthError,
    extract_post,
)
from hk_jobs.posts.store import PostStore
from hk_jobs.schema import Job
from hk_jobs.storage import JobStore

logger = logging.getLogger(__name__)

SOURCE = "linkedin_posts"
SOURCE_TIER = "social"


@dataclass
class PromotionSummary:
    processed: int = 0
    promoted: int = 0
    rejected: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


_EMPTY_TEXT = object()  # sentinel distinct from a legitimate None extraction result


def run_promotion(
    db_path: str,
    *,
    limit: int | None = None,
    extractor_fn: Callable[[str], ExtractionResult | None] | None = None,
    max_workers: int = 1,
) -> PromotionSummary:
    """
    Extract + promote every linkedin_posts row still in extraction_status='pending'.

    One bad post (extraction failure, malformed row) is logged and skipped —
    same per-item isolation convention as fetcher.py and BaseAdapter._safe_fetch.
    reconcile_cross_posted() is called once at the end of the whole pass, not
    per-post, matching how it's already called once per daily pipeline run for
    the ATS sources (storage.py's own convention — it re-derives cross_posted/
    apply_url/is_primary globally, not incrementally).

    extractor_fn defaults to hk_jobs.posts.extractor.extract_post (DeepSeek)
    when not passed — resolved dynamically INSIDE the function body (not as
    a literal parameter default) so tests that monkeypatch
    hk_jobs.posts.promote.extract_post keep working; a default bound at def
    time would capture the real function forever and silently bypass any
    monkeypatch. Pass extract_post_haiku (or any compatible callable) for a
    different model/provider — e.g. a one-time bulk backlog where DeepSeek's
    ~5-6s/call sequential rate would take hours.

    max_workers > 1 parallelizes ONLY the extractor_fn network calls, via a
    thread pool (I/O-bound HTTP requests — safe to run concurrently despite
    the GIL). Every SQLite write still happens on the single `conn`, in the
    main thread, one row at a time as each future completes — never from a
    worker thread — so there's no concurrent-write risk.
    """
    if extractor_fn is None:
        extractor_fn = extract_post

    summary = PromotionSummary()
    rows = _fetch_pending(db_path, limit=limit)
    if not rows:
        logger.info("No pending posts to promote")
        return summary

    # Loaded once up front rather than per-post — cheap (one query), and a job
    # promoted before its recruiter's email was harvested still gets it via
    # hk_jobs.posts.email_harvest's separate backfill pass over ALREADY-promoted
    # rows (this dict only helps NEW promotions in this run).
    recruiter_emails = PostStore(db_path).all_recruiter_emails()

    promoted_jobs: list[Job] = []
    conn = sqlite3.connect(db_path)

    def _extract(row: sqlite3.Row):
        text = row["post_text"]
        if not text or not text.strip():
            return (row, _EMPTY_TEXT, None)
        try:
            return (row, extractor_fn(text), None)
        except Exception as exc:  # noqa: BLE001 - surfaced to the main thread below
            return (row, None, exc)

    def _handle(row: sqlite3.Row, result, exc: Exception | None) -> bool:
        """Applies one row's extraction outcome. Returns False to stop the whole run."""
        summary.processed += 1

        if result is _EMPTY_TEXT:
            # Empty content (seen in real discovery-search results — e.g. a
            # company post with no body text). extractor_fn would also return
            # None for this, but leaving the row 'pending' would retry it
            # forever for zero chance of ever succeeding. Reject immediately.
            summary.rejected += 1
            _set_status(conn, row["post_urn"], "rejected")
            return True

        if isinstance(exc, ExtractorAuthError):
            # A bad/missing key affects every remaining post identically —
            # no point continuing just to fail the same way.
            logger.error("Extractor auth failed — aborting promotion run entirely")
            summary.errors.append("Extractor auth failed")
            summary.failed += 1
            return False

        if exc is not None:
            logger.error("Post %s: extraction failed: %s", row["post_urn"], exc)
            summary.failed += 1
            summary.errors.append(f"{row['post_urn']}: {exc}")
            return True

        try:
            _store_extraction_result(conn, row["post_urn"], result)

            if result is None:
                summary.failed += 1
                return True

            if not _passes_gate(result):
                summary.rejected += 1
                _set_status(conn, row["post_urn"], "rejected")
                return True

            job = _build_job(row, result, recruiter_emails.get(row["recruiter_slug"]))
            promoted_jobs.append(job)
            summary.promoted += 1
            _set_status(conn, row["post_urn"], "promoted")
        except Exception as exc2:  # noqa: BLE001 - one bad post must not stop the rest
            logger.exception("Post %s: promotion failed", row["post_urn"])
            summary.failed += 1
            summary.errors.append(f"{row['post_urn']}: {exc2}")
        return True

    try:
        if max_workers > 1:
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {pool.submit(_extract, row): row for row in rows}
                for future in as_completed(futures):
                    row, result, exc = future.result()
                    if not _handle(row, result, exc):
                        for f in futures:
                            f.cancel()
                        break
        else:
            for row in rows:
                _, result, exc = _extract(row)
                if not _handle(row, result, exc):
                    break
    finally:
        conn.close()

    if promoted_jobs:
        with JobStore(db_path) as store:
            inserted, updated = store.upsert_many(promoted_jobs)
            groups, rows_updated = store.reconcile_cross_posted()
        logger.info(
            "Promoted %d jobs (%d inserted, %d updated). Cross-source: %d groups, %d rows updated.",
            len(promoted_jobs), inserted, updated, groups, rows_updated,
        )

    logger.info(
        "Promotion run done: %d processed, %d promoted, %d rejected, %d failed",
        summary.processed, summary.promoted, summary.rejected, summary.failed,
    )
    return summary


def _fetch_pending(db_path: str, *, limit: int | None) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        sql = "SELECT * FROM linkedin_posts WHERE extraction_status = 'pending' ORDER BY fetched_at"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


# ── Does the extraction LOOK like what it claims to be? ───────────────────────
# The prompt in extractor.py is already explicit: "NEVER invent an employer name.
# employer_named is true ONLY if a specific company/bank/fund name is explicitly
# written in the post. A phrase like 'a leading private bank' or 'my client' is
# NOT a named employer." The model agrees and then does it anyway, and this module
# used to copy whatever it said onto the board: `employer_named: true,
# employer_hint: "business leaders to"` produced a company literally called
# "business leaders to", sliced out of "Partner with business leaders to forecast
# talent needs". 15% of named employers were prose like that. One guess collided
# with a real employer's name, so a recruiter's post answered a filter for that
# employer's own vacancies and inflated its count.
#
# So `employer_named` is no longer taken on trust — a hint has to look like a name
# before it is used as one. Tightening the prompt cannot replace this: the prompt
# was already correct, and a model's self-report about its own compliance is not
# evidence. These are shape tests, not a blocklist of known-bad strings, so a new
# fragment the model has never produced before is still caught.
#
# The thresholds are calibrated against every hint the live extractor has actually
# returned — see the table in tests/test_posts_promote.py, where the accept-list
# matters more than the reject-list. Known residue that still gets through: bare
# generic nouns ("Chinese", "DCM", "Private Family Office") and plausible-looking
# truncations ("Tier International Bank"). They are wrong but name-shaped, and
# tightening far enough to catch them starts rejecting real employers.

#: Words that begin prose, never a company name.
_PROSE_STARTERS = frozenset({
    "we", "we're", "we’re", "i", "i'm", "i’m", "our", "your", "their", "my",
    "this", "that", "these", "those", "it", "there",
    "join", "joining", "seeking", "looking", "hiring", "apply", "please",
    "exciting", "opportunity", "proven", "proficient", "experienced",
    "currently", "urgently", "now", "also", "given", "after",
})

#: A name cannot END on a function word — "business leaders to" is a clause with
#: its object cut off, which is exactly what slicing mid-sentence produces.
_DANGLING_WORDS = frozenset({
    "to", "and", "or", "with", "for", "of", "in", "on", "at", "from", "by",
    "as", "a", "an", "the", "&", "that", "which", "who", "is", "are",
})

#: What the prompt asks for when employer_named is FALSE — "a short generic
#: description like 'international private bank'". Ending on one of these means
#: the model described an employer rather than naming one, whatever the flag said.
_GENERIC_TAIL = frozenset({
    "leading", "foreign", "regional", "corporate", "international", "financial",
    "dynamic", "prestigious", "reputable", "renowned", "growing", "global",
    "boutique", "top", "major", "large", "established", "sizeable", "reputed",
})

#: Prose verbs. A name is a noun phrase; "We are partnering with…" is a sentence.
_PROSE_VERB = re.compile(r"\b(are|is|was|were|will|would|can|have|has|been)\b", re.I)

#: Text lifted out of a post body brings its layout with it. A real name never
#: contains a newline, a tab, or the non-breaking space LinkedIn sprinkles around.
_LAYOUT_CHARS = "\n\r\t\v\f\xa0  "

#: "東亞銀行 The Bank of East Asia (BEA)" is seven words and real, so the cap sits
#: above it rather than at the more natural four.
_NAME_WORD_CAP = 7


def _is_proper_noun(word: str) -> bool:
    """Capitalised, or any non-ASCII script (CJK names carry no case)."""
    head = word.lstrip("(“\"'‘（")[:1]
    return bool(head) and (head.isupper() or not head.isascii())


def _looks_like_an_employer_name(hint: str) -> bool:
    """
    Whether `hint` is shaped like an employer's name rather than post prose.

    Refusing is cheap and never blocks a promotion: the caller falls back to the
    "Confidential via {recruiter}" path that decision #7 already specifies for a
    mandate with no named employer, which is always available and always correct.
    """
    name = (hint or "").strip()
    if len(name) < 3:
        return False                                  # "Sc" — a truncation
    if any(ch in name for ch in _LAYOUT_CHARS):
        return False                                  # sliced out of the body
    if "#" in name or "http" in name.lower():
        return False                                  # hashtag block or a link
    if _PROSE_VERB.search(name):
        return False

    words = name.split()
    if len(words) > _NAME_WORD_CAP:
        return False
    if name[:1].islower() and len(words) > 1:
        return False                                  # "business leaders to"

    first = words[0].lower().strip(".,:;!?")
    if first in _PROSE_STARTERS:
        return False
    last = words[-1].lower().strip(".,:;!?()（）")
    if last in _DANGLING_WORDS or last in _GENERIC_TAIL:
        return False

    # An article has to be followed by the thing it introduces. This is the rule
    # that separates the two article shapes the model produces: "The Bank of East
    # Asia (BEA)" names an employer, "A leading foreign" only describes one.
    if first in {"a", "an", "the"} and not any(_is_proper_noun(w) for w in words[1:]):
        return False

    return True


def _looks_like_a_job_title(title: str) -> bool:
    """
    Whether `title` is a job title rather than a fragment of the post.

    Deliberately looser than the employer test, because there is no fallback for
    a title: refusing one refuses the whole post. So this rejects only shapes that
    cannot be a title under any reading — no word cap (real HK finance titles run
    long: "Executive Director, Consumer & Retail Coverage, Investment Banking"),
    and no vocabulary rules. It cannot catch a plausible truncation like "Direc".
    """
    text = (title or "").strip()
    if len(text) < 3:
        return False                                  # ":", ")", "! 🌟"
    if any(ch in text for ch in "\n\r\v\f  "):
        return False                                  # two fields glued together
    if not text[0].isalnum() and not _is_proper_noun(text):
        return False                                  # "| VP / Director", "🔔 !!"
    if text.startswith("#"):
        return False                                  # a hashtag block
    if not re.search(r"[^\W\d_]{3}", text, re.UNICODE):
        return False                                  # no word in it at all
    if text.endswith(":"):
        return False                                  # "stands out:", "for:"

    words = text.split()
    first = words[0].lower().strip(".,:;!?|")
    if first in _PROSE_STARTERS or first in _DANGLING_WORDS:
        return False                                  # "for you!", "and let's…"
    if text[:1].islower() and len(words) > 1:
        return False                                  # "covering custody"
    return True


def _passes_gate(result: ExtractionResult) -> bool:
    return (
        result.is_job_post
        and bool(result.title and result.title.strip())
        # The gate's contract has always said "concrete title" (see the module
        # docstring); until this call it only checked "non-empty", which let
        # "for you!" and "stands out:" onto the board as job titles.
        and _looks_like_a_job_title(result.title or "")
        and result.hk_plausible
    )


def _build_job(
    row: sqlite3.Row, result: ExtractionResult, recruiter_email: str | None = None
) -> Job:
    recruiter_slug = row["recruiter_slug"]
    author_name = row["author_name"] or recruiter_slug

    # `employer_named` alone is not enough — see _looks_like_an_employer_name.
    # A hint that doesn't look like a name is treated exactly as "no named
    # employer", which is the case decision #7 already covers.
    named = bool(
        result.employer_named
        and result.employer_hint
        and _looks_like_an_employer_name(result.employer_hint)
    )
    if named:
        company = result.employer_hint
        company_slug = _slugify(result.employer_hint)
    else:
        company = f"Confidential via {author_name}"
        company_slug = f"confidential-{recruiter_slug}"

    board_signals = {
        "recruiter_name": author_name,
        "recruiter_profile_url": row["author_profile_url"],
        "recruiter_email": recruiter_email,  # None until hk_jobs.posts.email_harvest runs
        # Keyed off `named`, not `employer_named`: a hint we refused to use as the
        # company is still the best evidence we have about the employer, so it is
        # kept here rather than discarded.
        "employer_hint": result.employer_hint if not named else None,
        "engagement": {
            "likes": row["engagement_likes"],
            "comments": row["engagement_comments"],
        },
        "post_created_at": row["posted_at"],
    }

    return Job(
        source=SOURCE,
        source_id=row["post_urn"],
        company=company,
        company_slug=company_slug,
        url=row["post_url"] or "",
        title=result.title.strip(),
        description_clean=row["post_text"] or "",
        locations=[result.location] if result.location else [],
        seniority=result.seniority if result.seniority in _VALID_SENIORITY else None,
        salary_min=result.salary_min,
        salary_max=result.salary_max,
        salary_currency=result.salary_currency,
        skills_required=result.skills,
        posted_at=_parse_posted_at(row["posted_at"]),
        fetched_at=datetime.now(UTC),
        board_signals=board_signals,
        source_tier=SOURCE_TIER,
        extraction_confidence=result.confidence,
    )


_VALID_SENIORITY = {"intern", "junior", "mid", "senior", "lead", "executive"}


def _parse_posted_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _slugify(name: str) -> str:
    """
    Best-effort slug from a free-text employer name. NOT guaranteed to match
    an existing companies.yaml slug — see module docstring. Good enough for
    a stable, readable company_slug even when it doesn't dedup-match.
    """
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-") or "unknown"


def _store_extraction_result(
    conn: sqlite3.Connection, post_urn: str, result: ExtractionResult | None
) -> None:
    with conn:
        conn.execute(
            "UPDATE linkedin_posts SET extraction_result_json = ?, extraction_confidence = ?, "
            "extraction_prompt_version = ? WHERE post_urn = ?",
            (
                json.dumps(result.raw, ensure_ascii=False) if result else None,
                result.confidence if result else None,
                PROMPT_VERSION,
                post_urn,
            ),
        )


def _set_status(conn: sqlite3.Connection, post_urn: str, status: str) -> None:
    with conn:
        conn.execute(
            "UPDATE linkedin_posts SET extraction_status = ? WHERE post_urn = ?",
            (status, post_urn),
        )


# ── Backfill ──────────────────────────────────────────────────────────────────

@dataclass
class RepairSummary:
    """What a repair pass found. `repaired` is what it did, or in a dry run what
    it would have done — the two are deliberately the same number so a dry run
    predicts the real thing exactly."""

    examined: int = 0
    repaired: int = 0
    names: list[str] = field(default_factory=list)


def repair_employer_names(db_path: str, *, dry_run: bool = True) -> RepairSummary:
    """
    Re-apply the employer-name rule to Recruiter Post rows already on the board.

    The validator only guards new promotions; the rows promoted before it existed
    keep whatever the model said. This re-reads each promoted post's STORED
    extraction result — no DeepSeek calls, so no cost and no risk of a re-run
    disagreeing with what was originally extracted — and rewrites the `jobs` row
    to the confidential form wherever the stored hint would be refused today.

    `dedup_hash` is recomputed because it is sha256(company_slug|title|location):
    leaving it would keep a fingerprint of a name no longer on the row, and
    reconcile_cross_posted() reads that fingerprint to decide cross_posted.

    Dry run by default — this rewrites production rows, so it has to be asked for.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    summary = RepairSummary()
    try:
        rows = conn.execute(
            "SELECT p.post_urn, p.author_name, p.recruiter_slug,"
            "       p.extraction_result_json, j.company, j.title, j.locations"
            "  FROM linkedin_posts p"
            "  JOIN jobs j ON j.source = ? AND j.source_id = p.post_urn"
            " WHERE p.extraction_status = 'promoted'"
            "   AND p.extraction_result_json IS NOT NULL",
            (SOURCE,),
        ).fetchall()

        pending: list[tuple[str, str, str, str]] = []
        for row in rows:
            summary.examined += 1
            try:
                stored = json.loads(row["extraction_result_json"])
            except (TypeError, ValueError):
                continue
            hint = (stored.get("employer_hint") or "").strip()
            if not (stored.get("employer_named") and hint):
                continue
            if _looks_like_an_employer_name(hint):
                continue

            author = row["author_name"] or row["recruiter_slug"]
            company = f"Confidential via {author}"
            slug = f"confidential-{row['recruiter_slug']}"
            if row["company"] == company:
                continue                      # already repaired — idempotent

            summary.repaired += 1
            summary.names.append(hint)
            pending.append((company, slug, _dedup_hash(slug, row), row["post_urn"]))

        if pending and not dry_run:
            with conn:
                conn.executemany(
                    "UPDATE jobs SET company = ?, company_slug = ?, dedup_hash = ?"
                    " WHERE source = 'linkedin_posts' AND source_id = ?",
                    pending,
                )
    finally:
        conn.close()

    if pending and not dry_run:
        # The rewritten slugs change which rows fingerprint alike, so the
        # cross_posted flags derived from them have to be rebuilt.
        with JobStore(db_path) as store:
            store.reconcile_cross_posted()

    logger.info(
        "Employer-name repair%s: %d promoted posts examined, %d rewritten to"
        " 'Confidential via …'", " (dry run)" if dry_run else "",
        summary.examined, summary.repaired,
    )
    return summary


def _dedup_hash(company_slug: str, row: sqlite3.Row) -> str:
    """The same fingerprint Job.dedup_hash() computes, from stored columns."""
    try:
        locations = json.loads(row["locations"] or "[]")
    except (TypeError, ValueError):
        locations = []
    first_loc = locations[0].lower() if locations else ""
    key = f"{company_slug}|{(row['title'] or '').lower()}|{first_loc}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]
