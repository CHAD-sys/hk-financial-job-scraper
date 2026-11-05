/**
 * Full programme content for "Advanced Quantitative Portfolio Management".
 *
 * The module titles match `COURSES[quant].modules` exactly, so progress
 * tracked in the catalogue (a count of completed modules) maps one-to-one
 * onto this syllabus. Every reading is a real, citable publication; the
 * numbers inside the interactive visuals are illustrative inputs pushed
 * through the real formulas, never historical claims.
 */

export type VisualId =
  | "frontier"
  | "fundamental-law"
  | "pipeline"
  | "shrinkage"
  | "risk-parity"
  | "deflated-sharpe"
  | "impact"
  | "attribution";

export interface Lesson {
  title: string;
  minutes: number;
  summary: string;
  body: string[];
  formula?: { label: string; expression: string; note: string };
  code?: string;
  visual?: VisualId;
  takeaway: string;
}

export interface KnowledgeCheck {
  question: string;
  options: string[];
  answer: number;
  explanation: string;
}

export interface Reading {
  citation: string;
  why: string;
}

export interface Lab {
  title: string;
  brief: string;
  deliverable: string;
  /** File name (no extension) under /learning-assets/notebooks/quant/. */
  notebook: string;
  /** Printed by the notebook when every automatic check passes; absent for the capstone. */
  code?: string;
  /** What the solution finds on the live data, revealed once the lab is complete. */
  findings?: string[];
}

export interface CourseModule {
  week: number;
  title: string;
  hook: string;
  hours: number;
  /** Open to everyone, enrolled or not. */
  free?: boolean;
  lessons: Lesson[];
  lab: Lab;
  check: KnowledgeCheck;
  readings: Reading[];
}

export const QUANT_OVERVIEW = {
  id: "quant",
  tagline: "From factor research to a portfolio you can defend in front of an investment committee.",
  intro: [
    "Most quantitative courses stop at the model. This programme follows an idea all the way to the trade blotter: where an expected return comes from, how risk is really measured, why the 'optimal' portfolio is so often the worst one out of sample, what a backtest can and cannot prove, and how to explain the result to someone who has to sign off on it.",
    "Each week pairs the core theory, from Markowitz to Black–Litterman to the deflated Sharpe ratio, with a Python lab on real public data. By week six you build, stress-test and present a complete multi-factor portfolio for an Asia-Pacific equity mandate.",
  ],
  audience: [
    "Portfolio managers and analysts moving from discretionary to systematic processes",
    "Risk and performance professionals who want to own the models they review",
    "Quantitative researchers who need the portfolio-construction half of the job",
    "Wealth and multi-asset teams building model portfolios or factor sleeves",
  ],
  prerequisites: [
    "Comfort with statistics: regression, variance, correlation",
    "Working Python, or willingness to complete the free pre-course primer",
    "Familiarity with equity markets and basic portfolio concepts",
  ],
  format: [
    { label: "Format", value: "Online · live + self-paced" },
    { label: "Duration", value: "6 weeks" },
    { label: "Effort", value: "≈ 6 hours / week" },
    { label: "CPD hours", value: "36" },
    { label: "Live sessions", value: "Tuesdays 7:00–8:30 pm HKT" },
    { label: "Next cohort", value: "Starts 23 November 2026" },
    { label: "Tools", value: "Python · pandas · cvxpy · scikit-learn" },
    { label: "Certificate", value: "FinEx certificate of completion" },
  ],
  outcomes: [
    "Derive and critique mean-variance, minimum-variance, risk-parity and Black–Litterman portfolios",
    "Build, neutralise and combine factor signals into a single expected-return forecast",
    "Estimate a covariance matrix that survives out of sample, using shrinkage and factor models",
    "Run a backtest that accounts for costs, turnover and multiple testing",
    "Decompose performance into allocation, selection and factor contributions",
    "Present a portfolio and its risks to an investment committee with conviction",
  ],
  capstone: {
    title: "Capstone: an APAC multi-factor equity mandate",
    brief:
      "You are handed a HK$2bn Asia-Pacific equity mandate benchmarked to a regional index, with a 4% tracking-error budget and a 30% annual turnover limit. Build a value-momentum-quality portfolio, size it with a risk model you can justify, backtest it honestly, and present it to a mock investment committee.",
    deliverables: [
      "A reproducible research notebook (signal → portfolio → backtest)",
      "A two-page investment memo with the risk budget and expected tracking error",
      "A 10-minute committee presentation with live Q&A",
    ],
    rubric: [
      { item: "Research process & reproducibility", weight: 30 },
      { item: "Portfolio construction & risk", weight: 30 },
      { item: "Backtest integrity & costs", weight: 20 },
      { item: "Communication & judgement", weight: 20 },
    ],
  },
};

export const QUANT_MODULES: CourseModule[] = [
  {
    week: 1,
    title: "Portfolio foundations & factor investing",
    hook: "Where expected returns come from, and why diversification is the only free lunch.",
    hours: 6,
    free: true,
    lessons: [
      {
        title: "Mean–variance: the idea that started it all",
        minutes: 35,
        summary: "Markowitz turned 'don't put all your eggs in one basket' into an optimisation problem.",
        body: [
          "In 1952 Harry Markowitz argued that investors should care about the whole portfolio, not individual securities. What matters is how an asset changes the portfolio's return and its variance, and variance depends on covariances as much as on individual volatilities.",
          "For any target return there is one portfolio with the lowest possible variance. Plot those portfolios and you get the efficient frontier. Add a risk-free asset and the best risky portfolio is the one that maximises the Sharpe ratio, the tangency portfolio. Every efficient investor then holds a mix of cash and that one portfolio, the capital market line.",
          "Use the chart: move the risk-aversion slider and watch the optimal portfolio slide along the frontier. Notice how little extra return the last units of risk buy you near the top.",
        ],
        formula: {
          label: "Mean–variance optimum",
          expression: "w* = (1/λ) · Σ⁻¹ μ",
          note: "λ is risk aversion, Σ the covariance matrix and μ the vector of expected excess returns. Everything that goes wrong later in this course goes wrong inside Σ⁻¹.",
        },
        visual: "frontier",
        takeaway: "The frontier is only as good as its inputs: μ and Σ are estimates, and the optimiser treats them as facts.",
      },
      {
        title: "CAPM, factors and the cross-section of returns",
        minutes: 40,
        summary: "From one factor (the market) to the factor zoo, and how to tell a premium from noise.",
        body: [
          "The CAPM (Sharpe, 1964) says only market beta should be rewarded. Empirically, other characteristics also explain returns: small caps and cheap stocks (Fama & French, 1993), recent winners (Jegadeesh & Titman, 1993; Carhart, 1997), profitable firms (Novy-Marx, 2013) and, counter-intuitively, low-beta stocks (Frazzini & Pedersen, 2014).",
          "A factor is a long–short portfolio sorted on a characteristic. A credible factor has an economic story (risk compensation or a persistent behavioural bias), survives across markets and asset classes (Asness, Moskowitz & Pedersen, 2013) and survives after costs.",
          "Harvey, Liu & Zhu (2016) counted more than 300 published factors and argued that, after accounting for data-mining, a new factor needs a t-statistic above roughly 3.0, not 2.0. We use that bar throughout the course.",
        ],
        formula: {
          label: "Factor regression",
          expression: "rᵢ − r_f = αᵢ + βᵢ,MKT·MKT + βᵢ,SMB·SMB + βᵢ,HML·HML + βᵢ,MOM·MOM + εᵢ",
          note: "α is what is left after known factors. Most 'alpha' turns out to be an unrecognised factor exposure.",
        },
        code: `import pandas as pd
import statsmodels.api as sm

# Monthly factor returns from the Kenneth French Data Library
ff = pd.read_csv("F-F_Research_Data_Factors.csv", index_col=0, parse_dates=True) / 100
fund = pd.read_csv("fund_returns.csv", index_col=0, parse_dates=True)["ret"]

X = sm.add_constant(ff[["Mkt-RF", "SMB", "HML"]].loc[fund.index])
y = fund - ff.loc[fund.index, "RF"]
model = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 6})
print(model.summary())   # alpha = const; look at its t-stat, not just its size`,
        takeaway: "Before you call something alpha, regress it on known factors and ask for a t-stat above 3.",
      },
      {
        title: "The fundamental law of active management",
        minutes: 30,
        summary: "Skill × breadth: why a small edge applied many times beats a big edge applied rarely.",
        body: [
          "Grinold (1989) showed that the best achievable information ratio is approximately the information coefficient (the correlation between your forecasts and realised returns) multiplied by the square root of breadth (the number of independent bets per year).",
          "An IC of 0.05 looks tiny, but applied to 400 independent bets a year it supports an IR near 1.0, which is world-class. A brilliant stock-picker with IC 0.20 and only 10 truly independent bets reaches about 0.63.",
          "The catch is the word independent. Fifty bank stocks are not fifty bets. Clarke, de Silva & Thorley (2002) added a transfer coefficient: constraints such as long-only rules stop forecasts reaching the portfolio, scaling the IR down further.",
        ],
        formula: {
          label: "Fundamental law (with transfer coefficient)",
          expression: "IR ≈ TC · IC · √BR",
          note: "IR is the information ratio, IC the forecast skill, BR the breadth in independent bets per year and TC the transfer coefficient (1.0 if unconstrained).",
        },
        visual: "fundamental-law",
        takeaway: "Breadth is a lever you control. Constraints quietly take it away again.",
      },
    ],
    lab: {
      title: "Lab 1 · Replicate value and momentum",
      brief: "Rebuild HML and WML for Asia-Pacific ex Japan (Australia, Hong Kong, New Zealand, Singapore) from their six building-block portfolios, annualise every factor, test each against the t > 3 hurdle and check whether value is just market beta.",
      deliverable: "Completed notebook: factor table, value–momentum correlation and a CAPM alpha test.",
      notebook: "lab1-value-momentum",
      code: "FINEX-LAB1-BF739B",
      findings: [
        "Value (HML) and momentum (WML) both clear t > 3 in Asia-Pacific since 1990: t = 4.1 and 4.3.",
        "They are negatively correlated (−0.30), so a 50/50 blend reaches a Sharpe ratio of 1.16, above either factor alone (0.68 and 0.72).",
        "Value's CAPM alpha has t = 4.2 with a market beta of 0.02: it is not a disguised market bet.",
        "The size premium (SMB) has been negative in this region, a reminder that a famous factor need not travel.",
      ],
    },
    check: {
      question: "A strategy has IC = 0.04 and makes 625 independent bets per year with no constraints. Its expected information ratio is closest to:",
      options: ["0.25", "1.00", "2.50", "25.0"],
      answer: 1,
      explanation: "IR ≈ IC × √BR = 0.04 × √625 = 0.04 × 25 = 1.0.",
    },
    readings: [
      { citation: "Markowitz, H. (1952). Portfolio Selection. Journal of Finance, 7(1), 77–91.", why: "The origin of mean–variance optimisation." },
      { citation: "Fama, E. & French, K. (1993). Common risk factors in the returns on stocks and bonds. Journal of Financial Economics, 33(1), 3–56.", why: "The three-factor model." },
      { citation: "Asness, C., Moskowitz, T. & Pedersen, L. (2013). Value and Momentum Everywhere. Journal of Finance, 68(3), 929–985.", why: "Evidence that factors travel across markets." },
      { citation: "Harvey, C., Liu, Y. & Zhu, H. (2016). …and the Cross-Section of Expected Returns. Review of Financial Studies, 29(1), 5–68.", why: "Why most published factors are probably false." },
      { citation: "Grinold, R. & Kahn, R. (2000). Active Portfolio Management (2nd ed.). McGraw-Hill.", why: "The reference text for the fundamental law." },
    ],
  },
  {
    week: 2,
    title: "Building a research workflow in Python",
    hook: "A signal is a pipeline, not a formula. Build one that is honest by construction.",
    hours: 6,
    lessons: [
      {
        title: "Data you can trust: point-in-time, survivorship and look-ahead",
        minutes: 35,
        summary: "Most backtest 'alpha' is a data error. Learn the three that matter most.",
        body: [
          "Survivorship bias: if your universe is today's index members, you have silently deleted every company that failed. Use historical constituents.",
          "Look-ahead bias: financial statements are published weeks after the period they describe and are often restated. A value signal must use what was known on the trade date, so lag fundamentals (a common rule is three to six months) or use a point-in-time database.",
          "Corporate actions and currency: splits, dividends and, for Hong Kong and China, dual listings (H-shares vs A-shares via Stock Connect) all need explicit handling. Total-return series, one base currency, one calendar.",
        ],
        code: `# Point-in-time join: only use fundamentals published before each rebalance date
fund = fundamentals.sort_values("publish_date")
panel = pd.merge_asof(
    prices.sort_values("date"), fund,
    left_on="date", right_on="publish_date",
    by="ticker", direction="backward",
)
# Universe = members of the index *on that date*, not today
panel = panel[panel.apply(lambda r: r.ticker in members[r.date], axis=1)]`,
        takeaway: "Ask of every number in your dataset: could I have known this on the day I traded?",
      },
      {
        title: "From raw characteristic to clean signal",
        minutes: 40,
        summary: "Winsorise, standardise, neutralise: turning a noisy ratio into a forecast.",
        body: [
          "Raw characteristics have outliers and incomparable scales. The standard recipe is: winsorise at the 1st/99th percentile, convert to cross-sectional z-scores each date, then neutralise against exposures you do not want to bet on, typically sector and market beta, by regressing and keeping the residual.",
          "Combine signals by z-score averaging or, better, by weighting each signal by its historical IC relative to its noise (an IC-weighted composite). Watch the correlation between signals: value and momentum are negatively correlated, which is exactly why they combine so well.",
          "Measure each signal with the rank IC (Spearman correlation of signal vs forward return) and its decay over horizons. A signal whose IC halves in a week needs a very different rebalancing frequency from one that lasts a quarter.",
        ],
        visual: "pipeline",
        code: `def clean(x: pd.Series) -> pd.Series:
    x = x.clip(x.quantile(0.01), x.quantile(0.99))
    return (x - x.mean()) / x.std()

def neutralise(signal: pd.Series, exposures: pd.DataFrame) -> pd.Series:
    X = sm.add_constant(exposures)          # sector dummies + beta
    return sm.OLS(signal, X).fit().resid

z = panel.groupby("date", group_keys=False).apply(
    lambda d: neutralise(clean(d["book_to_price"]), d[sector_cols + ["beta"]])
)
rank_ic = (panel.assign(z=z).groupby("date")
           .apply(lambda d: d["z"].corr(d["fwd_ret_1m"], method="spearman")))
print(f"Mean IC {rank_ic.mean():.3f} · t-stat {rank_ic.mean() / rank_ic.std() * len(rank_ic) ** 0.5:.2f}")`,
        takeaway: "Neutralise what you do not mean to bet on, so the portfolio expresses only the idea you can defend.",
      },
      {
        title: "Reproducible research",
        minutes: 25,
        summary: "Version data, log every trial, and keep a research journal you would show a regulator.",
        body: [
          "Every variant you test is a trial, and in Module 4 you will need the total number of trials to correct your Sharpe ratio. Log them from day one: parameters, date run, result.",
          "Separate code (Git), data (versioned snapshots) and results (an experiment log). Fix random seeds. Keep a hold-out period you never touch until the final test.",
        ],
        takeaway: "If you cannot reproduce a result six months later, you cannot defend it today.",
      },
    ],
    lab: {
      title: "Lab 2 · Build a composite value-momentum-quality signal",
      brief: "Treat the 25 Asia-Pacific size × book-to-market portfolios as your universe. Build momentum, value and low-volatility signals point-in-time, prove there is no look-ahead, neutralise to size, measure rank ICs and combine them with weights that never see the future.",
      deliverable: "Completed notebook: IC table and an IC-weighted composite.",
      notebook: "lab2-composite-signal",
      code: "FINEX-LAB2-8CBBC7",
      findings: [
        "All three signals have significant monthly rank ICs: momentum 0.051, value 0.074, low volatility 0.044 (t = 4.1, 4.4, 3.3).",
        "Value's IC grows with the horizon (0.23 at 12 months) while momentum's stays flat: they need different rebalancing speeds.",
        "The look-ahead-free composite reaches an IC of 0.072 (t = 4.3).",
      ],
    },
    check: {
      question: "Your value signal uses quarterly book values dated to the quarter end. What is the main risk?",
      options: ["Survivorship bias", "Look-ahead bias", "Overfitting", "Market impact"],
      answer: 1,
      explanation: "Accounts are published weeks after quarter end, so using them from the quarter-end date assumes information you did not yet have.",
    },
    readings: [
      { citation: "Jegadeesh, N. & Titman, S. (1993). Returns to Buying Winners and Selling Losers. Journal of Finance, 48(1), 65–91.", why: "The momentum anomaly." },
      { citation: "Novy-Marx, R. (2013). The other side of value: The gross profitability premium. Journal of Financial Economics, 108(1), 1–28.", why: "A clean quality factor." },
      { citation: "Kenneth R. French Data Library, Tuck School of Business, Dartmouth College (online).", why: "Free factor data used in the labs." },
    ],
  },
  {
    week: 3,
    title: "Risk models and portfolio construction",
    hook: "Why the 'optimal' portfolio is often the worst one, and four ways to fix it.",
    hours: 6,
    lessons: [
      {
        title: "The estimation-error problem",
        minutes: 30,
        summary: "Optimisers are error maximisers. They overweight assets whose returns you overestimated.",
        body: [
          "Michaud (1989) called mean–variance optimisers 'estimation-error maximisers': they place the largest bets exactly where the inputs are most wrong. With 500 stocks the covariance matrix has 125,250 parameters, and five years of monthly data gives you 30,000 observations. The maths does not work.",
          "DeMiguel, Garlappi & Uppal (2009) found that a naive 1/N portfolio was not consistently beaten out of sample by 14 optimised models. That is not an argument for 1/N. It is an argument for estimating inputs much more carefully.",
        ],
        takeaway: "Treat every input as a noisy estimate, and build portfolios that degrade gracefully when it is wrong.",
      },
      {
        title: "Shrinkage and factor risk models",
        minutes: 40,
        summary: "Pull the sample covariance toward structure. Ledoit–Wolf, and the Barra-style factor model.",
        body: [
          "Ledoit & Wolf (2004) proposed shrinking the sample covariance matrix toward a structured target, such as constant correlation, with an optimal, data-driven intensity δ. Extreme correlations are pulled toward the average and the matrix becomes well-conditioned and invertible.",
          "Commercial risk models (for example MSCI Barra) instead impose a factor structure: Σ = B F Bᵀ + D, where B holds exposures to industries and styles, F is the small factor covariance matrix and D the stock-specific variances. Thousands of parameters become a few hundred.",
          "Drag the slider: at δ = 0 the minimum-variance portfolio takes extreme positions to exploit tiny estimated correlations. As δ rises the weights calm down and become far more stable out of sample.",
        ],
        formula: {
          label: "Ledoit–Wolf shrinkage",
          expression: "Σ̂ = δ · F + (1 − δ) · S",
          note: "S is the sample covariance, F a structured target and δ ∈ [0, 1] the shrinkage intensity, chosen to minimise expected estimation error.",
        },
        visual: "shrinkage",
        code: `from sklearn.covariance import LedoitWolf
lw = LedoitWolf().fit(returns.values)
print(f"Shrinkage intensity δ = {lw.shrinkage_:.2f}")
Sigma = pd.DataFrame(lw.covariance_, index=returns.columns, columns=returns.columns)`,
        takeaway: "A slightly biased but stable risk model beats an unbiased one that changes its mind every month.",
      },
      {
        title: "Risk budgeting and risk parity",
        minutes: 35,
        summary: "Allocate risk, not capital. Equal weight is rarely equal risk.",
        body: [
          "Each asset's contribution to portfolio risk is RCᵢ = wᵢ · (Σw)ᵢ / σₚ, and the contributions sum exactly to portfolio volatility. In a 60/40 equity–bond portfolio, equities typically contribute around 90% of the risk.",
          "A risk-parity (equal risk contribution) portfolio sets every RCᵢ equal (Maillard, Roncalli & Teïletche, 2010). It needs no expected returns at all, only Σ, which makes it far more robust to estimation error. Hierarchical Risk Parity (López de Prado, 2016) goes further and clusters assets first, avoiding the matrix inversion altogether.",
        ],
        formula: {
          label: "Risk contribution",
          expression: "RCᵢ = wᵢ (Σw)ᵢ / √(wᵀΣw),   Σᵢ RCᵢ = σₚ",
          note: "Risk parity solves for weights where every RCᵢ is equal.",
        },
        visual: "risk-parity",
        takeaway: "Look at where the risk is, not where the money is.",
      },
      {
        title: "Black–Litterman: blending equilibrium with views",
        minutes: 40,
        summary: "Start from what the market implies, then tilt only as far as your confidence allows.",
        body: [
          "Black & Litterman (1992) reverse the optimiser: assume the market-cap portfolio is optimal and back out the implied returns Π = λΣw_mkt. These are sensible, diversified expected returns.",
          "Your views (for example 'HK financials will beat HK property by 2%') are blended with Π in proportion to your confidence. No view means you hold the benchmark. A confident view gives a controlled tilt, never a corner solution.",
          "Then add real-world constraints with a convex solver: long-only, position caps, sector limits, a tracking-error budget and a turnover penalty.",
        ],
        code: `import cvxpy as cp
w = cp.Variable(n)
active = w - w_bench
objective = cp.Maximize(mu_bl @ w - 0.5 * lam * cp.quad_form(w, Sigma)
                        - tc * cp.norm1(w - w_prev))          # turnover cost
constraints = [cp.sum(w) == 1, w >= 0, w <= 0.05,
               cp.quad_form(active, Sigma) <= 0.04 ** 2,     # 4% tracking error
               sector_matrix @ active <= 0.05, sector_matrix @ active >= -0.05]
cp.Problem(objective, constraints).solve()`,
        takeaway: "Constraints and priors are not a compromise of the model. They are how the model survives reality.",
      },
    ],
    lab: {
      title: "Lab 3 · Four portfolios, one universe",
      brief: "Run a rolling 60-month horse race between 1/N, sample minimum-variance, Ledoit–Wolf minimum-variance, equal risk contribution and market-cap weights, then reproduce the Black–Litterman starting point and solve a constrained version with cvxpy.",
      deliverable: "Completed notebook: out-of-sample volatility, turnover and exposure for every construction.",
      notebook: "lab3-four-portfolios",
      code: "FINEX-LAB3-E0D555",
      findings: [
        "The 'optimal' sample minimum-variance portfolio was more volatile out of sample than naive 1/N (21.7% vs 21.1%), with 85% monthly turnover and 734% gross exposure.",
        "Ledoit–Wolf shrinkage cut volatility to 18.2% and turnover to 26% a month: the same idea, estimated better.",
        "Implied Black–Litterman returns reproduce the market portfolio exactly, the neutral starting point views tilt away from.",
      ],
    },
    check: {
      question: "Which approach requires no expected-return estimates at all?",
      options: ["Mean–variance", "Black–Litterman", "Risk parity", "Maximum Sharpe"],
      answer: 2,
      explanation: "Risk parity only uses the covariance matrix, which is why it is robust to the noisiest input, expected returns.",
    },
    readings: [
      { citation: "Michaud, R. (1989). The Markowitz Optimization Enigma: Is 'Optimized' Optimal? Financial Analysts Journal, 45(1), 31–42.", why: "The original critique." },
      { citation: "Ledoit, O. & Wolf, M. (2004). Honey, I Shrunk the Sample Covariance Matrix. Journal of Portfolio Management, 30(4), 110–119.", why: "Shrinkage, practically explained." },
      { citation: "DeMiguel, V., Garlappi, L. & Uppal, R. (2009). Optimal Versus Naive Diversification. Review of Financial Studies, 22(5), 1915–1953.", why: "How hard 1/N is to beat." },
      { citation: "Black, F. & Litterman, R. (1992). Global Portfolio Optimization. Financial Analysts Journal, 48(5), 28–43.", why: "Equilibrium plus views." },
      { citation: "Maillard, S., Roncalli, T. & Teïletche, J. (2010). The Properties of Equally Weighted Risk Contribution Portfolios. Journal of Portfolio Management, 36(4), 60–70.", why: "Risk parity formalised." },
    ],
  },
  {
    week: 4,
    title: "Backtesting and execution strategies",
    hook: "A backtest is not a research tool. It is a way of finding out whether you fooled yourself.",
    hours: 6,
    lessons: [
      {
        title: "Backtest overfitting and the deflated Sharpe ratio",
        minutes: 40,
        summary: "Try enough variations and pure noise will hand you a Sharpe of 2.",
        body: [
          "If you test N independent strategies with zero true skill, the best one will still show a positive Sharpe ratio, and that expected maximum grows with N. Bailey & López de Prado (2014) derived it and proposed the deflated Sharpe ratio: the probability that your observed Sharpe is genuinely above that noise threshold.",
          "Move the slider. With 10 trials over five years, noise alone produces an expected best annualised Sharpe around 0.7. With 1,000 trials it is around 1.5. This is why logging every trial in Module 2 matters.",
          "Practical defences: walk-forward validation, combinatorially purged cross-validation, an untouched hold-out period, economic priors that come before the data, and a hard limit on the number of variants.",
        ],
        formula: {
          label: "Expected maximum Sharpe under the null",
          expression: "E[max SR] ≈ σ_SR · [(1 − γ)·Φ⁻¹(1 − 1/N) + γ·Φ⁻¹(1 − 1/(N·e))]",
          note: "N is the number of trials, γ ≈ 0.5772 (Euler–Mascheroni), Φ⁻¹ the inverse normal CDF and σ_SR the standard deviation of Sharpe estimates across trials.",
        },
        visual: "deflated-sharpe",
        takeaway: "Report the number of trials alongside every Sharpe ratio. Without it, the Sharpe is unreadable.",
      },
      {
        title: "Transaction costs and market impact",
        minutes: 35,
        summary: "Paper returns vs real returns: spread, commission, stamp duty and impact.",
        body: [
          "Perold (1988) called the gap between paper and real portfolios 'implementation shortfall'. Costs have a fixed part (commissions, exchange fees and, in Hong Kong, stamp duty on both sides of a stock trade), the bid–ask spread, and market impact, which grows with trade size.",
          "Empirically, impact grows roughly with the square root of the fraction of daily volume you trade (Tóth et al., 2011). In the chart, a stock with 2% daily volatility costs about 14 bps of impact at 1% of daily volume and about 70 bps at 25%: five times more, not 25 times more. On top of that sit fixed costs, here 10 bps of stamp duty, a half-spread and commission.",
          "Use the chart to see how quickly a 'profitable' high-turnover strategy loses its edge once impact is included.",
        ],
        formula: {
          label: "Square-root impact model",
          expression: "Impact ≈ Y · σ_daily · √(Q / V)",
          note: "Q is order size, V daily volume, σ_daily daily volatility and Y a constant of order 1, calibrated to your own fills.",
        },
        visual: "impact",
        takeaway: "Model costs before you fall in love with a signal. Turnover is the silent killer of factor strategies.",
      },
      {
        title: "Optimal execution",
        minutes: 30,
        summary: "Trade fast and pay impact, or trade slowly and bear price risk. Almgren–Chriss finds the balance.",
        body: [
          "Almgren & Chriss (2000) framed execution as a trade-off: trading quickly minimises exposure to price moves but maximises impact; trading slowly does the opposite. The optimal schedule depends on your urgency (risk aversion), the stock's volatility and its liquidity.",
          "In practice this becomes the choice between VWAP, TWAP, implementation-shortfall and liquidity-seeking algorithms, plus where to trade around the Hong Kong closing auction.",
        ],
        takeaway: "Execution is part of the strategy. A signal that only works with free trading does not work.",
      },
      {
        title: "Trading in Hong Kong: market structure for quants",
        minutes: 35,
        summary: "Stamp duty, board lots, short-selling rules, the closing auction and Stock Connect, and what each does to a backtest.",
        body: [
          "Costs. Hong Kong charges stamp duty of 0.1% on each side of a stock trade (cut from 0.13% in November 2023), on top of commission, exchange and regulatory levies, and the spread. A strategy turning over 200% a year pays roughly 0.4% a year in stamp duty alone, before any market impact.",
          "Board lots and short selling. Shares trade in board lots that differ from stock to stock, so small or high-priced positions round badly and odd lots trade at worse prices. Short selling is only allowed in designated securities and is subject to a tick rule, so a long–short backtest that shorts any name freely is not implementable here.",
          "Closing auction and settlement. The closing auction session concentrates liquidity at the close, which matters for index rebalances and benchmark-relative trading. Trades settle T+2.",
          "Dual listings and Stock Connect. Many mainland companies list H-shares in Hong Kong and A-shares in Shanghai or Shenzhen. The two lines can trade at a persistent gap (the AH premium), and Stock Connect flows, northbound and southbound, can move prices independently of fundamentals. Treat each line as a separate asset with its own liquidity and its own investor base.",
          "Index events. Hang Seng index reviews are announced in advance and implemented on fixed dates, which creates predictable, crowded flows around rebalances. A backtest that trades at index-change closes should include the impact of everyone else trading at the same moment.",
        ],
        code: `# Hong Kong cost model for the Lab 4 backtest (one side, as a fraction)
STAMP_DUTY = 0.0010           # both buyer and seller
COMMISSION = 0.0003           # negotiated; check your broker
HALF_SPREAD = 0.0005          # large caps; widen for small caps
def hk_cost(participation, daily_vol, y=0.7):
    impact = y * daily_vol * participation ** 0.5
    return STAMP_DUTY + COMMISSION + HALF_SPREAD + impact

def round_to_lot(shares, board_lot):
    return (shares // board_lot) * board_lot`,
        takeaway: "Model Hong Kong as it is traded: lots, shorting rules, stamp duty and the close, not as a frictionless return series.",
      },
    ],
    lab: {
      title: "Lab 4 · An honest backtest",
      brief: "Log 18 variants of a long-only momentum strategy with Hong Kong-style costs (25 bps per side, including 10 bps stamp duty), choose one using 1991–2010 only, evaluate it from 2011, and compute its deflated Sharpe ratio.",
      deliverable: "Completed notebook: trial log, in- vs out-of-sample Sharpe and the deflated Sharpe ratio.",
      notebook: "lab4-honest-backtest",
      code: "FINEX-LAB4-A11697",
      findings: [
        "The best of 18 variants had a net Sharpe of 0.53 in 1991–2010, and 0.22 from 2011.",
        "It still passed the deflated Sharpe test in-sample (0.98): a strategy can be genuinely selected and still decay.",
        "At about 240% annual turnover, costs alone take roughly 1.2% a year.",
      ],
    },
    check: {
      question: "You tested 200 strategy variants and report the best Sharpe ratio of 1.3. What is missing?",
      options: [
        "The strategy's beta",
        "An adjustment for the number of trials",
        "The maximum drawdown only",
        "Nothing, 1.3 is significant",
      ],
      answer: 1,
      explanation: "The best of 200 noisy trials is biased upward. The deflated Sharpe ratio corrects for the number of trials.",
    },
    readings: [
      { citation: "Bailey, D. & López de Prado, M. (2014). The Deflated Sharpe Ratio. Journal of Portfolio Management, 40(5), 94–107.", why: "Correcting for multiple testing." },
      { citation: "López de Prado, M. (2018). Advances in Financial Machine Learning. Wiley.", why: "Purged cross-validation and backtest hygiene." },
      { citation: "Perold, A. (1988). The Implementation Shortfall: Paper versus Reality. Journal of Portfolio Management, 14(3), 4–9.", why: "Measuring real costs." },
      { citation: "Almgren, R. & Chriss, N. (2000). Optimal execution of portfolio transactions. Journal of Risk, 3(2), 5–39.", why: "The execution trade-off." },
    ],
  },
  {
    week: 5,
    title: "Performance attribution",
    hook: "Was it skill, luck or a factor you did not know you owned?",
    hours: 6,
    lessons: [
      {
        title: "Brinson attribution",
        minutes: 35,
        summary: "Split active return into allocation, selection and interaction.",
        body: [
          "Brinson, Hood & Beebower (1986) decompose active return by segment (sector, country). Allocation asks whether you overweighted segments that beat the benchmark. Selection asks whether you picked better stocks within each segment. Interaction is the cross-term.",
          "The worked example in the chart uses four Hong Kong sectors. The portfolio returns 8.30% against the benchmark's 6.50%, an active return of 1.80%. Allocation adds 0.90%, almost all from underweighting property, which lagged. Selection adds 0.88%, mostly from better stocks in financials. Interaction is close to zero.",
        ],
        formula: {
          label: "Brinson–Fachler decomposition, per segment i",
          expression: "Alloc = (wᵢᴾ − wᵢᴮ)(Rᵢᴮ − Rᴮ) · Sel = wᵢᴮ(Rᵢᴾ − Rᵢᴮ) · Inter = (wᵢᴾ − wᵢᴮ)(Rᵢᴾ − Rᵢᴮ)",
          note: "The three effects sum exactly to the active return Rᴾ − Rᴮ.",
        },
        visual: "attribution",
        takeaway: "Attribution turns 'we outperformed' into 'we outperformed because…', the sentence a committee actually needs.",
      },
      {
        title: "Factor-based attribution and risk-adjusted metrics",
        minutes: 35,
        summary: "Separate deliberate factor bets from stock-specific skill.",
        body: [
          "Regress active returns on factor returns using your risk model's exposures. The portion explained by factors (style, industry, country, currency) is beta you could buy cheaply. The residual is specific return, the part closest to genuine skill.",
          "Report information ratio, tracking error, hit rate, up/down capture and maximum drawdown together. Any single metric can be flattering on its own. Follow GIPS principles for presenting composites to clients.",
        ],
        takeaway: "Know what you were paid for. Charge for skill, not for factor exposure a client could buy cheaply.",
      },
    ],
    lab: {
      title: "Lab 5 · Explain a decade of returns",
      brief: "Attribute the momentum strategy's returns since 2011 against a market-cap benchmark: Brinson–Fachler by size segment every month, then a regression on the Asia-Pacific five factors plus momentum.",
      deliverable: "Completed notebook and a one-page narrative of what you were paid for.",
      notebook: "lab5-attribution",
      code: "FINEX-LAB5-997117",
      findings: [
        "Active return was +0.37% a year, almost all from selection within size segments (+0.54%).",
        "Six factors explain 92% of the strategy's variance, and the remaining alpha is 0.12% a year (t = 0.09): factor exposure, not skill.",
        "The strategy carried more size (0.33) and value (0.17) exposure than momentum (0.07), which is worth knowing before you call it a momentum fund.",
      ],
    },
    check: {
      question: "You overweight a sector that underperformed the benchmark, but your stocks in it did very well. Which effect is negative?",
      options: ["Selection", "Allocation", "Both", "Neither"],
      answer: 1,
      explanation: "Overweighting an underperforming sector gives a negative allocation effect. Picking stocks that beat the sector gives a positive selection effect.",
    },
    readings: [
      { citation: "Brinson, G., Hood, L. & Beebower, G. (1986). Determinants of Portfolio Performance. Financial Analysts Journal, 42(4), 39–44.", why: "The attribution framework." },
      { citation: "Carhart, M. (1997). On Persistence in Mutual Fund Performance. Journal of Finance, 52(1), 57–82.", why: "Momentum explains much apparent manager skill." },
      { citation: "CFA Institute. Global Investment Performance Standards (GIPS®).", why: "How to present performance to clients." },
    ],
  },
  {
    week: 6,
    title: "Final portfolio case study",
    hook: "Put it all together and defend it in front of an investment committee.",
    hours: 6,
    lessons: [
      {
        title: "Building the capstone portfolio",
        minutes: 60,
        summary: "From signal library to a constrained, cost-aware APAC portfolio.",
        body: [
          "Combine your Module 2 signals into Black–Litterman views, use your shrunk risk model, impose the mandate constraints (4% tracking error, 30% turnover, long-only, 5% single-name cap) and run an honest walk-forward backtest.",
          "Stress-test it: 2008, the 2015 China sell-off, March 2020 and the 2022 rate shock. What happens to tracking error when correlations go to one?",
        ],
        takeaway: "A portfolio is a set of trade-offs you can explain, not a number an optimiser hands you.",
      },
      {
        title: "The investment committee",
        minutes: 45,
        summary: "Present the thesis, the risks and the evidence in ten minutes.",
        body: [
          "Structure: the mandate, the thesis in one sentence, the evidence (with the deflated Sharpe), the risk budget, the costs, what would make you wrong, and how you will monitor it.",
          "The committee, a panel of practitioners, will push on your weakest assumption. Prepare the answer to 'why will this keep working?'",
        ],
        takeaway: "Conviction comes from having already argued against yourself.",
      },
    ],
    lab: {
      title: "Capstone presentation",
      brief: "Start from the capstone template notebook, submit your notebook, memo and slides below, then present live to the investment committee panel. A reviewer returns written feedback and a score.",
      deliverable: "Notebook, two-page memo, 10-minute presentation.",
      notebook: "capstone-template",
    },
    check: {
      question: "During the 2008 crisis many factor portfolios suffered larger losses than their risk models predicted. The main reason was:",
      options: [
        "Too many positions",
        "Correlations rose sharply, so diversification failed when it was needed",
        "Stamp duty increased",
        "The benchmark changed",
      ],
      answer: 1,
      explanation: "Risk models estimated in calm periods underestimate co-movement in crises. Stress tests and regime-aware covariance help.",
    },
    readings: [
      { citation: "López de Prado, M. (2016). Building Diversified Portfolios that Outperform Out of Sample. Journal of Portfolio Management, 42(4), 59–69.", why: "Hierarchical Risk Parity." },
      { citation: "Frazzini, A. & Pedersen, L. (2014). Betting Against Beta. Journal of Financial Economics, 111(1), 1–25.", why: "Leverage constraints and the low-risk anomaly." },
    ],
  },
];

export const QUANT_LESSON_COUNT = QUANT_MODULES.reduce(
  (sum, module) => sum + module.lessons.length,
  0,
);
