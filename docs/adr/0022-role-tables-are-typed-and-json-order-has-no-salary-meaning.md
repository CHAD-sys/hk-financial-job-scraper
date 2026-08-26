# Role tables are typed and JSON order has no salary meaning

**Status:** accepted (2026-08-24)

`tables_monthly_hkd` combines two different kinds of data. Standardized bank and
insurance tables are corporate-grade ladders. Other tables are catalogues of
different job titles or specialisms collected from salary guides.

The old `_role_ceiling` treated every unrecognized table as a ladder and sampled
its insertion order at junior, mid, senior and lead fractions. Reordering an
unchanged `corporate_accounting_finance` object changed its inferred ceilings
from HK$23.5k/85.5k/42k/26k to HK$26k/42k/85.5k/23.5k. Fifteen Roles produced a
lower ceiling at a higher seniority.

## Decision

The anchor builder generates `role_table_semantics` after applying reviewed
overrides. Every Role is explicitly one of:

- `grade_ladder`, with a `seniority_to_grade` map; or
- `title_catalog`, whose row order carries no meaning.

Only an explicit grade-ladder map may translate coarse seniority into a role
band or ceiling. A title catalogue fails open to the tier/global constraints
unless enrichment supplied an exact `(tier, role, grade)` coordinate. Exact
coordinates remain valid for both table kinds.

The publishable build rejects missing/orphan types, unknown kinds, invalid or
flat salary cells, missing mapped rows, unknown seniority names and descending
grade ceilings. The runtime loader repeats validation; if it sees an invalid
artifact, coarse role/seniority pricing is disabled rather than guessed.

The immutable raw Hays input contains one cap-collapsed HK$200k–200k source cell.
Provenance-only `--without-overrides` rebuilds may preserve that source artifact,
but the publishable overlay widens the current M&A/ECM/DCM MD cell to the prior
Director floor, HK$142.5k–171.5k. A flat anchor cannot reach runtime.

## Consequences

- JSON key order can no longer change a salary.
- The 43 title catalogues require exact grade/title coordinates; 62 standardized
  grade ladders retain safe coarse-seniority fallback through explicit maps.
- Four partial ladders resolve only the seniorities they actually declare.
- Table-type changes participate in ADR 0020's salary fingerprint and therefore
  make unaccepted prior estimates stale.
- New Roles cannot be published without an explicit generated type and a valid
  salary shape.
