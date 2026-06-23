# Data Model & Pipeline Inputs

Machine-generated description of the project's data artifacts (SQLite DB, discovery CSVs, and companies.yaml config) so they are represented in the knowledge graph. Regenerate with scripts, do not hand-edit.

## Database (data/jobs.db)

### Table: company_metrics

65 rows. Columns:

- `id` INTEGER (primary key)
- `company_id` TEXT
- `company_name` TEXT
- `avg_jobs_7d` REAL
- `avg_jobs_30d` REAL
- `growth_rate_7d` REAL
- `growth_rate_30d` REAL
- `current_trend` TEXT
- `last_updated` TIMESTAMP

### Table: job_enrichments

2742 rows. Columns:

- `id` INTEGER (primary key)
- `source` TEXT
- `source_id` TEXT
- `seniority` TEXT
- `years_experience_required` INTEGER
- `required_skills` TEXT
- `remote_type` TEXT
- `salary_hkd_min` INTEGER
- `salary_hkd_max` INTEGER
- `job_category` TEXT
- `enriched_at` TIMESTAMP
- `model_used` TEXT

### Table: job_history

510 rows. Columns:

- `id` INTEGER (primary key)
- `company_id` TEXT
- `company_name` TEXT
- `job_count` INTEGER
- `scraped_date` DATE
- `trend_direction` TEXT
- `trend_percent` REAL
- `jobs_added` INTEGER
- `jobs_removed` INTEGER
- `created_at` TIMESTAMP

### Table: jobs

4827 rows. Columns:

- `source` TEXT (primary key)
- `source_id` TEXT (primary key)
- `company` TEXT
- `company_slug` TEXT
- `url` TEXT
- `dedup_hash` TEXT
- `title` TEXT
- `description_raw` TEXT
- `description_clean` TEXT
- `locations` TEXT
- `remote_type` TEXT
- `department` TEXT
- `seniority` TEXT
- `employment_type` TEXT
- `salary_min` INTEGER
- `salary_max` INTEGER
- `salary_currency` TEXT
- `skills_required` TEXT
- `skills_preferred` TEXT
- `years_experience_min` INTEGER
- `posted_at` TEXT
- `fetched_at` TEXT
- `is_active` INTEGER

### Table: sqlite_sequence

3 rows. Columns:

- `name` 
- `seq` 

### Current contents

- Active jobs: 2742
- Distinct companies with active jobs: 62
- Active jobs with descriptions: 2742
- Active jobs with AI enrichment: 2742
- Inactive jobs kept for history (descriptions cleared, enrichments removed): 2085

## Companies config (hk_jobs/companies.yaml)

78 companies total (65 enabled, 13 disabled). By adapter:

- **eightfold**: 3 companies
- **jobsdb**: 71 companies
- **workday**: 4 companies

### Company list (name → adapter → slug → enabled)

- HSBC Hong Kong → eightfold → `hsbc-hk` → enabled
- Bank of China (Hong Kong) → jobsdb → `bochk` → enabled
- Standard Chartered Bank (HK) → jobsdb → `standard-chartered-hk` → enabled
- Hang Seng Bank → eightfold → `hang-seng-bank` → disabled
- DBS Bank (Hong Kong) → jobsdb → `dbs-hk` → enabled
- Bank of East Asia → jobsdb → `bank-of-east-asia` → enabled
- Citibank Hong Kong → jobsdb → `citibank-hk` → enabled
- ICBC (Asia) → jobsdb → `icbc-asia` → enabled
- China Construction Bank (Asia) → jobsdb → `ccb-asia` → enabled
- OCBC Wing Hang Bank → jobsdb → `ocbc-wing-hang` → enabled
- AIA Hong Kong → workday → `aia-hk` → enabled
- Manulife Hong Kong → jobsdb → `manulife-hk` → enabled
- Prudential Hong Kong → workday → `prudential-hk` → enabled
- AXA Hong Kong → jobsdb → `axa-hk` → enabled
- Zurich Hong Kong → jobsdb → `zurich-hk` → enabled
- FWD Insurance → workday → `fwd-insurance` → enabled
- Sun Life Hong Kong → workday → `sun-life-hk` → enabled
- HSBC Life → eightfold → `hsbc-life` → disabled
- Generali Hong Kong → jobsdb → `generali-hk` → enabled
- China Taiping Insurance → jobsdb → `china-taiping` → enabled
- Value Partners → jobsdb → `value-partners` → enabled
- Fidelity International HK → jobsdb → `fidelity-international-hk` → enabled
- BlackRock Hong Kong → jobsdb → `blackrock-hk` → enabled
- Schroders Hong Kong → jobsdb → `schroders-hk` → enabled
- Amundi Hong Kong → jobsdb → `amundi-hk` → enabled
- Man Group Hong Kong → jobsdb → `man-group-hk` → enabled
- PIMCO Hong Kong → jobsdb → `pimco-hk` → enabled
- J.P. Morgan Asset Management HK → jobsdb → `jpmorgan-am-hk` → enabled
- UBS Asset Management HK → jobsdb → `ubs-am-hk` → enabled
- BNP Paribas Asset Management HK → jobsdb → `bnp-paribas-am-hk` → enabled
- Agricultural Bank of China → jobsdb → `agricultural-bank-china` → enabled
- Bank of Communications → jobsdb → `bank-of-communications` → enabled
- China CITIC Bank → jobsdb → `citic-bank` → enabled
- China Everbright Bank → jobsdb → `everbright-bank` → enabled
- China Merchants Bank → jobsdb → `china-merchants-bank` → enabled
- China Minsheng Bank → jobsdb → `minsheng-bank` → enabled
- Postal Savings Bank of China → jobsdb → `psbc` → enabled
- Mitsubishi UFJ (MUFG) → jobsdb → `mufg` → enabled
- Mizuho Financial Group → jobsdb → `mizuho` → enabled
- SMBC Group → jobsdb → `smbc` → enabled
- ANZ Group → jobsdb → `anz` → enabled
- UOB → jobsdb → `uob` → enabled
- Maybank → jobsdb → `maybank` → enabled
- Hana Financial Group → jobsdb → `hana-financial` → enabled
- State Bank of India → jobsdb → `sbi` → enabled
- Bank of America → jobsdb → `bank-of-america` → enabled
- Deutsche Bank → jobsdb → `deutsche-bank` → enabled
- Goldman Sachs → jobsdb → `goldman-sachs` → enabled
- JPMorgan Chase → jobsdb → `jpmorgan-chase` → enabled
- Morgan Stanley → jobsdb → `morgan-stanley` → enabled
- Barclays → jobsdb → `barclays` → enabled
- China Life Insurance → jobsdb → `china-life` → enabled
- China Pacific Insurance → jobsdb → `china-pacific-insurance` → enabled
- Ping An Insurance → jobsdb → `ping-an` → enabled
- Chubb → jobsdb → `chubb` → enabled
- Allianz → jobsdb → `allianz` → enabled
- Swiss Re → jobsdb → `swiss-re` → enabled
- Samsung Life Insurance → jobsdb → `samsung-life` → enabled
- Dai-ichi Life Insurance → jobsdb → `dai-ichi-life` → enabled
- MetLife → jobsdb → `metlife` → enabled
- Nippon Life Insurance → jobsdb → `nippon-life` → enabled
- Macquarie Group → jobsdb → `macquarie` → enabled
- State Street Global Advisors → jobsdb → `state-street` → enabled
- Invesco → jobsdb → `invesco` → enabled
- Northern Trust → jobsdb → `northern-trust` → enabled
- Franklin Templeton → jobsdb → `franklin-templeton` → enabled
- KKR → jobsdb → `kkr` → enabled
- Apollo Global Management → jobsdb → `apollo` → disabled
- Brookfield Asset Management → jobsdb → `brookfield` → disabled
- Carlyle Group → jobsdb → `carlyle` → disabled
- GIC Private Limited → jobsdb → `gic` → disabled
- KB Financial Group → jobsdb → `kb-financial` → disabled
- Munich Re → jobsdb → `munich-re` → disabled
- Shinhan Financial Group → jobsdb → `shinhan` → disabled
- Societe Generale → jobsdb → `societe-generale` → disabled
- T. Rowe Price → jobsdb → `t-rowe-price` → disabled
- Temasek Holdings → jobsdb → `temasek` → disabled
- Tokio Marine Holdings → jobsdb → `tokio-marine` → disabled

## Discovery inputs/outputs (scripts/*.csv)

### Master list (companies_master_list.csv)

133 candidate institutions, 72 marked STRONG.

### Discovery results (discovered_companies.csv)

52 probed, 41 reachable. Reachable companies:

- Agricultural Bank of China → jobsdb → `Agricultural-Bank-of-China` (30 jobs)
- Bank of America → jobsdb → `Bank-of-America` (30 jobs)
- Bank of Communications → jobsdb → `Bank-of-Communications` (30 jobs)
- China CITIC Bank → jobsdb → `China-CITIC-Bank` (30 jobs)
- China Everbright Bank → jobsdb → `China-Everbright-Bank` (30 jobs)
- China Life Insurance → jobsdb → `China-Life-Insurance` (30 jobs)
- China Merchants Bank → jobsdb → `China-Merchants-Bank` (30 jobs)
- China Minsheng Bank → jobsdb → `China-Minsheng-Bank` (30 jobs)
- Chubb → jobsdb → `Chubb` (30 jobs)
- Citigroup → jobsdb → `Citigroup` (30 jobs)
- Deutsche Bank → jobsdb → `Deutsche-Bank` (30 jobs)
- Goldman Sachs → jobsdb → `Goldman-Sachs` (30 jobs)
- Industrial and Commercial Bank of China → jobsdb → `Industrial-and-Commercial-Bank-of-China` (30 jobs)
- JPMorgan Chase → jobsdb → `JPMorgan-Chase` (30 jobs)
- Macquarie Group → jobsdb → `Macquarie-Group` (30 jobs)
- OCBC Bank → jobsdb → `ocbc-bank` (30 jobs)
- Standard Chartered → jobsdb → `Standard-Chartered` (30 jobs)
- UOB → jobsdb → `UOB` (30 jobs)
- Morgan Stanley → jobsdb → `Morgan-Stanley` (27 jobs)
- Mitsubishi UFJ Financial Group → jobsdb → `Mitsubishi-UFJ-Financial-Group` (26 jobs)
- China Pacific Insurance → jobsdb → `China-Pacific-Insurance` (13 jobs)
- Mizuho Financial Group → jobsdb → `Mizuho-Financial-Group` (13 jobs)
- Ping An Insurance → jobsdb → `Ping-An-Insurance` (12 jobs)
- State Street Global Advisors → jobsdb → `State-Street-Global-Advisors` (9 jobs)
- ANZ Group → jobsdb → `ANZ-Group` (8 jobs)
- Invesco → jobsdb → `Invesco` (8 jobs)
- Postal Savings Bank of China → jobsdb → `Postal-Savings-Bank-of-China` (7 jobs)
- Allianz → jobsdb → `Allianz` (5 jobs)
- Swiss Re → jobsdb → `Swiss-Re` (5 jobs)
- Northern Trust → jobsdb → `Northern-Trust` (3 jobs)
- SMBC Group → jobsdb → `SMBC-Group` (3 jobs)
- Samsung Life Insurance → jobsdb → `Samsung-Life-Insurance` (3 jobs)
- Hana Financial Group → jobsdb → `Hana-Financial-Group` (2 jobs)
- Maybank → jobsdb → `Maybank` (2 jobs)
- Barclays → jobsdb → `Barclays` (1 jobs)
- Dai-ichi Life Insurance → jobsdb → `Dai-ichi-Life-Insurance` (1 jobs)
- Franklin Templeton → jobsdb → `Franklin-Templeton` (1 jobs)
- KKR → jobsdb → `KKR` (1 jobs)
- MetLife → jobsdb → `MetLife` (1 jobs)
- Nippon Life Insurance → jobsdb → `Nippon-Life-Insurance` (1 jobs)
- State Bank of India → jobsdb → `State-Bank-of-India` (1 jobs)
