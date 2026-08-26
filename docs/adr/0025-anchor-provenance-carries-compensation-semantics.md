# Anchor provenance carries compensation semantics

**Status:** accepted (2026-08-25)

The merged salary table combines evidence with different meanings. Hays publishes
annual total package, PERSOLKELLY publishes annual base salary excluding benefits
and bonuses, and Adecco publishes monthly salary excluding named variable-pay and
allowance items. A source name alone cannot tell an auditor whether a number is
compatible with a monthly-base target or how it was transformed.

The legacy merge also did not preserve the exact native guide row and experience
band behind every anchor. Reconstructing those coordinates by guessing would make
the ledger look more complete while making it less truthful.

## Decision

`hk_salary_anchor_provenance.json` schema 2 defines every source as structured
compensation evidence: basis, native period, currency, inclusions/exclusions,
AWS/13th-month state, normalization, source artifact and evidence pages.

Every salary cell now carries its published period and currency, source-specific
compensation bases and transformations, a semantic compatibility status, mapping
rationale, and native-source coordinates. Where the old merger did not preserve a
native role or experience band, those values remain `null` with an explicit mapping
status. Human calibrations name their exact FinEx coordinate but do not claim an
undocumented base-pay definition.

The ledger's target is deliberately called
`mixed_calibration_not_strict_base_salary`. Hays-only `/14` values are marked
`total_package_proxy_not_base_compatible`; every multi-source cell containing Hays
is marked `mixed_basis_contains_total_package`. This metadata is audit-only and
does not change an anchor or participate in pricing.

## Consequences

- No Hays-derived cell can silently present itself as base-compatible evidence.
- The next numerical revision can identify package-contaminated cells directly
  instead of searching prose or re-inferring lineage.
- Native mapping gaps are measurable and can be repaired from the source PDFs one
  row at a time.
- Provenance changes do not stale or re-enrich Roles because they do not affect a
  salary result.
