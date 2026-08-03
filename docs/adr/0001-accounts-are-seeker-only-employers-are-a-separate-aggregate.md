# Accounts are Seeker-only; Employers are a separate aggregate, not a role

**Status:** accepted (2026-07-30)

FinEx Careers has three plausible account holders — job seekers, recruiters/employers,
and existing FinEx Club members — and only the seeker has a live, provable demand
signal today (3,612 roles on the board, saved roles currently stranded in
`localStorage` where they die with the browser profile). We are therefore shipping
**seeker accounts only**. Employer accounts stay out of scope until there is paid
inventory to sell (`docs/PLAN_FRONT_PAGE.md` decision 20 defers self-serve and
billing as a separate 20–25d item), and club-member identity stays out of scope
because it would mean an identity migration from a Wix site we do not control.

**What v1 is actually for.** Not Seeker demand — there is a deliberate decision to
gate nothing (ADR 0002) and to ship without alerts, so the account's only v1 benefit is
durable Saved Roles and few Seekers are expected to create one. v1 exists as the
identity foundation for **future paid personalisation** (CV matching and personalised
roles, built by another team member) which cannot exist without a Seeker to attach a
CV to. This implies two things: keep the v1 surface minimal rather than building
conversion pressure for features that do not exist yet, and get identity right the
first time, because migrating a *paying* user base later is far more expensive than
migrating a free one.

**Consequence that constrains the schema:** an Employer is *not* a `role` column on
the Seeker table. Employers bring organisations, seats, invoices and per-listing
ownership — a different aggregate with a different lifecycle. A single `users` table
with `role = 'seeker' | 'employer'` reads cheap now and becomes a permissions mess
the moment the paid-listing product lands. Employers get their own table when they
arrive; the Seeker table is designed to not need reshaping when that happens.
