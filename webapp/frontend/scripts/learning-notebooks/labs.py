"""Lab content for Advanced Quantitative Portfolio Management.

Each lab is a list of cells:
  ("md", text)                markdown
  ("code", source)            code given to the learner
  ("ex", stub, solution)      an exercise: learners get `stub`, the solution
                              notebook gets `solution`
build.py turns these into a learner notebook (public) and a solution notebook
(kept out of the public folder), and executes the solutions to prove every
check passes on the live data.
"""

DATA_NOTE = (
    "**Data.** Monthly returns from the Kenneth R. French Data Library "
    "(Tuck School of Business, Dartmouth), *Asia Pacific ex Japan* region: Australia, "
    "**Hong Kong**, New Zealand and Singapore, July 1990 onwards. The setup cell downloads "
    "it once and caches it in `finex_data/`."
)

HOW_TO = (
    "**How this lab works.** Run the setup cell, then work top to bottom. Each exercise has a "
    "`# TODO` cell followed by an automatic check (✓ / ✗ with a hint). When every check passes, "
    "the last cell prints a **completion code**: paste it into the course page to complete the lab."
)

LAB1 = [
    ("md", """# Lab 1 · Replicate value and momentum in Asia-Pacific

**Week 1 · Portfolio foundations & factor investing** · ≈ 75 minutes

You will rebuild two of the most famous factors from their building blocks, measure them, and decide
whether they clear the t > 3 bar from Lesson 1.2.

1. Build HML (value) from six size/book-to-market portfolios
2. Build WML (momentum) from six size/prior-return portfolios
3. Annualise returns, volatility, Sharpe ratios and t-statistics
4. Measure the value–momentum correlation and the benefit of combining them
5. Test whether value is just market beta, with a CAPM regression

""" + DATA_NOTE + "\n\n" + HOW_TO),
    ("setup", None),
    ("code", """factors = load_french("Asia_Pacific_ex_Japan_3_Factors")          # Mkt-RF, SMB, HML, RF
wml = load_french("Asia_Pacific_ex_Japan_MOM_Factor")["WML"]          # published momentum
bm6 = load_french("Asia_Pacific_ex_Japan_6_Portfolios_ME_BE-ME", "Average Value Weighted Returns -- Monthly")
prior6 = load_french("Asia_Pacific_ex_Japan_6_Portfolios_ME_Prior_12_2", "Average Value Weighted Returns -- Monthly")

print(f"{factors.index[0]} → {factors.index[-1]} · {len(factors)} months")
bm6.tail()"""),
    ("md", """## Exercise 1 · Build HML

Fama and French define value as the average of the two *value* portfolios minus the average of the two
*growth* portfolios:

$$HML = \\tfrac12(\\text{Small Value} + \\text{Big Value}) - \\tfrac12(\\text{Small Growth} + \\text{Big Growth})$$

In `bm6`, value is `HiBM` and growth is `LoBM`."""),
    ("ex", """my_hml = None  # TODO: a monthly Series built from bm6""",
     """my_hml = 0.5 * (bm6["SMALL HiBM"] + bm6["BIG HiBM"]) - 0.5 * (bm6["SMALL LoBM"] + bm6["BIG LoBM"])"""),
    ("code", """check("HML replicates the published factor",
      isinstance(my_hml, pd.Series) and my_hml.corr(factors["HML"]) > 0.99,
      "average the two HiBM columns, subtract the average of the two LoBM columns")"""),
    ("md", """## Exercise 2 · Build WML

Momentum works the same way on portfolios sorted by return from month −12 to −2 (the most recent month
is skipped because of short-term reversal): winners `HiPRIOR` minus losers `LoPRIOR`."""),
    ("ex", """my_wml = None  # TODO: a monthly Series built from prior6""",
     """my_wml = 0.5 * (prior6["SMALL HiPRIOR"] + prior6["BIG HiPRIOR"]) - 0.5 * (prior6["SMALL LoPRIOR"] + prior6["BIG LoPRIOR"])"""),
    ("code", """check("WML replicates the published factor",
      isinstance(my_wml, pd.Series) and my_wml.corr(wml) > 0.99,
      "same recipe as HML, with HiPRIOR (winners) and LoPRIOR (losers)")"""),
    ("md", """## Exercise 3 · Measure the premia

Use the `annualise()` helper from the setup cell to build a table with one column per factor:
`MKT` (`Mkt-RF`), `SMB`, `HML` and `WML`. Then list the factors whose t-statistic is above 3, the
data-mining-adjusted hurdle proposed by Harvey, Liu & Zhu (2016)."""),
    ("ex", """stats = None          # TODO: DataFrame, rows = mean/vol/sharpe/t_stat/months, columns = MKT, SMB, HML, WML
passes_hurdle = None  # TODO: list of column names with t_stat > 3""",
     """stats = pd.DataFrame({
    "MKT": annualise(factors["Mkt-RF"]),
    "SMB": annualise(factors["SMB"]),
    "HML": annualise(factors["HML"]),
    "WML": annualise(wml),
})
passes_hurdle = stats.columns[stats.loc["t_stat"] > 3].tolist()
stats.round(3)"""),
    ("code", """reference = {k: annualise(v)["t_stat"] for k, v in
             {"MKT": factors["Mkt-RF"], "SMB": factors["SMB"], "HML": factors["HML"], "WML": wml}.items()}
check("Statistics table has the four factors",
      isinstance(stats, pd.DataFrame) and set(stats.columns) == set(reference),
      "columns should be MKT, SMB, HML and WML")
check("t-statistics are correct",
      all(np.isclose(stats.loc["t_stat", k], v) for k, v in reference.items()),
      "use annualise() on the monthly excess returns")
check("You found the factors that clear t > 3",
      sorted(passes_hurdle or []) == sorted(k for k, v in reference.items() if v > 3),
      "filter stats.columns on stats.loc['t_stat'] > 3")"""),
    ("md", """## Exercise 4 · Why value and momentum belong together

Compute the correlation between HML and WML, then the Sharpe ratio of a 50/50 combination."""),
    ("ex", """value_momentum_corr = None  # TODO
combo_sharpe = None         # TODO: annualised Sharpe of 0.5*HML + 0.5*WML""",
     """value_momentum_corr = factors["HML"].corr(wml)
combo_sharpe = annualise(0.5 * factors["HML"] + 0.5 * wml)["sharpe"]
print(f"Correlation {value_momentum_corr:.2f} · combined Sharpe {combo_sharpe:.2f}")"""),
    ("code", """check("Correlation is right",
      value_momentum_corr is not None and np.isclose(value_momentum_corr, factors["HML"].corr(wml)),
      "factors['HML'].corr(wml)")
check("The combination beats both factors on its own",
      combo_sharpe is not None and combo_sharpe > max(annualise(factors["HML"])["sharpe"], annualise(wml)["sharpe"]),
      "average the two monthly series first, then annualise")"""),
    ("md", """## Exercise 5 · Is value just market beta?

Regress HML on the market (`Mkt-RF`) with Newey–West (HAC, 6 lags) standard errors. If the intercept
(alpha) stays significant, value is not simply a disguised bet on the market."""),
    ("ex", """import statsmodels.api as sm

alpha_t = None  # TODO: t-statistic of the intercept""",
     """import statsmodels.api as sm

capm = sm.OLS(factors["HML"], sm.add_constant(factors[["Mkt-RF"]])).fit(cov_type="HAC", cov_kwds={"maxlags": 6})
alpha_t = capm.tvalues["const"]
print(capm.summary().tables[1])"""),
    ("code", """reference_t = sm.OLS(factors["HML"], sm.add_constant(factors[["Mkt-RF"]])).fit(
    cov_type="HAC", cov_kwds={"maxlags": 6}).tvalues["const"]
check("Alpha t-statistic is right", alpha_t is not None and np.isclose(alpha_t, reference_t),
      "sm.OLS(y, sm.add_constant(X)).fit(cov_type='HAC', cov_kwds={'maxlags': 6})")
completion_code("lab1")"""),
    ("md", """## Reflect (bring to Tuesday's session)

* Which factors clear t > 3 in Asia-Pacific, and does that match what you expected?
* Value and momentum are negatively correlated. What does that imply for a portfolio that holds both?
* SMB has been *negative* in this region. What explanations would you test before dropping it?"""),
]

LAB2 = [
    ("md", """# Lab 2 · A composite value-momentum-quality signal

**Week 2 · Building a research workflow** · ≈ 90 minutes

Your universe is the 25 size × book-to-market portfolios for Asia-Pacific ex Japan, treated as 25
tradable "assets". You will build three signals point-in-time, clean and size-neutralise them, measure
their information coefficients (IC), and combine them without look-ahead.

""" + DATA_NOTE + "\n\n" + HOW_TO),
    ("setup", None),
    ("code", """import warnings
warnings.filterwarnings("ignore")
from scipy.stats import spearmanr

returns = load_french("Asia_Pacific_ex_Japan_25_Portfolios_ME_BE-ME", "Average Value Weighted Returns -- Monthly")
names = returns.columns
size_bucket = pd.Series([i // 5 + 1 for i in range(25)], index=names)   # 1 = small … 5 = big
value_bucket = pd.Series([i % 5 + 1 for i in range(25)], index=names)  # 1 = growth … 5 = value
returns.iloc[-3:, :6]"""),
    ("md", """## Exercise 1 · A momentum signal with no look-ahead

At the end of month *t* the signal may only use returns up to *t*. Momentum is the compounded return
from month *t−11* to *t−1* (skip the latest month)."""),
    ("ex", """def momentum_signal(r):
    # TODO: DataFrame of the same shape as r
    raise NotImplementedError("Exercise 1: write momentum_signal, then re-run this cell")""",
     """def momentum_signal(r):
    growth = (1 + r).rolling(11).apply(np.prod, raw=True)
    return growth.shift(1) - 1"""),
    ("code", """full = momentum_signal(returns)
truncated = momentum_signal(returns.iloc[:200])
check("Momentum uses months t-11 … t-1",
      np.isclose(full.iloc[150, 0], (1 + returns.iloc[139:150, 0]).prod() - 1),
      "compound 11 months and shift by one so the latest month is skipped")
check("No look-ahead: future data does not change past signals",
      np.allclose(full.iloc[:200].dropna(), truncated.dropna()),
      "the signal at t must not use any return after t")"""),
    ("md", """## Exercise 2 · Clean and neutralise

Value is the portfolio's book-to-market bucket, and *low volatility* (a defensive quality proxy) is minus
the trailing 36-month volatility. For each signal: z-score across the 25 assets each month, then remove
size by regressing on size-bucket dummies and keeping the residual, then z-score again."""),
    ("code", """def zscore(df):
    return df.sub(df.mean(axis=1), axis=0).div(df.std(axis=1), axis=0)

dummies = pd.get_dummies(size_bucket).astype(float).values"""),
    ("ex", """def size_neutral(df):
    # TODO: per month, regress the row on `dummies` and keep the residual
    raise NotImplementedError("Exercise 2: write size_neutral, then re-run this cell")

value_raw = pd.DataFrame(np.tile(value_bucket.values, (len(returns), 1)), index=returns.index, columns=names).astype(float)
signals = {
    "momentum": None,  # TODO
    "value": None,     # TODO
    "low_vol": None,   # TODO
}""",
     """def size_neutral(df):
    out = df.copy() * np.nan
    for t, row in df.iterrows():
        if row.isna().any():
            continue
        beta, *_ = np.linalg.lstsq(dummies, row.values, rcond=None)
        out.loc[t] = row.values - dummies @ beta
    return out

value_raw = pd.DataFrame(np.tile(value_bucket.values, (len(returns), 1)), index=returns.index, columns=names).astype(float)
signals = {
    "momentum": zscore(size_neutral(zscore(momentum_signal(returns)))),
    "value": zscore(size_neutral(zscore(value_raw))),
    "low_vol": zscore(size_neutral(zscore(-returns.rolling(36).std()))),
}"""),
    ("code", """last = signals["momentum"].dropna().iloc[-1]
by_size = last.groupby(size_bucket).mean()
check("Signals are size-neutral", np.allclose(by_size, 0, atol=1e-8),
      "after neutralising, the average signal within every size bucket should be zero")
check("All three signals are present",
      all(isinstance(signals[k], pd.DataFrame) for k in ["momentum", "value", "low_vol"]),
      "fill in every entry of `signals`")"""),
    ("md", """## Exercise 3 · Rank information coefficient

The rank IC at month *t* is the Spearman correlation between the signal at *t* and the return in *t+1*.
Report the mean IC and its t-statistic for each signal."""),
    ("ex", """def rank_ic(signal, horizon=1):
    # TODO: Series of monthly Spearman ICs against the forward `horizon`-month return
    raise NotImplementedError("Exercise 3: write rank_ic, then re-run this cell")

ic_table = None  # TODO: DataFrame with rows = signals, columns = mean_ic, t_stat""",
     """def rank_ic(signal, horizon=1):
    forward = ((1 + returns).rolling(horizon).apply(np.prod, raw=True) - 1).shift(-horizon)
    out = {}
    for t in signal.index:
        a, b = signal.loc[t], forward.loc[t]
        ok = a.notna() & b.notna()
        if ok.sum() > 10:
            out[t] = spearmanr(a[ok], b[ok]).statistic
    return pd.Series(out)

ics = {k: rank_ic(v) for k, v in signals.items()}
ic_table = pd.DataFrame({k: {"mean_ic": s.mean(), "t_stat": s.mean() / s.std() * np.sqrt(len(s))}
                         for k, s in ics.items()}).T
ic_table.round(3)"""),
    ("code", """check("IC table covers the three signals",
      isinstance(ic_table, pd.DataFrame) and set(ic_table.index) == {"momentum", "value", "low_vol"},
      "one row per signal")
check("Every signal has a positive mean IC", (ic_table["mean_ic"] > 0).all(),
      "check the sign: higher signal should mean higher next-month return")"""),
    ("md", """## Exercise 4 · Combine without peeking

Weight each signal by its **average IC up to the previous month** (an expanding mean, shifted by one),
so the weights never use information from the future. Measure the composite's IC."""),
    ("ex", """composite = None      # TODO: DataFrame, IC-weighted sum of the three signals
composite_ic = None   # TODO: Series of monthly rank ICs of the composite""",
     """ic_frame = pd.DataFrame(ics)
weights = ic_frame.expanding(min_periods=24).mean().shift(1).clip(lower=0)
weights = weights.div(weights.sum(axis=1), axis=0)
composite = sum(signals[k].mul(weights[k], axis=0) for k in signals)
composite_ic = rank_ic(composite.dropna(how="all"))
print(f"Composite mean IC {composite_ic.mean():.3f} · t-stat {composite_ic.mean() / composite_ic.std() * np.sqrt(len(composite_ic)):.2f}")"""),
    ("code", """check("Composite IC is positive and significant",
      composite_ic is not None and composite_ic.mean() > 0 and composite_ic.mean() / composite_ic.std() * np.sqrt(len(composite_ic)) > 3,
      "weights from an expanding mean of past ICs, shifted by one month")
completion_code("lab2")"""),
    ("md", """## Reflect

* Value's IC *rises* with the horizon while momentum's stays flat. What does that say about how often each should be rebalanced?
* Why does the composite need `shift(1)` on its weights? What would happen to its IC without it?
* These are portfolios, not stocks. What would change with a real stock universe of Hong Kong names?"""),
]

LAB3 = [
    ("md", """# Lab 3 · Four portfolios, one universe

**Week 3 · Risk models and portfolio construction** · ≈ 90 minutes

Using a rolling 60-month window on the 25 Asia-Pacific portfolios, you will compare five constructions
out of sample: 1/N, sample minimum-variance, Ledoit–Wolf minimum-variance, equal risk contribution and
market-cap weights, and then reproduce the Black–Litterman starting point.

""" + DATA_NOTE + "\n\n" + HOW_TO),
    ("setup", None),
    ("code", """import warnings
warnings.filterwarnings("ignore")
from sklearn.covariance import LedoitWolf

returns = load_french("Asia_Pacific_ex_Japan_25_Portfolios_ME_BE-ME", "Average Value Weighted Returns -- Monthly")
firms = load_french("Asia_Pacific_ex_Japan_25_Portfolios_ME_BE-ME", "Number of Firms in Portfolios", percent=False)
avg_size = load_french("Asia_Pacific_ex_Japan_25_Portfolios_ME_BE-ME", "Average Firm Size", percent=False)
market_cap = firms * avg_size
cap_weights = market_cap.div(market_cap.sum(axis=1), axis=0)
WINDOW = 60"""),
    ("md", """## Exercise 1 · Minimum variance and equal risk contribution

* Minimum variance: $w \\propto \\Sigma^{-1}\\mathbf{1}$, scaled to sum to one (shorting allowed).
* Equal risk contribution: iterate $w_i \\leftarrow w_i \\sqrt{\\bar{RC} / RC_i}$ with $RC_i = w_i(\\Sigma w)_i$, renormalising each step."""),
    ("ex", """def min_variance(cov):
    raise NotImplementedError("Exercise 1: write min_variance")  # TODO

def equal_risk(cov, steps=500):
    raise NotImplementedError("Exercise 1: write equal_risk")  # TODO""",
     """def min_variance(cov):
    w = np.linalg.solve(cov, np.ones(len(cov)))
    return w / w.sum()

def equal_risk(cov, steps=500):
    w = np.ones(len(cov)) / len(cov)
    for _ in range(steps):
        rc = w * (cov @ w)
        w = w * np.sqrt(rc.mean() / rc)
        w = w / w.sum()
    return w"""),
    ("code", """test_cov = returns.iloc[-WINDOW:].cov().values
rc = equal_risk(test_cov) * (test_cov @ equal_risk(test_cov))
check("Minimum-variance weights sum to one", np.isclose(min_variance(test_cov).sum(), 1), "divide by the sum")
check("Equal risk contributions are equal", np.allclose(rc, rc.mean(), rtol=1e-4), "keep iterating the multiplicative update")"""),
    ("md", """## Exercise 2 · The out-of-sample horse race

Each month *t*, estimate on the previous 60 months, form the five portfolios, and record next month's
return and turnover (half the sum of absolute weight changes). Use `LedoitWolf().fit(window).covariance_`
for the shrunk matrix and `cap_weights` from the previous month."""),
    ("ex", """oos = None       # TODO: DataFrame of monthly returns, one column per construction
turnover = None  # TODO: Series of average monthly turnover per construction""",
     """records, turns, previous = [], [], {}
for i in range(WINDOW, len(returns)):
    window = returns.iloc[i - WINDOW:i]
    sample, shrunk = window.cov().values, LedoitWolf().fit(window.values).covariance_
    weights = {
        "1/N": np.ones(25) / 25,
        "sample min-var": min_variance(sample),
        "Ledoit-Wolf min-var": min_variance(shrunk),
        "equal risk": equal_risk(shrunk),
        "market cap": cap_weights.iloc[i - 1].values,
    }
    records.append({k: w @ returns.iloc[i].values for k, w in weights.items()})
    if previous:
        turns.append({k: np.abs(w - previous[k]).sum() / 2 for k, w in weights.items()})
    previous = weights
oos = pd.DataFrame(records, index=returns.index[WINDOW:])
turnover = pd.DataFrame(turns).mean()
summary = pd.DataFrame({"oos_vol": oos.std() * np.sqrt(12), "monthly_turnover": turnover,
                        "gross_exposure_now": {k: np.abs(w).sum() for k, w in previous.items()}})
summary.round(3)"""),
    ("code", """vol = oos.std() * np.sqrt(12)
check("Five constructions evaluated", isinstance(oos, pd.DataFrame) and oos.shape[1] == 5, "one column per portfolio")
check("Shrinkage beats the sample estimate out of sample", vol["Ledoit-Wolf min-var"] < vol["sample min-var"],
      "use LedoitWolf().fit(window.values).covariance_ for the shrunk version")
check("Shrinkage also cuts turnover", turnover["Ledoit-Wolf min-var"] < turnover["sample min-var"],
      "turnover = half the sum of absolute weight changes")"""),
    ("md", """## Exercise 3 · The Black–Litterman starting point

With risk aversion λ = 3, the implied excess returns are $\\Pi = \\lambda \\Sigma w_{mkt}$. Show that an
unconstrained mean–variance investor who believes Π holds exactly the market portfolio. Then solve a
long-only version with a 10% cap per asset using `cvxpy`."""),
    ("ex", """import cvxpy as cp

LAMBDA = 3.0
sigma = LedoitWolf().fit(returns.iloc[-WINDOW:].values).covariance_ * 12
w_mkt = cap_weights.iloc[-1].values
implied = None        # TODO: Π
w_unconstrained = None  # TODO: (λΣ)⁻¹ Π
w_long_only = None      # TODO: cvxpy, maximise Πᵀw − λ/2 wᵀΣw, w ≥ 0, w ≤ 0.10, sum = 1""",
     """import cvxpy as cp

LAMBDA = 3.0
sigma = LedoitWolf().fit(returns.iloc[-WINDOW:].values).covariance_ * 12
w_mkt = cap_weights.iloc[-1].values
implied = LAMBDA * sigma @ w_mkt
w_unconstrained = np.linalg.solve(LAMBDA * sigma, implied)
w = cp.Variable(25)
problem = cp.Problem(cp.Maximize(implied @ w - LAMBDA / 2 * cp.quad_form(w, cp.psd_wrap(sigma))),
                     [cp.sum(w) == 1, w >= 0, w <= 0.10])
problem.solve()
w_long_only = w.value
pd.Series(w_long_only, index=returns.columns).nlargest(8).round(3)"""),
    ("code", """check("Implied returns reproduce the market portfolio", np.allclose(w_unconstrained, w_mkt, atol=1e-8),
      "Π = λΣw_mkt, then solve (λΣ) w = Π")
check("Long-only solution respects the constraints",
      w_long_only is not None and np.isclose(w_long_only.sum(), 1, atol=1e-4) and w_long_only.min() > -1e-6 and w_long_only.max() < 0.10 + 1e-5,
      "constraints: sum to one, non-negative, at most 10%")
completion_code("lab3")"""),
    ("md", """## Reflect

* The sample minimum-variance portfolio is the 'optimal' one in-sample. Why is it the most volatile out of sample?
* Look at `gross_exposure_now`. Would a risk committee approve the sample portfolio?
* Which construction would you take into the capstone, and why?"""),
]

STRATEGY_CODE = '''def momentum_strategy(returns, lookback, top_k, hold):
    """Long-only: equal-weight the top_k portfolios by past return, rebalanced every `hold` months."""
    score = (1 + returns).rolling(lookback - 1).apply(np.prod, raw=True).shift(1) - 1
    rows, weights, w_prev = [], [], np.zeros(returns.shape[1])
    for i in range(lookback + 1, len(returns)):
        if (i - lookback - 1) % hold == 0:
            w = np.zeros(returns.shape[1])
            w[returns.columns.get_indexer(score.iloc[i - 1].nlargest(top_k).index)] = 1 / top_k
        else:                                  # let weights drift between rebalances
            w = w_prev * (1 + returns.iloc[i - 1].values)
            w = w / w.sum()
        turnover = np.abs(w - w_prev).sum() / 2 if i > lookback + 1 else 1.0
        rows.append((returns.index[i], w @ returns.iloc[i].values, turnover))
        weights.append(w)
        w_prev = w
    frame = pd.DataFrame(rows, columns=["month", "ret", "turnover"]).set_index("month")
    return frame, pd.DataFrame(weights, index=frame.index, columns=returns.columns)'''

LAB4 = [
    ("md", """# Lab 4 · An honest backtest

**Week 4 · Backtesting and execution** · ≈ 90 minutes

You will test 18 variants of a long-only momentum strategy on the 25 Asia-Pacific portfolios, choose
one using **only** 1991–2010, pay realistic Hong Kong-style trading costs, and then look at what happens
from 2011 onwards. Finally you will compute the deflated Sharpe ratio for your choice.

""" + DATA_NOTE + "\n\n" + HOW_TO),
    ("setup", None),
    ("code", """import warnings
warnings.filterwarnings("ignore")
from itertools import product
from scipy.stats import kurtosis, norm, skew

returns = load_french("Asia_Pacific_ex_Japan_25_Portfolios_ME_BE-ME", "Average Value Weighted Returns -- Monthly")
rf = load_french("Asia_Pacific_ex_Japan_3_Factors")["RF"]
COST_PER_SIDE = 0.0025   # 25 bps: 10 bps stamp duty + half-spread + commission + impact
TRAIN, TEST = slice("1991-01", "2010-12"), slice("2011-01", None)

""" + STRATEGY_CODE),
    ("md", """## Exercise 1 · Run every trial and log it

Grid: lookback ∈ {6, 9, 12}, top_k ∈ {3, 5, 8}, hold ∈ {1, 3} (18 trials). For each, compute the
monthly **net excess return** = return − rf − turnover × 2 × cost (buying and selling)."""),
    ("ex", """trials = None  # TODO: dict {(lookback, top_k, hold): net excess return Series}""",
     """trials = {}
for lookback, top_k, hold in product([6, 9, 12], [3, 5, 8], [1, 3]):
    result, _ = momentum_strategy(returns, lookback, top_k, hold)
    trials[(lookback, top_k, hold)] = result["ret"] - rf.reindex(result.index) - result["turnover"] * 2 * COST_PER_SIDE
print(f"{len(trials)} trials logged")"""),
    ("code", """check("All 18 trials logged", isinstance(trials, dict) and len(trials) == 18, "three lookbacks × three top_k × two holds")"""),
    ("md", """## Exercise 2 · Select in-sample, evaluate out-of-sample

Pick the trial with the highest **monthly** Sharpe ratio over `TRAIN` only, then report its annualised
Sharpe in `TRAIN` and in `TEST`."""),
    ("ex", """best = None        # TODO: the winning (lookback, top_k, hold)
train_sharpe = None  # TODO: annualised
test_sharpe = None   # TODO: annualised""",
     """def sharpe(x):
    return x.mean() / x.std()

best = max(trials, key=lambda key: sharpe(trials[key][TRAIN]))
train_sharpe = sharpe(trials[best][TRAIN]) * np.sqrt(12)
test_sharpe = sharpe(trials[best][TEST]) * np.sqrt(12)
print(f"Best {best}: Sharpe {train_sharpe:.2f} in 1991–2010 → {test_sharpe:.2f} from 2011")"""),
    ("code", """reference_best = max(trials, key=lambda k: trials[k][TRAIN].mean() / trials[k][TRAIN].std())
check("Selection used the training period only", best == reference_best,
      "rank trials on trials[key][TRAIN], never on the full sample")
check("Out-of-sample Sharpe is right",
      np.isclose(test_sharpe, trials[best][TEST].mean() / trials[best][TEST].std() * np.sqrt(12)),
      "annualise a monthly Sharpe with √12")"""),
    ("md", """## Exercise 3 · The deflated Sharpe ratio

Bailey & López de Prado (2014). With $\\hat{SR}$ the best *monthly* training Sharpe, $T$ its number of
months, γ₃ skewness and γ₄ (non-excess) kurtosis of its returns, and $SR_0$ the expected maximum Sharpe of
N skill-less trials:

$$SR_0 = \\sqrt{V[\\hat{SR}_n]}\\,\\Big[(1-\\gamma)\\Phi^{-1}(1-\\tfrac1N) + \\gamma\\,\\Phi^{-1}(1-\\tfrac{1}{Ne})\\Big],\\qquad
DSR = \\Phi\\!\\left(\\frac{(\\hat{SR}-SR_0)\\sqrt{T-1}}{\\sqrt{1-\\gamma_3\\hat{SR}+\\frac{\\gamma_4-1}{4}\\hat{SR}^2}}\\right)$$"""),
    ("ex", """dsr = None  # TODO: probability that the selected strategy's true Sharpe is above SR0""",
     """EULER = 0.5772156649
train_sharpes = np.array([sharpe(t[TRAIN]) for t in trials.values()])
N, x = len(train_sharpes), trials[best][TRAIN]
sr_hat, T = sharpe(x), len(x)
sr0 = train_sharpes.std(ddof=1) * ((1 - EULER) * norm.ppf(1 - 1 / N) + EULER * norm.ppf(1 - 1 / (N * np.e)))
dsr = norm.cdf((sr_hat - sr0) * np.sqrt(T - 1) / np.sqrt(1 - skew(x) * sr_hat + (kurtosis(x, fisher=False) - 1) / 4 * sr_hat ** 2))
print(f"SR0 (monthly) {sr0:.3f} · deflated Sharpe ratio {dsr:.3f}")"""),
    ("code", """check("Deflated Sharpe ratio is a probability", dsr is not None and 0 <= dsr <= 1, "wrap the statistic in norm.cdf")
check("Deflated Sharpe ratio is correctly computed", dsr is not None and np.isclose(dsr, _reference_dsr(trials, best, TRAIN), atol=1e-6),
      "use monthly Sharpe ratios, ddof=1 for the variance, and non-excess kurtosis")
completion_code("lab4")"""),
    ("md", """## Reflect

* Your choice passes the deflated Sharpe test in-sample, yet its Sharpe falls sharply after 2010. Name three explanations.
* What is the annual cost drag at your strategy's turnover? Would it survive a 50 bps cost assumption?
* Write the one sentence you would put in an investment memo about this backtest."""),
]
# Hidden reference for the DSR check, inserted into the setup of lab 4 only.
LAB4_REFERENCE = '''
def _reference_dsr(trials, best, train):
    from scipy.stats import kurtosis, norm, skew
    srs = np.array([t[train].mean() / t[train].std() for t in trials.values()])
    x = trials[best][train]
    s, n = x.mean() / x.std(), len(srs)
    sr0 = srs.std(ddof=1) * ((1 - 0.5772156649) * norm.ppf(1 - 1 / n) + 0.5772156649 * norm.ppf(1 - 1 / (n * np.e)))
    return norm.cdf((s - sr0) * np.sqrt(len(x) - 1) / np.sqrt(1 - skew(x) * s + (kurtosis(x, fisher=False) - 1) / 4 * s ** 2))
'''

LAB5 = [
    ("md", """# Lab 5 · Explain a decade of returns

**Week 5 · Performance attribution** · ≈ 75 minutes

Take the momentum strategy (lookback 6, top 5, hold 3) from 2011 onwards and explain its returns against a
market-cap benchmark of the same 25 portfolios: first with Brinson–Fachler by **size segment**, then with
a factor regression on the Asia-Pacific five factors plus momentum.

""" + DATA_NOTE + "\n\n" + HOW_TO),
    ("setup", None),
    ("code", """import warnings
warnings.filterwarnings("ignore")
import statsmodels.api as sm

returns = load_french("Asia_Pacific_ex_Japan_25_Portfolios_ME_BE-ME", "Average Value Weighted Returns -- Monthly")
firms = load_french("Asia_Pacific_ex_Japan_25_Portfolios_ME_BE-ME", "Number of Firms in Portfolios", percent=False)
avg_size = load_french("Asia_Pacific_ex_Japan_25_Portfolios_ME_BE-ME", "Average Firm Size", percent=False)
five = load_french("Asia_Pacific_ex_Japan_5_Factors")
wml = load_french("Asia_Pacific_ex_Japan_MOM_Factor")["WML"]
segment = pd.Series([f"Size {i // 5 + 1}" for i in range(25)], index=returns.columns)

""" + STRATEGY_CODE + """

result, weights = momentum_strategy(returns, lookback=6, top_k=5, hold=3)
cap = (firms * avg_size).shift(1)
bench_weights = cap.div(cap.sum(axis=1), axis=0).loc[weights.index]
period = slice("2011-01", None)
w_p, w_b, r = weights.loc[period], bench_weights.loc[period], returns.loc[weights.index].loc[period]"""),
    ("md", """## Exercise 1 · Brinson–Fachler by size segment, every month

For each month and segment *i*: segment weights $w_i$, segment returns $R_i$ (weight-averaged inside the
segment; use the benchmark return if the portfolio holds nothing there), total benchmark return $R^B$:

* Allocation $(w_i^P - w_i^B)(R_i^B - R^B)$
* Selection $w_i^B(R_i^P - R_i^B)$
* Interaction $(w_i^P - w_i^B)(R_i^P - R_i^B)$"""),
    ("ex", """effects = None  # TODO: DataFrame indexed by month with columns allocation, selection, interaction, active""",
     """def segment_view(w, rets):
    weight = w.T.groupby(segment).sum().T
    contrib = (w * rets).T.groupby(segment).sum().T
    return weight, contrib / weight.replace(0, np.nan)

wp_seg, rp_seg = segment_view(w_p, r)
wb_seg, rb_seg = segment_view(w_b, r)
rp_seg = rp_seg.fillna(rb_seg)
RB = (w_b * r).sum(axis=1)
effects = pd.DataFrame({
    "allocation": ((wp_seg - wb_seg) * rb_seg.sub(RB, axis=0)).sum(axis=1),
    "selection": (wb_seg * (rp_seg - rb_seg)).sum(axis=1),
    "interaction": ((wp_seg - wb_seg) * (rp_seg - rb_seg)).sum(axis=1),
    "active": (w_p * r).sum(axis=1) - RB,
})
(effects.mean() * 12).round(4)"""),
    ("code", """check("Effects sum to the active return every month",
      isinstance(effects, pd.DataFrame) and np.allclose(effects[["allocation", "selection", "interaction"]].sum(axis=1), effects["active"], atol=1e-10),
      "fill segment returns where the portfolio has no weight with the benchmark segment return")"""),
    ("md", """## Exercise 2 · What factors were you paid for?

Regress the strategy's monthly excess return (from 2011) on `Mkt-RF`, `SMB`, `HML`, `RMW`, `CMA` and `WML`
with HAC (6 lags) errors. Report the exposures, the annualised alpha and R²."""),
    ("ex", """factor_model = None  # TODO: fitted statsmodels results""",
     """excess = (result["ret"] - five["RF"].reindex(result.index)).loc[period]
X = pd.concat([five[["Mkt-RF", "SMB", "HML", "RMW", "CMA"]], wml.rename("WML")], axis=1).loc[excess.index]
factor_model = sm.OLS(excess, sm.add_constant(X)).fit(cov_type="HAC", cov_kwds={"maxlags": 6})
print(f"Annualised alpha {factor_model.params['const'] * 12:.2%} (t = {factor_model.tvalues['const']:.2f}) · R² {factor_model.rsquared:.2f}")
factor_model.params.round(3)"""),
    ("code", """check("Model includes all six factors",
      factor_model is not None and set(["Mkt-RF", "SMB", "HML", "RMW", "CMA", "WML"]) <= set(factor_model.params.index),
      "concatenate the five factors with WML")
check("A momentum strategy loads positively on WML", factor_model is not None and factor_model.params["WML"] > 0,
      "the exposure to WML should be positive")
completion_code("lab5")"""),
    ("md", """## Reflect: write the one-page narrative

1. Where did the active return come from: allocation across size segments, or selection within them?
2. Which factor exposures were intended, and which were accidental?
3. Is there alpha left after the six factors? Would you charge active fees for this strategy?"""),
]

CAPSTONE = [
    ("md", """# Capstone · An APAC multi-factor equity mandate

**Week 6 · Final portfolio case study**

**Mandate.** HK$2bn Asia-Pacific ex Japan equity, benchmarked to a market-cap index, 4% annual
tracking-error budget, 30% maximum annual one-way turnover, long-only, 5% maximum active weight per
position.

**In this template** the investable universe is the 25 size × book-to-market portfolios you have used all
course. If your firm gives you stock-level Hong Kong / APAC data, replace the universe in section 1 and
keep the rest of the structure.

""" + DATA_NOTE + """

### Submission checklist
- [ ] Every section below runs top to bottom without errors
- [ ] Your trial log is complete (section 4) and the deflated Sharpe ratio is reported
- [ ] Expected tracking error ≤ 4% and turnover ≤ 30% are demonstrated, not asserted
- [ ] Your two-page memo and slides reference the numbers in this notebook
- [ ] Submit the notebook link, memo and slides on the course page"""),
    ("setup", None),
    ("md", "## 1 · Universe and benchmark"),
    ("code", """returns = load_french("Asia_Pacific_ex_Japan_25_Portfolios_ME_BE-ME", "Average Value Weighted Returns -- Monthly")
firms = load_french("Asia_Pacific_ex_Japan_25_Portfolios_ME_BE-ME", "Number of Firms in Portfolios", percent=False)
avg_size = load_french("Asia_Pacific_ex_Japan_25_Portfolios_ME_BE-ME", "Average Firm Size", percent=False)
cap = (firms * avg_size).shift(1)
benchmark_weights = cap.div(cap.sum(axis=1), axis=0)
TE_BUDGET, TURNOVER_LIMIT, MAX_ACTIVE = 0.04, 0.30, 0.05"""),
    ("md", "## 2 · Signals (reuse Lab 2)\n\nBuild value, momentum and quality/low-vol signals point-in-time and combine them. State your weighting rule *before* looking at results."),
    ("code", "# TODO: signals and composite"),
    ("md", "## 3 · Risk model and portfolio construction (reuse Lab 3)\n\nShrunk covariance; maximise expected active return subject to the tracking-error, turnover and active-weight limits with `cvxpy`."),
    ("code", "# TODO: monthly optimisation loop"),
    ("md", "## 4 · Honest backtest (reuse Lab 4)\n\nLog every variant you try in `trial_log`. Report gross and net performance, turnover, and the deflated Sharpe ratio."),
    ("code", "trial_log = []  # append a dict for every variant you run\n# TODO: backtest"),
    ("md", "## 5 · Attribution and stress tests (reuse Lab 5)\n\nBrinson by size segment, factor regression, and drawdowns in 2008, 2015 and 2020."),
    ("code", "# TODO: attribution and stress tests"),
    ("md", "## 6 · Recommendation\n\nIn five bullet points: the thesis, the evidence, the risk budget, the costs, and what would make you wrong."),
]

LABS = {
    "lab1-value-momentum": LAB1,
    "lab2-composite-signal": LAB2,
    "lab3-four-portfolios": LAB3,
    "lab4-honest-backtest": LAB4,
    "lab5-attribution": LAB5,
    "capstone-template": CAPSTONE,
}
