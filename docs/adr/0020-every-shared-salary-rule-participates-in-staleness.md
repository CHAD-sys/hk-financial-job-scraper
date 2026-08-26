# Every shared salary rule participates in staleness

**Status:** accepted (2026-08-24; amends ADR 0019)

`job_enrichments.prompt_version` is the Daily Run's signal that an estimate was
produced under older salary behaviour. That signal must change whenever a shared
rule can change the number stored for a Role.

The original fingerprint covered the model, salary prompt, core anchor ladders,
management caps and a hand-maintained subset of clamp constants. Later calibration
added title-grade bands, function bands, employer-size groups, employer overlays,
Manager floors, internship rules and many title regexes. Those rules changed actual
outputs while leaving the version unchanged, so the Daily Run could not distinguish
an estimate produced before the rule from one produced after it.

## Decision

`salary_anchors.fingerprint()` covers every non-prose top-level anchor section and
the behavioural global maximum. New shared configuration is therefore covered by
default instead of requiring another allowlist edit.

The clamp fingerprint covers all serialisable uppercase rule state and a normalised
AST of the executable finishing/clamp logic. Python comments and docstrings are
removed before hashing: explaining a rule remains free, while changing a formula,
branch, precedence order, regex, band or allowlist creates a new version.

The new version reaches the existing `_fetch_unenriched` selector. An unpinned row
carrying an unaccepted prior version is replayed through enrichment; a pinned admin
correction remains excluded under every mode.

## Cost remains an explicit decision

A version change does not require blindly paying for the whole catalogue.
`salary.ACCEPTED_PRIOR_VERSIONS` remains the operator's explicit decision to accept
an older result. When a shared change can be applied exactly in Python, the operator
may grandfather the old version and run a targeted deterministic repair instead.
When model judgement is required, leaving the version unaccepted deliberately queues
re-enrichment.

This amends ADR 0019's statement that `GRADE_BANDS` are excluded from the fingerprint.
Shared grade bands now participate. ADR 0019's boundary for individual admin salary
corrections is unchanged: dynamic per-Role evidence remains outside the global digest,
because one correction must not make every Role stale.

## Consequences

- A salary-changing rule can no longer ship with an unchanged version merely because
  it was added after the fingerprint allowlist.
- Logic changes no longer depend on remembering to bump `MANUAL_TAG`; that tag remains
  an escape hatch for external behaviour the fingerprint genuinely cannot observe.
- A newly detected version difference may represent a real model bill. The accepted
  prior-version ledger is the review point, not an invisible omission from hashing.
