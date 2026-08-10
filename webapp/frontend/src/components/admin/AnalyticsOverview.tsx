import { ArrowDownRight, ArrowUpRight, CopyCheck, Database, ShieldCheck, Sparkles } from 'lucide-react'
import type { AdminAnalyticsOverview, AdminMarketMover, AdminRunHistoryPoint } from '../../api/client'
import { getSectorColor } from '../../utils/format'
import HBarChart from './HBarChart'
import TrendLine from './TrendLine'

const SALARY_BUCKET_ORDER = ['<20k', '20-40k', '40-60k', '60-80k', '80-100k', '100-150k', '150k+']

function toEntries(record: Record<string, number>, limit = 8) {
  return Object.entries(record)
    .map(([label, value]) => ({ label, value }))
    .sort((a, b) => b.value - a.value)
    .slice(0, limit)
}

function toEntriesWithOther(record: Record<string, number>, keep = 6) {
  const sorted = Object.entries(record).sort((a, b) => b[1] - a[1])
  const head = sorted.slice(0, keep).map(([label, value]) => ({ label, value }))
  const rest = sorted.slice(keep).reduce((sum, [, value]) => sum + value, 0)
  return rest > 0 ? [...head, { label: 'Other', value: rest }] : head
}

function formatSalary(value: number) {
  return `HK$${(value / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 })}k`
}

function SectionHeading({ title, description }: { title: string; description: string }) {
  return (
    <div className="mb-5 max-w-3xl">
      <h2 className="text-2xl font-semibold tracking-tight" style={{ color: 'var(--color-ink)', fontFamily: 'var(--font-display)' }}>
        {title}
      </h2>
      <p className="mt-1.5 text-sm leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>{description}</p>
    </div>
  )
}

function MarketPulse({ overview }: { overview: AdminAnalyticsOverview }) {
  const metrics = [
    {
      label: 'Live board roles',
      value: overview.total_board_roles.toLocaleString(),
      detail: `${overview.total_active_rows.toLocaleString()} source listings before reconciliation`,
    },
    {
      label: 'Median estimated salary',
      value: formatSalary(overview.salary_median_hkd),
      detail: `Monthly · n=${overview.salary_sample_size.toLocaleString()} · middle 50% ${formatSalary(overview.salary_p25_hkd)}–${formatSalary(overview.salary_p75_hkd)}`,
    },
    {
      label: 'Duplicate listings suppressed',
      value: `${overview.cross_posting_rate_pct}%`,
      detail: `${overview.duplicate_rows_suppressed.toLocaleString()} copies removed from the board view`,
    },
    {
      label: 'Top-five employer share',
      value: `${overview.top5_company_share_pct}%`,
      detail: `HHI ${overview.company_concentration_hhi.toLocaleString()} · ${overview.company_concentration_label} across ${overview.company_entity_count} employers`,
    },
  ]

  return (
    <div className="overflow-hidden rounded-xl" style={{ backgroundColor: 'var(--color-masthead)', color: 'var(--color-ink-inverse)', boxShadow: 'var(--shadow-raised)' }}>
      <div className="flex flex-col gap-4 px-5 py-6 sm:px-7 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em]" style={{ color: '#F5C451' }}>
            <Sparkles size={14} aria-hidden="true" /> Market pulse
          </div>
          <h2 className="max-w-2xl text-3xl font-semibold leading-tight sm:text-4xl" style={{ fontFamily: 'var(--font-display)' }}>
            Hong Kong finance hiring, distilled.
          </h2>
        </div>
        <p className="max-w-md text-sm leading-relaxed" style={{ color: 'rgba(248,250,252,0.7)' }}>
          Board-visible vacancies are counted once. Salary figures use the midpoint of AI-estimated monthly ranges and always carry their sample size.
        </p>
      </div>
      <div className="grid sm:grid-cols-2 lg:grid-cols-4" style={{ borderTop: '1px solid rgba(248,250,252,0.14)' }}>
        {metrics.map((metric, index) => (
          <div
            key={metric.label}
            className={`px-5 py-5 sm:px-7 ${
              index > 0 ? 'border-t border-white/15' : ''
            } ${index % 2 ? 'sm:border-l' : ''} ${
              index >= 2 ? 'sm:border-t' : 'sm:border-t-0'
            } ${index > 0 ? 'lg:border-l' : ''} lg:border-t-0`}
          >
            <div className="text-3xl font-semibold tabular-nums" style={{ fontFamily: 'var(--font-mono)' }}>{metric.value}</div>
            <div className="mt-2 text-sm font-semibold">{metric.label}</div>
            <div className="mt-1 text-xs leading-relaxed" style={{ color: 'rgba(248,250,252,0.58)' }}>{metric.detail}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

function AnalystReadout({ overview }: { overview: AdminAnalyticsOverview }) {
  const flexibility = overview.remote_friendly_pct
  const highConfidence = overview.data_quality.high_confidence_salary_pct
  return (
    <div className="grid gap-px overflow-hidden rounded-lg md:grid-cols-3" style={{ backgroundColor: 'var(--color-border)', border: '1px solid var(--color-border)' }}>
      <article className="p-5" style={{ backgroundColor: 'var(--color-gold-light)' }}>
        <CopyCheck size={18} style={{ color: 'var(--color-gold)' }} aria-hidden="true" />
        <p className="mt-4 text-lg font-semibold leading-snug" style={{ color: 'var(--color-ink)' }}>
          {overview.cross_posting_rate_pct}% of active listings are duplicate copies.
        </p>
        <p className="mt-2 text-sm leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>
          Reconciliation suppresses {overview.duplicate_rows_suppressed.toLocaleString()} copies, so syndicated vacancies count once on the public board.
        </p>
      </article>
      <article className="p-5" style={{ backgroundColor: 'var(--color-surface)' }}>
        <Database size={18} style={{ color: 'var(--color-blue)' }} aria-hidden="true" />
        <p className="mt-4 text-lg font-semibold leading-snug" style={{ color: 'var(--color-ink)' }}>
          Flexible work is scarce: {flexibility}% hybrid or remote.
        </p>
        <p className="mt-2 text-sm leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>
          Workplace type is known for {overview.data_quality.workplace_coverage_pct}% of roles, making the on-site signal unusually complete.
        </p>
      </article>
      <article className="p-5" style={{ backgroundColor: 'var(--color-surface)' }}>
        <ShieldCheck size={18} style={{ color: '#0F766E' }} aria-hidden="true" />
        <p className="mt-4 text-lg font-semibold leading-snug" style={{ color: 'var(--color-ink)' }}>
          Salary coverage is broad; certainty is not.
        </p>
        <p className="mt-2 text-sm leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>
          {overview.data_quality.salary_coverage_pct}% have an estimate, but only {highConfidence}% of those estimates are high-confidence.
        </p>
      </article>
    </div>
  )
}

function SalaryRangeChart({ overview }: { overview: AdminAnalyticsOverview }) {
  const max = Math.max(1, ...overview.sector_salary.map(item => item.p75_hkd))
  return (
    <div className="rounded-lg p-5" style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)', boxShadow: 'var(--shadow-card)' }}>
      <h3 className="text-base font-semibold" style={{ color: 'var(--color-ink)' }}>Monthly salary by sector</h3>
      <p className="mt-1 text-xs leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>Median and middle 50% of estimated ranges · sectors with at least 10 roles</p>
      <div className="mt-6 space-y-4">
        {overview.sector_salary.map(item => (
          <div key={item.name} className="grid grid-cols-[7.5rem_1fr_4.5rem] items-center gap-3">
            <div className="min-w-0">
              <div className="truncate text-xs font-medium" style={{ color: 'var(--color-ink-muted)' }} title={item.name}>{item.name}</div>
              <div className="text-xs" style={{ color: 'var(--color-ink-muted)' }}>n={item.sample_size.toLocaleString()}</div>
            </div>
            <div className="relative h-5" aria-label={`${item.name}: median ${formatSalary(item.median_hkd)}, middle range ${formatSalary(item.p25_hkd)} to ${formatSalary(item.p75_hkd)}`}>
              <div className="absolute inset-x-0 top-1/2 h-px" style={{ backgroundColor: 'var(--color-border)' }} />
              <div
                className="absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full"
                style={{ left: `${item.p25_hkd / max * 100}%`, width: `${(item.p75_hkd - item.p25_hkd) / max * 100}%`, backgroundColor: getSectorColor(item.name).accent }}
              />
              <div
                className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white"
                style={{ left: `${item.median_hkd / max * 100}%`, backgroundColor: getSectorColor(item.name).accent, boxShadow: '0 1px 3px rgb(0 0 0 / 0.18)' }}
              />
            </div>
            <span className="text-right text-xs font-semibold tabular-nums" style={{ color: 'var(--color-ink)', fontFamily: 'var(--font-mono)' }}>{formatSalary(item.median_hkd)}</span>
          </div>
        ))}
      </div>
      <div className="sr-only">
        <table>
          <caption>Monthly estimated salary by sector</caption>
          <thead><tr><th scope="col">Sector</th><th scope="col">Sample</th><th scope="col">25th percentile</th><th scope="col">Median</th><th scope="col">75th percentile</th></tr></thead>
          <tbody>
            {overview.sector_salary.map(item => (
              <tr key={item.name}>
                <th scope="row">{item.name}</th><td>{item.sample_size}</td><td>{item.p25_hkd}</td><td>{item.median_hkd}</td><td>{item.p75_hkd}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function QualityPanel({ overview }: { overview: AdminAnalyticsOverview }) {
  const measures = [
    ['Descriptions', overview.data_quality.description_coverage_pct],
    ['AI enrichment row', overview.data_quality.enrichment_coverage_pct],
    ['Salary estimate', overview.data_quality.salary_coverage_pct],
    ['Required skills', overview.data_quality.skills_coverage_pct],
    ['Seniority', overview.data_quality.seniority_coverage_pct],
    ['Workplace type', overview.data_quality.workplace_coverage_pct],
  ] as const
  const confidenceTotal = Object.values(overview.salary_confidence).reduce((sum, value) => sum + value, 0)
  const confidence = [
    ['High', overview.salary_confidence.high ?? 0, '#15803D'],
    ['Medium', overview.salary_confidence.medium ?? 0, '#CA8A04'],
    ['Low', overview.salary_confidence.low ?? 0, '#DC2626'],
    ['Unknown', overview.salary_confidence.unknown ?? 0, '#94A3B8'],
  ] as const
  return (
    <div className="rounded-lg p-5" style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)', boxShadow: 'var(--shadow-card)' }}>
      <h3 className="text-base font-semibold" style={{ color: 'var(--color-ink)' }}>Data confidence</h3>
      <p className="mt-1 text-xs leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>Coverage is not certainty. Both are shown separately.</p>
      <div className="mt-5 space-y-3">
        {measures.map(([label, value]) => (
          <div key={label}>
            <div className="mb-1.5 flex justify-between gap-3 text-xs">
              <span style={{ color: 'var(--color-ink-muted)' }}>{label}</span>
              <span className="font-semibold tabular-nums" style={{ color: 'var(--color-ink)', fontFamily: 'var(--font-mono)' }}>{value}%</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full" style={{ backgroundColor: 'var(--color-surface-2)' }}>
              <div className="h-full rounded-full" style={{ width: `${value}%`, backgroundColor: value >= 90 ? '#0F766E' : value >= 70 ? 'var(--color-gold)' : 'var(--color-destructive)' }} />
            </div>
          </div>
        ))}
      </div>
      <div className="mt-6 border-t pt-5" style={{ borderColor: 'var(--color-border)' }}>
        <div className="mb-2 text-xs font-semibold" style={{ color: 'var(--color-ink)' }}>Salary estimate confidence</div>
        <div className="flex h-2 overflow-hidden rounded-full" aria-label="Salary estimate confidence distribution">
          {confidence.map(([label, value, color]) => value > 0 && (
            <div key={label} style={{ width: `${value / Math.max(1, confidenceTotal) * 100}%`, backgroundColor: color }} title={`${label}: ${value.toLocaleString()}`} />
          ))}
        </div>
        <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
          {confidence.map(([label, value, color]) => (
            <div key={label} className="flex items-center gap-2 text-xs" style={{ color: 'var(--color-ink-muted)' }}>
              <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
              {label} <strong className="tabular-nums" style={{ color: 'var(--color-ink)' }}>{value.toLocaleString()}</strong>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function MoverColumn({ title, rows, positive }: { title: string; rows: AdminMarketMover[]; positive: boolean }) {
  const Icon = positive ? ArrowUpRight : ArrowDownRight
  const color = positive ? '#15803D' : 'var(--color-destructive)'
  return (
    <div>
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold" style={{ color }}>
        <Icon size={16} aria-hidden="true" /> {title}
      </div>
      {rows.length === 0 ? (
        <p className="text-sm" style={{ color: 'var(--color-ink-muted)' }}>No comparable movement yet.</p>
      ) : (
        <div className="divide-y" style={{ borderColor: 'var(--color-border)' }}>
          {rows.map(row => (
            <div key={row.name} className="grid grid-cols-[1fr_auto] gap-3 py-2.5">
              <div className="min-w-0">
                <div className="truncate text-sm font-medium" style={{ color: 'var(--color-ink)' }} title={row.name}>{row.name}</div>
                <div className="mt-0.5 text-xs" style={{ color: 'var(--color-ink-muted)' }}>{row.previous} → {row.current} listings</div>
              </div>
              <div className="text-right text-sm font-semibold tabular-nums" style={{ color, fontFamily: 'var(--font-mono)' }}>
                {row.change > 0 ? '+' : ''}{row.change}
                {row.change_pct !== null && <div className="text-xs font-normal">{row.change_pct > 0 ? '+' : ''}{row.change_pct}%</div>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function MarketMovers({ overview }: { overview: AdminAnalyticsOverview }) {
  const movers = overview.market_movers
  return (
    <div className="rounded-lg p-5" style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)', boxShadow: 'var(--shadow-card)' }}>
      <div className="mb-5">
        <h3 className="text-base font-semibold" style={{ color: 'var(--color-ink)' }}>Employer momentum</h3>
        <p className="mt-1 text-xs leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>
          Change in observed source listings{movers.current_date && movers.comparison_date ? ` · ${movers.comparison_date} to ${movers.current_date}` : ''}. Complete scrape days only.
        </p>
      </div>
      <div className="grid gap-7 sm:grid-cols-2">
        <MoverColumn title="Expanding" rows={movers.gainers} positive />
        <MoverColumn title="Contracting" rows={movers.decliners} positive={false} />
      </div>
    </div>
  )
}

export default function AnalyticsOverview({ overview, history }: { overview: AdminAnalyticsOverview; history: AdminRunHistoryPoint[] }) {
  return (
    <div className="space-y-12">
      <section className="space-y-4">
        <MarketPulse overview={overview} />
        <AnalystReadout overview={overview} />
      </section>

      <section>
        <SectionHeading title="Market direction" description="Hiring inventory and employer-level movement. History reflects source listings observed by the scraper, not deduplicated board roles." />
        <div className="grid gap-5 lg:grid-cols-[1.1fr_0.9fr]">
          <TrendLine
            title="Observed listing inventory"
            description="Total listings returned on each broadly covered pipeline day"
            points={history.map(point => ({ x: point.scraped_date.slice(5), y: point.total_jobs }))}
            color="var(--color-blue)"
            unit=" listings"
          />
          <MarketMovers overview={overview} />
        </div>
      </section>

      <section>
        <SectionHeading title="Who is hiring" description="The board is deduplicated before sector and employer analysis, so a role syndicated across several platforms counts once." />
        <div className="grid gap-5 lg:grid-cols-2">
          <HBarChart title="Primary source mix" description="The source chosen to represent each board-visible vacancy" data={toEntriesWithOther(overview.by_board_source)} color="var(--color-blue)" unit=" roles" />
          <HBarChart title="Roles by inferred sector" description="Company-name heuristic; employers outside named groups currently fall into Banking" data={toEntries(overview.by_sector).map(item => ({ ...item, color: getSectorColor(item.label).accent }))} unit=" roles" />
          <HBarChart title="Top employers" description={`Top five hold ${overview.top5_company_share_pct}% · HHI ${overview.company_concentration_hhi.toLocaleString()} across ${overview.company_entity_count} canonical employer slugs`} data={overview.top_companies.map(company => ({ label: company.name, value: company.count }))} color="var(--color-ink)" unit=" roles" />
          <HBarChart title="Seniority mix" description={`${overview.data_quality.seniority_coverage_pct}% of visible roles classified`} data={toEntries(overview.by_seniority)} color="#0F766E" unit=" roles" />
        </div>
      </section>

      <section>
        <SectionHeading title="Pay intelligence" description={`Estimated monthly salary for ${overview.salary_sample_size.toLocaleString()} board-visible roles. Treat medium- and low-confidence estimates as directional, not quoted compensation.`} />
        <div className="grid gap-5 lg:grid-cols-2">
          <HBarChart
            title="Salary distribution"
            description={`Median ${formatSalary(overview.salary_median_hkd)} · middle 50% ${formatSalary(overview.salary_p25_hkd)}–${formatSalary(overview.salary_p75_hkd)}`}
            data={SALARY_BUCKET_ORDER.filter(bucket => overview.salary_distribution[bucket] !== undefined).map(bucket => ({ label: bucket, value: overview.salary_distribution[bucket] }))}
            color="var(--color-gold)"
            unit=" roles"
          />
          <SalaryRangeChart overview={overview} />
        </div>
      </section>

      <section>
        <SectionHeading title="Demand signals" description="Skills are case-normalized before counting, so capitalization variants do not manufacture separate trends." />
        <div className="grid gap-5 lg:grid-cols-[1.1fr_0.9fr]">
          <HBarChart title="Most requested skills" description="Share is measured against every board-visible role" data={overview.top_skills.map(skill => ({ label: skill.name, value: skill.count }))} color="var(--color-blue)" unit=" roles" />
          <HBarChart title="Workplace model" description={`${overview.remote_friendly_pct}% of classified roles are hybrid or remote`} data={toEntries(overview.by_remote_type)} color="#6D28D9" unit=" roles" />
        </div>
      </section>

      <section>
        <SectionHeading title="Can we trust the picture?" description="Completeness and model confidence are operational metrics. High coverage can still conceal uncertain estimates." />
        <div className="grid gap-5 lg:grid-cols-[0.9fr_1.1fr]">
          <QualityPanel overview={overview} />
          <TrendLine
            title="Zero-result companies"
            description="Companies returning no listings on each pipeline day—a source-health signal, not necessarily proof that hiring stopped"
            points={history.map(point => ({ x: point.scraped_date.slice(5), y: point.companies_down }))}
            color="#854D0E"
            unit=" companies"
          />
        </div>
      </section>
    </div>
  )
}
