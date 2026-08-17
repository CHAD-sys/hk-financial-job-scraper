"""
Specification for the promotion gate's plausibility checks and the backfill.

The extractor's prompt already forbids inventing an employer name ("a phrase
like 'a leading private bank' is NOT a named employer"). The model violates it
anyway, and promote.py used to copy whatever it claimed straight onto the board.
Every string asserted on below is one the live DeepSeek extractor actually
returned with `employer_named: true` — this is a calibration table, not a set of
invented examples, which is why the accept-list matters as much as the reject-list.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from hk_jobs.migrations import migrate
from hk_jobs.posts.extractor import ExtractionResult
from hk_jobs.posts.promote import (
    _build_job,
    _looks_like_a_job_title,
    _looks_like_an_employer_name,
    _passes_gate,
    repair_employer_names,
)


# ── The calibration table ─────────────────────────────────────────────────────
# Real employer names the extractor produced. Rejecting one of these would lose
# a genuine employer, so they are the expensive half of the calibration.
REAL_EMPLOYERS = [
    "Barclays",
    "BEA",
    "Citi",
    "Goldman Sachs",
    "HSBC",
    "HSBC Life",
    "Morgan Stanley",
    "Sun Life",
    "Selby Jennings",
    "Harbridge Partners",
    "Lote and Partners",
    "Chinese Banks' Association (CBSA)",
    "The Bank of East Asia (BEA)",
    "東亞銀行 The Bank of East Asia (BEA)",
    "東亞銀行（BEA）",
]

# Prose the model mislabelled as a named employer. Each is a fragment of the
# post body; the parenthetical says where it came from.
PROSE_NOT_EMPLOYERS = [
    "business leaders to",          # "Partner with business leaders to forecast…"
    "your career",
    "a strong focus",
    "corporates across the semiconductor and power",
    "CDD experience to gain exposure within a dynamic",
    "A leading",
    "A leading foreign",
    "A prestigious regional",
    "A reputable corporate",
    "Join a leading international",
    "Chinese international financial",
    "Opportunity to mentor junior",
    "Proficient in MS Office",
    "We are seeking a dedicated Company",
    "We are partnering with a leading international corporate & investment",
    "Transactionbanking Relationship Managers in Hong Kong with leading",
    "Exciting RM Career Opportunity in a prestigious\xa0foreign",
    "Global Banking\n\nJoin a growing international",
    "This role is ideal for RM professionals with background in\xa0corporate",
    "Proven leadership experience managing RM teams\n\nThis is a fantastic"
    " opportunity for senior",
    "Sc",                          # a truncation, not an abbreviation
]


@pytest.mark.parametrize("name", REAL_EMPLOYERS)
def test_a_real_employer_name_is_accepted(name):
    assert _looks_like_an_employer_name(name) is True


@pytest.mark.parametrize("prose", PROSE_NOT_EMPLOYERS)
def test_prose_is_not_accepted_as_an_employer_name(prose):
    assert _looks_like_an_employer_name(prose) is False


def test_an_article_needs_a_proper_noun_after_it():
    """This is the rule that separates the two shapes starting with an article:
    "The Bank of East Asia" names something, "A leading foreign" describes it."""
    assert _looks_like_an_employer_name("The Bank of East Asia (BEA)") is True
    assert _looks_like_an_employer_name("A leading foreign") is False


# ── The fallback that makes rejecting cheap ───────────────────────────────────

def _row(**over):
    row = {
        "post_urn": "urn-1",
        "recruiter_slug": "janice-wong",
        "author_name": "Janice Wong",
        "author_profile_url": "https://linkedin.com/in/janicewongsy",
        "post_url": "https://linkedin.com/posts/1",
        "post_text": "Partner with business leaders to forecast talent needs",
        "posted_at": "2026-07-15T08:42:50Z",
        "engagement_likes": 3,
        "engagement_comments": 0,
    }
    row.update(over)
    return row


def _result(**over):
    kwargs = dict(
        is_job_post=True, confidence=0.85, title="Talent Acquisition & HR Lead",
        employer_named=True, employer_hint="business leaders to",
        location="hong kong", hk_plausible=True,
    )
    kwargs.update(over)
    return ExtractionResult(**kwargs)


def test_a_rejected_hint_falls_back_to_confidential_via_the_recruiter():
    """Decision #7's path already exists and is always correct, so a hint that
    doesn't look like a name costs nothing to refuse — the post still promotes."""
    job = _build_job(_row(), _result())
    assert job.company == "Confidential via Janice Wong"
    assert job.company_slug == "confidential-janice-wong"
    assert job.title == "Talent Acquisition & HR Lead"


def test_a_rejected_hint_is_kept_as_a_hint_not_thrown_away():
    """board_signals already carries the hint whenever it is not used as the
    company. A refused guess belongs there too rather than vanishing."""
    job = _build_job(_row(), _result())
    assert job.board_signals["employer_hint"] == "business leaders to"


def test_a_real_hint_is_still_used_as_the_company():
    job = _build_job(_row(), _result(employer_hint="Goldman Sachs"))
    assert job.company == "Goldman Sachs"
    assert job.company_slug == "goldman-sachs"


def test_a_collision_can_no_longer_impersonate_a_real_employer():
    """The worst shape: the model guessed a real employer's name from prose, so a
    recruiter's post answered a filter for that employer's own vacancies. A
    genuine "HSBC" hint is still honoured — the fix is the shape test, not a
    blocklist of names."""
    prose = _build_job(_row(), _result(employer_hint="a leading bank, HSBC scale"))
    assert prose.company == "Confidential via Janice Wong"
    assert _build_job(_row(), _result(employer_hint="HSBC")).company == "HSBC"


# ── Titles: the gate promised "concrete", and checked only "non-empty" ────────

REAL_TITLES = [
    "Executive Director, Consumer & Retail Coverage, Investment Banking",
    "Quant Risk Analyst, Counterparty Credit & Market Risk",
    "VP / Executive Director – Debt Capital Markets (Origination / Execution)",
    "Battery Energy Storage System (BESS) / Energy Transition Professional",
    "CFO",
    "Sub Portfolio Manager, Long / Short Equity (Market Neutral)",
    "東亞銀行 Summer Internship",
]

NOT_TITLES = [
    "for you!",
    "stands out:",
    "for:",
    ":",
    ")",
    "| VP / Director",
    "! 🌟",
    "🔔 !!",
    "#HongKongJobs #BankingCareers #CareerGrowth",
    "covering custody",
    "Career Opportunity\n\nCredit Research Analyst",
    "Semiconductorintegratedcircuit\n\n\nSenior Marketing Manager",
    "and let's plan for your career ahead:",
]


@pytest.mark.parametrize("title", REAL_TITLES)
def test_a_real_title_still_passes(title):
    assert _looks_like_a_job_title(title) is True


@pytest.mark.parametrize("title", NOT_TITLES)
def test_a_fragment_is_not_a_title(title):
    assert _looks_like_a_job_title(title) is False


def test_the_gate_refuses_a_post_whose_title_is_a_fragment():
    """Unlike a bad employer name there is no fallback for a bad title, so the
    post stays in linkedin_posts as 'rejected' rather than reaching the board."""
    assert _passes_gate(_result(title="for you!")) is False
    assert _passes_gate(_result(title="Talent Acquisition & HR Lead")) is True


def test_the_gate_still_refuses_the_things_it_already_refused():
    assert _passes_gate(_result(is_job_post=False)) is False
    assert _passes_gate(_result(hk_plausible=False)) is False
    assert _passes_gate(_result(title=None)) is False


# ── The backfill ──────────────────────────────────────────────────────────────

@pytest.fixture()
def db(tmp_path: Path) -> str:
    path = str(tmp_path / "jobs.db")
    migrate(path)
    return path


def _seed(db: str, *, urn: str, hint: str, company: str, title="Stakeholder Partner"):
    conn = sqlite3.connect(db)
    with conn:
        conn.execute(
            "INSERT INTO linkedin_posts (post_urn, recruiter_slug, source_run,"
            " author_name, post_text, post_url, posted_at, fetched_at,"
            " vendor_payload_json, extraction_status, extraction_result_json)"
            " VALUES (?,?,?,?,?,?,?,?,'{}',?,?)",
            (urn, "janice-wong", "watchlist", "Janice Wong", "body", "u",
             "2026-07-15T00:00:00Z", "2026-07-16T00:00:00Z", "promoted",
             json.dumps({"is_job_post": True, "employer_named": True,
                         "employer_hint": hint, "title": title})),
        )
        conn.execute(
            "INSERT INTO jobs (source, source_id, company, company_slug, url,"
            " dedup_hash, title, locations, source_tier, fetched_at, is_active,"
            " is_primary) VALUES ('linkedin_posts',?,?,?,'u','oldhash',?,"
            "'[\"hong kong\"]','social','2026-07-16T00:00:00Z',1,1)",
            (urn, company, company.lower().replace(" ", "-"), title),
        )
    conn.close()


def test_the_backfill_rewrites_a_prose_company_to_confidential(db):
    _seed(db, urn="A", hint="business leaders to", company="business leaders to")
    summary = repair_employer_names(db, dry_run=False)
    assert summary.repaired == 1

    conn = sqlite3.connect(db)
    company, slug = conn.execute(
        "SELECT company, company_slug FROM jobs WHERE source_id='A'").fetchone()
    conn.close()
    assert company == "Confidential via Janice Wong"
    assert slug == "confidential-janice-wong"


def test_the_backfill_recomputes_dedup_hash(db):
    """dedup_hash is sha256(company_slug|title|location), so rewriting the slug
    without rewriting the hash would leave a fingerprint of a name that is no
    longer on the row — and cross-post reconciliation reads that fingerprint."""
    _seed(db, urn="A", hint="business leaders to", company="business leaders to")
    repair_employer_names(db, dry_run=False)
    conn = sqlite3.connect(db)
    (dedup,) = conn.execute("SELECT dedup_hash FROM jobs WHERE source_id='A'").fetchone()
    conn.close()
    assert dedup != "oldhash"
    assert len(dedup) == 12


def test_the_backfill_leaves_a_real_employer_alone(db):
    _seed(db, urn="B", hint="Goldman Sachs", company="Goldman Sachs",
          title="Equity Research Analyst")
    summary = repair_employer_names(db, dry_run=False)
    assert summary.repaired == 0

    conn = sqlite3.connect(db)
    (company,) = conn.execute("SELECT company FROM jobs WHERE source_id='B'").fetchone()
    conn.close()
    assert company == "Goldman Sachs"


def test_the_backfill_is_a_dry_run_by_default(db):
    """A repair that rewrites production rows should have to be asked for."""
    _seed(db, urn="A", hint="business leaders to", company="business leaders to")
    summary = repair_employer_names(db)
    assert summary.repaired == 1          # reports what it WOULD do

    conn = sqlite3.connect(db)
    (company,) = conn.execute("SELECT company FROM jobs WHERE source_id='A'").fetchone()
    conn.close()
    assert company == "business leaders to"


def test_the_backfill_is_idempotent(db):
    _seed(db, urn="A", hint="business leaders to", company="business leaders to")
    repair_employer_names(db, dry_run=False)
    assert repair_employer_names(db, dry_run=False).repaired == 0


def test_the_backfill_never_touches_another_source(db):
    """Only Recruiter Posts carry an extracted employer name. A jobsdb row whose
    company happens to look odd is a scraped fact, not a guess."""
    conn = sqlite3.connect(db)
    with conn:
        conn.execute(
            "INSERT INTO jobs (source, source_id, company, company_slug, url,"
            " dedup_hash, title, locations, source_tier, fetched_at, is_active,"
            " is_primary) VALUES ('jobsdb','J','a strong focus','a-strong-focus',"
            "'u','h','Analyst','[\"hong kong\"]','mainstream',"
            "'2026-07-16T00:00:00Z',1,1)")
    conn.close()
    assert repair_employer_names(db, dry_run=False).repaired == 0

    conn = sqlite3.connect(db)
    (company,) = conn.execute("SELECT company FROM jobs WHERE source_id='J'").fetchone()
    conn.close()
    assert company == "a strong focus"
