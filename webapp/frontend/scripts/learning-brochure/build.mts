/**
 * Builds the HTML for the quant programme brochure and course summary from
 * the same data the course page renders. render.py prints them to PDF.
 *
 *   node scripts/learning-brochure/build.mts && python scripts/learning-brochure/render.py
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { COURSES, TRAINERS } from "../../src/learning/catalogue.ts";
import { QUANT_MODULES, QUANT_OVERVIEW, QUANT_LESSON_COUNT } from "../../src/learning/courses/quant.ts";
import {
  FRONTIER_ASSETS,
  PARITY_ASSETS,
  brinson,
  covariance,
  expectedMaxSharpe,
  frontierGeometry,
  portfolioVol,
  riskContributions,
  riskParity,
} from "../../src/learning/courses/quantMath.ts";

const here = dirname(fileURLToPath(import.meta.url));
const out = resolve(here, "out");
const fonts = resolve(here, "../../public/learning-assets/fonts");
mkdirSync(out, { recursive: true });

const course = COURSES.find((c) => c.id === "quant")!;
const trainer = TRAINERS.find((t) => t.id === course.trainerId)!;
const hkd = (n: number) => `HK$${n.toLocaleString("en-HK")}`;
const pct = (x: number, d = 0) => `${(x * 100).toFixed(d)}%`;
const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const lin = (d0: number, d1: number, r0: number, r1: number) => (v: number) => r0 + ((v - d0) / (d1 - d0)) * (r1 - r0);

const C = {
  ink: "#17243a",
  muted: "#4c5c6e",
  faint: "#6b7787",
  line: "#dcdedc",
  soft: "#e6e6e0",
  gold: "#dfc28e",
  accent: "#805d23",
  paper: "#faf9f6",
  raised: "#f2f1ec",
  green: "#2c6a4e",
};

/* ------------------------------ Charts ------------------------------ */
function frontierSvg(w = 520, h = 300, dark = false) {
  const pad = { l: 44, r: 14, t: 14, b: 36 };
  const { mu, vols, corr, names } = FRONTIER_ASSETS;
  const g = frontierGeometry(mu, covariance(vols, corr));
  const x = lin(0, 0.26, pad.l, w - pad.r);
  const y = lin(0, 0.08, h - pad.b, pad.t);
  const fg = dark ? "#f7f5ee" : C.ink;
  const grid = dark ? "#33425a" : C.soft;
  const text = dark ? "#c2cbd8" : C.faint;
  const pts: string[] = [];
  for (let m = 0; m <= 0.08; m += 0.0005) {
    const v = g.volAt(m);
    if (v <= 0.26) pts.push(`${x(v).toFixed(1)},${y(m).toFixed(1)}`);
  }
  const tMu = g.C / g.B, tVol = Math.sqrt(g.C) / g.B, minMu = g.B / g.A;
  let s = `<svg viewBox="0 0 ${w} ${h}" xmlns="http://www.w3.org/2000/svg" font-family="DM Sans">`;
  for (const v of [0, 0.02, 0.04, 0.06, 0.08])
    s += `<line x1="${pad.l}" x2="${w - pad.r}" y1="${y(v)}" y2="${y(v)}" stroke="${grid}"/><text x="${pad.l - 7}" y="${y(v) + 3.5}" font-size="10" fill="${text}" text-anchor="end">${pct(v)}</text>`;
  for (const v of [0, 0.05, 0.1, 0.15, 0.2, 0.25])
    s += `<text x="${x(v)}" y="${h - pad.b + 16}" font-size="10" fill="${text}" text-anchor="middle">${pct(v)}</text>`;
  s += `<text x="${(pad.l + w) / 2}" y="${h - 4}" font-size="10" fill="${text}" text-anchor="middle">Volatility</text>`;
  s += `<line x1="${x(0)}" y1="${y(0)}" x2="${x(0.26)}" y2="${y(0.26 * g.maxSharpe)}" stroke="${C.gold}" stroke-width="1.5" stroke-dasharray="6 5"/>`;
  s += `<polyline points="${pts.join(" ")}" fill="none" stroke="${fg}" stroke-width="2.4" stroke-linecap="round"/>`;
  names.forEach((n, i) => {
    s += `<circle cx="${x(vols[i])}" cy="${y(mu[i])}" r="3.5" fill="${text}"/><text x="${x(vols[i]) + 6}" y="${y(mu[i]) + 3.5}" font-size="10" fill="${text}">${n}</text>`;
  });
  s += `<circle cx="${x(g.volAt(minMu))}" cy="${y(minMu)}" r="4" fill="${fg}"/>`;
  s += `<circle cx="${x(tVol)}" cy="${y(tMu)}" r="6" fill="${C.gold}" stroke="${dark ? "#f7f5ee" : C.accent}" stroke-width="1.5"/>`;
  s += `<text x="${x(tVol) - 9}" y="${y(tMu) - 8}" font-size="10.5" fill="${fg}" text-anchor="end" font-weight="500">Tangency · max Sharpe ${g.maxSharpe.toFixed(2)}</text>`;
  return s + "</svg>";
}

function fundamentalLawSvg(w = 400, h = 230) {
  const pad = { l: 40, r: 14, t: 14, b: 36 };
  const x = lin(0, 3, pad.l, w - pad.r);
  const y = lin(0, 2, h - pad.b, pad.t);
  let s = `<svg viewBox="0 0 ${w} ${h}" xmlns="http://www.w3.org/2000/svg" font-family="DM Sans">`;
  for (const v of [0, 0.5, 1, 1.5, 2])
    s += `<line x1="${pad.l}" x2="${w - pad.r}" y1="${y(v)}" y2="${y(v)}" stroke="${C.soft}"/><text x="${pad.l - 7}" y="${y(v) + 3.5}" font-size="10" fill="${C.faint}" text-anchor="end">${v.toFixed(1)}</text>`;
  for (const v of [0, 1, 2, 3])
    s += `<text x="${x(v)}" y="${h - pad.b + 16}" font-size="10" fill="${C.faint}" text-anchor="middle">${10 ** v}</text>`;
  s += `<text x="${(pad.l + w) / 2}" y="${h - 4}" font-size="10" fill="${C.faint}" text-anchor="middle">Independent bets per year (log scale)</text>`;
  [0.02, 0.05, 0.1].forEach((ic, k) => {
    const pts = Array.from({ length: 61 }, (_, i) => {
      const b = 10 ** (i / 20);
      return `${x(i / 20).toFixed(1)},${y(Math.min(2, ic * Math.sqrt(b))).toFixed(1)}`;
    }).join(" ");
    const strong = k === 1;
    s += `<polyline points="${pts}" fill="none" stroke="${strong ? C.ink : "#a9b3bf"}" stroke-width="${strong ? 2.4 : 1.5}" ${strong ? "" : 'stroke-dasharray="4 4"'}/>`;
    const lx = ic === 0.1 ? Math.log10(400) : 3;
    s += `<text x="${x(lx) - 4}" y="${y(Math.min(2, ic * Math.sqrt(10 ** lx))) - 7}" font-size="10" fill="${strong ? C.ink : C.faint}" text-anchor="end">IC ${ic.toFixed(2)}</text>`;
  });
  s += `<circle cx="${x(Math.log10(400))}" cy="${y(1)}" r="6" fill="${C.gold}" stroke="${C.accent}" stroke-width="1.5"/>`;
  s += `<text x="${x(Math.log10(400)) - 10}" y="${y(1) - 6}" font-size="10" fill="${C.ink}" text-anchor="end" font-weight="500">IC 0.05 × √400 = IR 1.0</text>`;
  return s + "</svg>";
}

function parityBarsSvg(w = 400, h = 210) {
  const { names, vols, corr } = PARITY_ASSETS;
  const cov = covariance(vols, corr);
  const sets = [
    { label: "60/40", w: [0.6, 0.4, 0, 0] },
    { label: "Risk parity", w: riskParity(cov) },
  ];
  let s = `<svg viewBox="0 0 ${w} ${h}" xmlns="http://www.w3.org/2000/svg" font-family="DM Sans">`;
  const colW = w / 2;
  sets.forEach((set, k) => {
    const rc = riskContributions(set.w, cov);
    const vol = portfolioVol(set.w, cov);
    const ox = k * colW + 10;
    s += `<text x="${ox}" y="14" font-size="11.5" font-weight="600" fill="${C.ink}">${set.label}</text>`;
    names.forEach((n, i) => {
      const yy = 30 + i * 42;
      const share = rc[i] / vol;
      s += `<text x="${ox}" y="${yy + 9}" font-size="10" fill="${C.muted}">${n}</text>`;
      s += `<rect x="${ox + 70}" y="${yy}" width="${set.w[i] * 70}" height="10" rx="2" fill="#e3e8ee"/>`;
      s += `<rect x="${ox + 70}" y="${yy + 13}" width="${Math.max(share * 70, 0.5)}" height="10" rx="2" fill="${C.ink}"/>`;
      s += `<text x="${ox + 74 + Math.max(set.w[i], share) * 70}" y="${yy + 18}" font-size="9.5" fill="${C.faint}">${pct(set.w[i])} / ${pct(share)}</text>`;
    });
  });
  s += `<rect x="10" y="${h - 14}" width="10" height="8" rx="1.5" fill="#e3e8ee"/><text x="25" y="${h - 7}" font-size="9.5" fill="${C.faint}">Capital</text>`;
  s += `<rect x="75" y="${h - 14}" width="10" height="8" rx="1.5" fill="${C.ink}"/><text x="90" y="${h - 7}" font-size="9.5" fill="${C.faint}">Share of risk</text>`;
  return s + "</svg>";
}

function deflatedSvg(w = 400, h = 230) {
  const pad = { l: 40, r: 14, t: 14, b: 36 };
  const x = lin(0, 3, pad.l, w - pad.r);
  const y = lin(0, 2, h - pad.b, pad.t);
  const pts = Array.from({ length: 61 }, (_, i) => {
    const n = Math.max(2, 10 ** (i / 20));
    return `${x(Math.log10(n)).toFixed(1)},${y(expectedMaxSharpe(n, 5)).toFixed(1)}`;
  }).join(" ");
  let s = `<svg viewBox="0 0 ${w} ${h}" xmlns="http://www.w3.org/2000/svg" font-family="DM Sans">`;
  for (const v of [0, 0.5, 1, 1.5, 2])
    s += `<line x1="${pad.l}" x2="${w - pad.r}" y1="${y(v)}" y2="${y(v)}" stroke="${C.soft}"/><text x="${pad.l - 7}" y="${y(v) + 3.5}" font-size="10" fill="${C.faint}" text-anchor="end">${v.toFixed(1)}</text>`;
  for (const v of [0, 1, 2, 3])
    s += `<text x="${x(v)}" y="${h - pad.b + 16}" font-size="10" fill="${C.faint}" text-anchor="middle">${10 ** v}</text>`;
  s += `<text x="${(pad.l + w) / 2}" y="${h - 4}" font-size="10" fill="${C.faint}" text-anchor="middle">Strategies tried (log scale) · 5-year backtest</text>`;
  s += `<polygon points="${x(Math.log10(2))},${y(0)} ${pts} ${x(3)},${y(0)}" fill="#f7efdf"/>`;
  s += `<polyline points="${pts}" fill="none" stroke="${C.ink}" stroke-width="2.4"/>`;
  for (const n of [10, 1000]) {
    const v = expectedMaxSharpe(n, 5);
    s += `<circle cx="${x(Math.log10(n))}" cy="${y(v)}" r="5" fill="${C.gold}" stroke="${C.accent}" stroke-width="1.5"/>`;
    const first = n === 10;
    s += `<text x="${x(Math.log10(n)) + (first ? 8 : -8)}" y="${y(v) + (first ? 15 : -8)}" font-size="10" fill="${C.ink}" text-anchor="${first ? "start" : "end"}">${n} trials → Sharpe ${v.toFixed(2)} from luck</text>`;
  }
  s += `<text x="${x(1.6)}" y="${y(0.25)}" font-size="10.5" fill="${C.accent}">Zone of luck</text>`;
  return s + "</svg>";
}

function attributionSvg(w = 400, h = 220) {
  const b = brinson();
  const steps = [
    { label: "Benchmark", v: b.RB, base: 0, total: true },
    { label: "Allocation", v: b.allocation, base: b.RB },
    { label: "Selection", v: b.selection, base: b.RB + b.allocation },
    { label: "Interaction", v: b.interaction, base: b.RB + b.allocation + b.selection },
    { label: "Portfolio", v: b.RP, base: 0, total: true },
  ];
  const y = lin(0, 0.09, h - 30, 18);
  let s = `<svg viewBox="0 0 ${w} ${h}" xmlns="http://www.w3.org/2000/svg" font-family="DM Sans">`;
  for (const v of [0, 0.03, 0.06, 0.09])
    s += `<line x1="40" x2="${w - 6}" y1="${y(v)}" y2="${y(v)}" stroke="${C.soft}"/><text x="33" y="${y(v) + 3.5}" font-size="10" fill="${C.faint}" text-anchor="end">${pct(v)}</text>`;
  steps.forEach((st, i) => {
    const cx = 70 + i * 76;
    const top = y(st.base + st.v);
    const bottom = y(st.base);
    s += `<rect x="${cx - 22}" y="${top}" width="44" height="${Math.max(bottom - top, 1.5)}" rx="3" fill="${st.total ? C.ink : C.gold}"/>`;
    s += `<text x="${cx}" y="${top - 6}" font-size="10.5" font-weight="500" fill="${C.ink}" text-anchor="middle">${st.total ? pct(st.v, 2) : "+" + pct(st.v, 2)}</text>`;
    s += `<text x="${cx}" y="${h - 12}" font-size="10" fill="${C.muted}" text-anchor="middle">${st.label}</text>`;
  });
  return s + "</svg>";
}

/* ------------------------------ Shared CSS ------------------------------ */
const css = `
@font-face { font-family: "DM Sans"; font-weight: 400; src: url("file://${fonts}/dm-sans-400.ttf"); }
@font-face { font-family: "DM Sans"; font-weight: 500; src: url("file://${fonts}/dm-sans-500.ttf"); }
@font-face { font-family: "DM Sans"; font-weight: 600; src: url("file://${fonts}/dm-sans-600.ttf"); }
@font-face { font-family: "DM Sans"; font-weight: 700; src: url("file://${fonts}/dm-sans-700.ttf"); }
@page { size: A4; margin: 0; }
* { box-sizing: border-box; margin: 0; padding: 0; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font-family: "DM Sans", sans-serif; color: ${C.ink}; background: ${C.paper}; font-size: 10pt; line-height: 1.5; }
.page { width: 210mm; height: 297mm; padding: 18mm 18mm 16mm; position: relative; overflow: hidden; page-break-after: always; background: ${C.paper}; }
.page:last-child { page-break-after: auto; }
.folio { position: absolute; left: 18mm; right: 18mm; bottom: 9mm; display: flex; justify-content: space-between; font-size: 7.5pt; color: ${C.faint}; border-top: 0.5pt solid ${C.line}; padding-top: 3mm; }
.brand { display: flex; align-items: center; gap: 8px; font-weight: 600; letter-spacing: -0.01em; }
.brand-mark { width: 26px; height: 26px; border: 1.2px solid ${C.gold}; border-radius: 6px; display: grid; place-items: center; font-size: 10pt; color: ${C.gold}; font-weight: 600; }
.brand em { font-style: italic; color: ${C.gold}; font-weight: 500; }
.eyebrow { font-size: 7.5pt; font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase; color: ${C.accent}; }
h1 { font-weight: 400; letter-spacing: -0.035em; line-height: 1.02; }
h2 { font-size: 22pt; font-weight: 400; letter-spacing: -0.03em; line-height: 1.1; margin: 2mm 0 6mm; }
h3 { font-size: 11.5pt; font-weight: 500; letter-spacing: -0.01em; }
p { color: ${C.muted}; }
.lead { font-size: 11.5pt; line-height: 1.6; color: ${C.muted}; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8mm; }
.card { background: #fff; border: 0.6pt solid ${C.line}; border-radius: 4mm; padding: 5mm; }
.ticks { list-style: none; display: grid; gap: 2.2mm; }
.ticks li { display: flex; gap: 2.5mm; color: ${C.muted}; }
.ticks li::before { content: "✓"; color: ${C.green}; font-weight: 700; }
.facts { display: grid; grid-template-columns: repeat(4, 1fr); border: 0.6pt solid ${C.line}; border-radius: 4mm; background: #fff; overflow: hidden; }
.facts div { padding: 3.5mm 4mm; border-right: 0.6pt solid ${C.soft}; border-bottom: 0.6pt solid ${C.soft}; }
.facts div:nth-child(4n) { border-right: 0; }
.facts div:nth-last-child(-n+4) { border-bottom: 0; }
.facts dt { font-size: 6.8pt; text-transform: uppercase; letter-spacing: 0.08em; color: ${C.faint}; }
.facts dd { font-size: 9.5pt; font-weight: 500; margin-top: 1mm; }
figure { background: #fff; border: 0.6pt solid ${C.line}; border-radius: 4mm; padding: 4mm 4mm 3mm; }
figure svg { width: 100%; height: auto; display: block; }
figcaption { font-size: 7.8pt; color: ${C.faint}; margin-top: 2mm; line-height: 1.45; }
figure strong.ft { display: block; font-size: 9pt; font-weight: 500; margin-bottom: 2mm; }
.syl { width: 100%; border-collapse: collapse; font-size: 9pt; }
.syl td { padding: 2mm 2mm; border-bottom: 0.6pt solid ${C.soft}; vertical-align: top; }
.formula { border-left: 2.5pt solid ${C.gold}; background: #faf3e5; padding: 3mm 4mm; border-radius: 0 3mm 3mm 0; font-family: Menlo, monospace; font-size: 9pt; }
`;

const folio = (n: number, label: string) =>
  `<div class="folio"><span>FinEx Learning · ${esc(course.title)}</span><span>${label} · ${n}</span></div>`;

const brand = (dark = false) =>
  `<div class="brand" style="color:${dark ? "#f7f5ee" : C.ink}"><span class="brand-mark">FC</span>FinEx <em>Careers</em></div>`;

/* ------------------------------ Brochure ------------------------------ */
function brochure() {
  const facts = QUANT_OVERVIEW.format
    .map((f) => `<div><dt>${esc(f.label)}</dt><dd>${esc(f.value)}</dd></div>`)
    .join("");
  const weeks = ["23 Nov", "30 Nov", "7 Dec", "14 Dec", "21 Dec", "28 Dec"];

  const cover = `
  <section class="page" style="background:${C.ink};color:#f7f5ee;padding:20mm">
    ${brand(true)}
    <div style="position:absolute;right:12mm;top:44mm;width:160mm;opacity:.95">${frontierSvg(520, 300, true)}</div>
    <div style="position:absolute;left:20mm;right:20mm;bottom:30mm">
      <div class="eyebrow" style="color:${C.gold}">FinEx Learning · Executive programme · ${esc(course.category)}</div>
      <h1 style="font-size:40pt;margin:5mm 0 6mm;max-width:150mm">${esc(course.title)}</h1>
      <p style="color:#c2cbd8;font-size:13pt;max-width:135mm;line-height:1.5">${esc(QUANT_OVERVIEW.tagline)}</p>
      <div style="display:flex;gap:10mm;margin-top:12mm;padding-top:6mm;border-top:0.6pt solid #435168;font-size:9pt;color:#c2cbd8">
        <span><b style="color:#f7f5ee;font-size:15pt;font-weight:500;display:block">${course.duration}</b>online · live + self-paced</span>
        <span><b style="color:#f7f5ee;font-size:15pt;font-weight:500;display:block">${course.hours}</b>CPD hours</span>
        <span><b style="color:#f7f5ee;font-size:15pt;font-weight:500;display:block">${QUANT_LESSON_COUNT}</b>lessons · 5 labs</span>
        <span><b style="color:#f7f5ee;font-size:15pt;font-weight:500;display:block">23 Nov</b>next cohort, 2026</span>
      </div>
    </div>
  </section>`;

  const p2 = `
  <section class="page">
    <div class="eyebrow">Why this programme</div>
    <h2>From a factor idea to a portfolio you can defend.</h2>
    <div class="grid2" style="grid-template-columns:1.25fr 1fr;gap:10mm">
      <div>${QUANT_OVERVIEW.intro.map((p) => `<p class="lead" style="margin-bottom:4mm">${esc(p)}</p>`).join("")}</div>
      <div class="card" style="background:${C.raised};border:0">
        <h3 style="margin-bottom:3mm">Each week includes</h3>
        <ul class="ticks">
          <li>Short video lessons with worked derivations</li>
          <li>Interactive models you can manipulate</li>
          <li>A Python lab on real public data</li>
          <li>A 90-minute live session, Tuesdays 7:00 pm HKT</li>
          <li>A knowledge check and curated research</li>
        </ul>
      </div>
    </div>
    <div class="eyebrow" style="margin:10mm 0 3mm">At a glance</div>
    <dl class="facts">${facts}</dl>
    <div class="grid2" style="margin-top:10mm">
      <div><h3 style="margin-bottom:3mm">Who it is for</h3><ul class="ticks">${QUANT_OVERVIEW.audience.map((a) => `<li>${esc(a)}</li>`).join("")}</ul></div>
      <div><h3 style="margin-bottom:3mm">Before you start</h3><ul class="ticks">${QUANT_OVERVIEW.prerequisites.map((a) => `<li>${esc(a)}</li>`).join("")}</ul></div>
    </div>
    ${folio(2, "Brochure")}
  </section>`;

  const p3 = `
  <section class="page">
    <div class="eyebrow">Learning outcomes</div>
    <h2>What you will be able to do.</h2>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:4mm">
      ${QUANT_OVERVIEW.outcomes.map((o, i) => `<div class="card" style="padding:4.5mm"><div class="eyebrow" style="margin-bottom:2.5mm">${String(i + 1).padStart(2, "0")}</div><div style="font-size:9.8pt;line-height:1.45">${esc(o)}</div></div>`).join("")}
    </div>
    <div class="grid2" style="margin-top:10mm;grid-template-columns:1.2fr 1fr;align-items:start">
      <figure><strong class="ft">Week 1 · The efficient frontier and the capital market line</strong>${frontierSvg()}<figcaption>Four illustrative asset classes put through the real mean–variance mathematics. On the course page you can move risk aversion and watch the optimal portfolio slide along the line.</figcaption></figure>
      <div>
        <h3 style="margin-bottom:3mm">Learn by experimenting</h3>
        <p style="margin-bottom:4mm">Eight interactive models sit inside the lessons: the efficient frontier, the fundamental law, the research pipeline, covariance shrinkage, risk parity, the deflated Sharpe ratio, market impact and Brinson attribution.</p>
        <div class="formula">w* = (1/λ) · Σ⁻¹ μ</div>
        <p style="margin-top:3mm;font-size:8.6pt">Every equation is paired with the Python that implements it, using pandas, statsmodels, scikit-learn and cvxpy.</p>
      </div>
    </div>
    <div class="eyebrow" style="margin:11mm 0 3mm">A typical week</div>
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:3mm">
      ${[
        ["Monday", "Lessons", "2–3 short lessons with derivations, interactive models and code walk-throughs."],
        ["Tuesday", "Live session", "90 minutes, 7:00 pm HKT: worked problems, Q&A and practitioner case discussion."],
        ["Wed–Sun", "Python lab", "Apply the week's method to real public data in a guided notebook."],
        ["Sunday", "Knowledge check", "A short check and the week's readings. Completing the week updates your CPD hours."],
      ].map(([when, what, detail], i) => `<div style="border-top:2pt solid ${i === 1 ? C.gold : C.ink};padding-top:3mm"><div style="font-size:7.5pt;color:${C.faint};text-transform:uppercase;letter-spacing:.08em">${when}</div><h3 style="margin:1mm 0 1.5mm">${what}</h3><p style="font-size:8.6pt;line-height:1.45">${detail}</p></div>`).join("")}
    </div>
    ${folio(3, "Brochure")}
  </section>`;

  const moduleCard = (m: (typeof QUANT_MODULES)[number]) => `
    <div class="card" style="padding:5mm 5.5mm;display:grid;grid-template-columns:16mm 1fr;gap:4mm;break-inside:avoid">
      <div><div style="width:13mm;height:13mm;border-radius:3mm;background:#faf3e5;color:${C.accent};display:grid;place-items:center;font-weight:600;font-size:10pt">W${m.week}</div><div style="font-size:7pt;color:${C.faint};margin-top:2mm">w/c ${weeks[m.week - 1]}</div></div>
      <div>
        <h3>${esc(m.title)}</h3>
        <p style="font-size:8.8pt;margin:1mm 0 2.5mm">${esc(m.hook)}</p>
        <ol style="list-style:none;display:grid;gap:1.4mm;font-size:8.8pt">
          ${m.lessons.map((l, i) => `<li style="display:flex;gap:2.5mm"><span style="color:${C.accent};min-width:7mm">${m.week}.${i + 1}</span><span>${esc(l.title)}<span style="color:${C.faint}"> · ${l.minutes} min</span></span></li>`).join("")}
          <li style="display:flex;gap:2.5mm;color:${C.green}"><span style="min-width:7mm">Lab</span><span>${esc(m.lab.title.replace(/^Lab \d · /, ""))}</span></li>
        </ol>
      </div>
    </div>`;

  const p4 = `
  <section class="page">
    <div class="eyebrow">Curriculum · weeks 1–3</div>
    <h2>Foundations, research and construction.</h2>
    <div style="display:grid;gap:4mm">${QUANT_MODULES.slice(0, 3).map(moduleCard).join("")}</div>
    <div class="grid2" style="margin-top:5mm">
      <figure><strong class="ft">Week 1 · The fundamental law</strong>${fundamentalLawSvg()}<figcaption>IR ≈ IC · √breadth. A small edge applied many times beats a big edge applied rarely.</figcaption></figure>
      <figure><strong class="ft">Week 3 · Capital vs risk</strong>${parityBarsSvg()}<figcaption>In a 60/40 portfolio equities carry over 90% of the risk. Risk parity equalises it.</figcaption></figure>
    </div>
    ${folio(4, "Brochure")}
  </section>`;

  const p5 = `
  <section class="page">
    <div class="eyebrow">Curriculum · weeks 4–6</div>
    <h2>Testing, attribution and the capstone.</h2>
    <div style="display:grid;gap:4mm">${QUANT_MODULES.slice(3).map(moduleCard).join("")}</div>
    <div class="grid2" style="margin-top:5mm">
      <figure><strong class="ft">Week 4 · The best Sharpe ratio noise will give you</strong>${deflatedSvg()}<figcaption>Bailey &amp; López de Prado (2014). Report the number of trials with every backtest.</figcaption></figure>
      <figure><strong class="ft">Week 5 · Brinson attribution</strong>${attributionSvg()}<figcaption>Worked example: 1.80% active return split into allocation, selection and interaction.</figcaption></figure>
    </div>
    ${folio(5, "Brochure")}
  </section>`;

  const cap = QUANT_OVERVIEW.capstone;
  const p6 = `
  <section class="page">
    <div class="eyebrow">Capstone</div>
    <h2>An APAC multi-factor equity mandate.</h2>
    <p class="lead" style="max-width:160mm;font-size:10.5pt">${esc(cap.brief)}</p>
    <div class="grid2" style="margin-top:6mm">
      <div class="card"><h3 style="margin-bottom:3mm">You will submit</h3><ul class="ticks">${cap.deliverables.map((d) => `<li>${esc(d)}</li>`).join("")}</ul></div>
      <div class="card"><h3 style="margin-bottom:3mm">How it is assessed</h3>
        ${cap.rubric.map((r) => `<div style="margin-bottom:2.2mm"><div style="display:flex;justify-content:space-between;font-size:9pt;color:${C.muted}"><span>${esc(r.item)}</span><b style="color:${C.ink}">${r.weight}%</b></div><div style="height:4px;border-radius:4px;background:#e1e5e8;margin-top:1.5mm"><div style="height:100%;width:${(r.weight / 30) * 100}%;background:${C.gold};border-radius:4px"></div></div></div>`).join("")}
      </div>
    </div>
    <div class="eyebrow" style="margin:7mm 0 2.5mm">Faculty</div>
    <div class="card" style="display:flex;gap:6mm;align-items:flex-start;padding:5mm">
      <div style="width:18mm;height:18mm;border-radius:50%;background:#e0e8f0;color:#405b7d;display:grid;place-items:center;font-size:16pt;font-weight:500;flex:none">${trainer.initials}</div>
      <div><h3 style="font-size:14pt">${esc(trainer.name)}</h3><p style="margin-top:1mm">${esc(trainer.role)}</p><p style="color:${C.accent};font-size:8.8pt;margin-top:1mm">${esc(trainer.credentials)}</p><p style="margin-top:2mm">${esc(trainer.bio)} Capstones are reviewed by a panel of portfolio managers and risk practitioners.</p></div>
    </div>
    <div class="eyebrow" style="margin:7mm 0 2.5mm">Schedule</div>
    <div style="display:grid;grid-template-columns:repeat(6,1fr);gap:2mm">
      ${QUANT_MODULES.map((m) => `<div style="border-top:2pt solid ${m.week === 6 ? C.gold : C.ink};padding-top:2mm;font-size:8pt"><b style="font-weight:600">Week ${m.week}</b><div style="color:${C.faint}">w/c ${weeks[m.week - 1]}</div><div style="margin-top:1mm;color:${C.muted};line-height:1.35">${esc(m.title)}</div></div>`).join("")}
    </div>
    <div class="eyebrow" style="margin:7mm 0 2.5mm">Six formulas you will own</div>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:3mm">
      ${[
        ["Mean–variance", "w* = (1/λ) Σ⁻¹ μ"],
        ["Fundamental law", "IR ≈ TC · IC · √BR"],
        ["Shrinkage", "Σ̂ = δF + (1 − δ)S"],
        ["Risk contribution", "RCᵢ = wᵢ(Σw)ᵢ / σₚ"],
        ["Market impact", "≈ Y · σ · √(Q/V)"],
        ["Brinson allocation", "(wᵖ − wᵇ)(Rᵢᵇ − Rᵇ)"],
      ].map(([k, f]) => `<div class="formula" style="font-family:'DM Sans';font-size:8pt;padding:2.4mm 3.5mm"><div style="color:${C.accent};font-weight:600;letter-spacing:.04em;text-transform:uppercase;font-size:6.8pt">${k}</div><div style="font-family:Menlo,monospace;font-size:9.2pt;margin-top:1mm;color:${C.ink}">${f}</div></div>`).join("")}
    </div>
    ${folio(6, "Brochure")}
  </section>`;

  const readings = QUANT_MODULES.flatMap((m) => m.readings);
  const p7 = `
  <section class="page">
    <div class="eyebrow">Fees &amp; enrolment</div>
    <h2>Invest in your next chapter.</h2>
    <div class="grid2" style="grid-template-columns:1fr 1fr">
      <div class="card" style="background:${C.ink};color:#f7f5ee;border:0;padding:7mm">
        <div class="eyebrow" style="color:${C.gold}">Programme fee</div>
        <div style="font-size:30pt;letter-spacing:-0.03em;margin:2mm 0">${hkd(course.fullPrice)}</div>
        <p style="color:#c2cbd8">FinEx members <b style="color:${C.gold}">${hkd(course.price)}</b> · save 20%</p>
        <p style="color:#c2cbd8;margin-top:4mm;font-size:8.8pt">Includes all live sessions, labs and datasets, capstone review and your certificate of completion.</p>
      </div>
      <div class="card" style="padding:7mm"><h3 style="margin-bottom:3mm">How to enrol</h3>
        <ol style="padding-left:5mm;display:grid;gap:2mm;color:${C.muted}">
          <li>Create a free FinEx Careers account</li>
          <li>Open Learning → Advanced Quantitative Portfolio Management</li>
          <li>Select <b style="color:${C.ink}">Enrol now</b> and confirm your details</li>
          <li>Complete the Python primer before 23 November</li>
        </ol>
        <p style="margin-top:4mm;font-size:8.6pt">Your progress and CPD hours are tracked automatically in <b>My learning</b>.</p>
      </div>
    </div>
    <div class="eyebrow" style="margin:11mm 0 3mm">Selected readings</div>
    <ol style="list-style:none;display:grid;grid-template-columns:1fr 1fr;gap:2.4mm 7mm;font-size:7.8pt;line-height:1.4;color:${C.muted}">
      ${readings.map((r) => `<li>${esc(r.citation)}</li>`).join("")}
    </ol>
    <p style="position:absolute;left:18mm;right:18mm;bottom:20mm;font-size:7pt;color:${C.faint};line-height:1.5">Illustrative programme. Faculty profile, ratings, dates and fees are sample content. CPD hours are FinEx learning hours and do not imply accreditation by any regulator or professional body. Chart inputs are illustrative; the formulas and readings are real.</p>
    ${folio(7, "Brochure")}
  </section>`;

  return `<!doctype html><html><head><meta charset="utf-8"><style>${css}</style></head><body>${cover}${p2}${p3}${p4}${p5}${p6}${p7}</body></html>`;
}

/* ------------------------------ Course summary ------------------------------ */
function summary() {
  const head = `
    <div style="background:${C.ink};color:#f7f5ee;margin:-18mm -18mm 6mm;padding:11mm 18mm 9mm">
      <div style="display:flex;justify-content:space-between;align-items:center">${brand(true)}<span class="eyebrow" style="color:${C.gold}">Course summary</span></div>
      <h1 style="font-size:23pt;margin:7mm 0 2mm">${esc(course.title)}</h1>
      <p style="color:#c2cbd8;font-size:10pt">${esc(QUANT_OVERVIEW.tagline)}</p>
    </div>`;
  const facts = QUANT_OVERVIEW.format.map((f) => `<div><dt>${esc(f.label)}</dt><dd>${esc(f.value)}</dd></div>`).join("");
  const rows = QUANT_MODULES.map(
    (m) => `<tr><td style="color:${C.accent};font-weight:600">W${m.week}</td><td><b style="font-weight:500">${esc(m.title)}</b><div style="color:${C.faint};font-size:7.6pt;line-height:1.35;margin-top:.5mm">${esc(m.lessons.map((l) => l.title).join(" · "))}</div></td><td style="text-align:right;white-space:nowrap;color:${C.faint}">${m.hours} h</td></tr>`,
  ).join("");
  const page1 = `
  <section class="page">
    ${head}
    <dl class="facts">${facts}</dl>
    <div class="grid2" style="margin-top:6mm;grid-template-columns:1.2fr 1fr">
      <div><div class="eyebrow" style="margin-bottom:2mm">Overview</div><p style="font-size:9pt;line-height:1.55">${esc(QUANT_OVERVIEW.intro[0])}</p></div>
      <div><div class="eyebrow" style="margin-bottom:2mm">Outcomes</div><ul class="ticks" style="font-size:8.2pt;gap:1.4mm;line-height:1.35">${QUANT_OVERVIEW.outcomes.map((o) => `<li>${esc(o)}</li>`).join("")}</ul></div>
    </div>
    <div class="eyebrow" style="margin:6mm 0 1mm">Syllabus</div>
    <table class="syl"><tbody>${rows}</tbody></table>
    ${folio(1, "Course summary")}
  </section>`;
  const cap = QUANT_OVERVIEW.capstone;
  const page2 = `
  <section class="page">
    <div class="grid2" style="grid-template-columns:1.3fr 1fr">
      <div>
        <div class="eyebrow" style="margin-bottom:2mm">Capstone</div>
        <h3 style="font-size:13pt;margin-bottom:2mm">An APAC multi-factor equity mandate</h3>
        <p style="font-size:9.4pt">${esc(cap.brief)}</p>
        <ul class="ticks" style="margin-top:3mm;font-size:8.8pt">${cap.deliverables.map((d) => `<li>${esc(d)}</li>`).join("")}</ul>
      </div>
      <figure style="align-self:start"><strong class="ft">The efficient frontier (Week 1)</strong>${frontierSvg(520, 290)}<figcaption>Interactive on the course page: move risk aversion and watch the optimal portfolio move.</figcaption></figure>
    </div>
    <div class="grid2" style="margin-top:8mm">
      <div class="card"><div class="eyebrow" style="margin-bottom:2mm">Faculty</div><h3>${esc(trainer.name)}</h3><p style="font-size:9pt">${esc(trainer.role)} · ${esc(trainer.credentials)}</p><p style="font-size:8.8pt;margin-top:2mm">${esc(trainer.bio)}</p></div>
      <div class="card" style="background:${C.ink};color:#f7f5ee;border:0"><div class="eyebrow" style="color:${C.gold};margin-bottom:2mm">Fees</div><div style="font-size:22pt;letter-spacing:-0.03em">${hkd(course.fullPrice)}</div><p style="color:#c2cbd8;font-size:9pt">Members ${hkd(course.price)} · ${course.hours} CPD hours · next cohort 23 November 2026</p><p style="color:#c2cbd8;font-size:8.6pt;margin-top:3mm">Enrol online: FinEx Careers → Learning</p></div>
    </div>
    <div class="eyebrow" style="margin:8mm 0 2mm">Key research</div>
    <ol style="list-style:none;display:grid;gap:1.8mm;font-size:8pt;color:${C.muted}">
      ${QUANT_MODULES.flatMap((m) => m.readings).slice(0, 12).map((r) => `<li>${esc(r.citation)}</li>`).join("")}
    </ol>
    <p style="position:absolute;left:18mm;right:18mm;bottom:20mm;font-size:7pt;color:${C.faint}">Illustrative programme. Faculty profile, dates and fees are sample content; CPD hours are FinEx learning hours and do not imply accreditation by any regulator or professional body.</p>
    ${folio(2, "Course summary")}
  </section>`;
  return `<!doctype html><html><head><meta charset="utf-8"><style>${css}</style></head><body>${page1}${page2}</body></html>`;
}

writeFileSync(resolve(out, "quant.html"), brochure());
writeFileSync(resolve(out, "quant-summary.html"), summary());
console.log(`Wrote ${out}/quant.html and quant-summary.html`);
