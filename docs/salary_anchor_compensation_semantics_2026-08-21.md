# Salary-anchor source semantics — 2026-08-21

## Decision

The current claim that the merged anchor table is **monthly base salary** is
not supportable while it contains Hays 2026 values. Hays explicitly defines
its figures as **total annual package values**, not base salary. Dividing a
Hays annual figure by 12 produces an average monthly *package* value, not a
monthly base-salary anchor.

PERSOLKELLY's three extracted source sections are suitable for conversion to
monthly base salary. Adecco is suitable as a monthly **salary excluding the
listed non-base items**, but the guide itself does not use the exact term
"base salary". Neither PERSOLKELLY nor Adecco states how a 13th-month/AWS
payment is treated; that must stay `unspecified`, not be inferred.

No anchor values are changed by this report.

## Scope checked

[`salary_guidlines/hk_salary_anchors.json`](../salary_guidlines/hk_salary_anchors.json)
currently calls its output "Monthly BASE HKD" and says it was merged from
Hays Asia Salary Guide 2026 (Hong Kong), PERSOLKELLY 2025, and Adecco 2026.
The merge script treats the main anchor table as Hays and combines it with
[`persolkelly_2025.json`](../salary_guidlines/persolkelly_2025.json) and
[`adecco_2026.json`](../salary_guidlines/adecco_2026.json). This review
checks the compensation definition of those three published guides only.

| Source | What its own source says | Native unit and seniority mapping | Status for a monthly-base table |
| --- | --- | --- | --- |
| Hays Asia Salary Guide 2026 — Hong Kong SAR | **Total annual package value.** The official FAQ says the salaries "reflect total annual package values"; the guide itself repeats that definition on every salary-table page. | Hong Kong local currency in `'000`, annual package. Tables pair each role with years of experience and role/grade titles. | **Do not use as a direct base-salary anchor.** Component breakdown is not published, so no generic package-to-base conversion is defensible. |
| PERSOLKELLY Hong Kong Salary Guide 2025 | **Base salary, excluding benefits and bonuses.** | The three sections extracted by this repo are annual HKD; rows give experience bands and titles. | **Compatible after annual ÷ 12.** Record conversion and retain open-ended bounds. |
| Adecco Hong Kong Salary Guide 2026 | **Monthly salary excluding overtime, commissions, allowances, and bonuses.** | Monthly HKD min/max; rows give role, qualification, and (where present) experience range. | **Compatible as a monthly salary excluding those items.** Call it `monthly_salary_excluding_variable_and_allowances`, not strict `base`, until Adecco confirms that equivalence. |

## Evidence by provider

### Hays Asia Salary Guide 2026 — not base salary

- Hays' Hong Kong [2026 Salary Guide FAQ](https://www.hays.com.hk/salary-guide)
  identifies the guide as covering Hong Kong SAR and answers its total-
  compensation question: "Salaries are presented in local currencies and
  reflect total annual package values, shown in ’000 for all markets except
  Japan, where figures are listed in millions." (FAQ, "Does the Hays Asia
  Salary Guide include total compensation?")
- The same provider-published guide held in this repository,
  [`2026 Hays Asia Salary Guide HK (1).pdf`](../salary_guidlines/2026%20Hays%20Asia%20Salary%20Guide%20HK%20%281%29.pdf),
  p. 20 says that the salary data are local currency `'000` and
  "representative of the total annual package value." The repeated note under
  the Hong Kong salary tables says the same (for example, Audit/Risk/
  Compliance pp. 38–46).
- Hays does **not** define, in either source, which components make up
  "total annual package" (for example, fixed 13th-month/AWS, variable bonus,
  cash allowances, or benefits). The guide therefore proves the semantic
  mismatch but does not provide a conversion factor to base pay.

**Result:** The repository's prior reading of the Hays Hong Kong `'000`
figures as annual base salary is contradicted by the primary source. Hays
contributions must be removed from a strict monthly-base merge, quarantined
as `annual_total_package_hkd`, or used only after a separately evidenced
component conversion.

### PERSOLKELLY Hong Kong Salary Guide 2025 — annual base for the extracted sections

- PERSOL's [official Salary Guides page](https://www.persolhongkong.com/salary-guides)
  lists the 2025 Hong Kong guide. Its issuer-hosted
  [2025 PDF](https://www.datocms-assets.com/133435/1734427316-final_hk-salary-guide-2025_singlepage.pdf)
  explains its methodology at PDF p. 3: senior-recruiter market knowledge plus
  job-placement data in the PERSOLKELLY Hong Kong database.
- The Banking & Financial Services tables used by this project label the data
  **"Range of Annual Base Salary (HKD)"** and state **"Figures are base salary
  (Not inclusive of Benefits & Bonuses)"** (for example PDF pp. 12–17). They
  pair grades with experience: Analyst 0–3, Associate 3–7, VP 7–10,
  Director 10+, and MD 15+.
- The project’s other extracted PERSOLKELLY areas use the same explicit annual
  base label: Corporate Professionals—Finance (PDF p. 20) and Insurance
  (PDF pp. 41–44). The insurance rows use Officer–Senior Analyst 0–4,
  Assistant Manager–Manager 5–9, Senior Manager–Senior Director 10–15,
  and Head 15+.
- The guide is not globally annual: its Commercial Staffing tables are
  explicitly **monthly base** (PDF pp. 51–53), while IT Contracting returns
  to annual base (from PDF p. 54). Those sections are not present in the
  repository's `persolkelly_2025.json`, but this is an important extraction
  rule for future expansion.
- A retail table contains a specific exception marked "Average take home
  (Basic salary + allowance + commission)" (PDF p. 34). It is not a general
  redefinition of the Banking/Finance/Insurance tables and must not be used
  as a base-pay source.

**Result:** The current three PERSOLKELLY JSON sections are accurately
described as annual HKD base salary excluding benefits and bonuses; division
by 12 is a transparent period conversion. The publisher does not state
whether a 13th-month/AWS payment is included in its annual base number.

### Adecco Hong Kong Salary Guide 2026 — monthly salary with explicit exclusions

- The official Adecco [2026 guide PDF](https://image.marketing.info.adecco.com/lib/fe32117175640474731478/m/1/044fa74e-de92-456e-b352-a498fecd27fa.pdf)
  says in "About the salaries in this guide" (PDF p. 16) that figures are
  average salaries from positions Adecco HK recruited for during 2024–2025,
  using data from Hong Kong clients and candidates.
- The same page says: "these salaries exclude overtime payments, commissions,
  allowances, and bonuses." It does not say "total package" or "total
  compensation."
- The salary tables label their figures **"Monthly Salary in HK$"** and show
  a minimum/maximum salary per job. They also supply qualification and, in
  many sections, an experience range (for example Accounting & Finance PDF
  pp. 18–20; Legal and Compliance p. 46; Supply Chain p. 63).
- The relevant repository extraction only uses Accounting & Finance,
  Corporate Support, Customer Service, Information Technology, Legal &
  Compliance, and Marketing—each comes from these monthly-HKD tables.

**Result:** Adecco is direct monthly-HKD evidence with clear exclusions. It
is the closest semantic match, but the evidence supports the wording
"monthly salary excluding overtime, commissions, allowances and bonuses"—not
an unqualified assertion that it is contractual base salary. 13th-month/AWS
treatment remains undisclosed.

## Required handling for the next anchor revision

1. Change the source registry/evidence ledger before changing numbers. Record
   `compensation_basis`, `period`, `currency`, `inclusions_exclusions`,
   `aws_13th_month_treatment`, source PDF and page, native role and experience
   band, and mapping rationale for every imported cell.
2. Mark all Hays-derived values as `annual_total_package_hkd` and exclude
   them from any calculation whose target is monthly base. Do not simply
   relabel or rescale them.
3. Preserve PERSOLKELLY's annual-base semantics and only convert its specific
   annual tables to monthly by `/12`; carry its `+` upper bounds as open-ended
   instead of manufacturing a ceiling.
4. Preserve Adecco as `monthly_salary_excluding_overtime_commission_allowance_bonus`.
   A future provider clarification is needed before promoting its semantic
   label to `monthly_base_salary`.
5. Treat `AWS/13th month: unspecified` as an actual data state for all three
   providers. Do not encode a presumed 12- or 13-payment convention.

## Open questions

- What Hays includes in its total annual package is not defined by its 2026
  guide or HK FAQ. A written clarification from Hays is required for anything
  more precise than `annual_total_package_hkd`.
- Neither PERSOLKELLY nor Adecco documents whether mandatory/contractual
  13th-month pay or AWS is included in the published number.
- Adecco's exclusions strongly indicate a base-like cash salary, but its
  exact definition of "salary" needs confirmation before it can be labeled
  contractual base pay.
