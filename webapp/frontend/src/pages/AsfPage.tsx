import { useCallback, useEffect, useMemo, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { Check, CircleAlert, ExternalLink, Loader2, RefreshCw } from 'lucide-react'
import Nav from '../components/Nav'
import { useAuth } from '../auth/useAuth'
import {
  fetchBannerValidationQueue,
  fetchMTAmbiguousCandidates,
  saveBannerCandidates,
  type BannerValidationQueue,
  type MTAmbiguousCandidate,
} from '../api/client'

const hkDate = (value: string) => new Intl.DateTimeFormat('en-HK', {
  day: 'numeric',
  month: 'short',
  timeZone: 'Asia/Hong_Kong',
}).format(new Date(`${value}T00:00:00+08:00`))

/** Ultimate Admin's editorial gate. Nothing here publishes automatically. */
export default function AsfPage() {
  const { seeker, loading } = useAuth()
  const [banner, setBanner] = useState<BannerValidationQueue | null>(null)
  const [mtCandidates, setMtCandidates] = useState<MTAmbiguousCandidate[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const load = useCallback(async () => {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const [nextBanner, mt] = await Promise.all([
        fetchBannerValidationQueue(),
        fetchMTAmbiguousCandidates(),
      ])
      const approved = new Set(
        nextBanner.approved.map(role => `${role.source}:${role.source_id}`),
      )
      const hasSavedSelection = nextBanner.saved || nextBanner.approved.length > 0
      setBanner(nextBanner)
      setMtCandidates(mt.roles)
      setSelected(hasSavedSelection
        ? approved
        : new Set(nextBanner.roles.map(role => `${role.source}:${role.source_id}`)))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load validation queues.')
    } finally {
      setBusy(false)
    }
  }, [])

  useEffect(() => {
    if (!loading && seeker?.is_super_admin) void load()
  }, [loading, seeker?.is_super_admin, load])

  const selectedRoles = useMemo(
    () => banner?.roles.filter(role => selected.has(`${role.source}:${role.source_id}`)) ?? [],
    [banner, selected],
  )

  if (!loading && !seeker?.is_super_admin) {
    return <Navigate to="/signin" state={{ from: '/validate' }} replace />
  }

  async function save() {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      await saveBannerCandidates(selectedRoles)
      await load()
      setNotice('Banner selection saved. You can add, remove, or switch Roles at any time.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save next week’s banner.')
    } finally {
      setBusy(false)
    }
  }

  function toggle(key: string) {
    setNotice(null)
    setSelected(current => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  return (
    <div className="min-h-dvh" style={{ backgroundColor: 'var(--color-bg)' }}>
      <Nav />
      <main className="mx-auto max-w-7xl px-4 pb-20 pt-10 sm:px-6 lg:px-8">
        <header
          className="grid gap-6 border-b pb-8 lg:grid-cols-[1fr_auto] lg:items-end"
          style={{ borderColor: 'var(--color-border)' }}
        >
          <div>
            <p
              className="text-xs font-semibold uppercase tracking-[.16em]"
              style={{ color: 'var(--color-gold)' }}
            >
              Ultimate Admin
            </p>
            <h1
              className="mt-2 text-4xl font-bold tracking-tight sm:text-5xl"
              style={{ color: 'var(--color-ink)', fontFamily: 'var(--font-display)' }}
            >
              Validate publication
            </h1>
            <p
              className="mt-3 max-w-2xl text-base leading-7"
              style={{ color: 'var(--color-ink-muted)' }}
            >
              Review the evidence behind each Role and keep the promoted selection current.
              Every saved selection remains editable.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void load()}
            disabled={busy}
            className="inline-flex min-h-11 items-center justify-center gap-2 border px-4 text-sm font-semibold disabled:opacity-50"
            style={{
              borderColor: 'var(--color-border-strong)',
              color: 'var(--color-ink)',
              backgroundColor: 'var(--color-surface)',
            }}
          >
            {busy ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
            Refresh queues
          </button>
        </header>

        {error && (
          <p
            role="alert"
            className="mt-6 border px-4 py-3 text-sm"
            style={{
              borderColor: 'var(--color-destructive)',
              color: 'var(--color-destructive)',
              backgroundColor: 'var(--color-surface)',
            }}
          >
            {error}
          </p>
        )}
        {notice && (
          <p
            role="status"
            className="mt-6 border px-4 py-3 text-sm"
            style={{
              borderColor: 'var(--color-border-strong)',
              color: 'var(--color-ink)',
              backgroundColor: 'var(--color-surface)',
            }}
          >
            {notice}
          </p>
        )}

        <section className="mt-10" aria-labelledby="banner-queue">
          <div
            className="flex flex-wrap items-end justify-between gap-4 border-b pb-4"
            style={{ borderColor: 'var(--color-border)' }}
          >
            <div>
              <p
                className="text-xs font-semibold uppercase tracking-[.14em]"
                style={{ color: 'var(--color-gold)' }}
              >
                Next week’s banner
              </p>
              <h2
                id="banner-queue"
                className="mt-1 text-2xl font-semibold"
                style={{ color: 'var(--color-ink)', fontFamily: 'var(--font-display)' }}
              >
                Choose the Roles visitors will see first
              </h2>
              <p className="mt-2 max-w-2xl text-sm leading-6" style={{ color: 'var(--color-ink-muted)' }}>
                Read the summary and open the live destination before selecting. Saving replaces
                the current banner, but never locks it.
              </p>
            </div>
            {banner && (
              <span className="text-sm" style={{ color: 'var(--color-ink-muted)' }}>
                {hkDate(banner.week_start)}–{hkDate(banner.week_end)} · {banner.roles.length} suggested
              </span>
            )}
          </div>

          {banner && banner.roles.length > 0 && (
            <div
              role="group"
              aria-label="Banner Role selection"
              className="mt-5 divide-y border"
              style={{
                borderColor: 'var(--color-border)',
                backgroundColor: 'var(--color-surface)',
              }}
            >
              {banner.roles.map((role, index) => {
                const key = `${role.source}:${role.source_id}`
                const titleId = `banner-role-${index}`
                return (
                  <article
                    key={key}
                    className="grid gap-4 p-5 transition-colors hover:bg-[var(--color-surface-2)] sm:grid-cols-[auto_minmax(0,1fr)_auto] sm:items-start"
                  >
                    <input
                      type="checkbox"
                      checked={selected.has(key)}
                      onChange={() => toggle(key)}
                      aria-labelledby={titleId}
                      className="mt-0.5 size-5 accent-[var(--color-blue)]"
                    />
                    <div className="min-w-0">
                      <h3 id={titleId} className="font-semibold" style={{ color: 'var(--color-ink)' }}>
                        {role.title}
                      </h3>
                      <p className="mt-1 text-sm" style={{ color: 'var(--color-ink-muted)' }}>
                        {role.company} · {role.category} · {role.seniority} · posted {hkDate(role.posted_at)}
                      </p>
                      <p className="mt-3 text-sm leading-6" style={{ color: 'var(--color-ink)' }}>
                        {role.description_summary || 'No description summary available yet.'}
                      </p>
                      {role.apply_url ? (
                        <a
                          href={role.apply_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          aria-label={`Check live posting for ${role.title}`}
                          className="mt-3 inline-flex min-h-11 items-center gap-2 text-sm font-semibold underline decoration-1 underline-offset-4"
                          style={{ color: 'var(--color-blue)' }}
                        >
                          Check live posting
                          <ExternalLink size={15} />
                        </a>
                      ) : (
                        <p className="mt-3 text-sm" style={{ color: 'var(--color-ink-faint)' }}>
                          No live posting link is available.
                        </p>
                      )}
                    </div>
                    <p
                      className="text-sm sm:min-w-36 sm:text-right"
                      style={{ color: 'var(--color-ink-muted)' }}
                    >
                      HK${role.salary_min.toLocaleString()}–{role.salary_max.toLocaleString()}
                      <br />
                      {role.salary_confidence} confidence
                    </p>
                  </article>
                )
              })}
            </div>
          )}

          {banner && banner.roles.length === 0 && !busy && (
            <p
              className="mt-5 border p-5 text-sm"
              style={{ borderColor: 'var(--color-border)', color: 'var(--color-ink-muted)' }}
            >
              No banner candidates are available right now. You can still save an empty banner.
            </p>
          )}

          {banner && (
            <div className="mt-4 flex flex-wrap items-center justify-between gap-4">
              <p className="max-w-2xl text-sm" style={{ color: 'var(--color-ink-muted)' }}>
                {selectedRoles.length} selected. Return at any time to add, remove, or switch Roles.
                Closed Roles are withheld from the public banner automatically.
              </p>
              <button
                type="button"
                disabled={busy}
                onClick={() => void save()}
                className="inline-flex min-h-11 items-center gap-2 px-5 text-sm font-semibold disabled:opacity-50"
                style={{ color: 'var(--color-ink-inverse)', backgroundColor: 'var(--color-ink)' }}
              >
                {busy ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
                Save {selectedRoles.length} {selectedRoles.length === 1 ? 'Role' : 'Roles'}
              </button>
            </div>
          )}
        </section>

        <section className="mt-14" aria-labelledby="mt-queue">
          <div className="border-b pb-4" style={{ borderColor: 'var(--color-border)' }}>
            <p
              className="text-xs font-semibold uppercase tracking-[.14em]"
              style={{ color: 'var(--color-gold)' }}
            >
              MT review
            </p>
            <h2
              id="mt-queue"
              className="mt-1 text-2xl font-semibold"
              style={{ color: 'var(--color-ink)', fontFamily: 'var(--font-display)' }}
            >
              Potential Management Trainee postings
            </h2>
            <p className="mt-2 max-w-2xl text-sm leading-6" style={{ color: 'var(--color-ink-muted)' }}>
              Workbook-company matches with a graduate or trainee signal, but not enough evidence
              for the public MT directory.
            </p>
          </div>
          <div
            className="mt-5 divide-y border"
            style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)' }}
          >
            {mtCandidates.map(({ job, reason, watchlist_company }) => (
              <article
                key={`${job.source}:${job.source_id}`}
                className="grid gap-4 p-5 md:grid-cols-[1fr_auto] md:items-center"
              >
                <div>
                  <h3 className="font-semibold" style={{ color: 'var(--color-ink)' }}>{job.title}</h3>
                  <p className="mt-1 text-sm" style={{ color: 'var(--color-ink-muted)' }}>
                    {job.company} → watchlist: {watchlist_company}
                  </p>
                  <p className="mt-3 inline-flex items-center gap-2 text-sm" style={{ color: 'var(--color-ink-muted)' }}>
                    <CircleAlert size={15} /> {reason}
                  </p>
                </div>
                <a
                  href={job.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex min-h-11 items-center justify-center gap-2 border px-4 text-sm font-semibold"
                  style={{ borderColor: 'var(--color-border-strong)', color: 'var(--color-blue)' }}
                >
                  Open source <ExternalLink size={15} />
                </a>
              </article>
            ))}
          </div>
          {!busy && mtCandidates.length === 0 && (
            <p
              className="mt-5 border p-5 text-sm"
              style={{ borderColor: 'var(--color-border)', color: 'var(--color-ink-muted)' }}
            >
              No ambiguous MT candidates need review right now.
            </p>
          )}
        </section>
      </main>
    </div>
  )
}
