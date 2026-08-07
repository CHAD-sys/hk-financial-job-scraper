import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, Loader2, RefreshCw, XCircle } from 'lucide-react'
import { Navigate } from 'react-router-dom'
import Nav from '../components/Nav'
import AnalyticsOverview from '../components/admin/AnalyticsOverview'
import JobEditor from '../components/admin/JobEditor'
import SubmissionsPanel from '../components/admin/SubmissionsPanel'
import { useAuth } from '../auth/useAuth'
import {
  fetchAdminAnalyticsOverview,
  fetchAdminRunHistory,
  fetchAdminRunToday,
  type AdminAnalyticsOverview,
  type AdminRunHistoryPoint,
  type AdminRunToday,
} from '../api/client'

type DashboardSection = 'market intelligence' | 'run history' | 'pipeline status'
type DashboardErrors = Partial<Record<DashboardSection, string>>

/**
 * Admin Mode — operational control plus a decision-grade market brief.
 *
 * The analytics lead because that is the page's recurring read; moderation and
 * direct edits remain one jump away in the same document. Every metric explains
 * whether it counts source listings or deduplicated board roles, because those
 * two populations answer different questions and must never be silently mixed.
 */
export default function AdminPage() {
  const { seeker, loading } = useAuth()
  const [today, setToday] = useState<AdminRunToday | null>(null)
  const [history, setHistory] = useState<AdminRunHistoryPoint[] | null>(null)
  const [overview, setOverview] = useState<AdminAnalyticsOverview | null>(null)
  const [sectionErrors, setSectionErrors] = useState<DashboardErrors>({})
  const [refreshing, setRefreshing] = useState(false)

  const loadDashboard = useCallback(async () => {
    setRefreshing(true)
    setSectionErrors({})
    const results = await Promise.allSettled([
      fetchAdminRunToday(),
      fetchAdminRunHistory(30),
      fetchAdminAnalyticsOverview(),
    ])
    const nextErrors: DashboardErrors = {}
    const [todayResult, historyResult, overviewResult] = results
    if (todayResult.status === 'fulfilled') setToday(todayResult.value)
    else nextErrors['pipeline status'] = todayResult.reason instanceof Error ? todayResult.reason.message : 'Could not load pipeline status.'
    if (historyResult.status === 'fulfilled') setHistory(historyResult.value)
    else nextErrors['run history'] = historyResult.reason instanceof Error ? historyResult.reason.message : 'Could not load run history.'
    if (overviewResult.status === 'fulfilled') setOverview(overviewResult.value)
    else nextErrors['market intelligence'] = overviewResult.reason instanceof Error ? overviewResult.reason.message : 'Could not load market intelligence.'
    setSectionErrors(nextErrors)
    setRefreshing(false)
  }, [])

  useEffect(() => {
    if (loading || !seeker?.is_admin) return
    void loadDashboard()
  }, [loading, seeker?.is_admin, loadDashboard])

  if (!loading && (!seeker || !seeker.is_admin)) {
    return <Navigate to="/signin" state={{ from: '/admin' }} replace />
  }

  const loadingDashboard = !overview && !sectionErrors['market intelligence']
  const errorEntries = Object.entries(sectionErrors)

  return (
    <div style={{ backgroundColor: 'var(--color-bg)', minHeight: '100dvh' }}>
      <Nav />
      <main
        className="mx-auto max-w-7xl px-4 pb-20 sm:px-6 lg:px-8"
        style={{ paddingTop: '2.5rem' }}
      >
        <header className="mb-8 flex flex-col gap-5 border-b pb-6 sm:flex-row sm:items-end sm:justify-between" style={{ borderColor: 'var(--color-border)' }}>
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em]" style={{ color: 'var(--color-gold)' }}>Admin Mode</p>
            <h1 className="mt-1 text-3xl font-bold tracking-tight sm:text-4xl" style={{ fontFamily: 'var(--font-display)', color: 'var(--color-ink)' }}>
              Intelligence desk
            </h1>
            <p className="mt-2 text-sm" style={{ color: 'var(--color-ink-muted)' }}>
              Signed in as {seeker?.display_name || seeker?.email} · live market data and pipeline controls
            </p>
          </div>
          <button
            type="button"
            onClick={() => void loadDashboard()}
            disabled={refreshing}
            className="inline-flex min-h-11 items-center justify-center gap-2 self-start rounded-md px-4 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-60 sm:self-auto"
            style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border-strong)', color: 'var(--color-ink)' }}
          >
            <RefreshCw size={15} className={refreshing ? 'animate-spin' : ''} aria-hidden="true" />
            {refreshing ? 'Refreshing…' : 'Refresh data'}
          </button>
        </header>

        <nav className="mb-7 flex flex-wrap gap-x-1 border-b" aria-label="Admin page sections" style={{ borderColor: 'var(--color-border)' }}>
          {[
            ['#market-intelligence', 'Market intelligence'],
            ['#pipeline-operations', 'Pipeline operations'],
            ['#verification', 'Verification'],
            ...(seeker?.is_super_admin ? [['#job-editor', 'Job editor']] : []),
          ].map(([href, label]) => (
            <a
              key={href}
              href={href}
              className="shrink-0 border-b-2 border-transparent px-3 py-3 text-sm font-medium transition-colors hover:border-current"
              style={{ color: 'var(--color-ink-muted)' }}
            >
              {label}
            </a>
          ))}
        </nav>

        {errorEntries.length > 0 && (
          <div className="mb-7 flex flex-col gap-3 rounded-lg p-4 sm:flex-row sm:items-center sm:justify-between" role="alert" style={{ backgroundColor: '#FEF2F2', border: '1px solid #FECACA', color: '#991B1B' }}>
            <div className="flex items-start gap-2 text-sm">
              <XCircle size={17} className="mt-0.5 shrink-0" aria-hidden="true" />
              <span>
                <strong>Some dashboard data could not be loaded.</strong>{' '}
                {errorEntries.map(([section, message]) => `${section}: ${message}`).join(' · ')}
              </span>
            </div>
            <button type="button" onClick={() => void loadDashboard()} className="min-h-10 shrink-0 rounded-md px-3 text-sm font-semibold" style={{ border: '1px solid #FCA5A5' }}>
              Try again
            </button>
          </div>
        )}

        <section id="market-intelligence" className="scroll-mt-28">
          {loadingDashboard ? (
            <div className="flex min-h-72 items-center justify-center rounded-xl" style={{ backgroundColor: 'var(--color-masthead)' }}>
              <div className="text-center" style={{ color: 'var(--color-ink-inverse)' }}>
                <Loader2 size={24} className="mx-auto animate-spin" aria-hidden="true" />
                <p className="mt-3 text-sm" style={{ color: 'rgba(248,250,252,0.7)' }}>Building the market brief…</p>
              </div>
            </div>
          ) : overview ? (
            <AnalyticsOverview overview={overview} history={history ?? []} />
          ) : (
            <div className="rounded-lg p-5 text-sm" role="status" style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)', color: 'var(--color-ink-muted)' }}>
              Market intelligence is unavailable. Use “Refresh data” to try this section again.
            </div>
          )}
        </section>

        <section id="pipeline-operations" className="mt-16 scroll-mt-28 border-t pt-12" style={{ borderColor: 'var(--color-border)' }}>
          <div className="mb-5 max-w-3xl">
            <h2 className="text-2xl font-semibold tracking-tight" style={{ color: 'var(--color-ink)', fontFamily: 'var(--font-display)' }}>Pipeline operations</h2>
            <p className="mt-1.5 text-sm leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>Today’s collection health. A zero result is an investigation signal, not automatic proof that an employer stopped hiring.</p>
          </div>

          {!today && sectionErrors['pipeline status'] ? (
            <div className="rounded-lg p-5 text-sm" role="status" style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)', color: 'var(--color-ink-muted)' }}>
              Pipeline status is unavailable. The market brief above may still be current.
            </div>
          ) : !today ? (
            <p className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-ink-muted)' }}><Loader2 size={14} className="animate-spin" /> Loading run status…</p>
          ) : (
            <div className="overflow-hidden rounded-lg" style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)', boxShadow: 'var(--shadow-card)' }}>
              <div className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:justify-between" style={{ backgroundColor: today.ran_today ? '#F0FDF4' : '#FFFBEB', borderBottom: '1px solid var(--color-border)' }}>
                <div className="flex items-center gap-2 text-sm font-semibold" style={{ color: today.ran_today ? '#166534' : '#854D0E' }}>
                  {today.ran_today ? <CheckCircle2 size={17} /> : <AlertTriangle size={17} />}
                  {today.ran_today ? `Pipeline recorded for ${today.date}` : `No pipeline record yet for ${today.date}`}
                </div>
                {today.snapshot_received_at && (
                  <div className="text-xs" style={{ color: 'var(--color-ink-muted)' }}>
                    Daily snapshot synced {new Date(today.snapshot_received_at).toLocaleTimeString('en-HK', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Hong_Kong' })} HKT
                  </div>
                )}
                {today.log.available && today.log.last_run_found && (
                  <div className="text-xs" style={{ color: today.log.crashed ? 'var(--color-destructive)' : 'var(--color-ink-muted)' }}>
                    {today.log.crashed
                      ? `Log reports a crash at ${today.log.last_phase ?? 'an unknown phase'}`
                      : today.log.finished ? 'Latest logged run finished cleanly' : `Run in progress · ${today.log.last_phase ?? 'phase unknown'}`}
                  </div>
                )}
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6">
                {[
                  ['Listings collected', today.listings_collected_today.toLocaleString(), `Pipeline snapshot for ${today.date}`],
                  ['Companies scraped', today.companies_scraped_today.toLocaleString(), 'Recorded today'],
                  ['Zero-result companies', today.companies_zero_today.toLocaleString(), 'Review source health'],
                  ['Listings added', `+${today.jobs_added_today.toLocaleString()}`, 'Versus prior company snapshots'],
                  ['Listings removed', `−${today.jobs_removed_today.toLocaleString()}`, 'Versus prior company snapshots'],
                  ['Description coverage', `${today.description_coverage_pct}%`, 'Across active source rows'],
                ].map(([label, value, detail], index) => (
                  <div
                    key={label}
                    className={`min-w-0 p-4 ${index > 1 ? 'border-t' : ''} ${
                      index % 2 ? 'border-l' : ''
                    } sm:border-l-0 sm:border-t-0 ${index >= 3 ? 'sm:border-t' : ''} ${
                      index % 3 ? 'sm:border-l' : ''
                    } lg:border-l-0 lg:border-t-0 ${index > 0 ? 'lg:border-l' : ''}`}
                    style={{ borderColor: 'var(--color-border)' }}
                  >
                    <div className="text-2xl font-semibold tabular-nums" style={{ color: label === 'Zero-result companies' && today.companies_zero_today > 0 ? '#854D0E' : 'var(--color-ink)', fontFamily: 'var(--font-mono)' }}>{value}</div>
                    <div className="mt-2 text-xs font-semibold" style={{ color: 'var(--color-ink)' }}>{label}</div>
                    <div className="mt-1 text-xs leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>{detail}</div>
                  </div>
                ))}
              </div>
              {today.zero_companies.length > 0 && (
                <details className="border-t px-5 py-4" style={{ borderColor: 'var(--color-border)' }}>
                  <summary className="cursor-pointer text-sm font-semibold" style={{ color: '#854D0E' }}>Review {today.zero_companies.length} highest-priority zero-result companies</summary>
                  <p className="mt-3 max-w-5xl text-sm leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>{today.zero_companies.join(' · ')}</p>
                </details>
              )}
            </div>
          )}
        </section>

        <section id="verification" className="mt-16 scroll-mt-28 border-t pt-12" style={{ borderColor: 'var(--color-border)' }}>
          <div className="mb-5 max-w-3xl">
            <h2 className="text-2xl font-semibold tracking-tight" style={{ color: 'var(--color-ink)', fontFamily: 'var(--font-display)' }}>Verification queue</h2>
            <p className="mt-1.5 text-sm leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>Review employer-submitted roles before they become part of the public market dataset.</p>
          </div>
          <SubmissionsPanel />
        </section>

        {seeker?.is_super_admin && (
          <section id="job-editor" className="mt-16 scroll-mt-28 border-t pt-12" style={{ borderColor: 'var(--color-border)' }}>
            <JobEditor />
          </section>
        )}
      </main>
    </div>
  )
}
