interface Datum {
  label: string
  value: number
  color?: string
}

interface HBarChartProps {
  title: string
  description?: string
  data: Datum[]
  /** Fill for bars that don't carry their own color. One hue: this is a
   * magnitude chart (count by category), not an identity chart — the
   * category name is read from its own label, never from color alone. */
  color?: string
  unit?: string
  emptyLabel?: string
}

/**
 * A labelled horizontal bar list — count by category, one hue.
 *
 * Deliberately not a generic "categorical palette" component: per-bar `color`
 * exists only so a caller can pass an ALREADY-ESTABLISHED semantic mapping
 * (e.g. utils/format.ts's SECTOR_COLOR, the same colors sector chips use
 * elsewhere on the board) rather than inventing a fresh one here.
 */
export default function HBarChart({ title, description, data, color = 'var(--color-blue)', unit = '', emptyLabel = 'No data yet.' }: HBarChartProps) {
  const max = Math.max(1, ...data.map(d => d.value))

  return (
    <div
      className="rounded-lg p-5"
      style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)', boxShadow: 'var(--shadow-card)' }}
    >
      <div className="mb-5">
        <h3 className="text-base font-semibold" style={{ color: 'var(--color-ink)' }}>{title}</h3>
        {description && <p className="mt-1 text-xs leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>{description}</p>}
      </div>

      {data.length === 0 ? (
        <p className="text-sm" style={{ color: 'var(--color-ink-muted)' }}>{emptyLabel}</p>
      ) : (
        <div className="flex flex-col gap-2.5">
          {data.map(d => (
            <div key={d.label} className="flex items-center gap-3">
              <span
                className="text-xs w-28 shrink-0 truncate text-right"
                style={{ color: 'var(--color-ink-muted)' }}
                title={d.label}
              >
                {d.label}
              </span>
              <div className="flex-1 h-3.5 rounded-full overflow-hidden" style={{ backgroundColor: 'var(--color-surface-2)' }}>
                <div
                  className="h-full rounded-full"
                  title={`${d.label}: ${d.value.toLocaleString()}${unit}`}
                  style={{
                    width: `${Math.max(2, (d.value / max) * 100)}%`,
                    backgroundColor: d.color ?? color,
                  }}
                />
              </div>
              <span
                className="text-xs tabular-nums w-12 shrink-0 text-right"
                style={{ color: 'var(--color-ink)', fontFamily: 'var(--font-mono)' }}
              >
                {d.value.toLocaleString()}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
