# Hays 2026: Hong Kong product-management evidence

## Question and scope

The next high-volume market gap is
`middle_office / product_management`.  The published generic table presently
has an especially unsafe `Manager` interval (HK$43,000--171,500 per month),
and is used at the role level by 92 active primary Listings.  It contains a
mixture of bank product, digital-product, product-owner, product-specialist,
cash-product and asset-management titles; those are not automatically the same
labour market.

This note reviews the local primary source,
[`2026 Hays Asia Salary Guide HK (1).pdf`](../../salary_guidlines/2026%20Hays%20Asia%20Salary%20Guide%20HK%20%281%29.pdf),
for Hong Kong data.  It deliberately does **not** convert all Hays packages
with a universal divisor: a period conversion and a base-pay assumption are
different operations.

## Direct Hays banking table: Product Management

Hays has a Hong Kong table named exactly `Banking & Financial Services ->
Banking/Middle Office -> Product Management` (PDF p. 67).  The native figures
and the experience column are:

| Hays role | Experience | HK annual total package, HKD '000 | Monthly package equivalent (`annual / 12`) |
| --- | ---: | ---: | ---: |
| Analyst | 6--7 years | 260--360 | 21.7--30.0k |
| Associate | 8--10 years | 360--600+ | 30.0--50.0k+ |
| Manager | 10--18 years | 600+ | 50.0k+ |

This is direct evidence for the current generic banking product-management
coordinate.  It explains the current table's weak upper bounds: Hays gives no
upper bound for Manager and makes the Associate upper bound open-ended.  The
published `Manager` maximum of 171.5k is a **local cap**, not a Hays result.

It does not establish the pay of Product Owner, Cash Product Manager, Product
Specialist, Digital Banking Product Manager or Retail Banking Product Manager;
the source labels neither the product domain nor any of those title variants.
It therefore supports the grade direction and a package floor, not a precise
base-pay band for every ambiguous posting.

## Adjacent Hays evidence and its boundary

| Hays table (PDF page) | HK role(s) | Native annual total package, HKD '000 | What it can and cannot support |
| --- | --- | ---: | --- |
| `Banking/Middle Office -> Asset Management` (p. 64) | Product Manager / Senior Product Manager | 600--780 / 780--960 | Direct only for **asset/investment-management** product; a valuable closed-range comparator, but a distinct named sub-market from p. 67's banking Product Management table. |
| `Banking/Front Office -> Transaction Banking (Cash Management, Trade Finance, Project & Export Finance)` (p. 61) | Assistant RM / RM / Senior RM / Team Head / Department Head | 300--480 / 480--720 / 720--1,000 / 1,000--1,700 / 1,600+ | Direct for **transaction-banking relationship-management**, not for Cash Product Manager or Product Owner.  It is relevant only where a role is actually RM/sales coverage. |
| `Banking/Retail -> Insurance and Investment` (p. 80) | Specialist / Senior Specialist / Team Head / Region Head | 300--420 / 420--660 / 660--1,080 / 660--1,080 | This is an insurance-and-investment distribution table, not a `Product Specialist` table.  It can be considered only when the description proves that meaning. |
| `Insurance -> Product Development` (p. 127) | Assistant Manager / Product Manager / Senior Manager / Director or Head of Products | 240--480 / 540--900 / 840--1,200 / 1,200+ | Direct future evidence for the separate **insurance product-development** role; it must not be used to price a bank product posting. |
| `Technology -> Projects & Change -> Analysis & Project` (p. 199) | Product Manager | 500--700 | A relevant functional comparator for a title that is demonstrably a technology Product Manager or Product Owner, but it is all-industry Technology data, not finance-sector evidence. |

For transparency, the corresponding monthly **package** equivalents are:

- Banking/Middle Office Product Management: 21.7--30.0k (Analyst),
  30.0--50.0k+ (Associate), and 50.0k+ (Manager).
- Asset-Management Product Management: 50.0--65.0k (Product Manager) and
  65.0--80.0k (Senior Product Manager).
- Transaction-banking RM ladder: 25--40k, 40--60k, 60--83.3k,
  83.3--141.7k, and 133.3k+.
- Retail insurance/investment Specialist ladder: 25--35k, 35--55k, 55--90k,
  and 55--90k.
- Insurance Product Development: 20--40k, 45--75k, 70--100k, and 100k+.
- Technology Product Manager: 41.7--58.3k.

Hays also explicitly says in its Banking & Financial Services outlook (PDF
p. 53) that digital banking and retail Product Managers are generating hiring
opportunities.  That is demand commentary, **not** a compensation row, and
should never be transformed into an anchor value.

## Missing titles and grades

Hays has **no Hong Kong compensation row** for any of the following in the
Banking & Financial Services salary tables:

- Product Owner;
- Cash Product Manager;
- Product Specialist;
- Digital Banking Product Manager;
- Retail Banking Product Manager;
- Assistant Manager, AVP, VP, Director or Head specifically for bank product
  management;
- a Senior Product Manager outside the separate Asset Management table.

There is likewise no cash-product salary row.  The Transaction Banking table
is useful evidence only after title classification establishes that the role is
a Relationship Manager; it cannot be relabelled as a Cash Product Manager.

The guide does contain product-related rows in Insurance and Technology, as
listed above, but they do not fill those missing banking grades or functions.

## Compensation basis: how to use the numbers safely

Every cited Hays table has the same footer: salary ranges are in local
currencies in '000 (Japan excepted) and are “representative of the **total
annual package value**.”  The exact `annual / 12` numbers above are therefore
monthly **total-package** equivalents.  They are not monthly base salary.

This yields a useful rule for the implementation review:

1. `/12` is only a transparent period conversion for an annual package.
2. `/13` or `/14` would be an **assumption** that uses the annual package as a
   proxy for a 13- or 14-payment fixed-salary structure.  Hays does not supply
   the bonus, allowance, benefit or guaranteed-month breakdown needed to make
   that assumption generally.
3. Accordingly, Hays can supply service-line-specific sanity envelopes and
   plausibility checks.  A closed monthly-base anchor needs either verified
   disclosed base pay or a separate base-salary source; it should record that
   evidence instead of claiming direct Hays provenance.

The repository's machine-readable
[`hays_2026.json`](../../salary_guidlines/hays_2026.json) currently represents
the p. 64 Asset Management figures as 50--65k and 65--80k, while its metadata
calls the whole file “monthly BASE salary.”  For these Hays-origin rows that
metadata is inaccurate: the PDF establishes **total package** only.  The
published anchor's provenance must retain the distinction.

## Implication for the product-management repair

Hays confirms the current generic Product Management ladder's source and
explains why it is unreliable at the top: the raw Hays Manager value is simply
`600+` annual total package.  Dividing that raw open-ended figure by 14 and
then applying a global cap is what creates an apparent HK$43--171.5k monthly
range.  The apparent maximum must not be described as market evidence.

The guide is enough to distinguish at least four contexts: generic banking
product management, asset-management product, insurance product development,
and technology product.  It is not enough to set base-salary bands for the
high-volume bank-specific gaps (cash products, digital banking, Product
Owner/Specialist, or the missing bank grade ladder).  Those cells require
independently verified base/disclosed evidence before any new salary values are
committed.

## Source locations and reproduction

- PDF p. 53: Banking & Financial Services outlook, digital/retail Product
  Manager hiring commentary.
- PDF p. 61: Transaction Banking (Cash Management, Trade Finance, Project &
  Export Finance) table.
- PDF p. 64: Banking/Middle Office, Asset Management table.
- PDF p. 67: Banking/Middle Office, Product Management table.
- PDF p. 80: Banking/Retail, Insurance and Investment table.
- PDF p. 127: Insurance, Product Development table.
- PDF p. 199: Technology, Projects & Change, Analysis & Project table.

The rows and their Hong Kong SAR columns were visually checked against those
PDF pages.  The Hays PDF, rather than the legacy JSON extraction, is the source
of record for the compensation-basis statement and native annual values.
