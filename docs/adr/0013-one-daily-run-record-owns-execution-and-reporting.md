# One Daily Run Record owns execution and reporting

**Status:** accepted (2026-08-11)

Every hosted or local Daily Run is executed by `hk_jobs.daily_run` and produces
one versioned Daily Run Record. GitHub Actions and `scripts/daily_run.sh` select
an execution profile; they do not define phase order, requiredness, failure
meaning, or operational status themselves.

The hosted and local profiles deliberately differ. They select phases from one
canonical registry, so a phase keeps the same name and outcome semantics in
both environments without pretending that PocketBase, local backups, Railway
restore, and Railway publication are the same work.

## Failure policy

- A required phase failure stops later catalogue-changing work. Publication is
  never attempted after an incomplete required path.
- An optional phase failure is a warning and later work continues.
- Reporting always runs after phase execution. A reporting failure cannot turn
  an already-published catalogue into a failed publication; the Daily Run is a
  warning, while the automation itself still exits unsuccessfully so the
  reporting fault remains visible.
- Expected cadence decisions, such as non-Monday LinkedIn discovery, are
  recorded as skipped rather than disguised as success or failure.

## One fact source

The Daily Run Record contains phase outcomes and timing, restore and publication
hashes, bounded data-quality facts, source health, AI usage, diagnostics, and
reporting outcomes. The GitHub summary, result email decision, Railway admin
ingestion, and uploaded JSON artifact consume this record rather than rebuilding
the run from YAML step names, temporary marker files, logs, or independent SQL.

Records use an explicit schema version. GitHub retains the JSON artifact for 90
days. Railway stores the record in its operational ledger and removes records
older than roughly 90 days. `pipeline_operations` is Railway-owned operational
state: catalogue export removes it and catalogue publication does not import it.

## Interface and adapters

`run_daily(profile, run_id, executor)` is the domain execution boundary. It owns
ordering, checkpointing, failure classification, and the finished record. The
injected executor owns replaceable command and transport details. Reporting
adapters run independently so an SMTP fault does not prevent Railway or GitHub
from receiving the record.

GitHub Actions now has one principal execution command and always uploads the
record and available catalogue artifacts. The local shell script is a thin
logging and environment adapter around the same command.

## Why

Before this decision, the same Daily Run was separately described by a large
workflow, a shell script, inline Python telemetry, backend phase constants, and
notification SQL. The descriptions had already drifted: hosted and local phase
sets disagreed, the shell documentation contradicted the workflow's email
behaviour, and operational rows could travel back through a stale catalogue
snapshot. Adding or reclassifying one phase required coordinated edits across
unrelated callers.

Centralising policy gives phase changes one implementation and one behavioural
test surface, while keeping actual external systems behind real adapters.

## Consequences

- `tests/test_daily_run.py` is the primary contract suite for ordering,
  required/optional behaviour, expected skips, facts, persistence, and reporting.
- Text-presence checks on YAML only guard the thin adapter; they no longer test
  business semantics.
- ADR 0012 remains authoritative for the watchlist cadence. The Daily Run calls
  that phase each local run; the watchlist implementation still decides whether
  work is due.
- The catalogue and Seeker database ownership rules in ADR 0006 are unchanged.
- A future phase belongs in the canonical registry first, followed by the
  profiles that actually need it and one adapter implementation.
