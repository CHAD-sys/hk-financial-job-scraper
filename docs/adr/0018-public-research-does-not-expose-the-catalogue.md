# Public research does not expose the catalogue

**Status:** accepted (2026-08-11; supersedes ADR 0002)

FinEx Careers remains usable without an account, but the Role catalogue is no
longer an enumerable public index. A visitor starts with a specific text
research query. That query establishes the eligible Role set; sector, employer,
seniority, salary, skill, tier and every other filter may only narrow that set.
Pagination and result counts describe the same set. An empty query, filters
without a query, and global filter-facet requests are refused.

Within that Research Scope, catalogue audience is also enforced. Anonymous
visitors receive mainstream Roles only. A signed-in Seeker or Admin additionally
receives `source_tier='boutique'` (the medium/boutique company and approved direct
submission track) and `source_tier='social'` (promoted recruiter posts). These
Roles remain mixed naturally into the same ranked stream; audience is not exposed
as a user-controlled tier switch.

## Detail access

Knowing a `(source, source_id)` pair is not permission to read the Role. Every
allowed discovery path—research results, evidence-based Roles for you, resume
matches and Saved Roles—attaches a short-lived HMAC-signed grant bound to the
exact Role reference.
The detail route requires that grant and answers with the same 404 for a missing
Role and a missing, modified, expired or wrong-Role grant. Admin accounts retain
operational read access; only Ultimate Admin retains editing access.

`ROLE_ACCESS_SECRET` keeps grants stable across Railway restarts and replicas.
When it is absent, a process-local random secret fails closed across restarts;
production should configure the stable secret.

## What remains public

No sign-in wall was added to mainstream research. Anonymous visitors can search,
receive scoped facets and open the mainstream Roles returned to them. A generic anonymous
Roles-for-you feed is not an allowed discovery path: it is available only to a
signed-in Seeker and stays empty until saved Roles, settled research, direct
feedback or resume evidence makes the output relevant. Aggregate market
statistics remain public only for the anonymous audience, so totals, companies,
sectors and tier counts agree with the Roles that visitor can actually search.
Anonymous research is not persisted in a profile.

## Why this replaces ADR 0002

ADR 0002 rejected account-gating descriptions and apply links. This decision
still rejects that sign-up wall, but removes the stronger and unintended
capability ADR 0002 preserved: paging through every Role and requesting any
known database key. The owner has now explicitly prioritised catalogue access
control. Search-led discovery keeps the acquisition path open while preventing
bulk catalogue enumeration.

## Consequences

- Filter options and counts are calculated from one research result set, never
  from the full catalogue.
- Recruiter-posted and medium/boutique-company Roles require a live Seeker or
  Admin session for discovery and detail access, including when a previously
  issued detail grant is replayed after logout.
- Frontend paths labelled “Explore all Roles” or “All jobs” are removed.
- Saved, evidence-based recommended and resume-matched Roles remain openable
  because those are explicit relevance paths.
- A Role access grant contains no personal data and is never stored in jobs.db.
- `job_read` still supports unscoped internal candidate reads for ranking and
  admin operations; the HTTP adapter owns the public research requirement.
