import { useState, useEffect, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ChevronDown } from 'lucide-react'
import type { Job, FiltersResponse, JobListResponse } from '../api/client'
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

export default function JobBoardPage() {
  const [searchParams, setSearchParams] = useSearchParams()

  // Initialise state from URL
  const initial = searchParamsToFilters(searchParams)
  const [filters, setFilters] = useState<JobFilters>(initial.filters)
  const [sort, setSort] = useState(initial.sort)
  const [page, setPage] = useState(initial.page)

  // Debounce search input only
  const debouncedSearch = useDebounce(filters.search, 300)

  const [filterData, setFilterData] = useState<FiltersResponse | null>(null)
  const [result, setResult] = useState<JobListResponse | null>(null)
  const [boardTotal, setBoardTotal] = useState<number | null>(null) // unfiltered active total
  const [loading, setLoading] = useState(true)
  const [selectedJob, setSelectedJob] = useState<Job | null>(null)

  const { toggle: toggleSave, isSaved, count: savedCount } = useSavedJobs()

  // Load filter options + unfiltered board total once
  useEffect(() => {
    fetchFilters().then(setFilterData).catch(console.error)
    fetchStats().then(s => setBoardTotal(s.total_active_jobs)).catch(console.error)
  }, [])

  // Build the active filters object substituting debounced search
  const activeFilters: JobFilters = { ...filters, search: debouncedSearch }
  const activeCount = countActiveFilters(activeFilters)

  // Sync URL whenever filters / sort / page change
  useEffect(() => {
    const p = filtersToSearchParams(activeFilters, sort, page)
    setSearchParams(p, { replace: true })
  }, [debouncedSearch, filters.sectors, filters.companies, filters.seniority,
      filters.remote_type, filters.skills, filters.salary_min, filters.salary_max,
      filters.salary_disclosed_only, filters.exp_min, filters.exp_max,
      filters.is_internship, sort, page])

  // Fetch jobs
  useEffect(() => {
    setLoading(true)
    fetchJobs(activeFilters, sort, page, PAGE_SIZE)
      .then(setResult)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [debouncedSearch, filters.sectors, filters.companies, filters.seniority,
      filters.remote_type, filters.skills, filters.salary_min, filters.salary_max,
      filters.salary_disclosed_only, filters.exp_min, filters.exp_max,
      filters.is_internship, sort, page])

  const updateFilters = useCallback((patch: Partial<JobFilters>) => {
    setFilters(prev => ({ ...prev, ...patch }))
    setPage(1) // reset page on filter change
  }, [])

  const clearFilters = useCallback(() => {
    setFilters(DEFAULT_FILTERS)
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
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-8">
          <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
            <div>
              <p
                className="text-xs font-semibold uppercase tracking-widest mb-1"
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
            {result && !loading && (
              <p
                className="text-sm tabular-nums"
                style={{ color: 'rgba(248,250,252,0.5)', fontFamily: 'var(--font-mono)' }}
              >
                {total.toLocaleString()} of{' '}
                {(boardTotal ?? total).toLocaleString()} roles
              </p>
            )}
          </div>
        </div>
      </section>

      {/* ── Sticky filter bar ───────────────────────────────── */}
      <FilterBar
        filters={filters}
        filterData={filterData}
        activeCount={activeCount}
        onUpdate={updateFilters}
        onClear={clearFilters}
      />

      {/* ── Main content ────────────────────────────────────── */}
      <main id="main-content" className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-6">

        {/* Results header */}
        <div className="flex items-center justify-between mb-5">
          <p className="text-sm" style={{ color: 'var(--color-ink-muted)' }}>
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
              className="appearance-none rounded pl-3 pr-8 py-2 text-sm font-medium transition-colors duration-150 cursor-pointer outline-none"
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
