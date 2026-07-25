import { useState, useEffect, useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ChevronDown, Star, EyeOff } from 'lucide-react'
import type { Job, FiltersResponse, JobListResponse, TierTab } from '../api/client'
import {
  DEFAULT_FILTERS, fetchJobs, fetchFilters, fetchStats,
  filtersToSearchParams, searchParamsToFilters,
  countActiveFilters,
} from '../api/client'
import type { JobFilters } from '../api/client'
import { useSavedJobs } from '../hooks/useSavedJobs'
import { useDebounce } from '../hooks/useDebounce'
import Nav from '../components/Nav'
import FilterBar from '../components/FilterBar'
import JobCard from '../components/JobCard'
import SkeletonCard from '../components/SkeletonCard'
import EmptyState from '../components/EmptyState'
import Pagination from '../components/Pagination'
import JobDetailModal from '../components/JobDetailModal'

const PAGE_SIZE = 24
const SORT_OPTIONS = [
  { value: 'newest', label: 'Newest first' },
  { value: 'salary_high', label: 'Salary: High → Low' },
  { value: 'salary_low', label: 'Salary: Low → High' },
  { value: 'company', label: 'Company A–Z' },
]

const TIER_TABS: { value: TierTab; label: string; star?: boolean; eyeOff?: boolean }[] = [
  { value: 'all', label: 'All jobs' },
  { value: 'mainstream', label: 'Mainstream' },
  { value: 'boutique', label: 'Exclusive', star: true },
  { value: 'social', label: 'Recruiter Posts', eyeOff: true },
]

// How many Recruiter Posts cards to show in the contextual sub-section
// (decision #9) — a preview strip, not the full list; "View all" switches to
// the tab.
const RECRUITER_POSTS_PREVIEW_SIZE = 3

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
  const [tierCounts, setTierCounts] = useState<Record<string, number>>({})
  const [loading, setLoading] = useState(true)
  const [selectedJob, setSelectedJob] = useState<Job | null>(null)
  // Recruiter Posts contextual sub-section (decision #9): a separate fetch/
  // state pair so these jobs render in their own distinct block, never mixed
  // into the main grid's `jobs.map(...)` loop above.
  const [recruiterPosts, setRecruiterPosts] = useState<JobListResponse | null>(null)

  const { toggle: toggleSave, isSaved, count: savedCount } = useSavedJobs()

  // Load filter options + unfiltered board total once
  useEffect(() => {
    fetchFilters().then(setFilterData).catch(console.error)
    fetchStats().then(s => {
      setBoardTotal(s.total_active_jobs)
      setTierCounts(s.by_source_tier ?? {})
    }).catch(console.error)
  }, [])

  // The filters actually applied to the data: debounced search substituted in.
  // Memoized so the effects below get a stable dependency.
  const activeFilters = useMemo<JobFilters>(
    () => ({ ...baseFilters, search: debouncedSearch }),
    [baseFilters, debouncedSearch],
  )
  const activeCount = countActiveFilters(activeFilters)

  // Sync URL whenever the applied filters / sort / page change
  useEffect(() => {
    setSearchParams(filtersToSearchParams(activeFilters, sort, page), { replace: true })
  }, [activeFilters, sort, page, setSearchParams])

  // Fetch jobs; the cancelled flag drops out-of-order responses from stale requests
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetchJobs(activeFilters, sort, page, PAGE_SIZE)
      .then(r => { if (!cancelled) setResult(r) })
      .catch(console.error)
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [activeFilters, sort, page])

  // Recruiter Posts preview strip: same active filters (sector/search/
  // seniority/etc.), tier forced to 'social', small page. Skipped entirely
  // when already ON the Recruiter Posts tab — the main grid below already
  // shows exactly this.
  useEffect(() => {
    if (activeFilters.tier === 'social') {
      setRecruiterPosts(null)
      return
    }
    let cancelled = false
    fetchJobs({ ...activeFilters, tier: 'social' }, 'newest', 1, RECRUITER_POSTS_PREVIEW_SIZE)
      .then(r => { if (!cancelled) setRecruiterPosts(r) })
      .catch(console.error)
    return () => { cancelled = true }
  }, [activeFilters])

  const updateFilters = useCallback((patch: Partial<JobFilters>) => {
    const { search, ...rest } = patch
    if (search !== undefined) setSearchInput(search)
    if (Object.keys(rest).length > 0) setBaseFilters(prev => ({ ...prev, ...rest }))
    setPage(1) // reset page on filter change
  }, [])

  const clearFilters = useCallback(() => {
    setBaseFilters(DEFAULT_FILTERS)
    setSearchInput(DEFAULT_FILTERS.search)
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
      <Nav savedCount={savedCount} />

      {/* ── Slim hero ───────────────────────────────────────── */}
      <section
        style={{
          backgroundColor: 'var(--color-nav)',
          borderBottom: '1px solid rgba(255,255,255,0.08)',
        }}
        aria-label="Job board header"
      >
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-4 sm:py-8">
          <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
            <div>
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
          </div>
        </div>
      </section>

      {/* ── Sticky filter bar ───────────────────────────────── */}
      <FilterBar
        filters={{ ...activeFilters, search: searchInput }}
        filterData={filterData}
        activeCount={activeCount}
        onUpdate={updateFilters}
        onClear={clearFilters}
      />

      {/* ── Main content ────────────────────────────────────── */}
      <main id="main-content" className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 pt-3 pb-6 sm:py-6">

        {/* Tier tabs: All / Mainstream / Exclusive / Recruiter Posts — segmented control.
            Below sm: this scrolls horizontally instead of wrapping, since 3
            tabs with icon+label+count can exceed a 360px viewport; wrapping
            them would push everything below down by an extra row. */}
        <div
          role="tablist"
          aria-label="Job tier"
          className="flex flex-nowrap sm:inline-flex sm:flex-wrap items-stretch gap-1.5 mb-3 sm:mb-6 p-1.5 rounded-xl overflow-x-auto sm:overflow-visible"
          style={{
            backgroundColor: 'var(--color-surface-2)',
            border: '1px solid var(--color-border-strong)',
            boxShadow: 'var(--shadow-card)',
          }}
        >
          {TIER_TABS.map(tab => {
            const selected = activeFilters.tier === tab.value
            const count = tab.value === 'all'
              ? (boardTotal ?? undefined)
              : tierCounts[tab.value]
            return (
              <button type="button"
                key={tab.value}
                role="tab"
                aria-selected={selected}
                onClick={() => updateFilters({ tier: tab.value })}
                className="tier-tab flex-shrink-0 inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold cursor-pointer outline-none"
                style={{
                  backgroundColor: selected ? 'var(--color-ink)' : 'transparent',
                  color: selected ? 'var(--color-ink-inverse)' : 'var(--color-ink-muted)',
                  boxShadow: selected ? 'var(--shadow-raised)' : 'none',
                  border: `1px solid ${selected ? 'var(--color-ink)' : 'transparent'}`,
                }}
              >
                {tab.star && (
                  <Star
                    size={15}
                    strokeWidth={2.25}
                    style={{ color: 'var(--color-gold-star, #E0A106)' }}
                    fill="var(--color-gold-star, #E0A106)"
                    aria-hidden="true"
                  />
                )}
                {tab.eyeOff && (
                  <EyeOff
                    size={15}
                    strokeWidth={2.25}
                    style={{ color: selected ? 'var(--color-ink-inverse)' : '#6B4EFF' }}
                    aria-hidden="true"
                  />
                )}
                {tab.label}
                {count != null && (
                  <span
                    className="tabular-nums text-xs font-bold rounded-full px-2 py-0.5 min-w-[1.5rem] text-center"
                    style={{
                      fontFamily: 'var(--font-mono)',
                      backgroundColor: selected ? 'rgba(255,255,255,0.16)' : 'var(--color-surface)',
                      color: selected ? 'var(--color-ink-inverse)' : 'var(--color-ink-muted)',
                      border: selected ? '1px solid rgba(255,255,255,0.12)' : '1px solid var(--color-border)',
                    }}
                  >
                    {count.toLocaleString()}
                  </span>
                )}
              </button>
            )
          })}
        </div>

        {/* Results header. The count text is hidden below sm: — it's redundant
            with the "All jobs N" tab badge just above and was one of two
            stacked rows contributing to excess chrome above the fold. */}
        <div className="flex items-center justify-end sm:justify-between mb-3 sm:mb-5">
          <p className="hidden sm:block text-sm" style={{ color: 'var(--color-ink-muted)' }}>
            {loading ? (
              <span className="animate-pulse">Loading…</span>
            ) : (
              <>
                Showing{' '}
                <span className="font-semibold tabular-nums" style={{ color: 'var(--color-ink)', fontFamily: 'var(--font-mono)' }}>
                  {total.toLocaleString()}
                </span>
                {activeCount > 0 && boardTotal != null && (
                  <> of <span className="tabular-nums" style={{ fontFamily: 'var(--font-mono)' }}>{boardTotal.toLocaleString()}</span></>
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

        {/* Recruiter Posts contextual sub-section (decision #9): a distinct
            block, never intermixed with the main grid below. Only shown when
            there's something to show and we're not already ON the Recruiter
            Posts tab. */}
        {activeFilters.tier !== 'social' && recruiterPosts && recruiterPosts.total > 0 && (
          <section
            className="hidden sm:block sm:mb-6 rounded-xl p-4 sm:p-5"
            style={{ backgroundColor: 'rgba(107,78,255,0.05)', border: '1px solid rgba(107,78,255,0.2)' }}
            aria-label="Recruiter Posts — hidden roles matching your filters"
          >
            <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
              <div className="flex items-center gap-2">
                <EyeOff size={16} strokeWidth={2.25} style={{ color: '#6B4EFF' }} aria-hidden="true" />
                <h2 className="text-sm font-bold" style={{ color: 'var(--color-ink)' }}>
                  Recruiter Posts
                </h2>
                <span className="text-xs" style={{ color: 'var(--color-ink-muted)' }}>
                  {recruiterPosts.total} role{recruiterPosts.total === 1 ? '' : 's'} sourced from recruiter posts
                  {activeCount > 0 ? ' matching your filters' : ''} — not on any public board
                </span>
              </div>
              <button
                type="button"
                onClick={() => updateFilters({ tier: 'social' })}
                className="text-xs font-semibold cursor-pointer"
                style={{ color: '#6B4EFF' }}
              >
                View all {recruiterPosts.total} →
              </button>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {recruiterPosts.jobs.map(job => (
                <JobCard
                  key={`${job.source}__${job.source_id}`}
                  job={job}
                  saved={isSaved(job)}
                  onToggleSave={toggleSave}
                  onClick={setSelectedJob}
                />
              ))}
            </div>
          </section>
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
