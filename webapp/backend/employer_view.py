"""
The Employer's perspective — what one Employer account has done with FinEx, and
what became of it.

One module owns this read, the same shape as admin_intelligence.py and
role_feed.py and for the same reason (ADRs 0013-0017): the question "what does
this Employer see?" spans three stores that have no business knowing about each
other — employers.db (the account, ADR 0001), the submitted_roles.jsonl
moderation queue (submissions.py), and jobs.db (the board) — and the join
belongs in one place rather than being re-derived at the route, in a script and
in the frontend.

WHY IT EXISTS
-------------
The Employer aggregate is deliberately thin: identity plus /api/post-role, and
nothing else (employers_store.py's docstring; Nav.tsx's EmployerMenu). An
Employer therefore has no dashboard of their own to read, which means when one
writes in to ask "where is my role?" there was no single place an admin could
look. The account directory shows that the account exists; the Verification
queue shows submissions with no idea which account sent them; the board shows
Roles with no idea an account is connected to them. This is the seam.

THE HONEST PART — how a submission is attributed
------------------------------------------------
/api/post-role does NOT record the signed-in Employer's id. It records
`contact_email`, `contact_name` and `company` free text (main.py's RoleIn), and
it accepts submissions from signed-out visitors too. So there is no foreign key
to follow and this module cannot invent one. It attributes by evidence and
SAYS WHICH:

  - "email"   — contact_email equals the account's email, case-insensitively.
                Strong: the address was verified at registration.
  - "company" — the company name matches but the address does not. Weaker: two
                real employers can share a name, and a colleague submitting
                from their own address looks identical to a stranger.

`matched_by` rides on every row so the admin sees the strength of the claim
rather than a merged list that quietly asserts more than we know. Nothing here
writes; wiring an employer_id into the submission is a change to /api/post-role,
not something this read model may fake.

STANDING — why an Employer cannot see their own Role
----------------------------------------------------
`standing` is the other half of the perspective, and the reason this is more
than a join. A Role can be perfectly alive and still be absent from the board
(ADR 0035's per-employer cap of 60, ADR 0039's headline that now counts exactly
what the cap leaves visible), and "it is capped out" is an answer an admin can
give an Employer where "I don't know" was the only one available before. The
states are derived by ruling BOARD_WHERE out clause by clause, so `capped` is
the residual — it cannot drift away from the real predicate, because the real
predicate is what is being tested first.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Iterable, Optional

import job_read
import submissions
from job_read import JobFilters, Sort, Visibility

#: How many of an Employer's board Roles the panel returns. The point is to let
#: an admin confirm the right Roles are live and open one, not to paginate a
#: mega-poster's whole catalogue — the counts above the list carry the totals,
#: and the Job Editor is where you go to work through them.
BOARD_SAMPLE_SIZE = 12

#: Every state a Role belonging to this Employer can be in, most-visible first.
#: `on_board` is the only one a visitor can browse to.
STANDINGS = (
    "on_board",
    "capped",
    "aged_out",
    "undated",
    "hidden",
    "duplicate",
    "closed",
)

#: One CASE, evaluated in order, that names why a Role is or is not on the
#: board. BOARD_WHERE is tested FIRST so the visible state is defined by the
#: real predicate rather than by a second copy of its clauses; each later branch
#: then rules out one reason BOARD_WHERE can fail, leaving the per-employer cap
#: (ADR 0035) as the only remaining explanation. Add a clause to
#: board_visible_sql() and the residual absorbs it — mislabelled as `capped`,
#: never silently dropped — which is the failure mode worth having.
_STANDING_SQL = f"""
    CASE
        WHEN {job_read.BOARD_WHERE} THEN 'on_board'
        WHEN j.is_active = 0 THEN 'closed'
        WHEN j.is_primary = 0 THEN 'duplicate'
        WHEN j.admin_hidden THEN 'hidden'
        WHEN j.posted_at IS NULL OR j.posted_at = '' THEN 'undated'
        WHEN date(j.posted_at) < date('now', '-1 month') THEN 'aged_out'
        ELSE 'capped'
    END
"""


def _norm(value: Optional[str]) -> str:
    return (value or "").strip().casefold()


def company_spellings(conn: sqlite3.Connection, company_name: str) -> list[str]:
    """
    The `jobs.company` spellings this account plausibly owns.

    Two independent routes to the same employer, because the two populations
    are slugged differently and neither alone is enough:

      - `company_slug`, which is how an APPROVED submission lands (submissions.
        slugify of the submitted company name). Exact by construction.
      - a case-insensitive `company` match, which is how SCRAPED rows arrive —
        their `company_slug` comes from companies.yaml, an operator's chosen
        handle, so slugging the account's name would miss them entirely.

    Deliberately NOT fuzzy. "Standard Chartered" and "Standard Chartered Bank
    (Hong Kong)" stay two spellings here even though main.py's landing-page
    index would fold them into one, because attributing another employer's
    Roles to this account is a worse error than showing none. The route takes a
    `company` override for exactly that case, so an Ultimate Admin can point
    the lens at the board's real spelling instead.
    """
    name = (company_name or "").strip()
    if not name:
        return []
    rows = conn.execute(
        """
        SELECT DISTINCT company FROM jobs
        WHERE company_slug = ? OR lower(company) = lower(?)
        ORDER BY company
        """,
        (submissions.slugify(name), name),
    ).fetchall()
    return [row["company"] for row in rows]


def submissions_for(
    queue: Iterable[dict[str, Any]], *, email: str, company_name: str
) -> list[dict[str, Any]]:
    """
    This Employer's submissions, newest first, each carrying how it was matched.

    See the module docstring for why `matched_by` exists rather than a silent
    merge. A row matching on both counts as "email" — the stronger claim wins,
    and an admin reading the panel should not have to reason about precedence.
    """
    wanted_email = _norm(email)
    wanted_company = _norm(company_name)
    out: list[dict[str, Any]] = []
    for row in queue:
        if wanted_email and _norm(row.get("contact_email")) == wanted_email:
            matched_by = "email"
        elif wanted_company and _norm(row.get("company")) == wanted_company:
            matched_by = "company"
        else:
            continue
        out.append(
            {
                "id": submissions.source_id_for(row),
                "title": row.get("title", ""),
                "company": row.get("company", ""),
                "location": row.get("location", ""),
                "employment_type": row.get("employment_type", ""),
                "salary_range": row.get("salary_range", ""),
                "apply_url": row.get("apply_url", ""),
                "contact_email": row.get("contact_email", ""),
                "contact_name": row.get("contact_name", ""),
                "received_at": row.get("received_at", ""),
                "status": row.get("status", "pending"),
                "rejected_reason": row.get("rejected_reason") or None,
                "approved_source_id": row.get("source_id") or None,
                "matched_by": matched_by,
            }
        )
    out.sort(key=lambda r: r["received_at"], reverse=True)
    return out


def catalogue_standing(
    conn: sqlite3.Connection, companies: list[str]
) -> dict[str, int]:
    """
    How many of this Employer's Roles are in each state — every key in
    `STANDINGS` present, zeroed, so the panel renders the same shape whether or
    not a state is occupied and a missing state can never read as missing data.
    """
    counts = {name: 0 for name in STANDINGS}
    if not companies:
        return counts
    placeholders = ",".join("?" * len(companies))
    rows = conn.execute(
        f"""
        SELECT {_STANDING_SQL} AS standing, COUNT(*) AS n
        FROM jobs j
        WHERE j.company IN ({placeholders})
        GROUP BY standing
        """,
        companies,
    ).fetchall()
    for row in rows:
        # An unrecognised standing would mean _STANDING_SQL grew a branch this
        # module's STANDINGS tuple does not know about. Keep it rather than
        # dropping it — a count that does not add up is a visible bug.
        counts[row["standing"]] = counts.get(row["standing"], 0) + row["n"]
    return counts


def board_roles(conn: sqlite3.Connection, companies: list[str]) -> list[dict[str, Any]]:
    """
    The Roles of this Employer a visitor can actually browse to, newest first.

    Goes through `job_read.list_jobs` at BOARD visibility rather than a query of
    its own, so this list is the board's own answer — same predicate, same
    cross-post signal merge, same expiry of perishable signals. A panel that
    built its own SELECT would be a second definition of "live" the moment
    ADR 0035's cap moved.

    MEMBER audience, not PUBLIC: an admin looking at an Employer must see the
    boutique and social tiers too, or a Role that is live for signed-in Seekers
    would read here as missing.
    """
    if not companies:
        return []
    page = job_read.list_jobs(
        conn,
        JobFilters.of(companies=companies),
        sort=Sort.NEWEST,
        page=1,
        page_size=BOARD_SAMPLE_SIZE,
        visibility=Visibility.BOARD,
        audience=job_read.CatalogueAudience.MEMBER,
    )
    return [job.model_dump() for job in page.jobs]


def employer_activity(
    conn: sqlite3.Connection,
    employer: dict[str, Any],
    queue: Iterable[dict[str, Any]],
    *,
    company: Optional[str] = None,
) -> dict[str, Any]:
    """
    One Employer's whole perspective: the account, what they submitted, what we
    did with it, and what of theirs is live.

    `company` overrides the account's own `company_name` when the board spells
    the employer differently — the one escape hatch for the deliberately exact
    matching in `company_spellings`. It changes which Roles are attributed, and
    is echoed back in the response so the panel can say the lens was moved.
    """
    lens = (company or employer.get("company_name") or "").strip()
    spellings = company_spellings(conn, lens)
    return {
        "employer": {
            "id": employer["id"],
            "email": employer["email"],
            "company_name": employer.get("company_name", ""),
            "contact_name": employer.get("contact_name") or None,
            "email_verified": bool(employer.get("email_verified")),
            "created_at": employer.get("created_at"),
            "last_login_at": employer.get("last_login_at"),
        },
        # What the Roles were matched on, so the panel never presents an
        # attribution as fact without showing its basis.
        "lens": {
            "company": lens,
            "overridden": bool(company and _norm(company) != _norm(employer.get("company_name"))),
            "matched_spellings": spellings,
        },
        "submissions": submissions_for(
            queue, email=employer["email"], company_name=lens
        ),
        "standing": catalogue_standing(conn, spellings),
        "board_roles": board_roles(conn, spellings),
        "board_sample_size": BOARD_SAMPLE_SIZE,
    }
