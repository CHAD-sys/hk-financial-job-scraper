# One Catalogue Publication owns the live handover

**Status:** accepted (2026-08-11)

`webapp/backend/pipeline_publish.py` is the single domain boundary that moves a
completed Daily Run's Listing facts into the live Railway catalogue. GitHub's
HTTP upload and download remain transport adapters. They do not decide table
ownership, validation, preservation, idempotency, backup policy, search-index
rebuilding or when a publication receipt exists.

## Interface

The module presents two outcome-oriented operations:

- `create_restore_point(live_path)` returns a checksummed, coherent
  `RestorePoint` from which another Daily Run can resume.
- `publish_catalogue(live_path, upload, identity)` validates and atomically
  publishes one catalogue, returning a typed `PublicationReceipt`.

The identity groups the run ID, expected content hash and trace URL. A receipt
is written and returned only in the same transaction that makes the new
catalogue visible. Repeating the same run and hash returns the existing receipt;
reusing a run ID with different content is a conflict.

## Ownership

Pipeline-owned tables are replaced as one set. The core Listing, enrichment,
history and company-metric tables are required. Optional pipeline datasets such
as AI usage, salary audit and source-health rows are also pipeline-owned: when a
run does not produce one of those datasets, its live contents become empty
rather than silently retaining facts from an earlier run.

Railway owns approved direct Roles, their enrichments, Ultimate Admin edits,
Daily Run operational records and publication receipts. Restore points remove
those rows, and publication preserves or reapplies them. Legacy Railway receipt
rows are also stripped from restore points so upgraded volumes cannot leak old
operational state back into a Daily Run.

ADR 0006 remains unchanged: `seekers.db` is not attached, exported, uploaded or
modified by Catalogue Publication.

## One publication path

The former `/api/admin/pipeline/snapshot` endpoint separately rewrote
`job_history` and recorded a second receipt after the database publication. It
was no longer called by the hosted Daily Run and could make the admin dashboard
describe a different handover from the live catalogue. It is removed.
`job_history` now travels only inside the atomic Catalogue Publication, and the
admin dashboard's “received” fact comes from its publication receipt.

## Consequences

- A schema or ownership change has one implementation location and one direct
  interface-level test surface.
- The HTTP route is limited to authentication, headers, upload/download and
  mapping domain errors to status codes.
- Every accepted handover is backed up, checksummed, validated, atomic and
  traceable to exactly one Daily Run.
- Publication fails closed on corrupt, incompatible or catastrophically small
  catalogues; the previous live catalogue remains visible.
