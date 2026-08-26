# Insurance tiers require positive classification

**Status:** accepted (2026-08-25)

The insurance title-grade table records reviewed Tier 1 and Tier 2 Employer
registries. The Tier 2 registry is currently empty because none of the reviewed
Tier 2 insurers is configured. Runtime nevertheless treated every insurer absent
from Tier 1 as Tier 2 and discounted its matched band by 15%. Seven configured
insurers therefore received an undocumented size adjustment, including Allianz,
even though the anchor metadata said the discount was inert.

The same table placed Vice President above Assistant Vice President but supplied
no VP band. A title such as `Vice President, Underwriting` consequently fell
through to the generic underwriting/VP coordinate, HK$53,000-70,000, below the
authoritative insurance AVP band of HK$100,000-150,000.

## Decision

The Tier 2 discount applies only when an Employer slug is explicitly present in
`tier_2_slugs`. Absence from Tier 1 is not evidence of Tier 2 membership. Tier 1
and Tier 2 registries must remain disjoint.

The DeepSeek instruction is rendered from the same Tier 2 slug registry and
discount value used by the deterministic clamp. It does not maintain another
Employer list or interpret every insurer absent from Tier 1 as Tier 2.

Insurance Vice President receives a deliberately broad HK$100,000-200,000 safety
band. Its lower endpoint is the reviewed AVP floor and its upper endpoint is the
existing global safety ceiling. This encodes the known hierarchy, prevents low
functional coordinates from undercutting AVP, and avoids claiming a precise
market benchmark that management has not supplied.

## Consequences

- Unclassified insurers keep the unadjusted generic insurance grade band.
- The 15% adjustment remains available for positively classified Tier 2 insurers.
- Every named insurance grade in `hierarchy_high_to_low` has a runtime band.
- VP estimates remain intentionally wide until a direct reviewed benchmark
  replaces the safety band.
- Both changes live in the reproducible anchor overlay and participate in the
  shared salary fingerprint under ADR 0020.
