interface Point {
  x: string
  y: number
}

interface TrendLineProps {
  title: string
  description?: string
  points: Point[]
  color?: string
  unit?: string
}

const WIDTH = 640
const HEIGHT = 160
const PAD_X = 8
const PAD_Y = 16

/**
 * A single-series trend line — one metric over time, one hue.
 *
 * Never a second line sharing this axis: two metrics of different scale
 * (jobs vs. companies) belong in two separate TrendLine charts, not one
 * dual-axis chart (the #1 chart mistake the dataviz skill's anti-patterns
 * list opens with).
 */
export default function TrendLine({ title, description, points, color = 'var(--color-blue)', unit = '' }: TrendLineProps) {
  const delta = points.length > 1 ? points[points.length - 1].y - points[0].y : 0

  return (
    <div
      className="rounded-lg p-5"
      style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)', boxShadow: 'var(--shadow-card)' }}
    >
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h3 className="text-base font-semibold" style={{ color: 'var(--color-ink)' }}>{title}</h3>
          {description && <p className="mt-1 text-xs leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>{description}</p>}
        </div>
        {points.length > 1 && (
          <span
            className="shrink-0 text-sm font-semibold tabular-nums"
            style={{ color: delta > 0 ? '#15803D' : delta < 0 ? 'var(--color-destructive)' : 'var(--color-ink-muted)', fontFamily: 'var(--font-mono)' }}
            aria-label={`${delta >= 0 ? 'Up' : 'Down'} ${Math.abs(delta)} over this period`}
          >
            {delta > 0 ? '+' : ''}{delta.toLocaleString()}
          </span>
        )}
      </div>

      {points.length < 2 ? (
        <p className="text-sm" style={{ color: 'var(--color-ink-muted)' }}>Not enough history yet.</p>
      ) : (
        <>
          <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="w-full h-auto" role="img" aria-label={title}>
            {(() => {
              const ys = points.map(p => p.y)
              const rawMax = Math.max(...ys, 1)
              const rawMin = Math.min(...ys)
              const padding = Math.max(1, (rawMax - rawMin) * 0.12)
              const maxY = rawMax + padding
              const minY = Math.max(0, rawMin - padding)
              const span = maxY - minY || 1
              const xStep = (WIDTH - PAD_X * 2) / (points.length - 1)
              const scaleY = (y: number) =>
                HEIGHT - PAD_Y - ((y - minY) / span) * (HEIGHT - PAD_Y * 2)
              const coords = points.map((p, i) => [PAD_X + i * xStep, scaleY(p.y)] as const)
              const linePath = coords.map(([x, y], i) => `${i === 0 ? 'M' : 'L'} ${x} ${y}`).join(' ')
              const areaPath =
                `${linePath} L ${coords[coords.length - 1][0]} ${HEIGHT - PAD_Y} ` +
                `L ${coords[0][0]} ${HEIGHT - PAD_Y} Z`

              return (
                <>
                  {[0, 0.5, 1].map(fraction => {
                    const y = PAD_Y + fraction * (HEIGHT - PAD_Y * 2)
                    const value = Math.round(maxY - fraction * span)
                    return (
                      <g key={fraction}>
                        <line x1={PAD_X} y1={y} x2={WIDTH - PAD_X} y2={y} stroke="var(--color-border)" strokeWidth={1} />
                        <text x={PAD_X + 2} y={Math.max(10, y - 4)} fill="var(--color-ink-muted)" fontSize={10}>{value.toLocaleString()}</text>
                      </g>
                    )
                  })}
                  <path d={areaPath} fill={color} opacity={0.08} stroke="none" />
                  <path d={linePath} fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
                  {coords.map(([x, y], i) => (
                    <circle key={points[i].x} cx={x} cy={y} r={2.5} fill={color}>
                      <title>{`${points[i].x}: ${points[i].y.toLocaleString()}${unit}`}</title>
                    </circle>
                  ))}
                </>
              )
            })()}
          </svg>
          <div className="flex justify-between text-xs mt-1" style={{ color: 'var(--color-ink-muted)' }}>
            <span>{points[0].x}</span>
            <span>{points[points.length - 1].x}</span>
          </div>
          <table className="sr-only">
            <caption>{title}</caption>
            <thead><tr><th scope="col">Date</th><th scope="col">Value</th></tr></thead>
            <tbody>
              {points.map(point => <tr key={point.x}><th scope="row">{point.x}</th><td>{point.y}{unit}</td></tr>)}
            </tbody>
          </table>
        </>
      )}
    </div>
  )
}
