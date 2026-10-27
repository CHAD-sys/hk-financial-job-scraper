# Salary anchor expansion and blinded listing audit — 27 October 2026

## Decision

The landing page now promotes a Role only when its monthly salary starts at HK$60,000 or above and its displayed range is at most HK$35,000 **and** 40% of its lower endpoint. HK$110,000–200,000 fails both width checks. Estimated pay also needs a medium or high confidence exact tier/role/grade match to a cell with compatible base-pay provenance; a complete employer-disclosed range can qualify on its own. Annual disclosed figures are normalized to monthly before the rule runs. This is an internal selection rule, not an uncertainty message in the UI. It is deliberately conservative and can leave fewer Roles in the rail.

## Anchor table and provenance

The merged table grew from **729 to 1,015 tier × role × grade cells** across **191 roles and seven tiers**. The new 286 cells come from 87 distinct finite role rows in [Randstad's 2025 Hong Kong Job Market Outlook and Salary Guide](https://www.randstad.com.hk/s3fs-media/hk/public/2025-01/Randstad-Hong-Kong-SAR-2025-Job-Market-Outlook-Salary-Guide.pdf?VersionId=Nbc9a4xsKw0jkw6VdMPz4ygnUr6zj93H), principally finance and insurance. Its figures are HKD **monthly basic salary**, excluding annual wage supplement and bonuses. The import excludes open-ended guide ranges and rows whose grade cannot be mapped without inventing a split. Each added cell has a source page and source row in `salary_guidlines/hk_salary_anchor_provenance.json`.

The new cells are role specific rather than a mechanical subdivision. For example, debt capital markets, M&A advisory, and IPO execution now have distinct front-office rows and guide values. The prior blended corporate-finance/M&A/ECM/DCM row remains as a fallback, but the retrieval layer removes it when a title explicitly names one of the more specific functions. We also fixed retrieval collisions in life-insurance distribution, credit research, and private-trust business development; generic words such as “development” no longer count as strong role evidence by themselves.

**Review of the full table:** 214 of 1,015 cells still span more than HK$35,000; 61 span at least 2× from lower to upper bound. Five have an upper endpoint over HK$200,000 and 38 end at HK$200,000. Examples requiring source-level reconsideration include front-office Assistant Private Banker/Director (HK$80,000–200,000), retail-banking Branch Operations/Operations Manager (HK$34,500–171,500; Hays package proxy), and back-office Fund Operations/MD (HK$62,500–200,000). These are **not** silently compressed: narrower endpoints without new pay evidence would be fabricated. The landing rule excludes them where relevant. The provenance sidecar also records legacy interpolations and package proxies so future source replacement can target them.

## Frozen blinded listing check

The [cohort](salary_blinded_holdout_2026-10-27.jsonl) contains 41 explicitly priced listings extracted from a read-only live-board snapshot: 37 recruiter-published LinkedIn posts and four JobsDB listings. They span five model tiers and three disclosed-pay segments. Posted dates include July 2026; “fresh” here means newly assembled and scored against the current model after the August audit, **not** all postings dated October. Annual salaries were divided by 12 from the source statement. Salary lines were removed from the title/description shown to the estimator; the frozen source pay was revealed only at scoring. The current two-pass estimator and final table lookup were used, with the existing administrator correction snapshot. The complete [predictions](salary_blinded_holdout_results_2026-10-27.jsonl) and [machine-readable metrics](salary_blinded_holdout_metrics_2026-10-27.json) are saved alongside this report. Approximate DeepSeek spend for 41 cases was **US$0.03**; this excludes prior development time and sourcing work.

“Coverage” means a priced prediction. Signed error is predicted midpoint minus disclosed midpoint; width is predicted maximum minus minimum. Error and width are averages over covered cases. All amounts below are **HKD per month**.

| Segment | Cases | Coverage | Mean signed error | Midpoint MAE | Mean width |
|---|---:|---:|---:|---:|---:|
| All | 41 | 39/41 (95%) | +483 | 8,671 | 23,962 |
| Below 40k disclosed midpoint | 11 | 10/11 (91%) | +2,383 | 6,767 | 14,050 |
| 40k–80k | 27 | 26/27 (96%) | −1,035 | 8,631 | 26,250 |
| 80k+ | 3 | 3/3 (100%) | +7,306 | 15,361 | 37,167 |
| Back-office operations | 8 | 8/8 (100%) | +1,073 | 6,177 | 22,000 |
| Corporate finance/accounting | 2 | 2/2 (100%) | −11,042 | 11,042 | 30,000 |
| Front office | 3 | 3/3 (100%) | −12,083 | 12,083 | 26,500 |
| Insurance | 13 | 13/13 (100%) | +3,545 | 12,199 | 19,038 |
| Middle office | 14 | 13/14 (93%) | +1,731 | 5,526 | 28,577 |
| JobsDB | 4 | 3/4 (75%) | −2,083 | 6,417 | 8,167 |
| Recruiter posts | 37 | 36/37 (97%) | +697 | 8,859 | 25,278 |

The low overall signed error reflects offsetting positive and negative errors; the **HK$8,671 MAE** is the more useful summary of per-listing disagreement. Only **67% of the disclosed midpoints** fall within estimated ranges across the 39 covered cases. Insurance is the clearest weakness: only **4 of 13** disclosed midpoints fall inside its predicted range despite full coverage. The high-pay segment has just three cases, so its favorable coverage cannot establish high-pay accuracy. The cohort is purposefully stratified, not a random sample from all board Roles; these rates must not be presented as production-wide accuracy.

The [August audit](../SALARY_ESTIMATOR_AUDIT.html) compared the then-current estimator to Sonnet's opinion on the same listings: more than 25% disagreement on about a third of listings and non-overlapping ranges on 32%. Those figures are **not directly comparable** to this run's error against disclosed pay, and the model and cohort both changed. Both checks nevertheless expose the same failure mode: aggregate bias can look small while a particular Role is materially wrong. The present blinded test adds source-stated pay evidence, but does not yet replace a verified independent-truth audit.

### What this check can and cannot establish

The pay statements are independent of the estimator, and the model did not see them. However, 37 statements are **recruiter-published, not independently reviewed by a senior recruiter**; the four JobsDB listings also need employer/source attribution verified outside the board. No external expert panel has validated the figures or role equivalence. The source mix, small front-office/high-pay cells, and older posting dates therefore **do not satisfy the requested independent-truth certification**. This run is a reproducible pilot that exposes model errors. A certification-quality next cohort needs newly published employer-disclosed pay or recruiter evidence individually checked by a Hong Kong finance compensation specialist, with quotas per tier, source, grade and high-pay segment fixed before scoring.

## Remaining salary work

1. Audit the 214 wide legacy cells against direct basic-pay sources, starting with the three examples above and the 99 Hays package-proxy cells. Replace or retire cells whose pay basis cannot be reconciled; do not reduce widths solely to make the landing rail look stronger.
2. Investigate insurance misses at listing level, especially agency distribution versus insurer operations and channel-specific titles. Re-run the blinded cohort after any targeted correction, retaining the original results for comparison.
3. Expand the independent validation set with verified employer-disclosed or expert-reviewed recruiter figures in front office and HK$80k+ roles. Publish the same coverage, signed error and width breakdown, plus sample counts, so small segments remain visible.

No salary accuracy percentage or uncertainty claim is added to the public interface from this pilot.
