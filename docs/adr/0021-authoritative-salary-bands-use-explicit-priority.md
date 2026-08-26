# Authoritative salary bands use explicit priority

**Status:** accepted (2026-08-24)

The salary clamp accumulated reviewed rules one correction at a time. Each rule
was implemented as another `if` assignment, so the last matching block silently
won. Source-code position became policy without being named as policy.

This produced a concrete error: `Associate Director, Relationship Manager` first
matched the bank Associate Director band, then the generic multi-grade rule counted
the functional word `Manager` as another corporate grade and overwrote the result.
Some employer-size rules happened to overwrite that mistake later, so identical
title shapes behaved differently across Employers.

## Decision

Every authoritative whole-band rule is collected as a `SalaryRuleMatch` with a
named `SalaryRulePriority`. A single resolver chooses the highest priority, retains
all competing matches, and reports an equal-priority disagreement. Candidate
construction order is not a tie-break policy; the rule name is only a deterministic
fail-safe when a misconfiguration leaves two top-priority bands in conflict.

The evidence order is:

1. adjusted generic bank/insurance title grade;
2. Employer-group grade;
3. genuine multi-grade ambiguity;
4. reviewed Employer-size band;
5. reviewed Employer-role band;
6. narrower Employer-role band;
7. explicitly reviewed mixed-grade band;
8. exact Employer/title overlay.

Two intentional refinements preserve the management review rather than flattening
it into that list. At Big Four firms a two-option `Manager / Associate Director`
title keeps the Associate Director grade, while a three-option title such as
`Senior Consultant / Manager / Associate Director` uses the broad ambiguity band.
CMB campus bands remain reviewed exceptions to the generic internship cap.

A Manager floor is a fallback, not another authoritative band. It runs only when
no whole-band rule won, so it cannot distort a reviewed `Cash Product Manager`
range or another exact title band.

## Consequences

- Adding or reordering Python blocks cannot silently change salary precedence.
- Audits can show the winner, all matches, different-band conflicts and whether
  the top priority itself is contradictory.
- Functional titles such as Relationship Manager no longer manufacture a second
  corporate grade; Manager counts for ambiguity only when it appears as a title
  option at the start or after a separator.
- The resolver and its priority state participate in the shared salary fingerprint
  under ADR 0020, so this behaviour change makes unaccepted estimates stale.
