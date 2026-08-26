# Manager floors require an exact table coordinate

**Status:** accepted (2026-08-25)

The generic Manager-grade floor is intentionally narrow: it may raise an
otherwise low estimate only when a finance title and salary-table coordinate
agree that the Role is genuinely Manager-grade. Runtime checked that `tier` was
known and that `role` was non-empty, but never checked that the Role existed
inside that Tier. `middle_office/made_up_role` and even
`middle_office/treasury`—where `treasury` belongs to another table—therefore
received the HK$50,000-60,000 large-employer floor.

## Decision

A Manager floor requires an exact `(tier, role)` membership in
`tables_monthly_hkd[tier].roles`. A real Role name paired with the wrong Tier is
invalid in the same way as an invented Role name. Missing or invalid coordinates
fail open and retain the estimate produced by the ordinary clamp.

The salary table is the coordinate registry. Its 105 Role coordinates and the
generated role-table-semantics registry currently have identical coverage, but
the table is the direct source of the salary evidence the floor claims to trust.

## Consequences

- Invented and cross-Tier coordinates cannot manufacture a promotion.
- Valid Manager coordinates keep the existing HK$40,000 or HK$50,000 floor,
  according to reviewed Employer size.
- Reviewed whole-band rules such as DBS Cash Product Manager remain authoritative
  and continue to bypass the fallback floor under ADR 0021.
- The historical Manager-floor backfill uses the same classifier and therefore
  inherits the correction without a second implementation.
- The clamp source participates in ADR 0020's shared salary fingerprint, making
  affected unaccepted estimates stale on the next enrichment run.
