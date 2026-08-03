# Seeker deletion is a real delete — an explicit carve-out from the soft-delete rule

**Status:** accepted (2026-07-30)

`CLAUDE.md` states a project-wide convention: *"Soft-delete only: when a job
disappears, set `is_active = False`. Never hard-delete (members may revisit past
applications)."* **That rule governs Roles, and does not extend to Seekers.**

When a Seeker deletes their account, the rows are actually removed and every session is
revoked. An account deletion that only flips a flag is not a deletion, and telling
someone their data is gone while retaining it converts an ordinary privacy question
into a serious complaint.

**Legal shape, recorded so it is not re-derived:** Hong Kong's PDPO has no explicit
right to erasure equivalent to GDPR's. It has a right of *access* (DPP6), a 40-day
window to answer such a request, and a duty not to retain personal data longer than
necessary (DPP2). Self-serve deletion is therefore good practice and the cleanest way
to discharge the retention duty, rather than something strictly compelled.

**Consequences:**

- v1 ships self-serve deletion. Access/export requests are answered manually within the
  40-day window until volume justifies automating them.
- Deletions are **logged as events** even though the personal data is removed, so that a
  deletion obligation can be honoured retroactively by the CV/personalisation component
  once its contract exists.
- The soft-delete convention in `CLAUDE.md` needs this carve-out written into it, or a
  future reader will correctly apply the wrong rule.
