# Hays 2026: Professional Practice / Big Four evidence

## Question and scope

The current highest-priority market gap is the generic
`corporate_finance_accounting / professional_practice_advisory` ladder.  It is
used for 170 active primary Listings at the **role** level, although only three
of those Listings currently resolve to each individual grade.  It currently
contains a mixture of Hays-derived package proxies, an interpolation, and an
unattributed entry; see
[`market_gap_queue.json`](../../salary_guidlines/market_gap_queue.json).

For this review, “Big Four” is the project's employer segment: **EY, KPMG,
Deloitte, and PwC**.  That correspondence is an internal classification, not
a statement made by Hays.  Hays labels the relevant employer market as
**Professional Practice**, **Professional Services**, or an individual service
line; it does not publish firm-specific figures for the four firms.

## Finding: Hays does contain directly relevant Hong Kong tables

The local primary source,
[`2026 Hays Asia Salary Guide HK (1).pdf`](../../salary_guidlines/2026%20Hays%20Asia%20Salary%20Guide%20HK%20%281%29.pdf),
has a Hong Kong SAR column for the following four Professional-Practice /
Professional-Services tables.  The amounts below are transcribed in their
**native form: annual HKD '000 total package**, rather than salary base.

| Hays table (PDF page) | Hays grade label | HK annual total package, HKD '000 | Mechanical monthly package equivalent (`annual / 12`) |
| --- | --- | ---: | ---: |
| `Accountancy & Finance → Professional Practice → Advisory Practices` (p. 33) | Consultant | 300–420 | 25.0–35.0k |
| same | Senior Associate / Assistant Manager | 420–600 | 35.0–50.0k |
| same (p. 34) | Manager | 600–840 | 50.0–70.0k |
| same | Senior Manager | 840–1,200 | 70.0–100.0k |
| same | Director / Partner | 1,200+ | 100.0k+ (open-ended) |
| `Audit, Risk & Compliance → Audit → Professional Services` (p. 40) | Associate / Senior Associate | 300–480 | 25.0–40.0k |
| same | Assistant Manager | 480–576 | 40.0–48.0k |
| same | Manager | 600–720 | 50.0–60.0k |
| same | Senior Manager | 780–1,100 | 65.0–91.7k |
| same | Director / Partner | 1,200+ | 100.0k+ (open-ended) |
| `Audit, Risk & Compliance → Risk → Professional Services Enterprise Risk` (p. 47) | Associate / Senior Associate | 240–300 | 20.0–25.0k |
| same | Assistant Manager | 360–540 | 30.0–45.0k |
| same | Manager | 540–780 | 45.0–65.0k |
| same | Senior Manager | 780–1,100 | 65.0–91.7k |
| same | Director / Partner | 1,200+ | 100.0k+ (open-ended) |
| `Audit, Risk & Compliance → Compliance → Professional Services` (p. 50) | Officer / Senior Officer | 216–360 | 18.0–30.0k |
| same | Assistant Manager | 360–480 | 30.0–40.0k |
| same | Manager | 480–780 | 40.0–65.0k |
| same | Senior Manager | 720–1,000 | 60.0–83.3k |
| same | Director / Partner | 1,000+ | 83.3k+ (open-ended) |

The first table is the exact source family for the project’s generic
`professional_practice_advisory` name.  Its grade sequence maps cleanly to
Consultant, Senior Associate / Assistant Manager, Manager, Senior Manager,
and Director / Partner.  It does **not** supply an Analyst/Graduate Associate,
Senior Consultant, stand-alone Associate Director, or stand-alone Partner
band.  Those cells therefore cannot honestly be attributed to that table.

The three other tables demonstrate a second issue with one generic ladder:
Hays treats advisory, audit, enterprise risk, and compliance as distinct
professional-services labour markets.  For example, its Manager package bands
are 50–70k, 50–60k, 45–65k, and 40–65k monthly-equivalent respectively.  A
single board coordinate must therefore retain a broad uncertainty range or be
split by function before it can claim function-specific evidence.

## The important limitation: this is not base-pay evidence

Hays’ table footer says the ranges are in local currency '000 (Japan excepted)
and are “representative of the **total annual package value**.” The official
[Hays Hong Kong 2026 Salary Guide FAQ](https://www.hays.com.hk/salary-guide)
states the same thing: salaries are local-currency annual package values
(FAQ, “Does the Hays Asia Salary Guide include total compensation?”).

Consequently, dividing by 12 is only a period conversion; it yields an
**average monthly total-package proxy**, not a monthly base salary.  Hays does
not break the package into fixed base, bonus, 13th-month/AWS, allowances, or
benefits, so no defensible general conversion factor is available.  The `+`
rows also have no published upper bound and must stay open-ended rather than
be capped by the Hays source.

This confirms why the queue marks most of this ladder
`replace_hays_package_proxy`: the problem is a compensation-basis mismatch,
not an absence of relevant Hays content.  The existing source-semantics audit
records the same conclusion in
[`salary_anchor_compensation_semantics_2026-08-21.md`](../salary_anchor_compensation_semantics_2026-08-21.md).

## What this supports, and what it does not

- It supports using the Hays figures as a **sanity-check envelope** for Big
  Four professional-practice roles.  The project’s existing owner-reviewed
  Big Four Manager band (50–60k) lies within both the Advisory Practices and
  Audit Professional Services monthly-package bands.
- It supports differentiating audit, enterprise-risk, compliance, and general
  advisory rather than treating every Big Four title as interchangeable.
- It does **not** validate a monthly-base anchor directly, does not identify
  individual Big Four firms, and does not produce a closed Director/Partner or
  Partner maximum.  It also cannot validate the stand-alone Associate Director
  rule because Hays publishes only `Director / Partner` at that level.

## Source locations and reproduction

- Local Hays PDF: pp. 33–34 (Advisory Practices), p. 40 (Audit Professional
  Services), p. 47 (Professional Services Enterprise Risk), p. 50 (Compliance
  Professional Services).  The four rendered table headers and values were
  visually checked from the PDF, rather than relying on column-order text
  extraction.
- Repository’s machine-readable Hays conversion:
  [`hays_2026.json`](../../salary_guidlines/hays_2026.json),
  `corporate_finance_accounting.roles.professional_practice_advisory`.  Its
  25–35 / 35–50 / 50–70 / 70–100 monthly values are the p. 33–34 figures
  divided by 12; they must be read as package proxies, notwithstanding the
  legacy `basis` field in that file.  The **published** generic anchor then
  uses a more conservative `/14` temporary proxy (21.5–30 / 30–43 / 43–60 /
  60–85.5 / 85.5–171.5); its provenance explicitly records that transformation
  and the requirement for replacement market evidence.
- Official issuer page: [Hays Asia Salary Guide — Hong Kong](https://www.hays.com.hk/salary-guide).
