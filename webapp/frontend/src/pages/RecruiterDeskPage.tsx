import { useCallback, useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { ExternalLink, Loader2, Search } from 'lucide-react'
import Nav from '../components/Nav'
import { useAuth } from '../auth/useAuth'
import { fetchRecruiterRoles, type Job, type JobListResponse } from '../api/client'

const HK_DATE = new Intl.DateTimeFormat('en-HK', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  timeZone: 'Asia/Hong_Kong',
})

function hkDate(value: string | null): string {
  if (!value) return 'No date'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? 'No date' : HK_DATE.format(parsed)
}

function salaryLabel(role: Job): string {
  const min = role.salary_hkd_min ?? role.salary_estimated_min
  const max = role.salary_hkd_max ?? role.salary_estimated_max
  if (!min && !max) return '—'
  const fmt = (n: number) => `${Math.round(n / 1000)}k`
  const disclosed = role.salary_hkd_min !== null || role.salary_hkd_max !== null
  const range = min && max ? `${fmt(min)}–${fmt(max)}` : fmt((min ?? max) as number)
  return disclosed ? range : `${range} est.`
}

/**
 * The Ultimate Admin's recruiter desk — the Secret Market, read whole.
 *
 * Recruiter Posts are headhunters' own adverts rather than employers'
 * listings, and the public board's one-month window hides effectively all of
 * them: on the day this page was built, 0 of 245 were reachable. That is why
 * it reads Visibility.RECRUITER_DESK server-side instead of the board
 * predicate — a desk for seeing what we actually hold cannot be built on the
 * rule that hides it.
 */
export default function RecruiterDeskPage() {
  const { seeker, loading } = useAuth()
  const [data, setData] = useState<JobListResponse | null>(null)
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setBusy(true)
    setError(null)
    try {
      setData(await fetchRecruiterRoles({ search: query, page }))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load recruiter roles.')
    } finally {
      setBusy(false)
    }
  }, [query, page])

  useEffect(() => {
    if (!loading && seeker?.is_super_admin) void load()
  }, [loading, seeker?.is_super_admin, load])

  if (!loading && !seeker?.is_super_admin) {
    return <Navigate to="/signin" state={{ from: '/recruiter-desk' }} replace />
  }

  const roles = data?.jobs ?? []
  const totalPages = data?.total_pages ?? 1

  return (
    <>
      <Nav />
      <main className="mx-auto w-full max-w-5xl px-4 py-8">
        <header className="mb-6">
          <h1 className="text-2xl font-semibold">Recruiter desk</h1>
          <p className="mt-1 text-sm opacity-70">
            Every open Recruiter Post we hold — headhunters’ own adverts, not employer
            listings. The public board shows these only while they are under a month old,
            so most of what is here is not reachable from the board.
          </p>
          {data && (
            <p className="mt-2 text-sm font-medium">
              {data.total.toLocaleString()} post{data.total === 1 ? '' : 's'}
              {query && <> matching “{query}”</>}
            </p>
          )}
        </header>

        <form
          className="mb-5 flex gap-2"
          onSubmit={e => {
            e.preventDefault()
            setPage(1)
            setQuery(search)
          }}
        >
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 opacity-50" />
            <input
              className="w-full rounded-md border py-2 pl-9 pr-3 text-sm"
              style={{ borderColor: 'var(--color-border)' }}
              placeholder="Search recruiter posts…"
              value={search}
              onChange={e => setSearch(e.target.value)}
              aria-label="Search recruiter posts"
            />
          </div>
          <button type="submit" className="rounded-md border px-4 py-2 text-sm font-medium">
            Search
          </button>
        </form>

        {error && (
          <p role="alert" className="mb-4 text-sm text-red-600">
            {error}
          </p>
        )}

        {busy && (
          <p className="flex items-center gap-2 py-8 text-sm opacity-70">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading…
          </p>
        )}

        {!busy && roles.length === 0 && (
          <p className="py-8 text-sm opacity-70">
            No recruiter posts found. If this is unexpected, check that the nightly
            watchlist poll ran — the <code>linkedin_fetch</code> phase in the daily run.
          </p>
        )}

        {!busy && roles.length > 0 && (
          <ul className="space-y-2">
            {roles.map(role => (
              <li
                key={`${role.source}:${role.source_id}`}
                className="rounded-lg border p-3"
                style={{ borderColor: 'var(--color-border)' }}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate font-medium">{role.title}</p>
                    <p className="truncate text-sm opacity-70">{role.company}</p>
                  </div>
                  <a
                    href={role.url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="shrink-0 opacity-60 hover:opacity-100"
                    aria-label={`Open ${role.title} at source`}
                  >
                    <ExternalLink className="h-4 w-4" />
                  </a>
                </div>
                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs opacity-70">
                  <span>{hkDate(role.posted_at)}</span>
                  <span>{salaryLabel(role)}</span>
                  {role.seniority && <span>{role.seniority}</span>}
                  {role.locations.length > 0 && <span>{role.locations.join(', ')}</span>}
                </div>
              </li>
            ))}
          </ul>
        )}

        {!busy && totalPages > 1 && (
          <nav className="mt-6 flex items-center justify-between text-sm">
            <button
              className="rounded-md border px-3 py-1.5 disabled:opacity-40"
              disabled={page <= 1}
              onClick={() => setPage(p => Math.max(1, p - 1))}
            >
              Previous
            </button>
            <span className="opacity-70">
              Page {page} of {totalPages}
            </span>
            <button
              className="rounded-md border px-3 py-1.5 disabled:opacity-40"
              disabled={page >= totalPages}
              onClick={() => setPage(p => p + 1)}
            >
              Next
            </button>
          </nav>
        )}
      </main>
    </>
  )
}
