import { useState, useEffect, useCallback } from 'react'
import { Sparkles, RefreshCw, ArrowRight } from 'lucide-react'
import type { Job, FiltersResponse } from '../api/client'
import { DEFAULT_FILTERS, fetchJobs } from '../api/client'
import JobCard from './JobCard'
import SkeletonCard from './SkeletonCard'

/**
 * TEMPORARY UI EXPERIMENT — a handful of roles instead of the whole database.
 *
 * WHAT THIS IS NOT
 * ----------------
 * It is not personalisation. Nothing here knows who is looking: the sample is
 * random within one sector, and every visitor sees a different six for no
 * reason connected to them. Real recommendation needs a Seeker's CV, which is
 * the paid personalisation work another team member owns (docs/PLAN_ACCOUNTS.md
 * §1). This is the *shape* that feature will slot into — a small, explained,
 * refreshable set at the top of the board — built now so the layout question is
 * settled before the matching exists.
 *
 * The heading says "Sampled from" and not "Matched to you" for exactly that
 * reason. Do not relabel it until the matching is real.
 *
 * HOW THE RANDOMNESS WORKS
 * ------------------------
 * The API has no random sort (sort is newest / salary / company), and adding one
 * would mean a backend change for a throwaway UI. Instead this reads the sector's
 * true size from /api/filters — which the board already fetches — and jumps to a
 * random page of that size. One request, no probe round-trip, and the sample
 * moves across the whole sector rather than the newest few.
 */

const SAMPLE_SIZE = 6

/**
 * Read this many rows, then narrow to SAMPLE_SIZE.
 *
 * Reading exactly six produced six roles from two employers: the API sorts by
 * recency, and a bank that posts a batch on Tuesday owns a whole page of it. A
 * wider window gives `diversify` below something to choose from.
 *
 * 24 was not wide enough — a single bulk upload can be 24 rows on its own, and
 * the strip still came back three-deep in one employer. 60 spans enough of the
 * recency ordering that one employer cannot own the whole window.
 */
const WINDOW_SIZE = SAMPLE_SIZE * 10

/**
 * Deep pages of a 2,000-row sector are months-old postings. Capping the jump
 * keeps the sample random but still live — variety without dredging.
 */
const MAX_PAGE_DEPTH = 25

/** Fisher-Yates. Returns a new array; does not touch the input. */
function shuffled<T>(items: T[]): T[] {
  const out = [...items]
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[out[i], out[j]] = [out[j], out[i]]
  }
  return out
}

/**
 * Collapse the legal-entity noise in a company name so one bank is one bank.
 *
 * The scrapers take the employer string from whatever each source printed, so
 * the same institution arrives as "Bank of Communications (Hong Kong) Limited"
 * from one board and "Bank of Communications Hong Kong Branch" from another.
 * Comparing raw strings put both in the strip side by side, which reads as a
 * duplicate even though the rows are two genuinely different vacancies.
 *
 * Deliberately conservative: it strips only locale and legal suffixes, never
 * meaningful words. Two names that differ in substance ("Standard Chartered"
 * vs "Standard Chartered Bank") stay distinct — under-merging shows one extra
 * employer, over-merging would silently hide roles from the sample.
 */
const ENTITY_NOISE = /\b(limited|ltd|inc|plc|co|company|hong\s*kong|hk|s\.?a\.?r\.?|branch)\b/g

function employerKey(company: string): string {
  return company
    .toLowerCase()
    .replace(/[(),.]/g, ' ')
    .replace(ENTITY_NOISE, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

/**
 * Pick `size` roles, taking one per employer before allowing a second.
 *
 * Six roles at the same bank reads as a broken sample even when it is a correct
 * one, and the point of this strip is to suggest breadth. Falls back to filling
 * from the remainder when the window does not hold enough distinct employers.
 */
function diversify(jobs: Job[], size: number): Job[] {
  const pool = shuffled(jobs)
  const seen = new Set<string>()
  const first: Job[] = []
  const rest: Job[] = []

  for (const job of pool) {
    const key = employerKey(job.company)
    if (!seen.has(key)) {
      seen.add(key)
      first.push(job)
    } else {
      rest.push(job)
    }
  }

  return [...first, ...rest].slice(0, size)
}

interface Props {
  /** Supplies the sector's row count, which is what makes the page jump possible. */
  filterData: FiltersResponse | null
  saved: (job: Job) => boolean
  onToggleSave: (job: Job) => void
  onSelect: (job: Job) => void
  /** "See all" — hands the sector to the board as a real filter. */
  onSeeAll: (sector: string) => void
}

/**
 * Which sector to sample. Banking by name when it exists (it is the largest by
 * far — 2,232 of ~4,900 active roles), otherwise whichever sector is biggest, so
 * this cannot render an empty strip if the taxonomy is ever renamed.
 */
function pickSector(filterData: FiltersResponse | null): { name: string; count: number } | null {
  if (!filterData || filterData.sectors.length === 0) return null
  const banking = filterData.sectors.find(s => /banking/i.test(s.name) && !/investment/i.test(s.name))
  if (banking) return banking
  return [...filterData.sectors].sort((a, b) => b.count - a.count)[0]
}

export default function RecommendedRoles({
  filterData,
  saved,
  onToggleSave,
  onSelect,
  onSeeAll,
}: Props) {
  const [jobs, setJobs] = useState<Job[] | null>(null)
  const [loading, setLoading] = useState(true)
  // Bumped by the shuffle button; the effect below keys off it to re-roll.
  const [nonce, setNonce] = useState(0)

  const sector = pickSector(filterData)
  const sectorName = sector?.name ?? null
  const sectorCount = sector?.count ?? 0

  useEffect(() => {
    if (!sectorName) return

    let cancelled = false
    setLoading(true)

    const totalPages = Math.max(1, Math.ceil(sectorCount / WINDOW_SIZE))
    const page = 1 + Math.floor(Math.random() * Math.min(totalPages, MAX_PAGE_DEPTH))

    fetchJobs({ ...DEFAULT_FILTERS, sectors: [sectorName] }, 'newest', page, WINDOW_SIZE)
      .then(r => {
        if (cancelled) return
        // A short final page can come back empty if the count drifted between
        // /api/filters and now. Falling back to page 1 beats an empty strip.
        if (r.jobs.length === 0 && page !== 1) {
          return fetchJobs({ ...DEFAULT_FILTERS, sectors: [sectorName] }, 'newest', 1, WINDOW_SIZE)
            .then(fallback => { if (!cancelled) setJobs(diversify(fallback.jobs, SAMPLE_SIZE)) })
        }
        setJobs(diversify(r.jobs, SAMPLE_SIZE))
      })
      .catch(err => {
        console.error(err)
        if (!cancelled) setJobs([])
      })
      .finally(() => { if (!cancelled) setLoading(false) })

    return () => { cancelled = true }
  }, [sectorName, sectorCount, nonce])

  const shuffle = useCallback(() => setNonce(n => n + 1), [])

  if (!sectorName) return null
  if (!loading && jobs !== null && jobs.length === 0) return null

  return (
    <section className="mb-10 sm:mb-14" aria-label={`Roles sampled from ${sectorName}`}>
      <div className="flex items-end justify-between gap-4 mb-4 flex-wrap">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Sparkles
              size={16}
              strokeWidth={2.25}
              style={{ color: 'var(--color-gold)' }}
              aria-hidden="true"
            />
            <h2
              className="text-lg sm:text-xl font-bold"
              style={{ fontFamily: 'var(--font-display)', color: 'var(--color-ink)' }}
            >
              Roles to start with
            </h2>
          </div>
          <p className="text-sm" style={{ color: 'var(--color-ink-muted)' }}>
            Sampled from{' '}
            <span className="font-semibold" style={{ color: 'var(--color-ink)' }}>
              {sectorName}
            </span>
            {sectorCount > 0 && (
              <>
                {' '}·{' '}
                <span className="tabular-nums" style={{ fontFamily: 'var(--font-mono)' }}>
                  {sectorCount.toLocaleString()}
                </span>{' '}
                open roles
              </>
            )}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={shuffle}
            disabled={loading}
            className="filter-pill inline-flex items-center gap-1.5 rounded-md px-3.5 text-xs font-semibold cursor-pointer outline-none"
            style={{
              minHeight: '2.75rem',
              border: '1px solid var(--color-border-strong)',
              backgroundColor: 'var(--color-surface)',
              color: 'var(--color-ink-muted)',
              opacity: loading ? 0.5 : 1,
            }}
          >
            <RefreshCw
              size={14}
              strokeWidth={2.25}
              aria-hidden="true"
              className={loading ? 'animate-spin' : undefined}
            />
            Show me others
          </button>

          <button
            type="button"
            onClick={() => onSeeAll(sectorName)}
            className="filter-pill inline-flex items-center gap-1.5 rounded-md px-3.5 text-xs font-semibold cursor-pointer outline-none"
            style={{
              minHeight: '2.75rem',
              border: '1px solid var(--color-ink)',
              backgroundColor: 'var(--color-ink)',
              color: 'var(--color-ink-inverse)',
            }}
          >
            See all {sectorName}
            <ArrowRight size={14} strokeWidth={2.5} aria-hidden="true" />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {loading || jobs === null
          ? Array.from({ length: SAMPLE_SIZE }).map((_, i) => <SkeletonCard key={i} />)
          : jobs.map(job => (
              <JobCard
                key={`${job.source}__${job.source_id}`}
                job={job}
                saved={saved(job)}
                onToggleSave={onToggleSave}
                onClick={onSelect}
              />
            ))}
      </div>
    </section>
  )
}
