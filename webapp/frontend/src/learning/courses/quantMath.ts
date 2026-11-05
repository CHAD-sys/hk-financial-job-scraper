/**
 * Small, dependency-free linear algebra and finance helpers behind the
 * course visuals. Inputs are illustrative; the formulas are the real ones.
 */
export type Matrix = number[][];

export const covariance = (vols: number[], corr: Matrix): Matrix =>
  vols.map((vi, i) => vols.map((vj, j) => vi * vj * corr[i][j]));

export function invert(m: Matrix): Matrix {
  const n = m.length;
  const a = m.map((row, i) => [
    ...row,
    ...Array.from({ length: n }, (_, j) => (i === j ? 1 : 0)),
  ]);
  for (let col = 0; col < n; col++) {
    let pivot = col;
    for (let r = col + 1; r < n; r++)
      if (Math.abs(a[r][col]) > Math.abs(a[pivot][col])) pivot = r;
    [a[col], a[pivot]] = [a[pivot], a[col]];
    const p = a[col][col];
    for (let c = 0; c < 2 * n; c++) a[col][c] /= p;
    for (let r = 0; r < n; r++) {
      if (r === col) continue;
      const f = a[r][col];
      for (let c = 0; c < 2 * n; c++) a[r][c] -= f * a[col][c];
    }
  }
  return a.map((row) => row.slice(n));
}

export const mulVec = (m: Matrix, v: number[]) =>
  m.map((row) => row.reduce((s, x, j) => s + x * v[j], 0));
export const dot = (a: number[], b: number[]) =>
  a.reduce((s, x, i) => s + x * b[i], 0);
export const sum = (v: number[]) => v.reduce((s, x) => s + x, 0);
export const portfolioVol = (w: number[], cov: Matrix) =>
  Math.sqrt(dot(w, mulVec(cov, w)));

/** Unconstrained (shorting allowed) mean–variance geometry in excess returns. */
export function frontierGeometry(mu: number[], cov: Matrix) {
  const inv = invert(cov);
  const ones = mu.map(() => 1);
  const invOnes = mulVec(inv, ones);
  const invMu = mulVec(inv, mu);
  const A = sum(invOnes);
  const B = sum(invMu);
  const C = dot(mu, invMu);
  const D = A * C - B * B;
  const volAt = (m: number) => Math.sqrt((A * m * m - 2 * B * m + C) / D);
  const tangency = invMu.map((x) => x / B);
  return { A, B, C, D, volAt, tangency, maxSharpe: Math.sqrt(C), invMu };
}

/** Minimum-variance weights. */
export function minVariance(cov: Matrix) {
  const w = mulVec(invert(cov), cov.map(() => 1));
  const total = sum(w);
  return w.map((x) => x / total);
}

/** Risk contributions that sum to portfolio volatility. */
export function riskContributions(w: number[], cov: Matrix) {
  const vol = portfolioVol(w, cov);
  const marginal = mulVec(cov, w);
  return w.map((wi, i) => (wi * marginal[i]) / vol);
}

/** Equal-risk-contribution weights by multiplicative fixed-point iteration. */
export function riskParity(cov: Matrix) {
  let w = cov.map(() => 1 / cov.length);
  for (let k = 0; k < 500; k++) {
    const rc = riskContributions(w, cov);
    const target = sum(rc) / rc.length;
    w = w.map((wi, i) => wi * Math.sqrt(target / rc[i]));
    const total = sum(w);
    w = w.map((x) => x / total);
  }
  return w;
}

/** Acklam's rational approximation to the inverse normal CDF. */
export function inverseNormal(p: number): number {
  const a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.357751867269, -30.66479806614716, 2.506628277459239];
  const b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572];
  const c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
  const d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416];
  const lo = 0.02425;
  if (p < lo) {
    const q = Math.sqrt(-2 * Math.log(p));
    return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  }
  if (p > 1 - lo) return -inverseNormal(1 - p);
  const q = p - 0.5;
  const r = q * q;
  return ((((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q) / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
}

const EULER_GAMMA = 0.5772156649;

/** Bailey & López de Prado (2014): expected max Sharpe of N skill-less trials. */
export function expectedMaxSharpe(trials: number, years: number) {
  if (trials <= 1) return 0;
  const sigma = Math.sqrt(1 / years);
  return (
    sigma *
    ((1 - EULER_GAMMA) * inverseNormal(1 - 1 / trials) +
      EULER_GAMMA * inverseNormal(1 - 1 / (trials * Math.E)))
  );
}

/* ---------- Illustrative inputs shared by the page and the brochure ---------- */

export const FRONTIER_ASSETS = {
  names: ["HK equities", "Global equities", "Global bonds", "Gold"],
  mu: [0.06, 0.055, 0.015, 0.03],
  vols: [0.22, 0.16, 0.06, 0.15],
  corr: [
    [1, 0.65, 0.05, 0.1],
    [0.65, 1, 0.1, 0.05],
    [0.05, 0.1, 1, 0.3],
    [0.1, 0.05, 0.3, 1],
  ],
};

export const SHRINK_ASSETS = {
  names: ["Bank A", "Bank B", "Insurer", "Utility"],
  vols: [0.24, 0.22, 0.26, 0.2],
  corr: [
    [1, 0.95, 0.6, 0.35],
    [0.95, 1, 0.55, 0.4],
    [0.6, 0.55, 1, 0.3],
    [0.35, 0.4, 0.3, 1],
  ],
};

export const PARITY_ASSETS = {
  names: ["Equities", "Gov. bonds", "Credit", "Commodities"],
  vols: [0.16, 0.06, 0.09, 0.18],
  corr: [
    [1, 0, 0.6, 0.3],
    [0, 1, 0.4, -0.1],
    [0.6, 0.4, 1, 0.25],
    [0.3, -0.1, 0.25, 1],
  ],
};

/** Constant-correlation shrinkage target (Ledoit–Wolf 2004 style). */
export function shrunkCovariance(vols: number[], corr: Matrix, delta: number) {
  const n = vols.length;
  let total = 0;
  for (let i = 0; i < n; i++)
    for (let j = 0; j < n; j++) if (i !== j) total += corr[i][j];
  const avg = total / (n * (n - 1));
  const blended = corr.map((row, i) =>
    row.map((x, j) => (i === j ? 1 : delta * avg + (1 - delta) * x)),
  );
  return covariance(vols, blended);
}

export const ATTRIBUTION = {
  sectors: ["Financials", "Property", "Technology", "Consumer"],
  benchWeight: [0.4, 0.15, 0.3, 0.15],
  benchReturn: [0.08, -0.06, 0.12, 0.04],
  portWeight: [0.45, 0.08, 0.3, 0.17],
  portReturn: [0.1, -0.05, 0.12, 0.035],
};

export function brinson() {
  const { benchWeight: wb, benchReturn: rb, portWeight: wp, portReturn: rp } = ATTRIBUTION;
  const RB = dot(wb, rb);
  const RP = dot(wp, rp);
  const allocation = wb.map((_, i) => (wp[i] - wb[i]) * (rb[i] - RB));
  const selection = wb.map((_, i) => wb[i] * (rp[i] - rb[i]));
  const interaction = wb.map((_, i) => (wp[i] - wb[i]) * (rp[i] - rb[i]));
  return {
    RB,
    RP,
    active: RP - RB,
    allocation: sum(allocation),
    selection: sum(selection),
    interaction: sum(interaction),
    bySector: ATTRIBUTION.sectors.map((name, i) => ({
      name,
      allocation: allocation[i],
      selection: selection[i],
      interaction: interaction[i],
    })),
  };
}

/** Square-root impact + fixed HK costs, in basis points (one side). */
export function costBps(participation: number, dailyVol: number, y = 0.7) {
  const fixed = 10 + 4 + 3; // stamp duty 10bp, half-spread ~4bp, commission ~3bp
  return fixed + y * dailyVol * Math.sqrt(participation) * 10000;
}
