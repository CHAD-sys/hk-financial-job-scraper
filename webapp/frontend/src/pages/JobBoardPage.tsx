import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useSearchParams, useLocation } from 'react-router-dom'
import { ChevronDown } from 'lucide-react'
import type {
  Job,
  FiltersResponse,
  JobListResponse,
  ResumeMatchesResponse,
} from '../api/client'
import {
  DEFAULT_FILTERS, fetchJobs, fetchFilters, fetchStats,
  filtersToSearchParams, searchParamsToFilters,
  countActiveFilters, recordDiscovery,
} from '../api/client'
import type { JobFilters } from '../api/client'
import { useAuth } from '../auth/useAuth'
import { useSavedRoles } from '../savedRoles/useSavedRoles'
import { useDebounce } from '../hooks/useDebounce'
import { scrollToTop } from '../utils/scroll'
import Nav from '../components/Nav'
import FilterBar from '../components/FilterBar'
import JobCard from '../components/JobCard'
import SkeletonCard from '../components/SkeletonCard'
import EmptyState from '../components/EmptyState'
import Pagination from '../components/Pagination'
import JobDetailModal from '../components/JobDetailModal'
import StatCard from '../components/StatCard'
import SearchHero from '../components/SearchHero'
import RecommendedRoles from '../components/RecommendedRoles'
import ResumeMatches from '../components/ResumeMatches'
import MemberRoleNotice from '../components/MemberRoleNotice'

const PAGE_SIZE = 24
const SORT_OPTIONS = [
  { value: 'relevance', label: 'Best match' },
  { value: 'newest', label: 'Newest first' },
  { value: 'salary_high', label: 'Salary: High → Low' },
  { value: 'salary_low', label: 'Salary: Low → High' },
  { value: 'company', label: 'Company A–Z' },
]

export default function JobBoardPage() {
  const [searchParams, setSearchParams] = useSearchParams()

  // Initialise state from URL (parsed once on mount)
  const [initial] = useState(() => searchParamsToFilters(searchParams))

  // The raw search text lives in its own state so the effects below can depend
  // on the debounced value without re-firing on every keystroke.
  const [searchInput, setSearchInput] = useState(initial.filters.search)
  const [baseFilters, setBaseFilters] = useState<JobFilters>(initial.filters)
  const [sort, setSort] = useState(initial.sort)
  const [page, setPage] = useState(initial.page)

  const debouncedSearch = useDebounce(searchInput, 300)

  const [filterData, setFilterData] = useState<FiltersResponse | null>(null)
  const [result, setResult] = useState<JobListResponse | null>(null)
  const [boardTotal, setBoardTotal] = useState<number | null>(null) // unfiltered active total
  const [employerCount, setEmployerCount] = useState<number | null>(null)
  const [sectorCount, setSectorCount] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedJob, setSelectedJob] = useState<Job | null>(null)
  const [resumeMatches, setResumeMatches] = useState<ResumeMatchesResponse | null>(null)
  const { toggle: toggleSave, isSaved } = useSavedRoles()
  const { seeker, loading: authLoading } = useAuth()

  // Public market totals are aggregate context only. Filter choices are never
  // loaded globally; the separate effect below derives them from one research.
  useEffect(() => {
    fetchStats().then(s => {
      setBoardTotal(s.total_active_jobs)
      setEmployerCount(s.employer_count)
      setSectorCount(Object.keys(s.by_sector).length)
    }).catch(console.error)
  }, [])

  // The filters actually applied to the data: debounced search substituted in.
  // Memoized so the effects below get a stable dependency.
  const activeFilters = useMemo<JobFilters>(
    () => ({ ...baseFilters, search: debouncedSearch }),
    [baseFilters, debouncedSearch],
  )
  const filterCount = countActiveFilters({ ...activeFilters, search: '' })
  const hasResearch = activeFilters.search.trim().length >= 2

  useEffect(() => {
    if (!hasResearch) {
      setFilterData(null)
      return
    }
    let cancelled = false
    fetchFilters(activeFilters.search)
      .then(data => { if (!cancelled) setFilterData(data) })
      .catch(console.error)
    return () => { cancelled = true }
  }, [activeFilters.search, hasResearch, seeker?.id])

  // ── Two modes ───────────────────────────────────────────────────────────────
  // The page is now a search engine, which means it is two screens rather than
  // one: a home that asks a question, and a results page that answers it.
  //
  //   discover  — no query, no filters. SearchHero + a sampled strip of roles.
  //   board     — one research stream: filter bar, grid, pagination.
  //
  // A research query is the boundary between the two. Structured filters can
  // narrow its result set but can never open the catalogue by themselves.
  const showBoard = hasResearch

  const runSearch = useCallback((query: string) => {
    setSearchInput(query)
    setBaseFilters(DEFAULT_FILTERS)
    setSort('relevance')
    setPage(1)
  }, [])

  const backToSearch = useCallback(() => {
    setBaseFilters(DEFAULT_FILTERS)
    setSearchInput(DEFAULT_FILTERS.search)
    setSort('newest')
    setPage(1)
  }, [])

  // Typing a fresh query straight into the board's own search field (rather
  // than starting from the hero) gets the same "best match first" treatment as
  // `runSearch` — a search box that only ranks by relevance when you happen to
  // arrive through the homepage would be a search box, apparently, until it isn't.
  //
  // Fires only on the empty -> non-empty transition, not on every keystroke of
  // an already-active query: someone who searched, then deliberately chose
  // "Salary: High -> Low", and is now refining the same query should not have
  // that choice silently overwritten on the next letter typed.
  const wasSearchEmpty = useRef(true)
  useEffect(() => {
    const isEmpty = searchInput.trim() === ''
    if (wasSearchEmpty.current && !isEmpty) setSort('relevance')
    wasSearchEmpty.current = isEmpty
  }, [searchInput])

  // "Careers" in the nav asks for the search home, not the route.
  //
  // Both screens live behind /jobs, so arriving at /jobs is not by itself a
  // request for either one — landing on the board is right for a deep link
  // carrying filters, and wrong for someone who just pressed Careers. Nav says
  // which it means with `state.discover`, and this is where that is honoured.
  //
  // Keyed on location.key rather than the state object: every navigation gets a
  // fresh key, so pressing Careers twice resets twice. Nothing else needs
  // guarding — the URL sync below replaces the location without state, so a
  // filter change cannot re-trigger this.
  //
  // Deliberately NOT "reset whenever the URL has no params". That would put a
  // second, implicit route back to discover mode next to this explicit one, and
  // the two would disagree the moment either changed.
  //
  // Note what it would collide with: `showBoard` already falls back to discover
  // when the last filter goes, so "Clear all" on a Role reached by deep link
  // does return to the hero. That is this page's existing behaviour, not
  // something this effect does.
  const location = useLocation()
  useEffect(() => {
    if (!(location.state as { discover?: boolean } | null)?.discover) return
    backToSearch()
    scrollToTop()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.key])

  // Sync URL whenever the applied filters / sort / page change
  useEffect(() => {
    setSearchParams(filtersToSearchParams(activeFilters, sort, page), { replace: true })
  }, [activeFilters, sort, page, setSearchParams])

  // Fetch jobs; the cancelled flag drops out-of-order responses from stale requests.
  // Skipped entirely in discover mode — the hero shows no grid, so fetching 24
  // rows to throw away would just slow the first paint of the page that matters.
  useEffect(() => {
    if (!showBoard) return
    let cancelled = false
    let discoveryTimer: ReturnType<typeof setTimeout> | null = null
    setLoading(true)
    fetchJobs(activeFilters, sort, page, PAGE_SIZE)
      .then(r => {
        if (cancelled) return
        setResult(r)

        // Recommendation learning records completed intent, not keystrokes.
        // Waiting until a result page has settled also gives rapid filter
        // changes a chance to cancel this timer. Page 2+ is navigation through
        // the same intent, so only page 1 becomes a discovery event.
        if (seeker && page === 1 && hasResearch) {
          discoveryTimer = setTimeout(() => {
            recordDiscovery(activeFilters, r.total).catch(console.error)
          }, 1_200)
        }
      })
      .catch(console.error)
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => {
      cancelled = true
      if (discoveryTimer) clearTimeout(discoveryTimer)
    }
  }, [activeFilters, hasResearch, page, seeker, showBoard, sort])

  const updateFilters = useCallback((patch: Partial<JobFilters>) => {
    const { search, ...rest } = patch
    if (search !== undefined) setSearchInput(search)
    if (Object.keys(rest).length > 0) setBaseFilters(prev => ({ ...prev, ...rest }))
    setPage(1) // reset page on filter change
  }, [])

  const clearFilters = useCallback(() => {
    setBaseFilters(DEFAULT_FILTERS)
    setSort('relevance')
    setPage(1)
  }, [])

  const handleSortChange = (val: string) => {
    setSort(val)
    setPage(1)
  }

  const total = result?.total ?? 0
  const totalPages = result?.total_pages ?? 0
  const jobs = result?.jobs ?? []

  return (
    <div style={{ backgroundColor: 'var(--color-bg)', minHeight: '100dvh' }}>
      <title>Search Hong Kong Finance Jobs — FinEx Careers</title>
      <meta
        name="description"
        content="Search open finance roles across Hong Kong — banking, asset management, insurance and professional services — indexed daily from employer ATSs, major boards and boutique firms."
      />
      <Nav />

      {/* ── DISCOVER MODE: the search-engine home ───────────── */}
      {!showBoard && (
        <>
          <SearchHero
            boardTotal={boardTotal}
            employerCount={employerCount}
            onSearch={runSearch}
          />
          {/* The page rises over the masthead rather than starting after it.
              A full-width navy block ending on a hairline, with a bold serif
              heading and a card grid beginning immediately underneath, read as
              two pages stacked — the value jump from #16223A to #FFFDF9 is
              about as large as this palette allows, and nothing mediated it.
              Overlapping the hero by one spacing step and rounding the top
              corners turns that seam into a join: the navy is still visible
              either side of the sheet for those few dozen pixels, so the two
              sections are seen to be layered rather than merely adjacent.
              The eye reads depth, and depth reads deliberate.

              Why an overlap and not a gradient: navy fading to cream passes
              through a muddy mid-grey that suits neither, and DESIGN.md keeps
              dark surfaces stepping monotonically instead of blending. */}
          <main
            id="main-content"
            className="relative mx-auto max-w-7xl -mt-8 rounded-t-3xl px-4 pt-8 pb-8 sm:-mt-12 sm:px-6 sm:pt-12 sm:pb-12 lg:px-8"
            style={{
              backgroundColor: 'var(--color-bg)',
              // Structural, not decorative: it is what makes the sheet read as
              // ABOVE the masthead rather than cut into it. Only visible in the
              // overlap — below the join it is cream on cream.
              boxShadow: 'var(--shadow-float)',
            }}
          >
            <ResumeMatches
              onResolved={setResumeMatches}
            />
            <RecommendedRoles
              saved={isSaved}
              onToggleSave={toggleSave}
              onSelect={setSelectedJob}
              resumeMatches={resumeMatches}
            />
            <IndexStats
              boardTotal={boardTotal}
              employerCount={employerCount}
              sectorCount={sectorCount}
            />
          </main>
        </>
      )}

      {/* ── BOARD MODE: the results page ────────────────────── */}
      {showBoard && (
        <>
      {/* ── Slim hero ───────────────────────────────────────── */}
      <section
        style={{
          backgroundColor: 'var(--color-masthead)',
          borderBottom: '1px solid rgba(255,255,255,0.08)',
        }}
        aria-label="Job board header"
      >
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-4 sm:py-8">
          <p
            className="text-xs font-semibold uppercase tracking-widest mb-0.5 sm:mb-1"
            style={{ color: 'var(--color-gold)', letterSpacing: '0.12em' }}
          >
            Hong Kong · Live Market Data
          </p>
          <h1
            className="text-2xl sm:text-3xl font-bold leading-tight"
            style={{
              fontFamily: 'var(--font-display)',
              color: 'var(--color-ink-inverse)',
              letterSpacing: '-0.02em',
            }}
          >
            Financial Careers Index
          </h1>
        </div>
      </section>

      {/* ── Sticky filter bar ───────────────────────────────── */}
      <FilterBar
        filters={{ ...activeFilters, search: searchInput }}
        filterData={filterData}
        activeCount={filterCount}
        onUpdate={updateFilters}
        onClear={clearFilters}
        onNewSearch={backToSearch}
      />

      {/* ── Main content ────────────────────────────────────── */}
      <main id="main-content" className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-5 sm:py-7">

        {/* One Google-style result stream: every matching source falls into
            the same ranked grid. Source attribution remains on individual
            cards, but it never becomes a separate lane or browsing mode. */}
        <div className="flex items-center justify-between gap-4 mb-4 sm:mb-5">
          <p className="text-sm" style={{ color: 'var(--color-ink-muted)' }}>
            {loading ? (
              <span className="animate-pulse">Loading…</span>
            ) : (
              <>
                Showing{' '}
                <span className="font-semibold tabular-nums" style={{ color: 'var(--color-ink)', fontFamily: 'var(--font-mono)' }}>
                  {total.toLocaleString()}
                </span>
                {filterCount > 0 && filterData != null && (
                  <> of <span className="tabular-nums" style={{ fontFamily: 'var(--font-mono)' }}>{filterData.research_total.toLocaleString()}</span> in this research</>
                )}{' '}
                role{total !== 1 ? 's' : ''}
              </>
            )}
          </p>

          {/* Sort dropdown */}
          <div className="relative">
            <select
              value={sort}
              onChange={e => handleSortChange(e.target.value)}
              className="appearance-none rounded pl-3 pr-8 py-2.5 min-h-11 text-sm font-medium transition-colors duration-150 cursor-pointer outline-none"
              style={{
                backgroundColor: 'var(--color-surface)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-ink-muted)',
              }}
              onFocus={e => (e.currentTarget.style.borderColor = 'var(--color-ring)')}
              onBlur={e => (e.currentTarget.style.borderColor = 'var(--color-border)')}
              aria-label="Sort results by"
            >
              {SORT_OPTIONS.map(o => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
            <ChevronDown
              size={14}
              className="absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none"
              style={{ color: 'var(--color-ink-faint)' }}
            />
          </div>
        </div>

        {!authLoading && !seeker && (
          <MemberRoleNotice returnTo={`${location.pathname}${location.search}`} />
        )}

        {/* Job grid */}
        {loading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {Array.from({ length: 8 }).map((_, i) => <SkeletonCard key={i} />)}
          </div>
        ) : jobs.length === 0 ? (
          <EmptyState onClear={clearFilters} />
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {jobs.map(job => (
              <JobCard
                key={`${job.source}__${job.source_id}`}
                job={job}
                saved={isSaved(job)}
                onToggleSave={toggleSave}
                onClick={setSelectedJob}
              />
            ))}
          </div>
        )}

        {/* Pagination */}
        {!loading && totalPages > 1 && (
          <Pagination page={page} totalPages={totalPages} onChange={setPage} />
        )}

      </main>
        </>
      )}

      {/* ── Job detail modal ────────────────────────────────── */}
      {selectedJob && (
        <JobDetailModal
          job={selectedJob}
          saved={isSaved(selectedJob)}
          onToggleSave={toggleSave}
          onClose={() => setSelectedJob(null)}
        />
      )}
    </div>
  )
}

// ── Index stats ───────────────────────────────────────────────────────────────

/**
 * The four stat cards that used to sit on the landing page.
 *
 * Placed at the foot of the board rather than above the filter bar: this page
 * has an explicit, hard-won budget for above-the-fold chrome, and four stat cards between the nav and
 * the first job would spend all of it on something a browsing visitor did not
 * come for. At the foot they still back the numbers up for anyone who scrolls.
 */
function IndexStats({
  boardTotal,
  employerCount,
  sectorCount,
}: {
  boardTotal: number | null
  employerCount: number | null
  sectorCount: number | null
}) {
  if (boardTotal == null) return null

  return (
    <section
      aria-label="About this index"
      className="mt-12 pt-8"
      style={{ borderTop: '1px solid var(--color-border)' }}
    >
      <h2
        className="mb-4 text-xs font-semibold uppercase"
        style={{ color: 'var(--color-ink-faint)', letterSpacing: '0.14em' }}
      >
        About this index
      </h2>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          value={boardTotal.toLocaleString()}
          label="Active roles"
          sub="Duplicates across sources already merged"
        />
        <StatCard
          value={employerCount ? employerCount.toLocaleString() : '—'}
          label="Employers"
          sub="Banks, insurers, asset managers & more"
        />
        <StatCard
          value={sectorCount ? String(sectorCount) : '—'}
          label="Sectors"
          sub="Banking · IB · Insurance · AM · Prof. services"
        />
        <StatCard value="Daily" label="Refreshed" sub="Collected and re-enriched every morning" />
      </div>
      <p className="mt-4 text-xs" style={{ color: 'var(--color-ink-faint)' }}>
        Counts are live from the index and exclude roles suppressed as cross-posted duplicates.
      </p>
    </section>
  )
}
