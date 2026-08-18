import {
  AlertTriangle,
  ArrowUpRight,
  Bot,
  Check,
  CheckCircle2,
  Circle,
  Clock3,
  Database,
  Gauge,
  ShieldCheck,
  X,
} from 'lucide-react'
import type { AdminOperationalStatus, AdminOperationsDashboard } from '../../api/client'

const SOURCE_LABELS: Record<string, string> = {
  efinancialcareers: 'eFinancialCareers',
  linkedin_posts: 'LinkedIn recruiter posts',
  jobsdb: 'JobsDB',
  linkedin: 'LinkedIn',
  longtail: 'Boutique sites',
  successfactors: 'SuccessFactors',
  workday: 'Workday',
  eightfold: 'Eightfold',
  indeed: 'Indeed',
  direct: 'Employer submissions',
}

function sourceLabel(source: string) {
  return SOURCE_LABELS[source] ?? source.replaceAll('_', ' ')
}

function durationLabel(seconds: number | null) {
  if (seconds == null) return 'Duration not recorded'
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  return `${minutes}m ${seconds % 60}s`
}

function statusLabel(status: AdminOperationalStatus) {
  return status === 'not_recorded' ? 'Awaiting telemetry' : status.replaceAll('_', ' ')
}

function StatusIcon({ status }: { status: AdminOperationalStatus | 'pass' | 'healthy' }) {
  if (status === 'success' || status === 'pass' || status === 'healthy') {
    return <Check size={14} aria-hidden="true" />
  }
  if (status === 'failed') return <X size={14} aria-hidden="true" />
  if (status === 'running') return <Clock3 size={14} aria-hidden="true" />
  return <Circle size={11} aria-hidden="true" />
}

function StatusPill({ status }: { status: AdminOperationalStatus | 'pass' | 'healthy' }) {
  const good = status === 'success' || status === 'pass' || status === 'healthy'
  const bad = status === 'failed'
  return (
    <span
      className="inline-flex min-h-7 items-center gap-1.5 rounded-full px-2.5 text-[11px] font-semibold capitalize"
      style={{
        backgroundColor: good ? 'var(--color-success-bg)' : bad ? 'var(--color-danger-bg)' : 'var(--color-warning-bg)',
        color: good ? 'var(--color-success)' : bad ? 'var(--color-destructive)' : 'var(--color-warning)',
        border: `1px solid ${good ? 'var(--color-success-border)' : bad ? 'var(--color-danger-border)' : 'var(--color-warning-border)'}`,
      }}
    >
      <StatusIcon status={status} />
      {statusLabel(status as AdminOperationalStatus)}
    </span>
  )
}

function Metric({ value, label, note }: { value: string; label: string; note?: string }) {
  return (
    <div className="min-w-0">
      <div className="text-xl font-semibold tabular-nums sm:text-2xl" style={{ color: 'var(--color-ink)', fontFamily: 'var(--font-mono)' }}>{value}</div>
      <div className="mt-1 text-xs font-semibold" style={{ color: 'var(--color-ink)' }}>{label}</div>
      {note && <div className="mt-0.5 text-[11px] leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>{note}</div>}
    </div>
  )
}

export default function OperationsCenter({ data }: { data: AdminOperationsDashboard }) {
  const runStatus = data.run.status ?? 'not_recorded'
  const runDate = data.run.scraped_date ?? 'No dated run recorded'
  const hash = data.publication?.snapshot_sha256
  // source_health and recommendations always resolve to *something* once
  // is_super_admin is true (a real list/dict, or a zeroed fallback) — never
  // null for privilege reasons — so either one reliably signals "this admin
  // can see the Ultimate-Admin-only sections". publication is excluded: it
  // can be null even for an Ultimate Admin, whenever no catalogue snapshot
  // has been received yet, so it cannot disambiguate the two null reasons.
  const isUltimateAdmin = data.source_health !== null
  const telemetryComplete = runStatus !== 'not_recorded'
    && (data.ai_cost == null || data.ai_cost.tracking_available)
    && (data.recommendations == null || data.recommendations.tracking_available)
    && (data.source_health == null || data.source_health.every(source => source.tracking_available))
  const criticalAlerts = data.alerts.filter(alert => alert.severity === 'critical').length
  const runHeading = runStatus === 'success'
    ? 'Latest pipeline phases completed'
    : runStatus === 'running'
      ? 'Pipeline is running now'
      : runStatus === 'not_recorded'
        ? 'Detailed telemetry begins with the next run'
        : `Latest pipeline finished with ${runStatus}`

  return (
    <div className="space-y-8">
      <div
        className="overflow-hidden rounded-lg"
        style={{ backgroundColor: 'var(--color-masthead)', color: 'var(--color-ink-inverse)', boxShadow: 'var(--shadow-raised)' }}
      >
        <div className="flex flex-col gap-5 px-5 py-5 sm:flex-row sm:items-center sm:justify-between sm:px-7">
          <div className="flex items-start gap-3">
            {runStatus === 'success' ? <CheckCircle2 className="mt-0.5 shrink-0" size={22} aria-hidden="true" /> : <AlertTriangle className="mt-0.5 shrink-0" size={22} aria-hidden="true" />}
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-lg font-semibold">{runHeading}</h3>
                {data.alerts.length > 0 && (
                  <span className="rounded-full px-2 py-0.5 text-[11px] font-semibold" style={{ backgroundColor: 'var(--color-warning-bg)', color: criticalAlerts ? 'var(--color-destructive)' : 'var(--color-warning)' }}>
                    {data.alerts.length} {criticalAlerts ? 'critical / warning' : 'warning'} {data.alerts.length === 1 ? 'alert' : 'alerts'}
                  </span>
                )}
              </div>
              <p className="mt-1 text-sm" style={{ color: 'color-mix(in srgb, var(--color-ink-inverse) 72%, transparent)' }}>
                Operating day {runDate} · generated {new Date(data.generated_at).toLocaleString('en-HK', { timeZone: 'Asia/Hong_Kong', dateStyle: 'medium', timeStyle: 'short' })} HKT
              </p>
            </div>
          </div>
          {data.run.source_run_url && (
            <a
              href={data.run.source_run_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex min-h-11 shrink-0 items-center gap-2 self-start rounded-md px-4 text-sm font-semibold sm:self-auto"
              style={{ color: 'var(--color-ink-inverse)', border: '1px solid color-mix(in srgb, var(--color-ink-inverse) 30%, transparent)' }}
            >
              Open GitHub run <ArrowUpRight size={15} aria-hidden="true" />
            </a>
          )}
        </div>

        <ol className="grid gap-px border-t sm:grid-cols-2 lg:grid-cols-7" style={{ borderColor: 'color-mix(in srgb, var(--color-ink-inverse) 14%, transparent)', backgroundColor: 'color-mix(in srgb, var(--color-ink-inverse) 14%, transparent)' }} aria-label="Pipeline phase timeline">
          {data.run.phases.map((phase) => (
            <li
              key={phase.key}
              className="min-w-0 px-4 py-4"
              style={{ backgroundColor: 'var(--color-masthead)' }}
            >
              <div className="flex items-center gap-2">
                <span
                  className="flex size-6 shrink-0 items-center justify-center rounded-full"
                  style={{
                    backgroundColor: phase.status === 'success' ? 'var(--color-success)' : phase.status === 'failed' ? 'var(--color-destructive)' : 'color-mix(in srgb, var(--color-ink-inverse) 16%, transparent)',
                    color: 'var(--color-ink-inverse)',
                  }}
                >
                  <StatusIcon status={phase.status} />
                </span>
                <span className="truncate text-xs font-semibold">{phase.label}</span>
              </div>
              <div className="mt-2 text-[11px] capitalize" style={{ color: 'color-mix(in srgb, var(--color-ink-inverse) 68%, transparent)' }}>
                {statusLabel(phase.status)} · {durationLabel(phase.duration_seconds)}
              </div>
            </li>
          ))}
        </ol>
      </div>

      <div className={`grid gap-8 ${data.ai_cost ? 'lg:grid-cols-[1.35fr_0.65fr]' : ''}`}>
        <section aria-labelledby="quality-heading">
          <div className="mb-4 flex items-center gap-2">
            <ShieldCheck size={18} style={{ color: 'var(--color-gold)' }} aria-hidden="true" />
            <h3 id="quality-heading" className="text-lg font-semibold" style={{ color: 'var(--color-ink)' }}>Data-quality gates</h3>
          </div>
          <div className="overflow-hidden rounded-lg" style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
            {data.quality_gates.map((gate, index) => (
              <div key={gate.key} className={`grid gap-3 px-4 py-4 sm:grid-cols-[1fr_auto_auto] sm:items-center ${index ? 'border-t' : ''}`} style={{ borderColor: 'var(--color-border)' }}>
                <div className="min-w-0">
                  <div className="text-sm font-semibold" style={{ color: 'var(--color-ink)' }}>{gate.label}</div>
                  <div className="mt-0.5 text-xs leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>{gate.detail}</div>
                </div>
                <div className="text-sm font-semibold tabular-nums" style={{ color: 'var(--color-ink)', fontFamily: 'var(--font-mono)' }}>{gate.value.toLocaleString()}{gate.unit === '%' ? '%' : ` ${gate.unit}`}</div>
                <StatusPill status={gate.status} />
              </div>
            ))}
          </div>
        </section>

        {data.ai_cost && (
          <section aria-labelledby="ai-heading" className="rounded-lg p-5" style={{ backgroundColor: 'var(--color-surface-2)', border: '1px solid var(--color-border)' }}>
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <Bot size={18} style={{ color: 'var(--color-gold)' }} aria-hidden="true" />
                <h3 id="ai-heading" className="text-lg font-semibold" style={{ color: 'var(--color-ink)' }}>AI cost control</h3>
              </div>
              {!data.ai_cost.tracking_available && <StatusPill status="not_recorded" />}
            </div>
            <div className="mt-6 grid grid-cols-2 gap-x-5 gap-y-6">
              <Metric value={data.ai_cost.tracking_available ? data.ai_cost.calls.toLocaleString() : '—'} label="DeepSeek calls" />
              <Metric value={data.ai_cost.tracking_available ? `$${data.ai_cost.estimated_cost_usd.toFixed(4)}` : '—'} label="Estimated spend" note={data.ai_cost.tracking_available ? 'From returned tokens' : 'Available after the next AI run'} />
              <Metric value={data.ai_cost.tracking_available ? data.ai_cost.roles_processed.toLocaleString() : '—'} label="Roles processed" />
              <Metric value={data.ai_cost.backlog.toLocaleString()} label="Remaining backlog" note={`${data.ai_cost.daily_limit} role safety ceiling`} />
            </div>
            <p className="mt-6 border-t pt-4 text-xs leading-relaxed" style={{ borderColor: 'var(--color-border)', color: 'var(--color-ink-muted)' }}>
              Cost uses DeepSeek’s returned cache-hit, cache-miss and output-token totals. Historical calls made before this ledger are not reconstructed.
            </p>
          </section>
        )}
      </div>

      {data.source_health && (
        <section aria-labelledby="source-health-heading">
          <div className="mb-4 flex items-end justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                <Gauge size={18} style={{ color: 'var(--color-gold)' }} aria-hidden="true" />
                <h3 id="source-health-heading" className="text-lg font-semibold" style={{ color: 'var(--color-ink)' }}>Source health</h3>
              </div>
              <p id="source-health-description" className="mt-1 text-xs" style={{ color: 'var(--color-ink-muted)' }}>State follows failures only. “Not hiring” counts companies that ran cleanly and had no open roles — normal for small firms, and not a fault. A source is marked failed when its runs error, or when every company ran clean and the source still returned nothing. Scroll horizontally for all columns on smaller screens.</p>
            </div>
          </div>
          <div className="overflow-x-auto rounded-lg focus-visible:outline-2 focus-visible:outline-offset-2" tabIndex={0} role="region" aria-labelledby="source-health-heading" aria-describedby="source-health-description" style={{ border: '1px solid var(--color-border)', backgroundColor: 'var(--color-surface)', outlineColor: 'var(--color-gold)' }}>
            <table className="w-full min-w-[720px] border-collapse text-left text-sm">
              <thead style={{ backgroundColor: 'var(--color-surface-2)', color: 'var(--color-ink-muted)' }}>
                <tr>
                  {['Source', 'Companies', 'Roles', 'Failures', 'Not hiring', 'Hiring', 'Runtime', 'State'].map((heading) => <th key={heading} scope="col" className="px-4 py-3 text-xs font-semibold">{heading}</th>)}
                </tr>
              </thead>
              <tbody>
                {data.source_health.map((source) => (
                  <tr key={source.source} className="border-t" style={{ borderColor: 'var(--color-border)' }}>
                    <th scope="row" className="px-4 py-3 font-semibold" style={{ color: 'var(--color-ink)' }}>{sourceLabel(source.source)}</th>
                    <td className="px-4 py-3 tabular-nums" style={{ color: 'var(--color-ink-muted)' }}>{source.companies?.toLocaleString() ?? '—'}</td>
                    <td className="px-4 py-3 tabular-nums" style={{ color: 'var(--color-ink-muted)' }}>{source.tracking_available ? `${source.roles_found?.toLocaleString() ?? '—'} found` : `${source.active_roles?.toLocaleString() ?? '—'} active`}</td>
                    <td className="px-4 py-3 tabular-nums" style={{ color: source.failed ? 'var(--color-ink)' : 'var(--color-ink-muted)' }}>{source.failed == null ? 'Next run' : source.failed === 0 ? 'None' : `${source.failed} (${source.failure_rate_pct}%)`}</td>
                    <td className="px-4 py-3 tabular-nums" style={{ color: 'var(--color-ink-muted)' }}>{source.zero_results?.toLocaleString() ?? '—'}</td>
                    <td className="px-4 py-3 tabular-nums" style={{ color: 'var(--color-ink-muted)' }}>{source.hiring_rate_pct == null ? '—' : `${source.hiring_rate_pct}%`}</td>
                    <td className="px-4 py-3 tabular-nums" style={{ color: 'var(--color-ink-muted)' }}>{durationLabel(source.runtime_seconds)}</td>
                    <td className="px-4 py-3"><StatusPill status={source.status === 'healthy' ? 'healthy' : source.status === 'failed' ? 'failed' : source.status === 'warning' ? 'warning' : 'not_recorded'} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {isUltimateAdmin && (
      <div className="grid gap-8 lg:grid-cols-2">
        <section aria-labelledby="publication-heading" className="rounded-lg p-5" style={{ border: '1px solid var(--color-border)', backgroundColor: 'var(--color-surface)' }}>
          <div className="flex items-center gap-2">
            <Database size={18} style={{ color: 'var(--color-gold)' }} aria-hidden="true" />
            <h3 id="publication-heading" className="text-lg font-semibold" style={{ color: 'var(--color-ink)' }}>Publication safety</h3>
          </div>
          {data.publication ? (
            <dl className="mt-5 grid grid-cols-[auto_1fr] gap-x-5 gap-y-3 text-sm">
              <dt style={{ color: 'var(--color-ink-muted)' }}>Published run</dt><dd className="min-w-0 text-right font-semibold" style={{ color: 'var(--color-ink)' }}>{data.publication.source_run_id}</dd>
              <dt style={{ color: 'var(--color-ink-muted)' }}>Active listings</dt><dd className="text-right font-semibold tabular-nums" style={{ color: 'var(--color-ink)' }}>{data.publication.active_jobs.toLocaleString()}</dd>
              <dt style={{ color: 'var(--color-ink-muted)' }}>Restore source</dt><dd className="text-right font-semibold capitalize" style={{ color: 'var(--color-ink)' }}>{data.publication.restore_source?.replaceAll('_', ' ') ?? 'Not recorded'}</dd>
              <dt style={{ color: 'var(--color-ink-muted)' }}>Snapshot SHA-256</dt><dd className="min-w-0 truncate text-right text-xs" title={hash} style={{ color: 'var(--color-ink)', fontFamily: 'var(--font-mono)' }}>{hash ? `${hash.slice(0, 12)}…${hash.slice(-8)}` : 'Not recorded'}</dd>
              <dt style={{ color: 'var(--color-ink-muted)' }}>Received</dt><dd className="text-right font-semibold" style={{ color: 'var(--color-ink)' }}>{new Date(data.publication.received_at).toLocaleString('en-HK', { timeZone: 'Asia/Hong_Kong', dateStyle: 'medium', timeStyle: 'short' })} HKT</dd>
            </dl>
          ) : (
            <p className="mt-5 text-sm" style={{ color: 'var(--color-ink-muted)' }}>No checksummed Railway publication receipt is available yet.</p>
          )}
        </section>

        {data.recommendations && (
        <section aria-labelledby="recommendation-heading" className="rounded-lg p-5" style={{ border: '1px solid var(--color-border)', backgroundColor: 'var(--color-surface)' }}>
          <div className="flex items-center gap-2">
            <Gauge size={18} style={{ color: 'var(--color-gold)' }} aria-hidden="true" />
            <h3 id="recommendation-heading" className="text-lg font-semibold" style={{ color: 'var(--color-ink)' }}>Recommendation health</h3>
          </div>
          {!data.recommendations.tracking_available && <div className="mt-4"><StatusPill status="not_recorded" /></div>}
          <div className="mt-5 grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-3">
            <Metric value={data.recommendations.tracking_available ? data.recommendations.impressions.toLocaleString() : '—'} label="Impressions" />
            <Metric value={data.recommendations.tracking_available ? data.recommendations.saves.toLocaleString() : '—'} label="Saves" />
            <Metric value={data.recommendations.tracking_available ? `${data.recommendations.click_through_pct}%` : '—'} label="Open rate" />
            <Metric value={data.recommendations.tracking_available ? data.recommendations.more_like.toLocaleString() : '—'} label="More like this" />
            <Metric value={data.recommendations.tracking_available ? data.recommendations.dismissals.toLocaleString() : '—'} label="Dismissals" />
            <Metric value={data.recommendations.tracking_available ? `${data.recommendations.coverage_pct}%` : '—'} label="Seeker coverage" note={`${data.recommendations.eligible_seekers.toLocaleString()} eligible seekers`} />
          </div>
        </section>
        )}
      </div>
      )}

      <section aria-labelledby="alerts-heading">
        <div className="mb-4 flex items-center gap-2">
          <AlertTriangle size={18} style={{ color: data.alerts.length ? 'var(--color-warning)' : 'var(--color-success)' }} aria-hidden="true" />
          <h3 id="alerts-heading" className="text-lg font-semibold" style={{ color: 'var(--color-ink)' }}>Actionable alerts</h3>
        </div>
        {data.alerts.length ? (
          <div className="divide-y overflow-hidden rounded-lg" style={{ border: '1px solid var(--color-warning-border)', backgroundColor: 'var(--color-warning-bg)', borderColor: 'var(--color-warning-border)' }}>
            {data.alerts.map((alert, index) => (
              <div key={`${alert.title}-${index}`} className="px-4 py-4">
                <div className="text-sm font-semibold" style={{ color: alert.severity === 'critical' ? 'var(--color-destructive)' : 'var(--color-warning)' }}><span className="uppercase">{alert.severity}:</span> {alert.title}</div>
                <p className="mt-1 text-xs leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>{alert.detail}</p>
              </div>
            ))}
          </div>
        ) : telemetryComplete ? (
          <div className="flex items-center gap-3 rounded-lg px-4 py-4" style={{ border: '1px solid var(--color-success-border)', backgroundColor: 'var(--color-success-bg)', color: 'var(--color-success)' }}>
            <CheckCircle2 size={18} aria-hidden="true" />
            <p className="text-sm font-semibold">No failure, unusual data drop, or cost spike needs attention.</p>
          </div>
        ) : (
          <div className="flex items-center gap-3 rounded-lg px-4 py-4" style={{ border: '1px solid var(--color-warning-border)', backgroundColor: 'var(--color-warning-bg)', color: 'var(--color-warning)' }}>
            <Clock3 size={18} aria-hidden="true" />
            <p className="text-sm font-semibold">Insufficient telemetry to assess failures, unusual drops, or cost spikes. The next complete daily run will establish the baseline.</p>
          </div>
        )}
      </section>
    </div>
  )
}
