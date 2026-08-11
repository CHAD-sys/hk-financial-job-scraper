# One Role Feed module owns Seeker suggestions

**Status:** accepted (2026-08-11)

`webapp/backend/role_feed.py` owns the complete read that produces “Roles for
you”: Seeker signal assembly, Listing candidate policy, reference resolution,
resume evidence reconstruction, ranking, exclusions, feedback projection, page
policy and recommendation-impression attribution.

FastAPI routes own transport concerns only: session lookup, query validation,
the jobs.db connection lifetime and the response declaration. They do not know
which Seeker-store calls must happen, how references become Roles, which
signals feed ranking, or when an impression is persisted.

The same module owns the adjacent resume-match read because both products select
from the same bounded, newest-first board candidate set and reconstruct the same
private resume evidence. Resume matches remain a distinct outcome and never
write recommendation impressions.

## Interface

The module presents two outcome-oriented operations:

- `roles_for_seeker(jobs_connection, seeker_id, page, page_size)` returns one
  complete Role Feed and records its signed-in impressions.
- `resume_matches_for_seeker(jobs_connection, seeker_id, limit)` returns the
  strongest observable resume alignments, or an honest no-resume result.

Candidate-window and page limits are implementation policy. The interface
accepts loose integer inputs and bounds them, so non-HTTP callers do not need to
learn route validation rules.

## Storage ownership

ADR 0006 remains unchanged. Listing facts stay in jobs.db and Seeker-owned
signals, feedback, resumes and impressions stay in seekers.db. The Role Feed
module coordinates reads across their existing adapters but never attaches,
joins or merges the databases. A nightly catalogue replacement therefore cannot
destroy Seeker data, and account deletion retains its existing real-delete
semantics.

## Why

Previously the `/api/recommendations` route was the actual recommendation
implementation. It coordinated roughly a dozen persistence calls, rebuilt five
reference collections, reconstructed resume evidence, selected 1,000 candidates,
called the ranker, shaped feedback and wrote impressions. The resume-match route
independently repeated candidate selection and resume reconstruction.

That interface was shallow: changing one signal or candidate rule required a
maintainer to understand HTTP, both database ownership models, ranking inputs
and write ordering at once. It also led endpoint tests to reach through
`SeekerStore._conn()` to verify implementation details.

The new module earns depth by hiding that orchestration behind two complete
outcomes. Tests use temporary jobs.db and seekers.db stand-ins and assert the
observable feed, exclusions and impressions through the module interface.

## Consequences

- `recommendations.py` remains the pure scoring implementation and
  `resume_intelligence.py` remains the pure resume implementation. They are
  implementation details used behind the Role Feed seam, not reimplemented.
- Anonymous feeds never initialise or write Seeker-owned recommendation state.
- Signed-in feed generation and impression attribution happen together; callers
  cannot accidentally show an untracked feed by forgetting a second store call.
- Adding a new signal, changing the candidate window or changing impression
  semantics has one implementation location and one interface-level test suite.
