import { useState } from 'react'
import { ArrowRight, Search } from 'lucide-react'

/**
 * TEMPORARY UI EXPERIMENT — the search-engine face of the board.
 *
 * The board used to open as a wall: sticky filters, controls, then 24
 * cards out of ~5,000. That asks a visitor to narrow a database they have not
 * seen. This asks them a question instead, which is what a search engine does:
 * one dominant field, a set of major finance categories underneath, and nothing else
 * competing for the first decision.
 *
 * It renders only while the board has no query and no filters (JobBoardPage's
 * "discover" mode). The moment a search is submitted or a sector is picked, the
 * page switches to the ordinary results board and this is gone — the same split
 * a search engine makes between its home page and its results page.
 */

interface Props {
  boardTotal: number | null
  employerCount: number | null
  /**
   * Run a text query — the thing on this screen that moves the page into
   * results mode. The sector counts below are read-only stats, and there is no
   * "browse everything" link, so for a visitor or a Seeker a search is the way
   * in by design.
   */
  onSearch: (query: string) => void
  /**
   * Let an empty submit through, as `onSearch('')`.
   *
   * True only for admins (ADR 0019): pressing Search on an empty box is how
   * they ask for the whole catalogue. For everyone else an empty submit stays
   * inert, which is what keeps the catalogue non-enumerable — and the backend
   * refuses their empty query regardless of what this prop says.
   */
  allowEmptySubmit?: boolean
}

/**
 * Major finance categories. Hardcoded rather than read from the live skill counts
 * because the top skills by volume ("stakeholder management", "project
 * management") are the generic ones every posting lists — true, and useless as
 * a suggestion. These are the queries a Hong Kong finance candidate actually
 * arrives with.
 */
//
// Each of these renders as a real <a href="/jobs?q=...">, not a button. Google
// cannot click a button: with these as buttons, "/jobs" showed a crawler a page
// promising jobs, delivering none (no session and no query means the API
// correctly returns nothing — ADR 0018), and offering no followable link to any
// job at all. Google called it a Soft 404 on 2026-08-18, correctly.
//
// As links they are thirteen real landing pages — "/jobs?q=Risk+Management"
// answers with ~2,000 roles for a signed-out visitor — and they carry a query,
// so nothing about the "no enumerable catalogue" rule bends to make them work.
// Kept in step with BOARD_CATEGORIES in webapp/backend/main.py by
// tests/test_route_meta_in_step.py.
const MAJOR_CATEGORIES = [
  'Risk Management',
  'Accounting & Finance',
  'Treasury',
  'Investment',
  'Operations',
  'Technology & Transformation',
  'Sales and Business Development',
  'Private Banking',
  'Commercial Banking',
  'Investment Banking',
  'Retail Banking',
  'Sales & Marketing',
  'Legal, Compliance & Audit',
]

export default function SearchHero({
  boardTotal, employerCount, onSearch, allowEmptySubmit = false,
}: Props) {
  const [value, setValue] = useState('')

  // Explicit submit, not the live-debounced search the results board uses. On a
  // search-engine home the query is a decision you finish before anything moves;
  // searching per keystroke here would flip the whole page on the first letter.
  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const q = value.trim()
    if (q || allowEmptySubmit) onSearch(q)
  }

  // The button was disabled on an empty box, which for an admin would have made
  // the empty submit unreachable by mouse — the exact gesture they are meant to
  // use. Enter still works either way; this keeps the two paths in step.
  const canSubmit = Boolean(value.trim()) || allowEmptySubmit

  return (
    <section
      style={{
        backgroundColor: 'var(--color-bg)',
        borderBottom: '1px solid var(--color-border)',
      }}
      aria-label="Search the Financial Careers Index"
    >
      {/* A light search surface directly beneath the dark navigation. The
          masthead is enough brand contrast; the task area itself stays calm. */}
      <div className="mx-auto max-w-5xl px-4 sm:px-6 pt-12 pb-16 sm:pt-16 sm:pb-20 lg:pt-20 lg:pb-24 text-center">
        <p
          className="text-xs font-semibold uppercase mb-3"
          style={{ color: 'var(--color-gold)', letterSpacing: '0.14em' }}
        >
          Hong Kong · Live Market Data
        </p>

        <h1
          className="text-3xl sm:text-5xl font-bold leading-tight mb-3"
          style={{
            fontFamily: 'var(--font-display)',
            color: 'var(--color-ink)',
            letterSpacing: '-0.02em',
          }}
        >
          Financial Careers Index
        </h1>

        <p
          className="text-sm sm:text-base mb-2 mx-auto"
          style={{ color: 'var(--color-ink-muted)', maxWidth: '34rem', lineHeight: 1.6 }}
        >
          {boardTotal != null ? (
            <>
              Search{' '}
              <span
                className="font-semibold tabular-nums"
                style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-ink)' }}
              >
                {boardTotal.toLocaleString()}
              </span>{' '}
              live roles
              {employerCount ? (
                <>
                  {' '}across{' '}
                  <span
                    className="font-semibold tabular-nums"
                    style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-ink)' }}
                  >
                    {employerCount.toLocaleString()}
                  </span>{' '}
                  employers
                </>
              ) : null}
              , refreshed every morning.
            </>
          ) : (
            'Search live roles across Hong Kong finance, refreshed every morning.'
          )}
        </p>

        {/* Secondary line: the board's reach beyond a plain aggregator — Secret
            Market recruiter posts and boutique/longtail roles that never appear
            on the major portals. Kept smaller and more muted than the stat line
            above it so it reads as supporting context, not a second headline. */}
        <p
          className="text-xs sm:text-sm mb-8 sm:mb-10 mx-auto"
          style={{ color: 'var(--color-ink-faint)', maxWidth: '34rem', lineHeight: 1.6 }}
        >
          Our search results will also lead you to jobs that are actively reviewing candidates by
          recruiters and jobs not available on major job portals.
        </p>

        {/* ── The search field ───────────────────────────────────────────────
            The single primary affordance on this screen. Nothing else here is
            styled to compete with it. */}
        <form onSubmit={submit} role="search" className="mx-auto" style={{ maxWidth: '38rem' }}>
          <label htmlFor="board-search" className="sr-only">
            Search roles, skills or employers
          </label>

          <div
            className="search-hero-field flex items-center gap-2 rounded-full pl-4 pr-2 py-2"
            style={{
              backgroundColor: 'var(--color-surface)',
              boxShadow: 'var(--shadow-raised)',
              border: '1px solid var(--color-border-strong)',
            }}
          >
            <Search
              size={20}
              strokeWidth={2.25}
              style={{ color: 'var(--color-ink-faint)', flexShrink: 0 }}
              aria-hidden="true"
            />
            <input
              id="board-search"
              type="search"
              value={value}
              onChange={e => setValue(e.target.value)}
              placeholder="Search roles, skills or employers"
              autoComplete="off"
              className="flex-1 min-w-0 bg-transparent outline-none text-base"
              style={{ color: 'var(--color-ink)', minHeight: '2.75rem' }}
            />
            <button
              type="submit"
              disabled={!canSubmit}
              // Below sm: the label is hidden and only the arrow shows, which
              // would leave the button nameless to a screen reader.
              aria-label="Search"
              className="inline-flex items-center gap-1.5 rounded-full px-4 sm:px-5 font-semibold text-sm cursor-pointer outline-none transition-opacity"
              style={{
                minHeight: '2.75rem',
                backgroundColor: 'var(--color-ink)',
                color: 'var(--color-ink-inverse)',
                opacity: canSubmit ? 1 : 0.38,
                cursor: canSubmit ? 'pointer' : 'not-allowed',
              }}
            >
              <span className="hidden sm:inline">Search</span>
              <ArrowRight size={16} strokeWidth={2.5} aria-hidden="true" />
            </button>
          </div>

          {/* Admins only. The capability is useless if nothing says it exists —
              an empty search box that suddenly has a live Search button is not
              self-explanatory. */}
          {allowEmptySubmit && (
            <p
              className="mt-3 text-center text-xs"
              style={{ color: 'var(--color-ink-faint)' }}
            >
              Admin — press Search with the box empty to browse the whole catalogue.
            </p>
          )}
        </form>

        {/* ── Major categories ───────────────────────────────────────────────
            The "reduce friction to search" half of the marketplace pattern: a
            visitor who does not know what to type gets a useful finance map. */}
        <div className="mt-10 border-t pt-7" aria-labelledby="major-categories-label">
          <div className="flex items-end justify-between gap-4 pb-4 text-left">
            <div>
              <h2
                id="major-categories-label"
                className="text-sm font-semibold"
                style={{ color: 'var(--color-ink)' }}
              >
                Explore major categories
              </h2>
              <p className="mt-1 text-xs" style={{ color: 'var(--color-ink-muted)' }}>
                Choose a discipline to see relevant Roles.
              </p>
            </div>
            <span
              className="hidden shrink-0 text-xs font-medium tabular-nums sm:block"
              style={{ color: 'var(--color-gold)', fontFamily: 'var(--font-mono)' }}
            >
              13 disciplines
            </span>
          </div>

          <div className="major-category-grid grid grid-cols-2 gap-2 lg:grid-cols-3">
            {MAJOR_CATEGORIES.map(label => (
              <a
                key={label}
                href={`/jobs?q=${encodeURIComponent(label)}`}
                onClick={e => {
                  // Left-click stays a single-page transition. Everything else —
                  // cmd/ctrl-click, middle-click, "open in new tab" — is left to
                  // the browser, which is the whole point of using a real href.
                  if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return
                  e.preventDefault()
                  onSearch(label)
                }}
                className="major-category-card flex min-h-14 items-center justify-center rounded-md px-3 py-3 text-center text-[0.8125rem] font-semibold leading-snug cursor-pointer outline-none no-underline sm:px-4 sm:text-sm"
                style={{
                  backgroundColor: 'var(--color-surface)',
                  border: '1px solid var(--color-border)',
                  color: 'var(--color-ink)',
                }}
              >
                {label}
              </a>
            ))}
          </div>
        </div>

        {/* NOTE — there is deliberately nothing below the major categories.
            A per-sector count block lived here through two revisions, as
            clickable category chips and then as a stat row, and both were
            wrong for the same underlying reason rather than for want of
            styling: the hero's job is to get one query typed, and a second
            block of information competes with the field for the first
            decision. The pattern this screen follows is blunt about it —
            "search bar is the CTA, reduce friction to search".

            Nothing was lost by cutting it. The sub-headline above already
            carries the totals, and the About-this-index block at the foot of
            the discover page carries the sector breakdown, in a section that
            exists to hold exactly that. Adding it back here would state the
            same fact for a third time. */}
      </div>
    </section>
  )
}
