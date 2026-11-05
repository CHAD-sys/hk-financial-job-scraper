import { useId, useMemo, useState, type ReactNode } from "react";
import {
  FRONTIER_ASSETS,
  PARITY_ASSETS,
  SHRINK_ASSETS,
  brinson,
  costBps,
  covariance,
  expectedMaxSharpe,
  frontierGeometry,
  minVariance,
  portfolioVol,
  riskContributions,
  riskParity,
  shrunkCovariance,
} from "./quantMath";
import type { VisualId } from "./quant";

const W = 560;
const H = 300;
const PAD = { l: 52, r: 18, t: 18, b: 42 };
const pct = (x: number, d = 1) => `${(x * 100).toFixed(d)}%`;

function Figure({
  title,
  caption,
  controls,
  readout,
  children,
}: {
  title: string;
  caption: string;
  controls?: ReactNode;
  readout?: ReactNode;
  children: ReactNode;
}) {
  return (
    <figure className="qv-figure">
      <figcaption className="qv-figure__head">
        <strong>{title}</strong>
        <span>{controls ? "Interactive" : "Worked example"} · illustrative inputs</span>
      </figcaption>
      <div className="qv-figure__chart">{children}</div>
      {(controls || readout) && (
        <div className="qv-figure__controls">
          {controls}
          {readout && <div className="qv-readout">{readout}</div>}
        </div>
      )}
      <p className="qv-figure__caption">{caption}</p>
    </figure>
  );
}

function Slider({
  label,
  value,
  min,
  max,
  step,
  format,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format: (v: number) => string;
  onChange: (v: number) => void;
}) {
  const id = useId();
  return (
    <label className="qv-slider" htmlFor={id}>
      <span>
        {label} <output>{format(value)}</output>
      </span>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  );
}

function Axes({
  xTicks,
  yTicks,
  x,
  y,
  xLabel,
  yLabel,
}: {
  xTicks: { v: number; label: string }[];
  yTicks: { v: number; label: string }[];
  x: (v: number) => number;
  y: (v: number) => number;
  xLabel: string;
  yLabel: string;
}) {
  return (
    <g className="qv-axes">
      {yTicks.map((t) => (
        <g key={`y${t.v}`}>
          <line x1={PAD.l} x2={W - PAD.r} y1={y(t.v)} y2={y(t.v)} className="qv-grid" />
          <text x={PAD.l - 8} y={y(t.v) + 4} textAnchor="end">
            {t.label}
          </text>
        </g>
      ))}
      {xTicks.map((t) => (
        <text key={`x${t.v}`} x={x(t.v)} y={H - PAD.b + 18} textAnchor="middle">
          {t.label}
        </text>
      ))}
      <line x1={PAD.l} x2={W - PAD.r} y1={H - PAD.b} y2={H - PAD.b} className="qv-axis" />
      <text x={(PAD.l + W - PAD.r) / 2} y={H - 6} textAnchor="middle" className="qv-axis-label">
        {xLabel}
      </text>
      <text
        transform={`translate(13 ${(PAD.t + H - PAD.b) / 2}) rotate(-90)`}
        textAnchor="middle"
        className="qv-axis-label"
      >
        {yLabel}
      </text>
    </g>
  );
}

const linear = (d0: number, d1: number, r0: number, r1: number) => (v: number) =>
  r0 + ((v - d0) / (d1 - d0)) * (r1 - r0);

/* ------------------------------ 1. Frontier ------------------------------ */
function Frontier() {
  const [lambda, setLambda] = useState(4);
  const { mu, vols, corr, names } = FRONTIER_ASSETS;
  const g = useMemo(() => frontierGeometry(mu, covariance(vols, corr)), [mu, vols, corr]);
  const x = linear(0, 0.26, PAD.l, W - PAD.r);
  const y = linear(0, 0.08, H - PAD.b, PAD.t);
  const minMu = g.B / g.A;
  const curve: string[] = [];
  for (let m = 0; m <= 0.08; m += 0.0005) {
    const v = g.volAt(m);
    if (v <= 0.26) curve.push(`${x(v).toFixed(1)},${y(m).toFixed(1)}`);
  }
  const tMu = g.C / g.B;
  const tVol = Math.sqrt(g.C) / g.B;
  const pVol = Math.sqrt(g.C) / lambda;
  const pMu = g.C / lambda;
  const riskyShare = g.B / lambda;
  return (
    <Figure
      title="The efficient frontier and the capital market line"
      caption="Excess returns, unconstrained (shorting allowed). The gold point is the optimal mix of cash and the tangency portfolio for your risk aversion λ: w* = Σ⁻¹μ / λ."
      controls={
        <Slider label="Risk aversion λ" value={lambda} min={1.5} max={10} step={0.1} format={(v) => v.toFixed(1)} onChange={setLambda} />
      }
      readout={
        <>
          <span>Expected excess return <strong>{pct(pMu)}</strong></span>
          <span>Volatility <strong>{pct(pVol)}</strong></span>
          <span>In tangency portfolio <strong>{pct(riskyShare, 0)}</strong></span>
        </>
      }
    >
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Efficient frontier chart">
        <Axes
          x={x}
          y={y}
          xTicks={[0, 0.05, 0.1, 0.15, 0.2, 0.25].map((v) => ({ v, label: pct(v, 0) }))}
          yTicks={[0, 0.02, 0.04, 0.06, 0.08].map((v) => ({ v, label: pct(v, 0) }))}
          xLabel="Volatility (σ)"
          yLabel="Expected excess return"
        />
        <line x1={x(0)} y1={y(0)} x2={x(0.26)} y2={y(0.26 * g.maxSharpe)} className="qv-line qv-line--cml" />
        <polyline points={curve.join(" ")} className="qv-line qv-line--main" />
        {names.map((name, i) => (
          <g key={name}>
            <circle cx={x(vols[i])} cy={y(mu[i])} r={4} className="qv-dot qv-dot--muted" />
            <text x={x(vols[i]) + 7} y={y(mu[i]) + 4} className="qv-note">
              {name}
            </text>
          </g>
        ))}
        <circle cx={x(g.volAt(minMu))} cy={y(minMu)} r={4} className="qv-dot" />
        <text x={x(g.volAt(minMu)) - 8} y={y(minMu) + 4} textAnchor="end" className="qv-note">
          Min variance
        </text>
        <circle cx={x(tVol)} cy={y(tMu)} r={5} className="qv-dot" />
        <text x={x(tVol) - 8} y={y(tMu) - 9} textAnchor="end" className="qv-note qv-note--strong">
          Tangency (max Sharpe {g.maxSharpe.toFixed(2)})
        </text>
        {pVol <= 0.26 && <circle cx={x(pVol)} cy={y(pMu)} r={7} className="qv-dot qv-dot--accent" />}
      </svg>
    </Figure>
  );
}

/* --------------------------- 2. Fundamental law --------------------------- */
function FundamentalLaw() {
  const [ic, setIc] = useState(0.05);
  const [breadth, setBreadth] = useState(200);
  const [tc, setTc] = useState(1);
  const lx = (b: number) => Math.log10(b);
  const x = linear(0, 3, PAD.l, W - PAD.r);
  const y = linear(0, 3, H - PAD.b, PAD.t);
  const line = (c: number) =>
    Array.from({ length: 61 }, (_, i) => {
      const b = 10 ** (i / 20);
      return `${x(lx(b)).toFixed(1)},${y(Math.min(3, tc * c * Math.sqrt(b))).toFixed(1)}`;
    }).join(" ");
  const ir = tc * ic * Math.sqrt(breadth);
  return (
    <Figure
      title="The fundamental law: IR ≈ TC · IC · √BR"
      caption="Each line is a constant level of skill (IC). Breadth is on a log scale. Lowering the transfer coefficient (constraints) pulls every line down."
      controls={
        <>
          <Slider label="Information coefficient" value={ic} min={0.01} max={0.2} step={0.01} format={(v) => v.toFixed(2)} onChange={setIc} />
          <Slider label="Independent bets / year" value={breadth} min={1} max={1000} step={1} format={(v) => v.toFixed(0)} onChange={setBreadth} />
          <Slider label="Transfer coefficient" value={tc} min={0.3} max={1} step={0.05} format={(v) => v.toFixed(2)} onChange={setTc} />
        </>
      }
      readout={<span>Expected information ratio <strong>{ir.toFixed(2)}</strong></span>}
    >
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Information ratio against breadth">
        <Axes
          x={x}
          y={y}
          xTicks={[0, 1, 2, 3].map((v) => ({ v, label: String(10 ** v) }))}
          yTicks={[0, 0.5, 1, 1.5, 2, 2.5, 3].map((v) => ({ v, label: v.toFixed(1) }))}
          xLabel="Breadth (independent bets per year, log scale)"
          yLabel="Information ratio"
        />
        {[0.02, 0.05, 0.1].map((c) => (
          <g key={c}>
            <polyline points={line(c)} className="qv-line qv-line--muted" />
            <text x={W - PAD.r - 4} y={y(Math.min(3, tc * c * Math.sqrt(1000))) - 6} textAnchor="end" className="qv-note">
              IC {c.toFixed(2)}
            </text>
          </g>
        ))}
        <polyline points={line(ic)} className="qv-line qv-line--main" />
        <circle cx={x(lx(breadth))} cy={y(Math.min(3, ir))} r={7} className="qv-dot qv-dot--accent" />
      </svg>
    </Figure>
  );
}

/* ------------------------------ 3. Pipeline ------------------------------ */
function Pipeline() {
  const steps = [
    ["Point-in-time data", "Prices, fundamentals, index members"],
    ["Universe", "Liquidity & listing filters"],
    ["Raw signal", "Value · momentum · quality"],
    ["Clean", "Winsorise, z-score"],
    ["Neutralise", "Sector & beta residual"],
    ["Combine", "IC-weighted composite"],
    ["Evaluate", "Rank IC, decay, turnover"],
  ];
  return (
    <figure className="qv-figure">
      <figcaption className="qv-figure__head">
        <strong>The signal research pipeline</strong>
        <span>Week 2 workflow</span>
      </figcaption>
      <ol className="qv-pipeline">
        {steps.map(([title, detail], i) => (
          <li key={title}>
            <span>{String(i + 1).padStart(2, "0")}</span>
            <strong>{title}</strong>
            <small>{detail}</small>
          </li>
        ))}
      </ol>
      <p className="qv-figure__caption">
        Every step is a function of data known on the trade date. Each variant you run is logged as a trial for the deflated Sharpe ratio in Week 4.
      </p>
    </figure>
  );
}

/* ------------------------------ Bar helper ------------------------------ */
function Bars({
  rows,
  min,
  max,
  format,
}: {
  rows: { label: string; value: number; tone?: "accent" | "muted" | "negative" }[];
  min: number;
  max: number;
  format: (v: number) => string;
}) {
  const rowH = 38;
  const height = rows.length * rowH + 26;
  const left = 110;
  const x = linear(min, max, left, W - 60);
  return (
    <svg viewBox={`0 0 ${W} ${height}`} role="img" aria-label="Bar chart">
      <line x1={x(0)} x2={x(0)} y1={6} y2={height - 18} className="qv-axis" />
      {rows.map((row, i) => {
        const y0 = 12 + i * rowH;
        const x0 = Math.min(x(0), x(row.value));
        const width = Math.abs(x(row.value) - x(0));
        const negative = row.value < 0;
        return (
          <g key={row.label}>
            <text x={left - 10} y={y0 + 17} textAnchor="end" className="qv-note qv-note--strong">
              {row.label}
            </text>
            <rect
              x={x0}
              y={y0 + 4}
              width={Math.max(width, 1)}
              height={20}
              rx={4}
              className={`qv-bar qv-bar--${negative ? "negative" : row.tone ?? "accent"}`}
            />
            <text
              x={negative ? x0 - 6 : x0 + width + 6}
              y={y0 + 18}
              textAnchor={negative ? "end" : "start"}
              className="qv-note"
            >
              {format(row.value)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/* ------------------------------ 4. Shrinkage ------------------------------ */
function Shrinkage() {
  const [delta, setDelta] = useState(0);
  const { names, vols, corr } = SHRINK_ASSETS;
  const cov = shrunkCovariance(vols, corr, delta);
  const w = minVariance(cov);
  const gross = w.reduce((s, x) => s + Math.abs(x), 0);
  return (
    <Figure
      title="Minimum-variance weights as you shrink the covariance matrix"
      caption="Bank A and Bank B are 95% correlated in the sample. With no shrinkage the optimiser shorts one to fund the other, a bet on a correlation estimate. Shrinking toward constant correlation removes the bet."
      controls={
        <Slider label="Shrinkage intensity δ" value={delta} min={0} max={1} step={0.05} format={(v) => v.toFixed(2)} onChange={setDelta} />
      }
      readout={
        <>
          <span>Gross exposure <strong>{pct(gross, 0)}</strong></span>
          <span>Portfolio vol <strong>{pct(portfolioVol(w, cov))}</strong></span>
        </>
      }
    >
      <Bars
        rows={names.map((label, i) => ({ label, value: w[i] }))}
        min={-0.3}
        max={0.7}
        format={(v) => pct(v, 0)}
      />
    </Figure>
  );
}

/* ----------------------------- 5. Risk parity ----------------------------- */
function RiskParity() {
  const { names, vols, corr } = PARITY_ASSETS;
  const cov = useMemo(() => covariance(vols, corr), [vols, corr]);
  const options = useMemo(
    () => ({
      "60/40": [0.6, 0.4, 0, 0],
      "Equal weight": [0.25, 0.25, 0.25, 0.25],
      "Risk parity": riskParity(cov),
    }),
    [cov],
  );
  const [choice, setChoice] = useState<keyof typeof options>("60/40");
  const w = options[choice];
  const rc = riskContributions(w, cov);
  const vol = portfolioVol(w, cov);
  return (
    <Figure
      title="Capital weights vs risk contributions"
      caption="Light bars show where the money is; dark bars show where the risk is. Only risk parity makes them tell the same story about diversification."
      controls={
        <div className="qv-segment" role="radiogroup" aria-label="Portfolio">
          {(Object.keys(options) as (keyof typeof options)[]).map((key) => (
            <button
              key={key}
              type="button"
              role="radio"
              aria-checked={choice === key}
              className={choice === key ? "is-active" : ""}
              onClick={() => setChoice(key)}
            >
              {key}
            </button>
          ))}
        </div>
      }
      readout={<span>Portfolio volatility <strong>{pct(vol)}</strong></span>}
    >
      <svg viewBox={`0 0 ${W} 250`} role="img" aria-label="Weights and risk contributions">
        {names.map((name, i) => {
          const cx = 70 + i * 125;
          const base = 200;
          const hw = w[i] * 300;
          const hr = (rc[i] / vol) * 300;
          return (
            <g key={name}>
              <rect x={cx - 28} y={base - hw} width={26} height={Math.max(hw, 0.5)} rx={3} className="qv-bar qv-bar--muted" />
              <rect x={cx + 2} y={base - hr} width={26} height={Math.max(hr, 0.5)} rx={3} className="qv-bar qv-bar--ink" />
              <text x={cx - 15} y={base - hw - 6} textAnchor="middle" className="qv-note">{pct(w[i], 0)}</text>
              <text x={cx + 15} y={base - hr - 6} textAnchor="middle" className="qv-note qv-note--strong">{pct(rc[i] / vol, 0)}</text>
              <text x={cx} y={base + 22} textAnchor="middle" className="qv-note qv-note--strong">{name}</text>
            </g>
          );
        })}
        <line x1={20} x2={W - 20} y1={200} y2={200} className="qv-axis" />
        <g className="qv-legend" transform="translate(360 14)">
          <rect width={12} height={12} rx={2} className="qv-bar qv-bar--muted" />
          <text x={18} y={10}>Capital</text>
          <rect x={86} width={12} height={12} rx={2} className="qv-bar qv-bar--ink" />
          <text x={104} y={10}>Share of risk</text>
        </g>
      </svg>
    </Figure>
  );
}

/* --------------------------- 6. Deflated Sharpe --------------------------- */
function DeflatedSharpe() {
  const [trials, setTrials] = useState(50);
  const [years, setYears] = useState(5);
  const x = linear(0, 3, PAD.l, W - PAD.r);
  const y = linear(0, 2.5, H - PAD.b, PAD.t);
  const curve = Array.from({ length: 61 }, (_, i) => {
    const n = Math.max(2, 10 ** (i / 20));
    return `${x(Math.log10(n)).toFixed(1)},${y(Math.min(2.5, expectedMaxSharpe(n, years))).toFixed(1)}`;
  }).join(" ");
  const value = expectedMaxSharpe(trials, years);
  return (
    <Figure
      title="The best Sharpe ratio pure noise will give you"
      caption="Expected maximum annualised Sharpe ratio across N strategies with zero true skill (Bailey & López de Prado, 2014). Any backtest below the curve is indistinguishable from luck."
      controls={
        <>
          <Slider label="Strategies tried (N)" value={trials} min={2} max={1000} step={1} format={(v) => v.toFixed(0)} onChange={setTrials} />
          <Slider label="Backtest length (years)" value={years} min={1} max={20} step={1} format={(v) => v.toFixed(0)} onChange={setYears} />
        </>
      }
      readout={<span>Noise-only best Sharpe <strong>{value.toFixed(2)}</strong></span>}
    >
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Expected maximum Sharpe ratio against number of trials">
        <Axes
          x={x}
          y={y}
          xTicks={[0, 1, 2, 3].map((v) => ({ v, label: String(10 ** v) }))}
          yTicks={[0, 0.5, 1, 1.5, 2, 2.5].map((v) => ({ v, label: v.toFixed(1) }))}
          xLabel="Number of strategies tried (log scale)"
          yLabel="Expected best Sharpe"
        />
        <polygon points={`${x(Math.log10(2))},${y(0)} ${curve} ${x(3)},${y(0)}`} className="qv-area" />
        <polyline points={curve} className="qv-line qv-line--main" />
        <circle cx={x(Math.log10(trials))} cy={y(Math.min(2.5, value))} r={7} className="qv-dot qv-dot--accent" />
        <text x={x(0.4)} y={y(0.25)} className="qv-note">Zone of luck</text>
      </svg>
    </Figure>
  );
}

/* ------------------------------ 7. Impact ------------------------------ */
function Impact() {
  const [vol, setVol] = useState(0.02);
  const [turnover, setTurnover] = useState(300);
  const x = linear(0, 0.3, PAD.l, W - PAD.r);
  const y = linear(0, 150, H - PAD.b, PAD.t);
  const curve = Array.from({ length: 61 }, (_, i) => {
    const q = (i / 60) * 0.3;
    return `${x(q).toFixed(1)},${y(Math.min(150, costBps(q, vol))).toFixed(1)}`;
  }).join(" ");
  const at5 = costBps(0.05, vol);
  const drag = (at5 / 10000) * 2 * (turnover / 100);
  return (
    <Figure
      title="What a trade really costs (one side, Hong Kong equities)"
      caption="Fixed costs (10 bps stamp duty, ≈4 bps half-spread, ≈3 bps commission) plus square-root market impact with Y = 0.7. Annual drag assumes every trade is 5% of daily volume, buying and selling."
      controls={
        <>
          <Slider label="Daily volatility" value={vol} min={0.01} max={0.04} step={0.0025} format={(v) => pct(v, 2)} onChange={setVol} />
          <Slider label="Annual turnover" value={turnover} min={25} max={1000} step={25} format={(v) => `${v.toFixed(0)}%`} onChange={setTurnover} />
        </>
      }
      readout={
        <>
          <span>Cost at 5% of volume <strong>{at5.toFixed(0)} bps</strong></span>
          <span>Annual cost drag <strong>{pct(drag, 2)}</strong></span>
        </>
      }
    >
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Trading cost against participation rate">
        <Axes
          x={x}
          y={y}
          xTicks={[0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3].map((v) => ({ v, label: pct(v, 0) }))}
          yTicks={[0, 30, 60, 90, 120, 150].map((v) => ({ v, label: String(v) }))}
          xLabel="Order size as % of daily volume"
          yLabel="Cost (bps)"
        />
        <rect x={x(0)} y={y(17)} width={x(0.3) - x(0)} height={y(0) - y(17)} className="qv-area qv-area--muted" />
        <text x={x(0.2)} y={y(17) + 12} className="qv-note">Fixed costs</text>
        <polyline points={curve} className="qv-line qv-line--main" />
        <circle cx={x(0.05)} cy={y(at5)} r={7} className="qv-dot qv-dot--accent" />
      </svg>
    </Figure>
  );
}

/* ---------------------------- 8. Attribution ---------------------------- */
function Attribution() {
  const b = brinson();
  const steps = [
    { label: "Benchmark", value: b.RB, base: 0, total: true },
    { label: "Allocation", value: b.allocation, base: b.RB },
    { label: "Selection", value: b.selection, base: b.RB + b.allocation },
    { label: "Interaction", value: b.interaction, base: b.RB + b.allocation + b.selection },
    { label: "Portfolio", value: b.RP, base: 0, total: true },
  ];
  const y = linear(0, 0.09, 250, 20);
  return (
    <Figure
      title="Brinson attribution: where 1.80% of active return came from"
      caption="Four Hong Kong sectors, one year. Allocation came from underweighting property; selection came mostly from financials. The effects sum exactly to the active return."
    >
      <svg viewBox={`0 0 ${W} 290`} role="img" aria-label="Attribution waterfall">
        {[0, 0.02, 0.04, 0.06, 0.08].map((v) => (
          <g key={v} className="qv-axes">
            <line x1={50} x2={W - 10} y1={y(v)} y2={y(v)} className="qv-grid" />
            <text x={42} y={y(v) + 4} textAnchor="end">{pct(v, 0)}</text>
          </g>
        ))}
        {steps.map((s, i) => {
          const cx = 100 + i * 100;
          const top = y(s.base + Math.max(s.value, 0));
          const bottom = y(s.base + Math.min(s.value, 0));
          return (
            <g key={s.label}>
              <rect x={cx - 30} y={top} width={60} height={Math.max(bottom - top, 1.5)} rx={4} className={`qv-bar qv-bar--${s.total ? "ink" : "accent"}`} />
              <text x={cx} y={top - 7} textAnchor="middle" className="qv-note qv-note--strong">
                {s.total ? pct(s.value, 2) : `+${pct(s.value, 2)}`}
              </text>
              <text x={cx} y={274} textAnchor="middle" className="qv-note qv-note--strong">{s.label}</text>
            </g>
          );
        })}
      </svg>
      <table className="qv-table">
        <thead>
          <tr>
            <th>Sector</th>
            <th>Allocation</th>
            <th>Selection</th>
            <th>Interaction</th>
          </tr>
        </thead>
        <tbody>
          {b.bySector.map((row) => (
            <tr key={row.name}>
              <td>{row.name}</td>
              <td>{pct(row.allocation, 2)}</td>
              <td>{pct(row.selection, 2)}</td>
              <td>{pct(row.interaction, 2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Figure>
  );
}

const VISUALS: Record<VisualId, () => ReactNode> = {
  frontier: Frontier,
  "fundamental-law": FundamentalLaw,
  pipeline: Pipeline,
  shrinkage: Shrinkage,
  "risk-parity": RiskParity,
  "deflated-sharpe": DeflatedSharpe,
  impact: Impact,
  attribution: Attribution,
};

export default function QuantVisual({ id }: { id: VisualId }) {
  const Component = VISUALS[id];
  return <Component />;
}
