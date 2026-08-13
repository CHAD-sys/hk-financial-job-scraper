"""
Alerts: an opt-in weekly email of newly-recommended Roles.

WHAT THIS IS
------------
Not a saved-search re-run. Despite what CONTEXT.md's `Alert` entry currently
says, this was a deliberate product decision made against that default: each
Seeker's weekly email is driven by the same first-party recommendation engine
that ranks the in-app "Roles for you" feed (role_feed.rank_for_seeker), not by
an explicit filter the Seeker set. CONTEXT.md needs a matching rewrite; it has
not received one yet.

THE RULES THIS MODULE ENFORCES (each traceable to a decision made against a
recommendation, not an assumption):

  - At most one email per Seeker per 7 days, and only if there is something to
    say — never an empty digest. `seekers_due_for_alert` + the loop below is
    the whole cadence engine; there is no separate scheduler.
  - Opt-in only. A Seeker who has never touched the toggle is never
    considered — enforced entirely inside seekers_store (opted_in defaults to
    0), not re-checked here.
  - Cold start is silence, not a fallback. `role_feed.rank_for_seeker`
    returns `ranked=None` for a Seeker with no first-party signal at all yet;
    that Seeker is skipped this run, not sent a generic sample.
  - "Matches their profile" means `RankedRole.matched` is True — at least one
    real signal (a saved Role, a settled search, a click, "More like this",
    resume fit) contributed to the score, not freshness alone. A role that
    only cleared the freshness floor is not a match and never appears here.
  - "New-to-you": a Role is eligible at most once per Seeker, ever, via
    `alerted_roles` (seekers_store.py) — permanent, independent of whether it
    is still on the board.
  - Every source tier is eligible, Recruiter Posts included — no tier filter
    here on purpose.
  - Bare listing: title, company, salary, tier, a direct link to the original
    posting (`job.url`, the same field JobDetailModal's own Apply button
    uses — there is no separate FinEx-hosted Role detail page to link to
    instead). No "why this matched" reasoning text in the email body.
  - The email and the in-app feed are independent surfaces (see
    role_feed.rank_for_seeker's own docstring): being alerted about a Role
    does not remove it from "Roles for you", and vice versa.

A due Seeker whose only candidates are all `matched=False`, or all already in
`alerted_roles`, is skipped this run exactly like a Seeker with zero
candidates — from the outside these are indistinguishable, which is correct:
"nothing new to say this week" is the same outcome regardless of why.

Only sent to a verified address (`seekers.email_verified`), matching the
existing rule elsewhere in this backend that verification gates outbound
mail, not access — an unverified Seeker still uses the whole app.

`last_sent_at` and `alerted_roles` are advanced ONLY when the send actually
succeeds. If mail is down, the Seeker stays "due" and is retried on the next
run rather than silently losing a week or being marked delivered for mail
that never left.

WHAT THIS MODULE DOES NOT DO
-----------------------------
Does not decide *when* it runs — that is scripts/daily_run.sh's job. Does not
construct a Sender, a jobs.db connection, or an AlertUnsubscribeToken — the
caller wires those, same seam sender.py already established for Seeker mail
(SmtpSender in production, RecordingSender in tests).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Sequence

import role_feed
import seekers_store
from alert_unsubscribe import AlertUnsubscribeToken
from job_read import JobSummary
from sender import Message, Sender

#: The rolling per-Seeker cadence (Q8 of the feature spec): at least this long
#: since the last successful send before a Seeker is considered again.
ALERT_INTERVAL = timedelta(days=7)

#: Display cap for a single email (Q6: threshold-based selection, capped for
#: readability — however many Roles qualify, however many that is, up to this).
MAX_ROLES_PER_EMAIL = 8

#: The candidate pool size pulled from the ranking engine per Seeker. This is
#: recommendations.rank_roles's own hard ceiling (`min(page_size, 24)`), not a
#: choice made here — passing anything larger would silently be clamped to it.
#: Known v1 limitation: a genuine new-to-you match ranked below the top 24
#: overall for that Seeker will not surface until a higher-ranked backlog Role
#: is exhausted (alerted or no longer eligible) in a later week.
CANDIDATE_PAGE_SIZE = 24


@dataclass(frozen=True)
class AlertOutcome:
    seeker_id: str
    sent: bool
    role_count: int


def _format_salary(job: JobSummary) -> str:
    lo = job.salary_hkd_min or job.salary_estimated_min
    hi = job.salary_hkd_max or job.salary_estimated_max
    if not lo and not hi:
        return ""
    period = job.salary_period or "month"
    if lo and hi and lo != hi:
        return f"HK${lo:,}–HK${hi:,}/{period}"
    return f"HK${(lo or hi):,}/{period}"


def _compose(
    *,
    to: str,
    roles: Sequence[JobSummary],
    unsubscribe_url: str,
) -> Message:
    noun = "role" if len(roles) == 1 else "roles"
    lines = [
        f"FinEx found {len(roles)} new {noun} that match your profile this week:",
        "",
    ]
    for job in roles:
        lines.append(f"{job.title} — {job.company} ({job.source_tier})")
        salary = _format_salary(job)
        if salary:
            lines.append(f"  {salary}")
        lines.append(f"  {job.url}")
        lines.append("")
    lines.append(f"Don't want these emails? Unsubscribe any time: {unsubscribe_url}")
    return Message(
        to=to,
        subject=f"FinEx Careers: {len(roles)} new {noun} for you this week",
        body="\n".join(lines),
    )


def run_weekly_alerts(
    jobs_conn: sqlite3.Connection,
    sender: Sender,
    unsubscribe_tokens: AlertUnsubscribeToken,
    *,
    public_base_url: str,
    now: datetime | None = None,
) -> list[AlertOutcome]:
    """Consider every due, opted-in Seeker and send at most one Alert each.

    Called once per pipeline run (scripts/daily_run.sh); most nights this does
    nothing for most Seekers, because `seekers_due_for_alert` only returns
    someone whose 7-day window has actually elapsed.
    """
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    store = seekers_store.get_store()
    cutoff = moment - ALERT_INTERVAL

    outcomes: list[AlertOutcome] = []
    for seeker_id in store.seekers_due_for_alert(cutoff=cutoff):
        seeker = store.get_seeker(seeker_id)
        if seeker is None or not seeker["email_verified"]:
            # Deleted between the due-query and this loop, or never verified —
            # either way, not a Seeker we may mail.
            continue

        ranking = role_feed.rank_for_seeker(
            jobs_conn,
            seeker_id=seeker_id,
            page=1,
            page_size=CANDIDATE_PAGE_SIZE,
            now=moment,
        )
        if ranking.ranked is None:
            continue  # cold start (Q3): no first-party signal yet — stay silent

        already_sent = store.list_alerted_role_ids(seeker_id)
        qualifying = [
            item.job
            for item in ranking.ranked.items
            if item.matched and (item.job.source, item.job.source_id) not in already_sent
        ]
        if not qualifying:
            continue  # nothing new this week (Q1): no email, ever

        selected = qualifying[:MAX_ROLES_PER_EMAIL]
        # An SPA route, not the API URL directly — mirrors _account_link_url's
        # verify/reset links (main.py). The frontend page fires the actual
        # POST /api/alerts/unsubscribe from JS; a mail client that pre-fetches
        # links to scan them must not be able to unsubscribe someone by
        # merely receiving the email.
        unsubscribe_url = f"{public_base_url}/unsubscribe?token={unsubscribe_tokens.issue(seeker_id)}"
        message = _compose(to=str(seeker["email"]), roles=selected, unsubscribe_url=unsubscribe_url)
        sent = sender.send(message)

        if sent:
            store.record_alerted_roles(
                seeker_id, [(job.source, job.source_id) for job in selected], now=moment
            )
            store.mark_alert_sent(seeker_id, now=moment)
        outcomes.append(AlertOutcome(seeker_id=seeker_id, sent=sent, role_count=len(selected)))

    return outcomes
