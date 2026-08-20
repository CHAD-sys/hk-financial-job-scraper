import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, Loader2, RefreshCw, XCircle } from 'lucide-react'
import { Navigate } from 'react-router-dom'
import Nav from '../components/Nav'
import AccountsDirectory from '../components/admin/AccountsDirectory'
import AnalyticsOverview from '../components/admin/AnalyticsOverview'
import AdminSectionNav from '../components/admin/AdminSectionNav'
import JobEditor from '../components/admin/JobEditor'
import OperationsCenter from '../components/admin/OperationsCenter'
import SubmissionsPanel from '../components/admin/SubmissionsPanel'
import UserActivity from '../components/admin/UserActivity'
import { useAuth } from '../auth/useAuth'
import { useAdminMode } from '../adminMode/useAdminMode'
import {
  fetchAdminAccounts,
  fetchAdminIntelligence,
  type AdminAccountsResponse,
  type AdminIntelligenceSnapshot,
} from '../api/client'

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
  const { adminMode, canUseAdminMode, setAdminMode } = useAdminMode()

  // Being on this page IS the admin view, so arriving here turns the mode on —
  // by the switch, by a bookmark, or by typing the URL. Without this an admin
  // who deep-linked to /admin would sit in the panel while the nav still
  // offered to take them INTO Admin Mode, and the board behind them would still
  // be the Seeker's.
  useEffect(() => {
    if (!loading && canUseAdminMode && !adminMode) setAdminMode(true)
  }, [loading, canUseAdminMode, adminMode, setAdminMode])
  const [snapshot, setSnapshot] = useState<AdminIntelligenceSnapshot | null>(null)
  const [dashboardError, setDashboardError] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [days, setDays] = useState(30)
  const [accounts, setAccounts] = useState<AdminAccountsResponse | null>(null)
  const [accountsError, setAccountsError] = useState<string | null>(null)

  const loadDashboard = useCallback(async (windowDays: number) => {
    setRefreshing(true)
    setDashboardError(null)
    try {
      setSnapshot(await fetchAdminIntelligence(windowDays))
    } catch (error) {
      setDashboardError(error instanceof Error ? error.message : 'Could not load admin intelligence.')
    } finally {
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    if (loading || !seeker?.is_admin) return
    void loadDashboard(days)
  }, [loading, seeker?.is_admin, days, loadDashboard])

  // Its own fetch, not folded into loadDashboard: the account directory has
  // no "window" to respond to, so it should not re-fetch every time `days`
  // changes, and it is Ultimate-Admin-only so ordinary admins never call it.
  useEffect(() => {
    if (loading || !seeker?.is_super_admin) return
    fetchAdminAccounts()
      .then(setAccounts)
      .catch(error => setAccountsError(error instanceof Error ? error.message : 'Could not load the account directory.'))
  }, [loading, seeker?.is_super_admin])

  if (!loading && (!seeker || !seeker.is_admin)) {
    return <Navigate to="/signin" state={{ from: '/admin' }} replace />
  }

  const today = snapshot?.today ?? null
  const history = snapshot?.history.points ?? []
  const overview = snapshot?.analytics ?? null
  const operations = snapshot?.operations ?? null
  const userActivity = snapshot?.user_activity ?? null
  const loadingDashboard = !snapshot && !dashboardError
  const loadingOperations = loadingDashboard

  return (
    <div style={{ backgroundColor: 'var(--color-bg)', minHeight: '100dvh' }}>
      <Nav />
      <main
        className="mx-auto max-w-7xl px-4 pb-20 sm:px-6 lg:px-8"
        style={{ paddingTop: '2.5rem' }}
      >
        <header className="mb-8 flex flex-col gap-5 border-b pb-6 sm:flex-row sm:items-end sm:justify-between" style={{ borderColor: 'var(--color-border)' }}>
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em]" style={{ color: 'var(--color-gold)' }}>Admin panel</p>
            <h1 className="mt-1 text-3xl font-bold tracking-tight sm:text-4xl" style={{ fontFamily: 'var(--font-display)', color: 'var(--color-ink)' }}>
              Intelligence desk
            </h1>
            <p className="mt-2 text-sm" style={{ color: 'var(--color-ink-muted)' }}>
              Signed in as {seeker?.display_name || seeker?.email} · live market data and pipeline controls
            </p>
          </div>
          <button
            type="button"
            onClick={() => void loadDashboard(days)}
            disabled={refreshing}
            className="inline-flex min-h-11 items-center justify-center gap-2 self-start rounded-md px-4 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-60 sm:self-auto"
            style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border-strong)', color: 'var(--color-ink)' }}
          >
            <RefreshCw size={15} className={refreshing ? 'animate-spin' : ''} aria-hidden="true" />
            {refreshing ? 'Refreshing…' : 'Refresh data'}
          </button>
        </header>

        <AdminSectionNav isSuperAdmin={Boolean(seeker?.is_super_admin)} />

        {dashboardError && (
          <div className="mb-7 flex flex-col gap-3 rounded-lg p-4 sm:flex-row sm:items-center sm:justify-between" role="alert" style={{ backgroundColor: '#FEF2F2', border: '1px solid #FECACA', color: '#991B1B' }}>
            <div className="flex items-start gap-2 text-sm">
              <XCircle size={17} className="mt-0.5 shrink-0" aria-hidden="true" />
              <span>
                <strong>The intelligence snapshot could not be loaded.</strong>{' '}
                {dashboardError}
              </span>
            </div>
            <button type="button" onClick={() => void loadDashboard(days)} className="min-h-10 shrink-0 rounded-md px-3 text-sm font-semibold" style={{ border: '1px solid #FCA5A5' }}>
              Try again
            </button>
          </div>
        )}

        <section id="operations-center" className="scroll-mt-28">
          <div className="mb-6 max-w-3xl">
            <p className="text-xs font-semibold uppercase tracking-[0.14em]" style={{ color: 'var(--color-gold)' }}>Daily control room</p>
            <h2 className="mt-1 text-2xl font-semibold tracking-tight sm:text-3xl" style={{ color: 'var(--color-ink)', fontFamily: 'var(--font-display)' }}>Pipeline reliability and cost</h2>
            <p className="mt-2 text-sm leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>What ran, what changed, what it cost, and what needs an administrator’s attention. Detailed phase and source telemetry starts with the first pipeline run after this release.</p>
          </div>
          {loadingOperations ? (
            <div className="flex min-h-64 items-center justify-center rounded-lg" style={{ backgroundColor: 'var(--color-masthead)' }}>
              <div className="text-center" style={{ color: 'var(--color-ink-inverse)' }}>
                <Loader2 size={24} className="mx-auto animate-spin" aria-hidden="true" />
                <p className="mt-3 text-sm">Loading operational evidence…</p>
              </div>
            </div>
          ) : operations ? (
            <OperationsCenter data={operations} />
          ) : (
            <div className="rounded-lg p-5 text-sm" role="status" style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)', color: 'var(--color-ink-muted)' }}>
              Pipeline operations are unavailable. Use “Refresh data” to try this section again.
            </div>
          )}
        </section>

        <section id="user-activity" className="mt-16 scroll-mt-28 border-t pt-12" style={{ borderColor: 'var(--color-border)' }}>
          {loadingDashboard ? (
            <div className="flex min-h-64 items-center justify-center rounded-lg" style={{ backgroundColor: 'var(--color-masthead)' }}>
              <div className="text-center" style={{ color: 'var(--color-ink-inverse)' }}>
                <Loader2 size={24} className="mx-auto animate-spin" aria-hidden="true" />
                <p className="mt-3 text-sm">Loading Seeker activity…</p>
              </div>
            </div>
          ) : userActivity ? (
            <UserActivity overview={userActivity} days={days} onDaysChange={setDays} />
          ) : (
            <div className="rounded-lg p-5 text-sm" role="status" style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)', color: 'var(--color-ink-muted)' }}>
              Seeker activity is unavailable. Use “Refresh data” to try this section again.
            </div>
          )}
        </section>

        <section id="market-intelligence" className="mt-16 scroll-mt-28 border-t pt-12" style={{ borderColor: 'var(--color-border)' }}>
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

        <section id="daily-collection" className="mt-16 scroll-mt-28 border-t pt-12" style={{ borderColor: 'var(--color-border)' }}>
          <div className="mb-5 max-w-3xl">
            <h2 className="text-2xl font-semibold tracking-tight" style={{ color: 'var(--color-ink)', fontFamily: 'var(--font-display)' }}>Daily collection totals</h2>
            <p className="mt-1.5 text-sm leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>Today’s collection health. A zero result is an investigation signal, not automatic proof that an employer stopped hiring.</p>
          </div>

          {!today && dashboardError ? (
            <div className="rounded-lg p-5 text-sm" role="status" style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)', color: 'var(--color-ink-muted)' }}>
              Daily collection is unavailable because the intelligence snapshot could not be loaded.
            </div>
          ) : !today ? (
            <p className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-ink-muted)' }}><Loader2 size={14} className="animate-spin" /> Loading run status…</p>
          ) : (
            <div className="overflow-hidden rounded-lg" style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)', boxShadow: 'var(--shadow-card)' }}>
              <div className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:justify-between" style={{ backgroundColor: today.ran_today ? '#F0FDF4' : '#FFFBEB', borderBottom: '1px solid var(--color-border)' }}>
                <div className="flex items-center gap-2 text-sm font-semibold" style={{ color: today.ran_today ? '#166534' : '#854D0E' }}>
                  {today.ran_today ? <CheckCircle2 size={17} /> : <AlertTriangle size={17} />}
                  {!today.tracking_available
                    ? 'Daily collection history is not available'
                    : today.ran_today
                      ? `Pipeline recorded for ${today.date}`
                      : `No pipeline record yet for ${today.date}`}
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
              {!today.tracking_available ? (
                <div className="px-5 py-6 text-sm" style={{ color: 'var(--color-ink-muted)' }}>
                  The live Role catalogue is available, but no collection-history ledger was found.
                  The figures below are withheld so missing evidence is never presented as zero activity.
                </div>
              ) : (
                <>
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
                </>
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
          <section id="accounts" className="mt-16 scroll-mt-28 border-t pt-12" style={{ borderColor: 'var(--color-border)' }}>
            {accounts ? (
              <AccountsDirectory data={accounts} />
            ) : accountsError ? (
              <div className="rounded-lg p-5 text-sm" role="status" style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)', color: 'var(--color-ink-muted)' }}>
                {accountsError}
              </div>
            ) : (
              <div className="flex min-h-64 items-center justify-center rounded-lg" style={{ backgroundColor: 'var(--color-masthead)' }}>
                <div className="text-center" style={{ color: 'var(--color-ink-inverse)' }}>
                  <Loader2 size={24} className="mx-auto animate-spin" aria-hidden="true" />
                  <p className="mt-3 text-sm">Loading the account directory…</p>
                </div>
              </div>
            )}
          </section>
        )}

        {/* Every admin, not just Ultimate Admin (ADR 0019). The board's pencil
            covers correcting a Role you happened to be looking at; this covers
            working through a list of corrections without hunting for each one
            on the board first. Both call the same two endpoints. */}
        <section id="job-editor" className="mt-16 scroll-mt-28 border-t pt-12" style={{ borderColor: 'var(--color-border)' }}>
          <JobEditor />
        </section>
      </main>
    </div>
  )
}
