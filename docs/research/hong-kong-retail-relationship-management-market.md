# Hong Kong retail relationship-management salary market

**Purpose.** Assess the two retail-banking relationship-management cells
currently suspected of being Hays total-package proxies: `Sales Manager` and
`Head of Personal Banking`.  This is research only; it does not change an
anchor, pricing rule, provenance record, database, or test.  Researched 26
August 2026.  Amounts below are HKD per month.

## Decision summary

Neither title is a safe corporate grade.  `Sales Manager` can mean a first-line
leader of a small branch/premier-sales team, a sales-performance specialist, or
a multi-branch distribution manager.  `Head of Personal Banking` can mean a
department head (for a product, channel, segment, or function) or the executive
who owns an entire retail/personal-banking division.  The title must therefore
be read with its **organisational and commercial scope** before pricing.

| Title and verified scope | Conservative base-pay recommendation | How to use it |
|---|---:|---|
| Sales Manager: one branch, small premier/RM team, or local sales-performance remit; no formal VP/Head/Director grade | **45–65k** | Default only for a clearly local first-line sales leader. |
| Sales Manager: manages several branches or a material retail segment, owns sales planning/targets and people leadership | **60–85k** | Wider local distribution scope.  Do not infer this from the word `Sales` alone. |
| Sales Manager: regional/HK-wide distribution, a formal VP/Director grade, or divisional P&L | **Do not use a Sales Manager cell** | Route to explicit grade/scope evidence.  A narrow manager cap would underprice it. |
| Head of Personal Banking: a single product, channel, customer segment, or department within the division | **90–130k** | A conservative local functional-head fallback, only where there is no explicit corporate grade. |
| Head of Personal Banking: owns the HK personal-banking/retail-banking division, branches and/or wealth business, divisional strategy/P&L and senior leaders | **140–200k+** | Treat as an executive/GM-level market gap or use a verified employer-grade rule.  Do not cap it at 180k merely because the title says `Head`. |

The `Head` bands are deliberately wide.  They are a conservative synthesis,
not a published title-for-title salary survey.  The available direct Hong Kong
source gives `Head of Personal Banking` a very broad 40–160k range, while the
scope evidence shows that the division-wide version is an executive role.  A
single 100–180k value conceals that material distinction.

## Compensation basis: Hays cannot produce a monthly-base anchor

The existing Hays relationship-management row is `Sales Manager` **55–90k**
in `salary_guidlines/hays_2026.json`.  Hays labels its 2026 Hong Kong guide
figures as **annual total package**, rather than basic monthly salary.  Thus a
mechanical conversion of that row to a monthly figure (whether `/12`, `/13` or
`/14`) would manufacture a base-pay definition Hays did not publish.  It can
be retained only as a directional seniority/package sanity check, not evidence
for a closed base-pay band.

By contrast, Randstad's Hong Kong 2025 Banking & Financial Services table says
that its figures are **basic monthly salary for a permanent role**, excluding
AWS and fixed/variable bonus.  That is the appropriate primary benchmark for a
base-pay envelope.  Sources: [Hays Hong Kong Salary Guide
methodology](https://www.hays.com.hk/salary-guide) and [Randstad Hong Kong 2025
Salary Guide, banking table p.16](https://www.randstad.com.hk/s3fs-media/hk/public/2025-01/Randstad-Hong-Kong-SAR-2025-Job-Market-Outlook-Salary-Guide.pdf?VersionId=Nbc9a4xsKw0jkw6VdMPz4ygnUr6zj93H).

## Direct base-pay evidence

Randstad does not publish a `Sales Manager` or `Head of Personal Banking` row
in its retail-banking table.  It does publish the closest direct base-pay
ladder, which makes the present title-only bands testable against the actual
retail relationship market:

| Randstad retail-banking role | 1–3 years | 3–6 years | 7–10 years | 10+ years |
|---|---:|---:|---:|---:|
| Premier Banking Relationship Manager | 30–44k | 35–65k | 45–70k | 70k+ |
| Investment Consultant | 38–65k | 50–65k | 65–85.5k | 85k+ |
| Insurance Specialist | 25–35k | 30–55k | 45–65k | 65k+ |

Source: [Randstad Hong Kong 2025 Salary Guide, p.16](https://www.randstad.com.hk/s3fs-media/hk/public/2025-01/Randstad-Hong-Kong-SAR-2025-Job-Market-Outlook-Salary-Guide.pdf?VersionId=Nbc9a4xsKw0jkw6VdMPz4ygnUr6zj93H).  The guide expressly defines these as basic
monthly salary, excluding AWS and bonuses.

This evidence supports a 45–65k first-line sales-manager default: it sits above
ordinary experienced Premier RM pay without asserting that every sales-manager
title is an executive leader.  It also supports 60–85k for a senior
multi-branch/segment manager: that range overlaps the guide's 7–10-year
investment-consultant cohort and has room for people and target accountability.
It does **not** support flattening an explicit VP/Director, regional, or
division-wide role into either band.

The government-supported Vocational Training Council (VTC) Occupation
Dictionary publishes a separate private-sector career path for personal
banking: Customer Services Officer 20–30k, Customer Services Manager 40–60k,
and `Head of Personal Banking` **40–160k** per month.  This source is useful
because it confirms title breadth and a distinct head-level ceiling, but it is
too broad and lacks methodology/date detail to select a precise anchor alone.
Source: [VTC Occupation Dictionary — Personal Banking Customer Services
Officers](https://occupation-dictionary.vtc.edu.hk/occupation/personal-banking-customer-services-officers).

## Scope evidence: why the two Head cases must split

Current bank postings demonstrate that headings under Personal Banking are
senior leadership work, but at different organisational levels:

- BEA's `Head of Strategy & Business Planning — Personal Banking Division`
  reports to the **General Manager and Head of Personal Banking Division** and
  leads division strategy, business planning, financial governance,
  performance management and risk oversight.  This is a *department head
  within* the division, not necessarily the person who owns the whole retail
  business.  [BEA posting](https://hk.linkedin.com/jobs/view/head-of-strategy-business-planning-personal-banking-division-at-the-bank-of-east-asia-bea-4435031927).
- Bank of China (Hong Kong)'s `Head of Securities & Structured Investment
  Division, Personal Banking Product Department` requires at least 10 years'
  specialist experience and five years of management, and owns product,
  pricing, service-model, sales-platform, budget and regulatory decisions.
  It is labelled Director by the posting.  This validates a functional Head as
  a senior commercial/product leader, not an ordinary RM manager.  [BOCHK
  posting](https://hk.linkedin.com/jobs/view/head-of-securities-structured-investment-division-personal-banking-product-department-at-bank-of-china-hong-kong-4294173236).

These postings establish role *scope*, not disclosed pay.  They should never
be represented as salary evidence.  Their practical implication is that the
formal grade and remit must override a generic relationship-management cell.

## Classification guardrails

1. A `Sales Manager` whose work is direct sales/RM performance for a local
   team is in scope for the 45–65k default.  `Branch`, `Premier`, `Wealth`,
   `sales performance`, a small number of named RMs, and local target ownership
   are positive scope signals.  A role that is principally an individual RM
   should remain an RM, even if its sales target is high.
2. Do not promote the title just because it contains `sales`.  Conversely, do
   not use the first-line band where the description shows a network-wide,
   regional, cross-border, channel-P&L, or executive remit.
3. `Head of Personal Banking` is only a function/department head when the
   title says what it heads (for example, a channel, product, strategy,
   propositions or segment) and reports into a divisional Head/GM.  Use the
   90–130k fallback only after checking that it has no stated VP/Director/ED
   grade.
4. `General Manager and Head of Personal Banking Division`, `Head of Retail
   Banking`, titles that own branches and wealth/P&L, and regional/global/group
   heads are not the same coordinate.  Leave them to an explicit employer
   grade, a disclosed salary, or a dedicated executive-scope rule.
5. Keep all stated base/annual salary advertisements and verified
   company-specific ranges above these generic recommendations.  Never reduce
   a stated `VP`, `Director`, `ED`, or `GM` merely because another phrase in
   the title is `Sales Manager` or `Head`.

## Confidence and limitation

- **High confidence:** Hays-package figures must not be mechanically treated
  as monthly base; Randstad's retail table is explicit base-pay evidence.
- **Moderate confidence:** the 45–65k and 60–85k Sales Manager bands.  They are
  conservative relationships to direct retail RM/specialist base bands, not an
  exact published Sales Manager series.
- **Moderate-to-low confidence:** a numerical `Head of Personal Banking`
  fallback.  VTC provides the only direct title match but its 40–160k span is
  intentionally broad.  The 90–130k functional-head band is a cautious
  operating range; division-wide heads should be treated as a separate,
  unresolved executive-scope band rather than priced by title alone.
