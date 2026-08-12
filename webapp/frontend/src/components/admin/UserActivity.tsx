import type { AdminUserActivity } from '../../api/client'
import TrendLine from './TrendLine'

const WINDOW_OPTIONS = [7, 30, 90, 365] as const

function Metric({ value, label, note }: { value: string; label: string; note?: string }) {
  return (
    <div className="min-w-0">
      <div className="text-2xl font-semibold tabular-nums" style={{ color: 'var(--color-ink)', fontFamily: 'var(--font-mono)' }}>{value}</div>
      <div className="mt-1 text-xs font-semibold" style={{ color: 'var(--color-ink)' }}>{label}</div>
      {note && <div className="mt-0.5 text-[11px] leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>{note}</div>}
    </div>
  )
}

function SubsectionHeading({ eyebrow, title, description }: { eyebrow: string; title: string; description: string }) {
  return (
    <div className="mb-5 max-w-3xl">
      <p className="text-xs font-semibold uppercase tracking-[0.14em]" style={{ color: 'var(--color-gold)' }}>{eyebrow}</p>
      <h3 className="mt-1 text-xl font-semibold tracking-tight" style={{ color: 'var(--color-ink)', fontFamily: 'var(--font-display)' }}>{title}</h3>
      <p className="mt-1.5 text-sm leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>{description}</p>
    </div>
  )
}

/**
 * Who is using the board — two independent, non-overlapping populations over
 * an admin-selectable window, presented side by side rather than summed:
 * signed-in Seekers (a `sessions` row is issued on every sign-in path) and
 * anonymous visitors (a hashed, non-identifying cookie set by /api/visit,
 * skipped entirely for a request that already carries a Seeker session).
 * Summing the two would double-count anyone who browsed anonymously before
 * signing in later the same window.
 */
export default function UserActivity({
  overview,
  days,
  onDaysChange,
}: {
  overview: AdminUserActivity
  days: number
  onDaysChange: (days: number) => void
}) {
  const anonymous = overview.anonymous

  return (
    <div>
      <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="max-w-3xl">
          <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl" style={{ color: 'var(--color-ink)', fontFamily: 'var(--font-display)' }}>Who is using the board</h2>
          <p className="mt-2 text-sm leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>
            Signed-in Seekers and anonymous visitors, reported separately — the two counts are never added together, since a Seeker may have visited anonymously before signing in the same window.
          </p>
        </div>
        <div className="inline-flex shrink-0 items-center gap-1 self-start rounded-md p-1" style={{ backgroundColor: 'var(--color-surface-2)', border: '1px solid var(--color-border)' }} role="group" aria-label="Activity window">
          {WINDOW_OPTIONS.map(option => (
            <button
              key={option}
              type="button"
              onClick={() => onDaysChange(option)}
              aria-pressed={days === option}
              className="min-h-9 rounded px-3 text-xs font-semibold transition-colors"
              style={{
                backgroundColor: days === option ? 'var(--color-gold)' : 'transparent',
                color: days === option ? 'var(--color-masthead)' : 'var(--color-ink-muted)',
              }}
            >
              {option === 365 ? '12mo' : `${option}d`}
            </button>
          ))}
        </div>
      </div>

      {!overview.tracking_available ? (
        <div className="rounded-lg p-5 text-sm" role="status" style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)', color: 'var(--color-ink-muted)' }}>
          Activity data is unavailable. Use “Refresh data” to try this section again.
        </div>
      ) : (
        <div className="space-y-10">
          <section>
            <SubsectionHeading
              eyebrow="Seeker accounts"
              title="Signed-in Seekers"
              description="A session is issued on every sign-in path (register, login, password reset, Google, LinkedIn) — the one visit signal available for accounts."
            />
            <div className="mb-6 grid grid-cols-2 gap-x-5 gap-y-6 rounded-lg p-5 sm:grid-cols-3 lg:grid-cols-5" style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)', boxShadow: 'var(--shadow-card)' }}>
              <Metric value={overview.total_seekers.toLocaleString()} label="Total Seeker accounts" note="All time" />
              <Metric value={overview.new_signups.toLocaleString()} label="New signups" note={`Last ${overview.days} days`} />
              <Metric value={overview.active_seekers.toLocaleString()} label="Active Seekers" note={`Last ${overview.days} days`} />
              <Metric value={overview.returning_seekers.toLocaleString()} label="Returning Seekers" note="Visited on 2+ separate days" />
              <Metric value={`${overview.repeat_visit_rate_pct}%`} label="Repeat visit rate" note="Of active Seekers in window" />
            </div>
            <div className="grid gap-5 lg:grid-cols-3">
              <TrendLine
                title="New signups"
                description="Accounts created each day"
                points={overview.points.map(point => ({ x: point.date.slice(5), y: point.new_signups }))}
                color="var(--color-gold)"
                unit=" signups"
              />
              <TrendLine
                title="Active Seekers"
                description="Distinct Seekers with a session each day"
                points={overview.points.map(point => ({ x: point.date.slice(5), y: point.active_seekers }))}
                color="var(--color-blue)"
                unit=" Seekers"
              />
              <TrendLine
                title="Returning Seekers"
                description="Active Seekers who had already visited earlier in the window"
                points={overview.points.map(point => ({ x: point.date.slice(5), y: point.returning_seekers }))}
                color="#0F766E"
                unit=" Seekers"
              />
            </div>
          </section>

          <section className="border-t pt-10" style={{ borderColor: 'var(--color-border)' }}>
            <SubsectionHeading
              eyebrow="Everyone else"
              title="Anonymous visitors"
              description="Requests with no Seeker session, counted by a hashed, non-identifying cookie — never an IP address, never linked to an account. The board is public (docs/adr/0002), so this is most of its actual traffic."
            />
            <div className="mb-6 grid grid-cols-2 gap-x-5 gap-y-6 rounded-lg p-5 sm:grid-cols-3" style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)', boxShadow: 'var(--shadow-card)' }}>
              <Metric value={anonymous.unique_visitors.toLocaleString()} label="Unique visitors" note={`Last ${overview.days} days`} />
              <Metric value={anonymous.returning_visitors.toLocaleString()} label="Returning visitors" note="Visited on 2+ separate days" />
              <Metric value={`${anonymous.repeat_visit_rate_pct}%`} label="Repeat visit rate" note="Of unique visitors in window" />
            </div>
            <div className="grid gap-5 lg:grid-cols-2">
              <TrendLine
                title="Unique visitors"
                description="Distinct anonymous visitors each day"
                points={anonymous.points.map(point => ({ x: point.date.slice(5), y: point.unique_visitors }))}
                color="var(--color-blue)"
                unit=" visitors"
              />
              <TrendLine
                title="Returning visitors"
                description="Anonymous visitors who had already visited earlier in the window"
                points={anonymous.points.map(point => ({ x: point.date.slice(5), y: point.returning_visitors }))}
                color="#0F766E"
                unit=" visitors"
              />
            </div>
          </section>
        </div>
      )}
    </div>
  )
}
