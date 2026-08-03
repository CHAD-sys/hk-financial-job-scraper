# The board stays public; accounts gate nothing

**Status:** accepted (2026-07-30)

A Seeker account unlocks features (durable Saved Roles, email alerts) but is never
required to read a Role. Title, company, location, full description, salary estimate
and apply link stay public to anonymous visitors exactly as they are today.

We considered gating the description, salary and apply link behind sign-in to force
adoption, and rejected it on three grounds:

1. **It is unmeasurable.** The platform runs no analytics at all — by choice, and
   `PrivacyNotice.tsx` advertises that fact. Gating is an irreversible change to the
   only acquisition funnel, with no instrumentation to tell whether signups rose or
   traffic fell. That decision needs a before/after number we cannot produce.
2. **It would make our own published commitments false in the same release.**
   `AboutPage.tsx` promises "free to browse and needs no account — no paywall on any
   listing."
3. **It forecloses a channel worth more than gated signups.** A Role currently has no
   URL (the detail view is React state, not a route) and the site emits no
   `JobPosting` structured data, so there are 3,612 roles and zero indexable pages.
   Building per-Role URLs and structured data is a real acquisition engine, and
   gating descriptions is exactly what would make it non-compliant with Google's
   cloaking policy.

**Consequence:** a gate can be added later once analytics justify it; it cannot easily
be *removed* after being announced. If adoption is poor, the first response is to
strengthen the carrot or add instrumentation — not to reach for the gate.
