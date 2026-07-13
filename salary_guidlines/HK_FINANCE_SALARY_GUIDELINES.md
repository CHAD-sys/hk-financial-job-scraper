# HK Financial-Sector Salary Guidelines (calibration reference)

**Source:** *2026 Hays Asia Salary Guide — Hong Kong* (19th edition), in this folder.
**Purpose:** ground-truth anchors for our AI salary estimator, which had been
**over-estimating** — especially at senior levels and for control/operations roles.

> ⚠️ **Units.** Every figure in the Hays tables is **annual base salary in HK$'000**
> (per the note "Salary ranges are represented in local currencies in '000").
> Our DB stores **monthly** base, so **monthly ≈ annual ÷ 12**. All the "/mo" figures
> below are already converted. These are **base salary only** — in HK finance total
> comp is ~1.3–3× base at senior levels; we do **not** estimate total comp.

---

## The two mistakes we were making

1. **Senior bands 2–3× too high.** Old prompt priced "MD/C-suite" at
   HK$400k–900k/month (= HK$4.8M–10.8M/yr *base*). Hays shows an M&A Managing
   Director at HK$3M+/yr base ≈ **HK$250k/month**. Every tier above VP was inflated.
2. **No desk/function distinction.** A Compliance VP (~HK$70–100k/mo) was priced
   like an M&A VP (~HK$125–167k/mo). **Most scraped postings are commercial,
   operations, or control roles — the cheaper ladders — not front-office IB.**
   Default to the modest ladder; only apply the front-office uplift when the title
   clearly says so.

---

## Function tiers (who pays what)

- **Front office** — Investment Banking / M&A / Corporate Finance, Private Equity,
  Hedge Funds, Asset Management (portfolio/fund/research/sales), Global Markets /
  Trading, Private Banking RMs. **Highest pay.**
- **Commercial / Retail banking** — Corporate / Commercial / SME / FI Relationship
  Managers, Wealth Managers, branch. **Mid pay.**
- **Middle office** — Risk (credit/market/ops/enterprise), Compliance, Internal Audit.
  **Below front office at the same title.**
- **Back office / Operations** — Treasury/Trade/Payment/Fund/Securities operations,
  KYC/documentation, loan admin, settlements. **Lowest of the professional bands.**
- **Corporate finance & accounting** (in-house FP&A, controllers, finance managers)
  and **Professional services / Big 4** — roughly the middle-office ladder.

HK banks title by rank: **Analyst/Officer → Associate → AVP → VP → SVP/Director → MD/Head**.
Map those to our `seniority` field: Analyst/Officer→`junior`, Associate/AVP→`mid`,
VP/SVP→`senior`, Director/MD/Head→`lead`.

---

## Anchor tables (monthly HK$ base, from Hays 2026 HK)

### Front office
| Desk | Analyst | Associate | VP | Director | MD / Head |
|---|---|---|---|---|---|
| IB / M&A / Corp Finance | 42k–83k | 83k–125k | 125k–167k | 167k–250k | 250k+ |
| Private Equity | 40k–50k | 55k–125k | 100k–150k | 117k–167k | 167k+ |
| Asset Mgmt (fund/PM) | RA 30k–50k | AsstFM 55k–83k | FM 83k–117k | SrFM 167k–250k | CIO 250k+ |
| Global Markets / Trading | JrTrader 35k–55k | Trader 57k–100k | SrTrader 100k–158k | Desk Head 167k+ | — |
| Private Banking (RM) | — | AsstRM 38k–100k | RM 80k–125k | Sr RM 125k–208k | Head 250k+ |

### Commercial / Retail banking (Relationship Management)
| Level | Corporate | Commercial | SME | Retail/Wealth |
|---|---|---|---|---|
| Assistant RM | 21k–33k | 20k–28k | 20k–30k | Wealth 25k–40k |
| RM | 32k–50k | 30k–50k | 25k–45k | Premier 30k–63k |
| Senior RM | 70k–100k | 50k–70k | 45k–60k | — |
| Team / Dept Head | 75k–150k+ | 63k–133k+ | 58k–100k+ | Branch Mgr 60k–100k |

### Middle office — Risk / Compliance / Audit (Banking)
| Level | Credit/Mkt/Ops Risk | Compliance | Internal Audit |
|---|---|---|---|
| Analyst | 20k–40k | 18k–30k | Auditor 29k–38k |
| Associate | 28k–60k | 28k–45k | AVP 38k–54k |
| AVP | 40k–75k | — | Asst Mgr 54k–71k |
| VP | 60k–100k | 70k–100k | Audit Mgr 71k–92k |
| Director / SVP | 90k–150k | — | SVP 92k–108k |
| Head / CxO | CRO 120k–150k+ | CCO 150k+ | Head 108k–133k+ |

### Back office / Operations (Treasury/Trade/Payments/Fund/Securities Ops, KYC)
| Level | Monthly HK$ base |
|---|---|
| Officer / Analyst | 17k–30k |
| Associate | 25k–50k |
| AVP | 38k–70k |
| VP | 50k–83k |
| Director | 67k–88k+ |

### Corporate finance & accounting (in-house)
| Role | Monthly HK$ base |
|---|---|
| Financial Analyst | 28k–38k |
| FP&A Manager | 50k–75k |
| Senior Finance Manager | 40k–80k |
| Financial Controller | 55k–113k |
| FP&A Director | 70k–125k |
| Finance Director / CFO (MNC) | 125k–417k (SME 67k–125k) |

### Insurance (risk / compliance / actuarial-adjacent)
| Level | Monthly HK$ base |
|---|---|
| Executive / Senior Executive | 25k–35k |
| Manager | 60k–70k |
| Senior Manager | 70k–90k |
| Director | 100k–180k |
| Chief Risk Officer | 180k+ |

---

## How to guess a range when nothing is disclosed

1. **Detect the function tier** from the title/description (front / commercial /
   middle / back office / corporate-finance / insurance).
2. **Detect the level** (Analyst/Officer → Associate → AVP → VP → SVP/Director → MD/Head,
   or junior/mid/senior/lead).
3. Read the monthly band from the matching table. **When the tier is ambiguous,
   default to the middle/back-office or commercial ladder, NOT front office** — most
   scraped postings are those, and biasing low corrects our historical overestimate.
4. Apply role-type caps first (internship/part-time/contract — see the prompt's Step 1).
5. A disclosed salary in the description always **overrides** these benchmarks.

### Sector / employer adjustments (vs. the anchors above)
- **Bulge-bracket / Tier-1** (Goldman, JPMorgan, Morgan Stanley, HSBC, BlackRock):
  upper third of the band.
- **Insurance, in-house corporate finance, Big 4 / professional services:** at or
  slightly below the banking anchors (use the middle-office ladder, not front office).
- **Virtual banks / fintech:** roughly the default ladder, ~10–20% below Tier-1.
- **Digital assets / crypto:** wide and volatile — 30k–200k/mo by seniority.

### Confidence
- `high` — salary explicitly stated in the description.
- `medium` — not stated, but function tier + level + employer are all clear.
- `low` — tier or level ambiguous, or context thin (default low + the modest ladder).

---

*Generated for the `hk-job-scraper` enrichment pipeline. When a newer Hays guide is
dropped in this folder, re-derive these anchors and update the prompt's Step 3 bands
in `hk_jobs/enrichers/deepseek.py` to match.*
