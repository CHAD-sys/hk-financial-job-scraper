# Seeker data lives in its own SQLite file, never in jobs.db

**Status:** accepted (2026-07-30)

Accounts, sessions, saved roles and Seeker-owned state live in `/data/seekers.db` on
the Railway volume — a separate file from `jobs.db`, with its own writable connection.
Saved Roles join to job data via SQLite `ATTACH`.

Four reasons, strongest first:

1. **`get_db()` sets `PRAGMA query_only=ON`** (`webapp/backend/main.py:90`). The public
   API is structurally incapable of writing to job data. Putting Seeker tables in
   `jobs.db` means deleting that invariant and giving every request handler write
   access to 3,612 roles, in exchange for a table location.
2. **The scraper owns `jobs.db` and rewrites it nightly.** Credentials do not belong in
   the write path of the pipeline.
3. **`backup.py` copies `jobs.db` wholesale and defaults to `retention_days=0`** — it
   keeps every daily snapshot forever. Seeker data in `jobs.db` would be duplicated
   into an unbounded, indefinitely-retained archive on a laptop, which is a PDPO
   retention problem created for no benefit.
4. **Wholesale replacement of `jobs.db` is explicitly contemplated** —
   `_seed_db_if_missing()` exists to drop a fresh copy onto a volume. Any future
   re-seed would silently delete every account.

**Consequences:**

- This is the **first time the backend writes to a database**; its only write today is
  appending JSONL. WAL mode, write concurrency and locking on a network-backed Railway
  volume become live concerns.
- `seekers.db` has no second copy anywhere — unlike `jobs.db`, which is reproducible
  from the local pipeline. Railway's scheduled volume backups are therefore mandatory,
  not optional. Note a restore is whole-volume and rolls `jobs.db` back with it.
- `seeker_id` is a UUID: opaque, permanent, never reused, and never the email address.
  Email is mutable and must never be an identifier for anything downstream — including
  the CV/personalisation component, whose contract is deliberately deferred.
