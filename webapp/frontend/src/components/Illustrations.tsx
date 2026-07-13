/**
 * Crafted SVG artwork for the FinEx job board — no stock photos.
 * A data-serious, FT/institutional aesthetic: Hong Kong skyline + market motifs,
 * drawn with the design tokens (navy / gold / cream) and theme-aware via currentColor.
 * All decorative; every consumer marks aria-hidden.
 */

type SvgProps = { className?: string; style?: React.CSSProperties }

/**
 * Hero graphic: a stylised Hong Kong skyline under an ascending market trend line
 * with data nodes and a gold "market open" sun. Navy structure, gold accents.
 */
export function SkylineTrend({ className, style }: SvgProps) {
  return (
    <svg viewBox="0 0 480 360" className={className} style={style}
         role="img" aria-label="Abstract Hong Kong skyline with an ascending market trend"
         fill="none" xmlns="http://www.w3.org/2000/svg">
      {/* soft framing */}
      <defs>
        <linearGradient id="fx-sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="var(--color-gold)" stopOpacity="0.10" />
          <stop offset="1" stopColor="var(--color-gold)" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="fx-bld" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="var(--color-nav)" />
          <stop offset="1" stopColor="var(--color-blue)" />
        </linearGradient>
      </defs>

      {/* gold "market open" disc */}
      <circle cx="372" cy="86" r="34" fill="url(#fx-sky)" />
      <circle cx="372" cy="86" r="17" fill="var(--color-gold)" opacity="0.9" />

      {/* ascending trend line + nodes */}
      <polyline points="30,232 96,206 150,214 210,158 268,170 330,110 402,70"
                stroke="var(--color-gold)" strokeWidth="3"
                strokeLinecap="round" strokeLinejoin="round" />
      {[[30,232],[96,206],[150,214],[210,158],[268,170],[330,110],[402,70]].map(([x,y],i)=>(
        <circle key={i} cx={x} cy={y} r={i===6?6:4} fill="var(--color-surface)"
                stroke="var(--color-gold)" strokeWidth="2.5" />
      ))}

      {/* skyline (varied towers, a couple iconic tapered shapes) */}
      <g fill="url(#fx-bld)">
        <rect x="24"  y="250" width="30" height="86" rx="2" />
        <rect x="60"  y="222" width="26" height="114" rx="2" />
        <path d="M92 336 V208 l14-16 14 16 V336 Z" />           {/* tapered tower */}
        <rect x="128" y="238" width="24" height="98" rx="2" />
        <rect x="158" y="196" width="30" height="140" rx="2" />
        <rect x="194" y="256" width="22" height="80" rx="2" />
        <path d="M222 336 V176 l16-22 16 22 V336 Z" />          {/* tallest tapered tower */}
        <rect x="260" y="230" width="26" height="106" rx="2" />
        <rect x="292" y="248" width="22" height="88" rx="2" />
        <rect x="318" y="210" width="30" height="126" rx="2" />
        <rect x="354" y="252" width="24" height="84" rx="2" />
        <rect x="384" y="234" width="28" height="102" rx="2" />
        <rect x="418" y="262" width="22" height="74" rx="2" />
      </g>
      {/* lit windows — gold flecks */}
      <g fill="var(--color-gold)" opacity="0.85">
        {[[166,210],[176,210],[166,226],[176,226],[230,196],[230,214],[326,226],[336,226],[326,244],[68,238],[136,254],[396,250]]
          .map(([x,y],i)=>(<rect key={i} x={x} y={y} width="4" height="6" rx="1" />))}
      </g>
      {/* ground line */}
      <rect x="0" y="335" width="480" height="2" fill="var(--color-border-strong)" opacity="0.5" />
    </svg>
  )
}

/** A subtle dotted grid field for section backgrounds (decorative). */
export function DotField({ className, style }: SvgProps) {
  return (
    <svg className={className} style={style} aria-hidden="true"
         xmlns="http://www.w3.org/2000/svg">
      <defs>
        <pattern id="fx-dots" width="22" height="22" patternUnits="userSpaceOnUse">
          <circle cx="1.5" cy="1.5" r="1.5" fill="var(--color-gold)" opacity="0.14" />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill="url(#fx-dots)" />
    </svg>
  )
}

/**
 * Data-pipeline graphic: sources on the left flow into an AI hub, then fan out
 * into a structured index on the right. Used as the About-page hero (distinct
 * from the skyline). Navy structure, one gold "live" path.
 */
export function DataFlow({ className, style }: SvgProps) {
  const sources = [64, 116, 168, 220]
  const outs = [96, 158, 220]
  return (
    <svg viewBox="0 0 480 300" className={className} style={style}
         role="img" aria-label="Data pipeline: sources flow into AI enrichment, then into a structured index"
         fill="none" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <radialGradient id="fx-hub" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="var(--color-gold)" stopOpacity="0.25" />
          <stop offset="1" stopColor="var(--color-gold)" stopOpacity="0" />
        </radialGradient>
      </defs>
      {/* connectors: sources -> hub */}
      {sources.map((y, i) => (
        <path key={i} d={`M70 ${y} C150 ${y}, 170 152, 232 152`}
              stroke={i === 1 ? 'var(--color-gold)' : 'var(--color-border-strong)'}
              strokeWidth={i === 1 ? 2.5 : 1.5} opacity={i === 1 ? 1 : 0.7} />
      ))}
      {/* connectors: hub -> outputs */}
      {outs.map((y, i) => (
        <path key={i} d={`M268 152 C330 152, 350 ${y}, 410 ${y}`}
              stroke={i === 0 ? 'var(--color-gold)' : 'var(--color-border-strong)'}
              strokeWidth={i === 0 ? 2.5 : 1.5} opacity={i === 0 ? 1 : 0.7} />
      ))}
      {/* source nodes */}
      {sources.map((y, i) => (
        <g key={i}>
          <circle cx="52" cy={y} r="14" fill="var(--color-surface)" stroke="var(--color-blue)" strokeWidth="2" />
          <circle cx="52" cy={y} r="4" fill="var(--color-blue)" />
        </g>
      ))}
      {/* AI hub */}
      <circle cx="250" cy="152" r="48" fill="url(#fx-hub)" />
      <circle cx="250" cy="152" r="28" fill="var(--color-nav)" stroke="var(--color-gold)" strokeWidth="2.5" />
      <path d="M250 138 l4 9 9 4 -9 4 -4 9 -4 -9 -9 -4 9 -4 Z" fill="var(--color-gold)" />
      {/* output cards */}
      {outs.map((y, i) => (
        <rect key={i} x="410" y={y - 14} width="52" height="28" rx="5"
              fill={i === 0 ? 'var(--color-gold-light)' : 'var(--color-surface)'}
              stroke={i === 0 ? 'var(--color-gold)' : 'var(--color-border-strong)'} strokeWidth="1.5" />
      ))}
    </svg>
  )
}

/** Coverage radar: concentric arcs + institution dots + a gold sweep. */
export function CoverageRadar({ className, style }: SvgProps) {
  return (
    <svg viewBox="0 0 240 240" className={className} style={style} aria-hidden="true"
         fill="none" xmlns="http://www.w3.org/2000/svg">
      {[40, 72, 104].map((r) => (
        <circle key={r} cx="120" cy="120" r={r} stroke="var(--color-border-strong)" strokeWidth="1.5" opacity="0.6" />
      ))}
      {/* sweep wedge */}
      <path d="M120 120 L120 16 A104 104 0 0 1 210 68 Z" fill="var(--color-gold)" opacity="0.12" />
      <line x1="120" y1="120" x2="120" y2="16" stroke="var(--color-gold)" strokeWidth="2" />
      {/* institution dots */}
      {[[150,70],[92,64],[176,132],[70,150],[132,178],[100,110],[188,96],[64,104]].map(([x,y],i)=>(
        <circle key={i} cx={x} cy={y} r={i%3===0?4:3} fill={i%3===0?'var(--color-gold)':'var(--color-blue)'} />
      ))}
      <circle cx="120" cy="120" r="5" fill="var(--color-nav)" />
    </svg>
  )
}

/** Ascending growth bars with a gold cap — trend/section accent. */
export function GrowthBars({ className, style }: SvgProps) {
  const hs = [22, 34, 30, 46, 58, 52, 74]
  return (
    <svg viewBox="0 0 200 90" className={className} style={style} aria-hidden="true"
         fill="none" xmlns="http://www.w3.org/2000/svg">
      {hs.map((h, i) => (
        <rect key={i} x={8 + i * 27} y={82 - h} width="18" height={h} rx="2"
              fill={i === hs.length - 1 ? 'var(--color-gold)' : 'var(--color-blue)'}
              opacity={i === hs.length - 1 ? 1 : 0.28} />
      ))}
      <polyline points={hs.map((h, i) => `${17 + i * 27},${82 - h - 4}`).join(' ')}
                stroke="var(--color-gold)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
    </svg>
  )
}

/** Compact candlestick motif — used as a section accent. */
export function Candles({ className, style }: SvgProps) {
  const bars = [
    [6, 20, 10, false], [22, 12, 8, true], [38, 26, 14, false],
    [54, 8, 6, true], [70, 18, 12, false], [86, 4, 4, true],
  ] as const
  return (
    <svg viewBox="0 0 100 52" className={className} style={style} aria-hidden="true"
         fill="none" xmlns="http://www.w3.org/2000/svg">
      {bars.map(([x, top, bh, up], i) => (
        <g key={i} stroke={up ? 'var(--color-gold)' : 'var(--color-blue)'}>
          <line x1={x + 5} y1={top - 5} x2={x + 5} y2={top + bh + 5} strokeWidth="1.5" />
          <rect x={x} y={top} width="10" height={bh} rx="1.5"
                fill={up ? 'var(--color-gold)' : 'var(--color-blue)'} opacity="0.9" stroke="none" />
        </g>
      ))}
    </svg>
  )
}
