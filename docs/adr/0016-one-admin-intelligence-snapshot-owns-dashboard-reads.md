# One Admin Intelligence Snapshot owns dashboard reads

**Status:** accepted (2026-08-11)

`webapp/backend/admin_intelligence.py` owns the complete read that builds the
admin intelligence desk. Its interface is one operation:
`build_admin_intelligence(connection, history_days, operating_day)`. It returns
the Daily Run status, run history, operational health, publication safety,
source health, AI usage, recommendation health and market intelligence as one
versioned, timestamped outcome.

## Coherence and degradation

All jobs.db evidence is read inside one SQLite read transaction, with one Hong
Kong operating date and one generation timestamp. The frontend therefore cannot
combine data observed before and after a catalogue publication. Recommendation
health is sampled through seekers.db's existing store rather than joining or
attaching Seeker data; ADR 0006 remains unchanged.

The snapshot explicitly reports availability for the catalogue, history, Daily
Run ledger, source-health ledger, AI-usage ledger, publication receipt and
recommendation evidence. A missing optional table may still produce safe empty
shapes for rendering, but callers can distinguish “not recorded” from a genuine
zero. The Daily Collection UI withholds zero-looking activity cards when its
history ledger is unavailable.

## HTTP and frontend

FastAPI exposes one authenticated `GET /api/admin/intelligence` adapter. The
former four read routes independently queried today, history, operations and
analytics; the React page called all four concurrently and could display four
different SQLite points in time with four error states. They are replaced by
one fetch and one refresh/error state. Submission review and Ultimate Admin job
editing remain separate write modules and routes.

## Why the module is deep

Callers learn one interface and receive every evidence-backed admin read. The
implementation hides SQL, completeness thresholds, market cohort rules,
percentiles, phase projection, alert derivation, graceful legacy-schema handling
and cross-store recommendation sampling. Deleting it would spread those rules
back across routes and frontend callers, so the module earns depth.

## Consequences

- A new admin metric or degradation rule has one implementation location.
- Snapshot-level behavioural tests are the primary test surface; they assert
  complete and missing-evidence outcomes rather than private SQL helpers.
- jobs.db uses the existing local SQLite stand-in. seekers.db remains a second
  local adapter with its own failure semantics.
- The snapshot schema is versioned so future incompatible response changes are
  deliberate rather than accidental.
