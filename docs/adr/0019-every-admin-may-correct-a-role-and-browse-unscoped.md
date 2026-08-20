# Every admin may correct a Role, and browse unscoped

**Status:** accepted (2026-08-20; amends ADR 0018)

Three changes, one decision behind them: an admin is staff, and the constraints
that protect the catalogue from visitors were never meant to bind the people who
maintain it.

## Editing is no longer Ultimate-Admin-only

`/api/admin/jobs/{source}/{source_id}` (GET and PATCH) moves from
`require_super_admin` to `require_admin`. Every admin may now correct any field
in `job_edit.JOB_FIELDS` / `ENRICHMENT_FIELDS`, salary included.

ADR 0018 said "only Ultimate Admin retains editing access". That is superseded
here. A wrong salary is this board's most visible defect, and routing every
correction through one account made the fix wait on that account's availability.

Nothing else about the write moved. The allowlist still bounds what is reachable,
`admin_edits` still records which human changed which field from what to what,
and every enrichment write still sets `manually_edited_at`. Widening who may
write is defensible precisely because who wrote was already recorded.

Ultimate Admin keeps two things the other four still do not have: the account
directory, and a Seeker's stored resume.

## Editing happens on the board, not only in the panel

The panel's `JobEditor` is a destination: go to /admin, search for a posting,
pick it out of results, edit it. That is the right shape for working through a
list of known corrections and the wrong shape for how a bad salary is actually
noticed — while browsing, on a card, mid-scroll.

Each card now carries a pencil for admins, opening `AdminJobEditDrawer` over the
board. Same endpoints, same allowlist, same audit trail; it is an entry point,
not a second editor. `JobEditor` stays for the list-driven case.

## Research Scope does not bind staff

ADR 0018 requires a two-character research query before the catalogue answers,
so that it cannot be enumerated. An admin submitting an EMPTY query is now
exempt: they get the whole live catalogue, and catalogue-wide filter facets with
it. Everyone else — anonymous or signed-in Seeker — gets the same 422 as before.

This is less a change to 0018 than a wiring of what it already said: *"job_read
still supports unscoped internal candidate reads for ranking and admin
operations; the HTTP adapter owns the public research requirement."* The
adapter simply never asked who was calling.

The exemption lifts the QUERY requirement only. `Visibility.BOARD` still applies,
so an admin browsing everything sees one card per live vacancy — not closed
rows, not the non-primary copies of a cross-posted Role. Reaching those remains
a per-Role act, as it has been.

## An admin's salary correction is evidence, not just an override

A hand-corrected salary was already permanent: `manually_edited_at` excludes the
row from re-enrichment, the nightly outlier audit and the deterministic repair
pass, and `job_edit.reapply_recorded_edits` re-applies it after every nightly
publication. What it was not, was *knowledge*. The judgement stopped at the row
it was made on, and the next posting of the same shape got the same wrong answer.

`admin_salary_corrections` (migration phase 36) keeps each correction alongside
the shape of the Role it was about — title, employer, tier, seniority, category —
and `hk_jobs/salary_corrections.py` puts the most relevant handful in front of
the estimator when it prices a similar Role.

Two boundaries make this safe to have:

- **The anchors file is not written to.** `hk_salary_anchors.json` is a weighted
  merge of three published salary guides. Single observations folded into it
  would corrupt a calibration nobody could reconstruct. Corrections sit beside
  the anchors and are offered as evidence; the anchors remain the baseline.
- **Corrections are outside `salary.version()`.** That fingerprint decides what
  gets re-enriched. Inside it, every hand-correction would mark ~13,000 stored
  estimates stale and re-pay DeepSeek for all of them — around $40 at the
  observed rate, triggered by one admin fixing one salary. The same reasoning as
  the `GRADE_BANDS` exclusion in `salary_anchors.py`.

The consequence, stated so it is chosen rather than discovered: corrections
change what FUTURE enrichments are told, not what is already stored. To
propagate them across the back catalogue, remove the 2026-08-20 entry from
`salary.ACCEPTED_PRIOR_VERSIONS` — a real recalibration, and a real bill.

## The board stops calling a corrected salary a guess

`JobSummary.salary_verified` is derived from `manually_edited_at`, and a Role
carrying it shows "Checked" rather than "AI est.". Badging a figure a human
verified as a machine estimate is the same provenance error as the reverse, and
the badge exists to prevent exactly that.

## Admin Mode is a mode again

The nav's one-way "Admin panel" link is replaced by `AdminModeSwitch`, a
persistent Admin ⇄ Seeker toggle whose direction is read from the current route.
The link left an admin inside the panel with no nav route back to the product
they administer.

## Consequences

- Four more people can now permanently overwrite any published salary. The audit
  log is the control; there is no approval step and no un-pin in the UI.
- Pinned rows will accumulate faster, and every pinned row is one the automated
  passes no longer maintain.
- The catalogue is enumerable by anyone holding an admin session. That was
  already true of the admin panel's analytics; it is now true of the board.
