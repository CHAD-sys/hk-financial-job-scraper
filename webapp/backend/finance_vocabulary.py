"""The finance vocabulary a Hong Kong CV and a HK job posting are read against.

Two layers, and both are load-bearing:

**Handwritten** (this file). What a CANDIDATE writes about themselves. Curated
by hand because no corpus can supply it: a posting asks for "quantitative
analysis", while the person who can do it writes "Quantitative Strategist",
"alpha research", "stat arb", "q/kdb". The board can only ever teach us the
demand side's words. Aliases are the whole point — `statistical arbitrage` and
`stat arb` are one skill, and a CV picks whichever it likes.

**Mined** (`vocabulary_mined.json`, built by `scripts/mine_vocabulary.py` from
`job_enrichments.required_skills`). What EMPLOYERS ask for, in their own words,
with the document frequency each term carries. That frequency is what makes
scoring honest: `stakeholder management` appears in 18.2% of postings and
`statistical arbitrage` in 0.02%, so matching the second says something and
matching the first says almost nothing. See `resume_intelligence.score_resume_fit`.

Why this module exists at all: a Morgan Stanley VP with four years as a
Quantitative Strategist — statistical arbitrage, alpha research, market-making,
portfolio optimisation, Sharpe above 2, q/kdb — was read as
`skills: [data analysis, liquidity management, java, machine learning, python,
risk management]` and `role_families: [consulting, data, risk, trading]`. Not
one quant token, because there was no quant vocabulary to find them with. The
old list had `matlab`, `sas`, `vba` and `tableau` but not one of kdb,
arbitrage, market-making, backtesting or alpha research.

CONVENTIONS
  * Every key and every alias is lowercase. Matching is case-folded upstream.
  * The key is the canonical display term; aliases are what a CV might say.
  * A key is itself an implicit alias — do not repeat it in the tuple.
  * Prefer specific over generic. `equity derivatives` earns its place;
    `finance` does not.
  * British and American spellings are BOTH listed. A HK CV mixes them freely
    ("optimisation" / "optimization", "modelling" / "modeling").
  * NEVER add an alias shorter than 3 characters unless it is a genuine,
    unambiguous industry acronym (`fx`, `ib`, `pe`, `vc`, `ml`). Short aliases
    are matched with word boundaries upstream, but a 2-letter alias still
    collides far too easily.
  * NEVER add an alias that is a common English word in a non-finance sense.
    `training` was matching "strength training" from a hobbies line, and
    `english` was matching a Languages line — both scored real points.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

#: Terms a CV uses that generic English also uses. These are matched ONLY as
#: whole phrases and never contribute rarity weight, because they carry no
#: discriminating information: everyone writes them.
STOP_SKILLS: frozenset[str] = frozenset({
    "english", "cantonese", "mandarin", "putonghua", "chinese", "bilingual",
    "training", "leadership", "teamwork", "communication", "communications",
    "interpersonal skills", "problem solving", "time management", "access",
    "presentation", "presentation skills", "organisation", "organization",
    "detail oriented", "attention to detail", "multitasking", "microsoft office",
    "ms office", "word", "powerpoint", "outlook", "email", "writing",
    "written communication", "verbal communication", "collaboration",
    "adaptability", "self motivated", "team player", "fast paced",
    "analytical skills", "critical thinking", "research", "reporting",
    "documentation", "administration", "coordination", "planning", "mathematics",
})


# ── Quantitative finance ─────────────────────────────────────────────────────
# The gap this whole module was written to close.
QUANT: dict[str, tuple[str, ...]] = {
    "alpha research": ("alpha generation", "alpha signal", "alpha signals",
                       "signal research", "signal discovery", "alpha modelling",
                       "alpha modeling", "alpha capture"),
    "statistical arbitrage": ("stat arb", "statarb", "statistical arb",
                              "pairs trading", "relative value arbitrage",
                              "mean reversion strategy"),
    "systematic trading": ("systematic strategies", "systematic strategy",
                           "rules based trading", "quantitative trading",
                           "quant trading", "systematic investing"),
    "electronic market making": ("market making", "market-making", "market maker",
                                 "automated market making", "liquidity provision",
                                 "quoting strategy", "two way pricing"),
    "portfolio optimisation": ("portfolio optimization", "mean variance optimisation",
                               "mean variance optimization", "portfolio construction",
                               "efficient frontier", "risk parity",
                               "black litterman"),
    "backtesting": ("backtest", "backtested", "back-testing", "backtesting framework",
                    "strategy backtesting", "walk forward analysis",
                    "out of sample testing"),
    "algorithmic trading": ("algo trading", "trading algorithms", "execution algorithms",
                            "execution algos", "algo execution", "smart order routing",
                            "sor", "vwap strategy", "twap strategy",
                            "implementation shortfall"),
    "high frequency trading": ("hft", "low latency trading", "ultra low latency",
                               "tick to trade", "colocation", "co-location"),
    "transaction cost analysis": ("tca", "market impact model", "market impact",
                                  "slippage analysis", "execution quality",
                                  "markout", "markouts", "intraday markouts"),
    "quantitative research": ("quant research", "quantitative analysis",
                              "quantitative analytics", "quantitative modelling",
                              "quantitative modeling", "quantitative models",
                              "quant modelling", "quant modeling"),
    "derivatives pricing": ("option pricing", "options pricing", "exotic pricing",
                            "pricing models", "black scholes", "black-scholes",
                            "binomial model", "local volatility", "stochastic volatility",
                            "heston model", "sabr model"),
    "volatility modelling": ("volatility modeling", "volatility surface",
                             "implied volatility", "vol surface", "garch",
                             "realised volatility", "realized volatility",
                             "variance swap", "volatility arbitrage"),
    "stochastic calculus": ("ito calculus", "stochastic processes",
                            "brownian motion", "stochastic differential equations",
                            "sde"),
    "monte carlo simulation": ("monte carlo", "monte-carlo", "path simulation",
                               "quasi monte carlo"),
    "numerical methods": ("finite difference", "finite element", "pde solver",
                          "numerical analysis", "numerical optimisation",
                          "numerical optimization", "convex optimisation",
                          "convex optimization", "linear programming",
                          "quadratic programming"),
    "time series analysis": ("time-series analysis", "time series modelling",
                             "time series modeling", "arima", "kalman filter",
                             "cointegration", "autocorrelation", "stationarity"),
    "statistical modelling": ("statistical modeling", "statistical analysis",
                              "regression analysis", "linear regression",
                              "logistic regression", "bayesian statistics",
                              "bayesian inference", "hypothesis testing",
                              "multivariate analysis", "econometrics"),
    "factor modelling": ("factor modeling", "factor models", "risk factor model",
                         "multi factor model", "barra", "axioma", "factor exposure"),
    "market microstructure": ("microstructure", "order book dynamics",
                              "limit order book", "order flow", "order flow analysis",
                              "adverse selection", "toxicity model",
                              "counterparty toxicity", "flow toxicity"),
    "sharpe ratio": ("information ratio", "sortino ratio", "risk adjusted return",
                     "risk adjusted returns", "drawdown analysis", "maximum drawdown"),
    "delta hedging": ("dynamic hedging", "gamma hedging", "greeks", "option greeks",
                      "vega", "theta", "delta one", "delta-one"),
    "inventory management": ("inventory risk", "position management",
                             "overnight inventory", "book management",
                             "central risk book", "principal risk book",
                             "internalisation", "internalization"),
    "signal processing": ("feature extraction", "feature engineering",
                          "signal extraction", "denoising", "filtering"),
    "alternative data": ("alt data", "satellite data", "web scraped data",
                         "sentiment data", "esg data"),
    "portfolio analytics": ("performance attribution", "return attribution",
                            "risk attribution", "pnl attribution",
                            "p&l attribution", "pnl explain"),
}

# ── Trading, markets and asset classes ───────────────────────────────────────
MARKETS: dict[str, tuple[str, ...]] = {
    "equities": ("equity", "cash equities", "equity trading", "stocks",
                 "equity markets", "single stock"),
    "equity derivatives": ("equity options", "equity swaps", "convertible bonds",
                           "structured equity", "warrants", "cbbc",
                           "callable bull bear contracts", "total return swap"),
    "fixed income": ("bonds", "bond trading", "credit trading", "rates trading",
                     "government bonds", "corporate bonds", "sovereign debt",
                     "fixed income trading", "dcm secondary"),
    "interest rate derivatives": ("interest rate swaps", "irs", "swaptions",
                                  "rates derivatives", "cross currency swaps",
                                  "fra", "forward rate agreement", "ois",
                                  "yield curve", "duration", "convexity", "dv01"),
    "credit derivatives": ("cds", "credit default swap", "credit default swaps",
                           "cdx", "itraxx", "structured credit", "clo", "cdo"),
    "foreign exchange": ("fx", "fx trading", "currency trading", "spot fx",
                         "fx forwards", "fx options", "fx swaps", "efx",
                         "electronic fx", "ndf", "non deliverable forward",
                         "currency markets"),
    "commodities": ("commodity trading", "precious metals", "base metals",
                    "energy trading", "oil trading", "gold trading",
                    "commodity derivatives"),
    "futures": ("futures trading", "listed derivatives", "exchange traded derivatives",
                "index futures", "etd"),
    "etf": ("exchange traded fund", "exchange traded funds", "etfs",
            "creation redemption", "etf market making", "authorised participant"),
    "prime brokerage": ("prime services", "securities lending", "stock borrow loan",
                        "sbl", "margin financing", "synthetic prime",
                        "client financing"),
    "structured products": ("structured notes", "accumulators", "decumulators",
                            "autocallable", "autocallables", "elns",
                            "equity linked notes", "principal protected notes"),
    "money markets": ("repo", "reverse repo", "repurchase agreement",
                      "commercial paper", "certificates of deposit",
                      "short term funding"),
    "digital assets": ("cryptocurrency", "crypto", "crypto trading", "digital asset",
                       "virtual assets", "stablecoin", "tokenisation",
                       "tokenization", "defi", "blockchain", "distributed ledger",
                       "web3", "custody of digital assets"),
    "block trading": ("high touch", "high-touch", "low touch", "low-touch",
                      "program trading", "portfolio trading", "facilitation",
                      "risk pricing", "closing auction", "auction participation"),
    "sales trading": ("sales trader", "client flow", "flow trading",
                      "institutional sales", "cash sales"),
}

# ── Risk ─────────────────────────────────────────────────────────────────────
RISK: dict[str, tuple[str, ...]] = {
    "market risk": ("var", "value at risk", "expected shortfall", "stress testing",
                    "scenario analysis", "sensitivity analysis", "greeks risk",
                    "risk limits", "limit monitoring", "frtb",
                    "fundamental review of the trading book"),
    "credit risk": ("counterparty credit risk", "ccr", "pd", "lgd", "ead",
                    "probability of default", "loss given default", "credit modelling",
                    "credit modeling", "credit scoring", "credit rating",
                    "obligor risk", "wrong way risk"),
    "xva": ("cva", "dva", "fva", "kva", "mva", "credit valuation adjustment",
            "funding valuation adjustment", "pfe", "potential future exposure",
            "simm", "initial margin"),
    "liquidity risk": ("lcr", "nsfr", "liquidity coverage ratio",
                       "net stable funding ratio", "liquidity stress testing",
                       "funding liquidity", "contingency funding plan"),
    "operational risk": ("op risk", "operational resilience", "risk and control",
                         "rcsa", "risk control self assessment", "incident management",
                         "loss event", "key risk indicators", "kri"),
    "model risk": ("model validation", "model governance", "model risk management",
                   "sr 11-7", "model documentation", "independent validation"),
    "enterprise risk management": ("erm", "risk appetite", "risk framework",
                                   "risk governance", "three lines of defence",
                                   "three lines of defense", "icaap", "ilaap"),
    "basel iii": ("basel 3", "basel ii", "basel iv", "basel framework"),
    "regulatory capital": ("rwa", "risk weighted assets", "capital adequacy",
                           "capital planning", "leverage ratio", "capital ratio",
                           "tlac", "capital management"),
    "interest rate risk": ("irrbb", "interest rate risk in the banking book",
                           "repricing gap", "basis risk", "eve sensitivity"),
    "climate risk": ("climate stress testing", "transition risk", "physical risk",
                     "tcfd", "climate scenario analysis"),
    "independent price verification": ("ipv", "price testing", "valuation control",
                                       "product control", "fair value hierarchy",
                                       "prudent valuation"),
}

# ── Programming, data and platform ───────────────────────────────────────────
TECHNOLOGY: dict[str, tuple[str, ...]] = {
    # Languages. Each is its own canonical term, never folded into a family:
    # a posting asks for "Docker" or "kdb+" by name, and a Seeker reviewing
    # what we read off their CV expects to see the tool they actually use.
    "python": ("python3", "cpython"),
    "q/kdb": ("kdb", "kdb+", "kdb q", "kx", "kx systems", "q language"),
    "c++": ("c/c++", "cpp", "modern c++", "c++17", "c++20"),
    "java": ("java 8", "java11", "jvm", "core java"),
    "c#": ("csharp", ".net", "dotnet"),
    "rust": (),
    "go": ("golang",),
    "scala": (),
    "r": ("r language", "rstudio"),
    "matlab": (),
    "sql": ("t-sql", "pl/sql", "ansi sql"),
    "vba": ("excel vba", "visual basic for applications"),
    "shell scripting": ("bash", "shell scripting", "ksh", "powershell", "zsh"),
    "perl": (),
    "julia": (),
    # Scientific and data libraries.
    "pandas": ("dataframes",),
    "numpy": ("scipy",),
    "polars": (),
    "scikit-learn": ("scikit learn", "sklearn"),
    "pytorch": ("torch",),
    "tensorflow": ("keras",),
    # Concepts.
    "machine learning": ("ml", "supervised learning", "unsupervised learning",
                         "deep learning", "neural networks", "gradient boosting",
                         "xgboost", "lightgbm", "random forest",
                         "reinforcement learning", "model training",
                         "feature selection", "cross validation"),
    "natural language processing": ("nlp", "text mining", "named entity recognition",
                                    "sentiment analysis", "topic modelling",
                                    "topic modeling", "transformers",
                                    "large language models", "llm", "llms"),
    "generative ai": ("gen ai", "genai", "prompt engineering", "rag",
                      "retrieval augmented generation", "retrieval-augmented generation",
                      "ai assisted", "copilot", "openai", "chatgpt"),
    "computer vision": ("image recognition", "object detection", "ocr"),
    # Data platform.
    "data engineering": ("etl", "elt", "data pipelines", "data pipeline",
                         "data modelling", "data modeling", "data quality"),
    "data warehousing": ("data warehouse", "data lake", "lakehouse",
                         "dimensional modelling", "star schema"),
    "airflow": ("apache airflow", "dagster", "prefect", "luigi"),
    "dbt": (),
    "kafka": ("apache kafka", "event streaming", "pub sub", "pubsub"),
    "spark": ("pyspark", "apache spark", "hadoop", "mapreduce", "hive"),
    "snowflake": (),
    "databricks": (),
    # Databases, individually nameable.
    "postgresql": ("postgres",),
    "mysql": ("mariadb",),
    "oracle database": ("oracle db", "pl sql"),
    "sql server": ("mssql", "microsoft sql server"),
    "mongodb": ("mongo",),
    "redis": (),
    "cassandra": (),
    "elasticsearch": ("opensearch",),
    "clickhouse": (),
    "dynamodb": (),
    "sybase": (),
    "time series database": ("timeseries database", "influxdb", "timescaledb"),
    # Cloud.
    "aws": ("amazon web services", "s3", "ec2", "lambda", "redshift"),
    "azure": ("microsoft azure", "azure devops"),
    "gcp": ("google cloud", "google cloud platform", "bigquery"),
    "cloud architecture": ("cloud migration", "serverless", "multi cloud",
                           "cloud native", "cloud security"),
    # Delivery.
    "docker": ("containerisation", "containerization", "containers"),
    "kubernetes": ("k8s", "openshift", "helm"),
    "terraform": ("infrastructure as code", "pulumi", "cloudformation"),
    "ci/cd": ("continuous integration", "continuous delivery", "jenkins",
              "gitlab ci", "github actions", "teamcity", "bamboo"),
    "ansible": ("puppet", "chef", "saltstack"),
    "git": ("github", "gitlab", "bitbucket", "version control", "svn"),
    "linux": ("unix", "rhel", "centos", "ubuntu", "solaris"),
    "observability": ("prometheus", "grafana", "datadog", "splunk",
                      "elk stack", "monitoring and alerting", "opentelemetry"),
    # Web and services.
    "react": ("react.js", "reactjs", "next.js", "nextjs"),
    "typescript": (),
    "javascript": ("es6", "node.js", "nodejs"),
    "angular": (),
    "vue": ("vue.js", "vuejs"),
    "fastapi": (),
    "django": (),
    "flask": (),
    "spring": ("spring boot", "spring framework"),
    "rest api": ("rest apis", "restful", "api design", "openapi", "swagger"),
    "graphql": (),
    "microservices": ("service oriented architecture", "soa",
                      "event driven architecture", "domain driven design"),
    "grpc": ("protobuf", "protocol buffers"),
    # Trading technology.
    "low latency engineering": ("lock free", "kernel bypass", "fpga",
                                "multicast", "solarflare", "onload",
                                "performance tuning", "latency optimisation",
                                "latency optimization", "cache optimisation"),
    "messaging middleware": ("tibco", "solace", "zeromq", "rabbitmq",
                             "rendezvous", "amps", "aeron"),
    "fix protocol": ("fix engine", "fix connectivity", "quickfix",
                     "itch", "ouch", "binary protocol",
                     "market data feed handler", "feed handler"),
    # Analytics and office.
    "tableau": (),
    "power bi": ("powerbi",),
    "qlik": ("qlikview", "qlik sense"),
    "looker": (),
    "sas": (),
    "alteryx": (),
    "data visualisation": ("data visualization", "dashboarding", "dashboard design"),
    "excel": ("microsoft excel", "advanced excel", "pivot tables", "power query",
              "excel modelling", "excel modeling"),
    "robotic process automation": ("rpa", "uipath", "blue prism",
                                   "automation anywhere"),
    "agile": ("scrum", "kanban", "sprint planning", "jira", "confluence",
              "safe framework", "agile delivery"),
    "software testing": ("unit testing", "integration testing", "test automation",
                         "selenium", "pytest", "tdd", "regression testing",
                         "system acceptance testing"),
    "cyber security": ("information security", "infosec", "penetration testing",
                       "vulnerability management", "iam", "identity and access management",
                       "zero trust", "encryption", "soc"),
}

# ── Banking, investment and corporate finance ────────────────────────────────
BANKING: dict[str, tuple[str, ...]] = {
    "investment banking": ("ib", "corporate finance", "advisory", "coverage banker",
                           "origination", "deal execution", "pitch book",
                           "pitchbook", "sell side", "sell-side"),
    "mergers and acquisitions": ("m&a", "mergers & acquisitions", "buy side advisory",
                                 "sell side advisory", "takeover", "divestiture",
                                 "carve out", "joint venture"),
    "equity capital markets": ("ecm", "ipo", "initial public offering",
                               "follow on offering", "rights issue", "placement",
                               "book building", "bookbuilding", "listing"),
    "debt capital markets": ("dcm", "bond issuance", "syndicated loans",
                             "loan syndication", "leveraged finance", "high yield",
                             "private placement"),
    "valuation": ("dcf", "discounted cash flow", "comparable company analysis",
                  "comps", "precedent transactions", "lbo model", "lbo modelling",
                  "lbo modeling", "enterprise value", "multiples analysis",
                  "business valuation", "fair value measurement"),
    "financial modelling": ("financial modeling", "three statement model",
                            "3 statement model", "scenario modelling",
                            "scenario modeling", "forecasting model",
                            "budget model", "operating model"),
    "private equity": ("pe", "buyout", "growth equity", "portfolio company",
                       "fund investing", "co-investment", "gp", "lp"),
    "venture capital": ("vc", "early stage investing", "seed investing",
                        "startup investing", "term sheet", "cap table"),
    "due diligence": ("financial due diligence", "commercial due diligence",
                      "vendor due diligence", "red flag report", "data room",
                      "vdr"),
    "project finance": ("infrastructure finance", "structured finance",
                        "asset finance", "aviation finance", "shipping finance",
                        "real estate finance"),
    "trade finance": ("letters of credit", "documentary credit", "lc",
                      "supply chain finance", "export finance", "factoring",
                      "guarantees", "bank guarantee"),
    "corporate banking": ("commercial banking", "relationship banking",
                          "credit facility", "loan origination", "working capital",
                          "cash management", "transaction banking"),
    "retail banking": ("consumer banking", "branch banking", "personal banking",
                       "mortgage lending", "credit cards", "unsecured lending",
                       "deposits"),
    "private banking": ("wealth management", "private wealth", "high net worth",
                        "hnw", "uhnw", "ultra high net worth", "family office",
                        "discretionary portfolio management", "dpm",
                        "investment advisory", "client advisory"),
}

# ── Asset management, insurance and actuarial ────────────────────────────────
BUY_SIDE: dict[str, tuple[str, ...]] = {
    "asset management": ("fund management", "investment management", "buy side",
                         "buy-side", "portfolio management", "mandate management"),
    "equity research": ("sell side research", "buy side research", "stock coverage",
                        "company analysis", "earnings model", "initiating coverage",
                        "analyst coverage"),
    "credit research": ("credit analysis", "fundamental credit", "issuer analysis",
                        "covenant analysis"),
    "hedge fund": ("long short equity", "long/short", "global macro",
                   "event driven", "multi strategy", "absolute return",
                   "prop trading", "proprietary trading"),
    "fund operations": ("fund accounting", "nav calculation", "net asset value",
                        "fund administration", "transfer agency", "unit pricing",
                        "fund valuation"),
    "esg": ("sustainable investing", "responsible investment", "esg integration",
            "green finance", "sustainability reporting", "impact investing",
            "net zero", "carbon accounting", "sfdr"),
    "actuarial": ("actuarial modelling", "actuarial modeling", "reserving",
                  "pricing actuary", "valuation actuary", "embedded value",
                  "solvency ii", "ifrs 17", "prophet", "moses", "axis actuarial",
                  "mortality assumptions", "lapse assumptions", "experience study"),
    "insurance": ("underwriting", "reinsurance", "claims management", "bancassurance",
                  "life insurance", "general insurance", "health insurance",
                  "policy administration", "mpf", "mandatory provident fund",
                  "orsa"),
}

# ── Finance, accounting, audit and tax ───────────────────────────────────────
ACCOUNTING: dict[str, tuple[str, ...]] = {
    "financial reporting": ("statutory reporting", "management reporting",
                            "group reporting", "consolidation", "month end close",
                            "period end close", "financial statements",
                            "mis reporting"),
    "ifrs": ("hkfrs", "ifrs 9", "ifrs 16", "ifrs 15", "us gaap", "hk gaap",
             "accounting standards"),
    "management accounting": ("budgeting", "forecasting", "variance analysis",
                              "cost accounting", "cost allocation", "fp&a",
                              "financial planning and analysis", "profitability analysis"),
    "internal audit": ("audit", "auditing", "external audit", "statutory audit",
                       "audit planning", "audit testing", "control testing",
                       "sox", "sarbanes oxley", "internal controls", "audit readiness"),
    "taxation": ("tax", "tax compliance", "tax advisory", "transfer pricing",
                 "international tax", "corporate tax", "profits tax", "tax structuring",
                 "tax reporting", "beps", "fatca", "crs",
                 "common reporting standard"),
    "treasury operations": ("treasury", "treasurer", "treasury management",
                            "intercompany funding", "in house bank"),
    "liquidity management": ("liquidity", "cash and liquidity management",
                             "liquidity planning", "liquidity forecasting",
                             "cash positioning"),
    "cash management": ("cash flow forecasting", "cashflow forecasting",
                        "cash flow analysis", "cash pooling", "payments and cash"),
    "asset liability management": ("alm", "asset and liability management",
                                   "balance sheet management",
                                   "balance sheet optimisation"),
    "funding strategy": ("wholesale funding", "funding plan", "debt issuance",
                         "funding and liquidity"),
    "hedging": ("hedge accounting", "fx hedging", "interest rate hedging",
                "cash flow hedge", "net investment hedge"),
    "accounts payable": ("accounts receivable", "ap", "ar", "reconciliations",
                         "general ledger", "gl", "journal entries", "invoicing",
                         "expense management"),
}

# ── Compliance, legal and financial crime ────────────────────────────────────
COMPLIANCE: dict[str, tuple[str, ...]] = {
    "regulatory compliance": ("compliance monitoring", "compliance advisory",
                              "regulatory reporting", "regulatory change",
                              "regulatory affairs", "policy drafting",
                              "compliance testing", "regulatory liaison"),
    "anti-money laundering": ("aml", "anti money laundering", "cft",
                              "counter terrorist financing", "transaction monitoring",
                              "suspicious transaction report", "str", "sar",
                              "name screening", "sanctions screening", "sanctions",
                              "pep screening", "financial crime"),
    "know your customer": ("kyc", "cdd", "edd", "customer due diligence",
                           "enhanced due diligence", "client onboarding",
                           "periodic review", "beneficial ownership"),
    "market conduct": ("market abuse", "insider dealing", "market manipulation",
                       "trade surveillance", "communications surveillance",
                       "conflicts of interest", "best execution", "mar",
                       "conduct risk", "control room"),
    "hk regulation": ("sfc", "securities and futures commission", "hkma",
                      "hong kong monetary authority", "sfo",
                      "securities and futures ordinance", "hkex", "insurance authority",
                      "ia", "type 1 licence", "type 2 licence", "type 4 licence",
                      "type 9 licence", "responsible officer", "licensed representative",
                      "mpfa"),
    "global regulation": ("mifid", "mifid ii", "dodd frank", "emir", "sftr",
                          "uncleared margin rules", "umr", "volcker",
                          "gdpr", "pdpo", "data privacy", "crd iv"),
    "legal": ("isda", "isda master agreement", "csa", "gmra", "msla",
              "contract negotiation", "legal documentation", "corporate secretarial",
              "company secretarial", "regulatory enforcement", "litigation"),
}

# ── Operations, post-trade and client service ────────────────────────────────
OPERATIONS: dict[str, tuple[str, ...]] = {
    "trade settlement": ("settlements", "clearing", "trade confirmation",
                         "trade capture", "trade lifecycle", "post trade",
                         "post-trade", "failed trades", "dvp", "custody",
                         "corporate actions", "ccass", "swift"),
    "collateral management": ("margin call", "margin calls", "margining",
                              "collateral optimisation", "collateral optimization",
                              "triparty", "clearing house", "ccp"),
    "reconciliation": ("nostro reconciliation", "cash reconciliation",
                       "position reconciliation", "break resolution",
                       "intersystem reconciliation"),
    "client onboarding": ("account opening", "static data", "reference data",
                          "client lifecycle management", "clm", "documentation review"),
    "middle office": ("trade support", "desk support", "pnl production",
                      "p&l production", "daily pnl", "position keeping",
                      "books and records"),
    "change management": ("business analysis", "requirements gathering",
                          "process improvement", "process reengineering",
                          "target operating model", "tom", "uat",
                          "user acceptance testing", "system implementation",
                          "vendor management", "lean six sigma", "six sigma"),
    "project management": ("programme management", "program management", "pmo",
                           "project delivery", "stakeholder management",
                           "governance and control", "milestone tracking",
                           "raid log"),
}

# ── Market data and vendor platforms ─────────────────────────────────────────
PLATFORMS: dict[str, tuple[str, ...]] = {
    "bloomberg": ("bloomberg terminal", "blp", "bloomberg api", "emsx", "aim"),
    "refinitiv": ("reuters", "eikon", "datastream", "tick history", "lseg"),
    "market data": ("level 2 data", "tick data", "historical data",
                    "reference data management", "market data vendor"),
    "order management system": ("oms", "ems", "execution management system",
                                "charles river", "fidessa", "murex", "calypso",
                                "summit", "kondor", "front arena", "openlink",
                                "trading system", "risk system"),
    "portfolio systems": ("aladdin", "simcorp", "bloomberg port", "factset",
                          "morningstar", "msci", "riskmetrics"),
    "core banking": ("temenos", "finacle", "flexcube", "mambu", "sap", "oracle erp",
                     "workday finance", "netsuite"),
    "crm": ("salesforce", "dynamics", "crm management"),
}

#: Every handwritten skill group, merged. Order matters only for readability.
SKILL_GROUPS: tuple[dict[str, tuple[str, ...]], ...] = (
    QUANT, MARKETS, RISK, TECHNOLOGY, BANKING, BUY_SIDE,
    ACCOUNTING, COMPLIANCE, OPERATIONS, PLATFORMS,
)


# ── Role families ────────────────────────────────────────────────────────────
#: Matched against a ROLE TITLE, so every alias must read like part of a title.
#: These are matched with word boundaries upstream — but keep them specific
#: anyway: "strat" alone would match "Strategic Planning Manager".
ROLE_FAMILIES: dict[str, tuple[str, ...]] = {
    "quantitative": ("quant", "quants", "quantitative analyst",
                     "quantitative researcher", "quantitative strategist",
                     "quantitative developer", "quantitative trader",
                     "quant analyst", "quant researcher", "quant strategist",
                     "quant developer", "quant dev", "quantitative engineer",
                     "strategist", "research analyst quantitative",
                     "risk quant", "pricing quant", "desk quant"),
    "trading": ("trader", "trading", "dealer", "dealing", "market maker",
                "sales trader", "execution trader", "portfolio trader",
                "trading desk", "flow trader"),
    "portfolio management": ("portfolio manager", "fund manager",
                             "investment manager", "assistant portfolio manager"),
    "research": ("research analyst", "equity research", "credit research",
                 "investment research", "economist", "strategy research"),
    "risk": ("risk analyst", "risk manager", "risk management", "market risk",
             "risk officer", "cro", "chief risk officer", "risk controller",
             "operational risk", "risk specialist"),
    "credit": ("credit analyst", "credit manager", "credit risk", "credit officer",
               "credit approval", "underwriter", "credit underwriter",
               "loan officer"),
    "investment banking": ("investment banker", "investment banking", "m&a",
                           "corporate finance", "capital markets", "ecm", "dcm",
                           "coverage", "origination"),
    "actuarial": ("actuary", "actuarial", "actuarial analyst", "actuarial manager"),
    "compliance": ("compliance officer", "compliance manager", "compliance analyst",
                   "aml officer", "financial crime", "surveillance analyst",
                   "regulatory affairs", "mlro"),
    "audit": ("auditor", "audit", "internal audit", "external audit",
              "audit manager"),
    "finance": ("financial analyst", "finance manager", "accountant", "controller",
                "financial controller", "fp&a", "cfo", "finance director",
                "product control", "product controller"),
    "treasury": ("treasurer", "treasury", "treasury manager", "alm manager",
                 "balance sheet manager", "liquidity manager"),
    "technology": ("software engineer", "developer", "engineer", "architect",
                   "programmer", "technology", "devops", "sre",
                   "platform engineer", "full stack"),
    "data": ("data analyst", "data scientist", "data engineer", "analytics",
             "machine learning engineer", "ml engineer", "ai engineer",
             "business intelligence"),
    "operations": ("operations", "settlements", "middle office", "back office",
                   "trade support", "operations analyst", "operations manager"),
    "relationship management": ("relationship manager", "client relationship",
                                "client advisor", "private banker",
                                "wealth manager", "account manager",
                                "business development"),
    "sales": ("sales", "institutional sales", "distribution", "sales manager",
              "coverage sales"),
    "product": ("product manager", "product owner", "product development",
                "product specialist"),
    "consulting": ("consultant", "consulting", "advisory", "strategy consultant"),
    "legal": ("legal counsel", "lawyer", "solicitor", "company secretary",
              "paralegal"),
    "human resources": ("human resources", "hr", "talent acquisition", "recruiter",
                        "people partner", "compensation and benefits"),
}

# ── Credentials ──────────────────────────────────────────────────────────────
#: On a HK finance CV these are among the most valuable tokens on the page.
CERTIFICATIONS: dict[str, tuple[str, ...]] = {
    "cfa": ("chartered financial analyst", "cfa charterholder", "cfa level",
            "cfa level i", "cfa level ii", "cfa level iii"),
    "frm": ("financial risk manager", "garp frm"),
    "cqf": ("certificate in quantitative finance",),
    "caia": ("chartered alternative investment analyst",),
    "cpa": ("hkicpa", "certified public accountant", "aicpa", "cpa australia"),
    "acca": ("fcca", "association of chartered certified accountants"),
    "cima": ("chartered institute of management accountants",),
    "cfp": ("certified financial planner",),
    "cams": ("certified anti-money laundering specialist", "acams"),
    "cisa": ("certified information systems auditor",),
    "cissp": ("certified information systems security professional",),
    "prm": ("professional risk manager",),
    "hksi": ("hong kong securities institute", "hksi paper"),
    "ctp": ("certified treasury professional",),
    "pmp": ("project management professional",),
    "fia": ("fellow of the institute of actuaries", "ifoa", "faculty of actuaries"),
    "fsa actuarial": ("fellow of the society of actuaries", "soa fellow"),
    "asa actuarial": ("associate of the society of actuaries",),
    "lean six sigma": ("six sigma", "lssbb", "six sigma black belt",
                       "green belt", "black belt"),
    "series 7": ("series 63", "series 79", "finra licence"),
    "caia level": (),
    "cfa esg": ("certificate in esg investing",),
}

# ── Sectors ──────────────────────────────────────────────────────────────────
SECTOR_ALIASES: dict[str, tuple[str, ...]] = {
    "Asset Management": ("asset management", "fund management", "investment management",
                         "buy side", "mutual fund", "hedge fund", "private equity",
                         "venture capital"),
    "Banking": ("banking", "commercial bank", "retail bank", "corporate bank",
                "universal bank", "licensed bank"),
    "Insurance": ("insurance", "insurer", "reinsurance", "life insurance",
                  "general insurance", "bancassurance"),
    "Investment Banking": ("investment banking", "capital markets", "m&a",
                           "sell side", "broker dealer", "securities house",
                           "global markets"),
    "Professional Services": ("professional services", "consulting", "advisory",
                              "big four", "big 4", "accounting firm", "law firm"),
    "Technology": ("fintech", "technology company", "software company",
                   "financial technology", "regtech", "insurtech"),
    "Exchange": ("stock exchange", "clearing house", "market infrastructure",
                 "central counterparty"),
}

#: Employer names carry sector far more reliably than a CV's prose does — the
#: generic aliases above only fire when someone literally writes "banking".
#: Every entry here is matched case-folded AND against a space-stripped copy of
#: the CV, because a PDF that glues words produces "MorganStanley", which is
#: precisely the token this table needs to recognise (see `_deglue`).
EMPLOYER_SECTORS: dict[str, tuple[str, ...]] = {
    "Investment Banking": (
        "goldman sachs", "morgan stanley", "j.p. morgan", "jpmorgan", "jp morgan",
        "bank of america", "merrill lynch", "citigroup", "citi", "barclays",
        "deutsche bank", "credit suisse", "ubs", "nomura", "daiwa", "mizuho",
        "smbc nikko", "bnp paribas", "societe generale", "natixis", "macquarie",
        "jefferies", "lazard", "rothschild", "evercore", "moelis", "houlihan lokey",
        "citic securities", "citic clsa", "clsa", "haitong", "guotai junan",
        "cicc", "china international capital", "huatai", "gf securities",
        "everbright securities", "bocom international", "cmb international",
        "futu", "tiger brokers",
    ),
    "Banking": (
        "hsbc", "hang seng bank", "standard chartered", "bank of china",
        "boc hong kong", "bank of east asia", "dbs", "ocbc", "uob",
        "citibank", "icbc", "china construction bank", "agricultural bank of china",
        "bank of communications", "china citic bank", "nanyang commercial bank",
        "chiyu banking", "public bank", "dah sing bank", "chong hing bank",
        "wing lung bank", "cmb wing lung", "shanghai commercial bank",
        "fubon bank", "za bank", "mox bank", "welab bank", "livi bank",
        "airstar bank", "ant bank", "pao bank", "anz", "westpac", "rbc",
        "scotiabank", "mufg", "sumitomo mitsui", "norinchukin", "rabobank",
        "ing", "commerzbank", "unicredit", "intesa",
    ),
    "Asset Management": (
        "blackrock", "vanguard", "fidelity", "invesco", "schroders", "pimco",
        "amundi", "eastspring", "value partners", "jpmorgan asset management",
        "allianz global investors", "aberdeen", "abrdn", "janus henderson",
        "franklin templeton", "t. rowe price", "wellington management",
        "capital group", "state street", "northern trust", "bny mellon",
        "manulife investment", "principal", "e fund", "china asset management",
        "harvest fund", "bosera", "hillhouse", "primavera", "pag", "baring private equity",
        "carlyle", "kkr", "blackstone", "bain capital", "tpg", "warburg pincus",
        "sequoia", "hongshan", "temasek", "gic",
    ),
    "Insurance": (
        "aia", "prudential", "manulife", "axa", "fwd", "chubb", "zurich",
        "sun life", "allianz", "bupa", "blue cross", "china life", "ping an",
        "cpic", "taiping", "generali", "aig", "msig", "qbe", "hsbc life",
        "boc life", "china taiping", "swiss re", "munich re", "scor",
        "hannover re", "marsh", "aon", "willis towers watson", "gallagher",
    ),
    "Professional Services": (
        "pwc", "pricewaterhousecoopers", "deloitte", "kpmg", "ernst and young",
        "ernst & young", "ey", "grant thornton", "bdo", "rsm", "mazars",
        "crowe", "mckinsey", "bain", "boston consulting", "bcg", "accenture",
        "oliver wyman", "kearney", "roland berger", "alvarez and marsal",
        "fti consulting", "kroll",
    ),
    "Exchange": (
        "hong kong exchanges", "hkex", "hong kong exchanges and clearing",
        "sgx", "singapore exchange", "cme", "ice", "nasdaq", "nyse", "lseg",
        "euronext", "cboe", "shanghai stock exchange", "shenzhen stock exchange",
    ),
    "Technology": (
        "bloomberg", "refinitiv", "msci", "factset", "s&p global", "moody's",
        "fitch", "ion group", "murex", "finastra", "temenos", "fis", "fiserv",
        "broadridge", "ssnc", "simcorp", "charles river", "calypso",
        "tencent", "alibaba", "ant group", "bytedance", "jd.com", "meituan",
        "google", "microsoft", "amazon", "apple", "meta", "stripe", "airwallex",
        "revolut", "wise",
    ),
}


# ── Mined layer ──────────────────────────────────────────────────────────────
#: Built by `scripts/mine_vocabulary.py`. Absent in a fresh checkout, and that
#: must stay non-fatal: the handwritten layer above is a complete, working
#: vocabulary on its own, and the mined layer only sharpens it.
MINED_PATH = Path(__file__).resolve().parent / "vocabulary_mined.json"


@lru_cache(maxsize=1)
def mined() -> dict:
    """Load the mined term→document-frequency table, or an empty one.

    Cached because `score_resume_fit` runs once per candidate Role and the
    candidate window is 1,000 wide.
    """
    try:
        raw = json.loads(MINED_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"document_count": 0, "terms": {}}
    if not isinstance(raw, dict) or not isinstance(raw.get("terms"), dict):
        return {"document_count": 0, "terms": {}}
    return raw


@lru_cache(maxsize=1)
def skill_aliases() -> dict[str, tuple[str, ...]]:
    """The handwritten skill table, flattened to canonical term → aliases."""
    merged: dict[str, tuple[str, ...]] = {}
    for group in SKILL_GROUPS:
        for canonical, aliases in group.items():
            merged.setdefault(canonical, ())
            merged[canonical] = tuple(dict.fromkeys(merged[canonical] + aliases))
    return merged


@lru_cache(maxsize=1)
def all_phrases() -> tuple[str, ...]:
    """Every handwritten phrase, longest first.

    Longest-first is what makes greedy matching correct: `statistical arbitrage`
    must be found before `arbitrage`, and `equity derivatives` before `equity`.
    Used by skill extraction and by the de-gluer in `resume_intelligence`.
    """
    phrases: set[str] = set()
    for canonical, aliases in skill_aliases().items():
        phrases.add(canonical)
        phrases.update(aliases)
    for canonical, aliases in CERTIFICATIONS.items():
        phrases.add(canonical)
        phrases.update(aliases)
    for canonical, aliases in ROLE_FAMILIES.items():
        phrases.add(canonical)
        phrases.update(aliases)
    for names in EMPLOYER_SECTORS.values():
        phrases.update(names)
    for aliases in SECTOR_ALIASES.values():
        phrases.update(aliases)
    phrases.discard("")
    return tuple(sorted(phrases, key=lambda value: (-len(value), value)))


@lru_cache(maxsize=1)
def canonical_by_alias() -> dict[str, str]:
    """alias → canonical skill, for collapsing `stat arb` onto its real name."""
    table: dict[str, str] = {}
    for canonical, aliases in skill_aliases().items():
        table[canonical] = canonical
        for alias in aliases:
            table.setdefault(alias, canonical)
    return table


# ── Rarity ───────────────────────────────────────────────────────────────────
#: A term seen in this share of postings or more carries essentially no
#: information: everybody asks for it, so matching it says nothing about fit.
#: 10% of the catalogue — `risk management` (11.8%) and `stakeholder
#: management` (18.2%) both sit above it.
COMMON_SHARE = 0.10
#: A term seen in this share or less is a genuine specialism. 0.2% is ~35
#: postings out of 17,479: `market making` (28), `algorithmic trading` (53),
#: `kdb` (11), `statistical arbitrage` (4) are all at or below it.
RARE_SHARE = 0.002
#: What an unknown term is worth. A term absent from the mined table is usually
#: specialist language the catalogue has not seen — but it can equally be the
#: model inventing a phrase, so it is treated as informative without being
#: treated as the rarest thing on the board.
UNKNOWN_RARITY = 0.6


def _frequency(value: str, table: dict) -> int | None:
    """How often the catalogue asks for this, counting synonyms and compounds.

    Two lookups, both necessary:

    * EFFECTIVE frequency counts the terms that CONTAIN this one. Bare `risk`
      was written as a skill in 2 postings but appears inside a skill in 6,312
      of them; on its own count it scored as a rarer specialism than
      `statistical arbitrage`, which is how an HR Technology & Analytics role
      reached the top of a quant trader's matches.

    * ALIASES, because the two halves of the vocabulary spell things
      differently. A posting asks for `KDB/q`; the handwritten table calls it
      `q/kdb`; the mined table knows `kdb`. Without resolving between them a
      genuine specialism falls through to `UNKNOWN_RARITY` and scores as merely
      plausible. We take the most common spelling found — if ANY spelling of a
      skill is commonplace, the skill is commonplace.
    """
    effective = table.get("effective", {})
    raw = table.get("terms", {})

    def one(term: str) -> int | None:
        found = effective.get(term)
        return found if found is not None else raw.get(term)

    direct = one(value)
    canonical = canonical_by_alias().get(value)
    if canonical is None:
        return direct

    spellings = {canonical, *skill_aliases().get(canonical, ())}
    counts = [n for n in (one(spelling) for spelling in spellings) if n is not None]
    if direct is not None:
        counts.append(direct)
    return max(counts) if counts else None


def rarity(term: str) -> float:
    """How much does matching this term actually tell us? 0.0 (nothing) to 1.0.

    The whole point of mining document frequencies. `stakeholder management`
    appears in 18.2% of HK finance postings and `statistical arbitrage` in
    0.02%; scoring a match on each identically is how a Morgan Stanley quant's
    best match came to be a Compliance Manager — matched on "english",
    "training" (from "strength training", in his hobbies) and "mathematics"
    (from his degree), while a real Risk Quant role ranked eleven places below
    a Precious Metals Trader.

    Log-scaled, because document frequency spans four orders of magnitude and
    a linear scale would make everything below 1% indistinguishable.
    """
    value = " ".join(str(term or "").casefold().split())
    if not value or value in STOP_SKILLS:
        return 0.0

    table = mined()
    documents = table.get("document_count") or 0
    if not documents:
        return UNKNOWN_RARITY

    frequency = _frequency(value, table)
    if frequency is None:
        return UNKNOWN_RARITY

    share = max(frequency, 1) / documents
    if share >= COMMON_SHARE:
        return 0.0
    if share <= RARE_SHARE:
        return 1.0
    # Linear in log-space between the two anchors.
    span = math.log(COMMON_SHARE) - math.log(RARE_SHARE)
    return (math.log(COMMON_SHARE) - math.log(share)) / span
