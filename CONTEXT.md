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
