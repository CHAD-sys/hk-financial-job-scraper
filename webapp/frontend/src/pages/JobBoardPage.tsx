import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useSearchParams, useLocation } from 'react-router-dom'
import { ChevronDown, Star, EyeOff, ArrowLeft } from 'lucide-react'
import type { Job, FiltersResponse, JobListResponse, TierTab } from '../api/client'
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

const PAGE_SIZE = 24
const SORT_OPTIONS = [
  { value: 'relevance', label: 'Best match' },
  { value: 'newest', label: 'Newest first' },
  { value: 'salary_high', label: 'Salary: High → Low' },
  { value: 'salary_low', label: 'Salary: Low → High' },
  { value: 'company', label: 'Company A–Z' },
]

const TIER_TABS: { value: TierTab; label: string; star?: boolean; eyeOff?: boolean }[] = [
  { value: 'all', label: 'All results' },
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
  const [employerCount, setEmployerCount] = useState<number | null>(null)
  const [sectorCount, setSectorCount] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedJob, setSelectedJob] = useState<Job | null>(null)
  // Recruiter Posts contextual sub-section (decision #9): a separate fetch/
  // state pair so these jobs render in their own distinct block, never mixed
  // into the main grid's `jobs.map(...)` loop above.
  const [recruiterPosts, setRecruiterPosts] = useState<JobListResponse | null>(null)

  const { toggle: toggleSave, isSaved } = useSavedRoles()
  const { seeker } = useAuth()

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
  }, [activeFilters.search, hasResearch])

  // ── Two modes ───────────────────────────────────────────────────────────────
  // The page is now a search engine, which means it is two screens rather than
  // one: a home that asks a question, and a results page that answers it.
  //
  //   discover  — no query, no filters. SearchHero + a sampled strip of roles.
  //   board     — the ordinary index: filter bar, tier tabs, grid, pagination.
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

  // Recruiter Posts preview strip: same active filters (sector/search/
  // seniority/etc.), tier forced to 'social', small page. Skipped entirely
  // when already ON the Recruiter Posts tab — the main grid below already
  // shows exactly this.
  useEffect(() => {
    if (!showBoard || activeFilters.tier === 'social') {
      setRecruiterPosts(null)
      return
    }
    let cancelled = false
    fetchJobs({ ...activeFilters, tier: 'social' }, 'newest', 1, RECRUITER_POSTS_PREVIEW_SIZE)
      .then(r => { if (!cancelled) setRecruiterPosts(r) })
      .catch(console.error)
    return () => { cancelled = true }
  }, [activeFilters, showBoard])

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
              saved={isSaved}
              onToggleSave={toggleSave}
              onSelect={setSelectedJob}
            />
            <RecommendedRoles
              saved={isSaved}
              onToggleSave={toggleSave}
              onSelect={setSelectedJob}
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

            {/* The way back to the search home. A results page that cannot
                return to its own search box is a dead end. */}
            <button
              type="button"
              onClick={backToSearch}
              className="hero-chip self-start sm:self-auto inline-flex items-center gap-2 rounded-lg px-3.5 text-sm font-semibold cursor-pointer outline-none"
              style={{
                minHeight: '2.75rem',
                backgroundColor: 'rgba(255,255,255,0.08)',
                border: '1px solid rgba(255,255,255,0.18)',
                color: 'rgba(248,250,252,0.9)',
              }}
            >
              <ArrowLeft size={15} strokeWidth={2.5} aria-hidden="true" />
              New search
            </button>
          </div>
        </div>
      </section>

      {/* ── Sticky filter bar ───────────────────────────────── */}
      <FilterBar
        filters={{ ...activeFilters, search: searchInput }}
        filterData={filterData}
        activeCount={filterCount}
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
            const researchCount = tab.value === 'all'
              ? filterData?.research_total
              : filterData?.tier_counts[tab.value]
            // Once a refinement is active, only the selected tier's returned
            // total is truthful. The other tier counts describe the wider
            // research and would imply that the filter had not narrowed it.
            const count = filterCount > 0
              ? (selected ? total : undefined)
              : researchCount
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

        <TierExplainer tier={activeFilters.tier} />

        {/* Results header. The count text is hidden below sm: — it's redundant
            with the "All results N" tab badge just above and was one of two
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
                  {' matching your research'} — not on any public board
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

// ── Tier explainer ────────────────────────────────────────────────────────────

/**
 * What "Exclusive" and "Recruiter Posts" actually mean, shown only while that
 * tab is active.
 *
 * The landing page used to carry two large callouts explaining these tiers; the
 * portal rebuild moved that job here. It is deliberately NOT a copy of those
 * callouts — the tabs above already sell the tiers. What was missing was the
 * explanation of where the data comes from, which matters most at the moment
 * someone switches to the tab and wonders what they are looking at.
 */
const TIER_NOTES: Partial<Record<TierTab, { title: string; body: string; colour: string }>> = {
  boutique: {
    title: 'Roles the major boards miss',
    body:
      'Openings at boutique and specialist firms — smaller institutions and niche players whose roles rarely reach the large aggregators. Read from each employer\'s own public hiring activity, then structured with AI.',
    colour: 'var(--color-gold)',
  },
  social: {
    title: 'Mandates that never reach a job board',
    body:
      'LinkedIn posts from recruiters and headhunters working Hong Kong finance — live mandates often shared with their network before, or instead of, a formal listing. Where a post also matches a listing already on the board we mark it Verified.',
    colour: '#6B4EFF',
  },
}

function TierExplainer({ tier }: { tier: TierTab }) {
  const note = TIER_NOTES[tier]
  if (!note) return null

  return (
    <div
      className="mb-4 sm:mb-6 rounded-lg px-4 py-3"
      style={{ backgroundColor: 'var(--color-surface-2)', borderLeft: `3px solid ${note.colour}` }}
    >
      <p className="text-sm font-semibold" style={{ color: 'var(--color-ink)' }}>
        {note.title}
      </p>
      <p className="mt-1 text-sm leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>
        {note.body}
      </p>
    </div>
  )
}

// ── Index stats ───────────────────────────────────────────────────────────────

/**
 * The four stat cards that used to sit on the landing page.
 *
 * Placed at the foot of the board rather than above the filter bar: this page
 * has an explicit, hard-won budget for above-the-fold chrome (see the comments
 * on the tier tabs and results header), and four stat cards between the nav and
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
