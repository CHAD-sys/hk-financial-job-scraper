# FinEx Careers

The domain language of the FinEx Careers platform: a Hong Kong financial-sector job
board fed by an automated multi-source scraping pipeline, sitting inside a
three-product portal (Careers, Executive Consultation, Professional L&D).

This file is a glossary. It records what terms *mean*, never how they are
implemented — implementation decisions belong in `docs/adr/`.

## Language

### People

**Seeker**:
A person who uses the board to find work, and the only kind of account holder the
platform has. See `docs/adr/0001`.
_Avoid_: user, candidate, member, applicant, job seeker (two words)

**Employer**:
An organisation that has roles to fill. Not currently an account holder, and when it
becomes one it will be a distinct aggregate rather than a Seeker with a different
role. See `docs/adr/0001`.
_Avoid_: company (reserved for the scraping-side config entity), client, recruiter

**Recruiter**:
An agency recruiter or independent headhunter whose LinkedIn posts are a data
*source*. Distinct from an Employer: a Recruiter advertises somebody else's vacancy,
often confidentially.
_Avoid_: headhunter, agency

**Club Member**:
A member of FinEx Club, the organisation behind the platform, whose membership lives
on finexclub.org and has no relationship to a Seeker account.
_Avoid_: member (unqualified — ambiguous with Seeker)

**Verified Identity Claim**:
The checked identity evidence returned after a Google or LinkedIn sign-in round
trip: provider, immutable subject, optional email, explicit email-verification
status and optional display name. It is evidence, not permission. Seeker and
Employer account policies separately decide whether it may recognise, link or
create an account. See `docs/adr/0017`.
_Avoid_: OAuth user, social account, authenticated user (the claim alone does
not establish a FinEx session)

### The board

**Role**:
One open vacancy as the board presents it to a Seeker.
_Avoid_: job (reserved for the stored row), listing, posting, vacancy

**Listing**:
The stored record of a Role as collected from one source. Several Listings can
describe the same Role when it is cross-posted; exactly one is primary.
_Avoid_: job row, entry

**Tier**:
Which class of source a Listing came from, as surfaced in the board's tabs:
Mainstream, Exclusive, or Recruiter Posts.
_Avoid_: category (reserved for the AI-assigned job category), type, source type

**Saved Role**:
A Role a Seeker has marked to return to. It is a reference to a Role, never a copy of
one, so a Saved Role always reflects the Role as it stands now — including showing as
Closed once the Role is gone. It stops being listed once it has been Closed a
fortnight: still saved, still reachable, no longer in the way (`docs/adr/0011`).
_Avoid_: bookmark, favourite, shortlist, starred job

**Closed**:
A Role that is no longer open. The Listing is kept rather than removed, so a Seeker can
still look at a vacancy after it stops accepting applications — which is the whole point
of never hard-deleting one. Closed is a *state a Role is in*, not a reason it is
missing: a Closed Role is still readable, still Saveable, and still says what it paid.
Only a Role reached by reference is ever Closed; the board shows open Roles only. We
also record *when* it closed, which is what lets a Saved Role drop off a list after a
fortnight without the Role itself going anywhere. See `docs/adr/0010` and `0011`.
_Avoid_: expired, inactive, dead, archived, deleted (a Role is never deleted)

**Alert**:
A standing request to be told when new Roles match a Seeker's criteria. An Alert *is* a
saved search — the same criteria the board already filters on, kept and re-run — not a
separate notion of what a Seeker wants. Decided but not yet built.
_Avoid_: job alert, notification, subscription, watch

**Role Feed**:
The ordered, explainable set of open Roles shown as “Roles for you”. For a Seeker it
learns cautiously from Saved Roles, settled searches, opened Roles, explicit feedback
and resume evidence; for a visitor it reflects the current market. It is discovery
guidance, not a hiring assessment or a claim that the Seeker should remain in one field.
_Avoid_: job match, CV match, guaranteed fit, recommendation algorithm (the implementation)

**Research Scope**:
The live set of Roles matched by one Seeker or visitor's specific text query.
Filters, facets, counts, sorting and pagination may narrow or arrange this set
but never expand beyond it. A Research Scope is public and needs no account; it
is not permission to enumerate the Role catalogue. See `docs/adr/0018`.
_Avoid_: all jobs, database view, global filter set

### Collection

**Daily Run**:
One attempt to refresh and publish the Role catalogue. Every Daily Run uses the same
phase names and outcome meanings, whether a hosted or local execution profile performs
it; a profile may include different phases without creating a different kind of run.
_Avoid_: pipeline (when referring to one execution), scrape (only one phase), cron job

**Daily Run Record**:
The authoritative account of one Daily Run: its phase outcomes, timing, restored and
published catalogue identity, collection quality, source health, AI usage, overall
result and diagnostics. Admin reporting, result email and automation summaries describe
this same record rather than independently reconstructing what happened.
_Avoid_: telemetry payload, operations blob, log summary

**Catalogue Publication**:
The atomic handover of a completed Daily Run's Listing facts into the live Role
catalogue. It preserves Railway-owned direct Roles, admin corrections, operational
records and receipts, and produces one traceable receipt only after the whole catalogue
is visible. See `docs/adr/0015`.
_Avoid_: database replacement, snapshot sync, pipeline snapshot (implementation details)

**Admin Intelligence Snapshot**:
One coherent, timestamped view of the live Role catalogue, Daily Run evidence,
publication safety, source health, AI cost, recommendation health and market movement.
It says when an evidence ledger is unavailable instead of presenting missing facts as
zero. See `docs/adr/0016`.
_Avoid_: dashboard payload, analytics response, admin stats
