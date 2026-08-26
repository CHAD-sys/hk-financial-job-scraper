# Total-package evidence is fallback-only

**Status:** accepted (2026-08-25)

Hays 2026 reports annual total package, while PERSOLKELLY reports annual base
salary and Adecco reports monthly salary with explicit variable-pay and allowance
exclusions. The original merger ranked all three ranges by midpoint and blended
them. That gave package evidence a vote in a base-oriented calibration whenever
sources overlapped.

## Decision

The guide builder now merges PERSOLKELLY and Adecco whenever either is available
for a coordinate. Hays is excluded from that calculation and is used only when
neither package-free guide covers the coordinate. Existing conservative weighting
continues between PERSOLKELLY and Adecco.

Reviewed owner overrides still apply after the guide build. The rebuild preserves
all 729 payable coordinates and changes 127 direct guide-overlap bands. Hays-only
fallback cells are not silently deleted or relabelled; provenance schema 2 keeps
them non-base-compatible until replacement evidence is available.

## Consequences

- Hays total-package evidence no longer influences a direct guide coordinate that
  has PERSOLKELLY or Adecco coverage.
- The anchor fingerprint changes, so unaccepted unpinned estimates become stale and
  can be replayed deliberately.
- Legacy post-merge interpolations may still inherit old mixed values. They remain
  visible in provenance and are the next cleanup boundary.
- Eliminating the remaining Hays-only fallbacks requires new market evidence; this
  decision does not invent a package-to-base conversion.
