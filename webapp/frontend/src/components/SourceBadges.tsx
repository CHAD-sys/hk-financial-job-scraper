import { Building2 } from 'lucide-react'

/**
 * "Listed on" board tags for the job detail view.
 *
 * Each source maps to its board's brand colour and a small letter-mark logo.
 * Third-party ATS sources (Workday / Eightfold) and boutique own-site scrapes
 * (longtail) represent the employer's OWN careers page, so they collapse into a
 * single neutral "Company site" tag rather than a board.
 */

interface Board {
  label: string
  color: string    // brand colour — used for the mark, text and tint
  mark: string     // 1–2 char letter-mark shown in the little logo square
}

const BOARDS: Record<string, Board> = {
  jobsdb:            { label: 'JobsDB',            color: '#003C64', mark: 'J' },
  indeed:            { label: 'Indeed',            color: '#2557A7', mark: 'i' },
  linkedin:          { label: 'LinkedIn',          color: '#0A66C2', mark: 'in' },
  efinancialcareers: { label: 'eFinancialCareers', color: '#00857C', mark: 'eF' },
  // Not a job board — a recruiter's own LinkedIn post (LP-5 "Recruiter Posts").
  // Kept distinct from `linkedin` (LinkedIn Jobs) since it's a different kind
  // of listing: a personal post, not a formal board posting.
  linkedin_posts:    { label: 'Recruiter post',    color: '#6B4EFF', mark: 'in' },
}

// Sources that are the employer's own careers page rather than a job board.
// Every entry is an ATS vendor's name, which is exactly what a Seeker does not
// need to know — they all collapse into one "Company site" tag.
//
// Kept in step with hk_jobs/sources.py by tests/test_sources.py, which reads
// this file. A source missing from BOTH this set and BOARDS is dropped silently
// by normalise() below: it survives neither branch, so the tag never renders.
// That is not hypothetical — `successfactors` was absent here for two days and
// HKJC's roles showed no "Listed on" section at all.
const OWN_SITE = new Set(['workday', 'eightfold', 'successfactors', 'longtail'])

// Display order: own site first, then boards by preference, recruiter posts last
// (lowest priority everywhere else in the pipeline too — sources.py APPLY_ORDER).
const ORDER = ['company', 'efinancialcareers', 'indeed', 'jobsdb', 'linkedin', 'linkedin_posts']

/** hex (#rrggbb) → rgba() string at the given alpha, for subtle tints. */
function tint(hex: string, alpha: number): string {
  const n = parseInt(hex.slice(1), 16)
  const r = (n >> 16) & 255
  const g = (n >> 8) & 255
  const b = n & 255
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

function normalise(sources: string[]): string[] {
  const keys = new Set<string>()
  for (const s of sources) {
    keys.add(OWN_SITE.has(s) ? 'company' : s)
  }
  return ORDER.filter(k => keys.has(k))
}

/**
 * Two densities, one tag.
 *
 * `compact` is the job card, where the tag sits in the meta row next to the
 * seniority badge and must not out-weigh it. The default is the detail view's
 * "Listed on" row. Same registry, same colours, same marks in both — a Seeker
 * who learns the JobsDB mark on a card has to meet that same mark in the modal,
 * which is the whole reason this is one component and not two.
 *
 * The two densities differ in more than size: `compact` is monochrome.
 *
 * A board's brand colour earns its place in the "Listed on" row, where several
 * tags sit together and the colour is what tells them apart at a glance. On a
 * card there is only ever ONE tag, so the hue distinguishes it from nothing —
 * it just adds a fifth colour to a grid that already has a sector accent and a
 * tier chip competing for attention. The letter-mark still identifies the board;
 * it does that by shape, which is what was doing the work anyway.
 */
function BoardTag({
  board,
  compact = false,
}: {
  board: Board
  compact?: boolean
}) {
  const color = compact ? 'var(--color-ink-muted)' : board.color
  const mark = compact ? 14 : 18
  return (
    <span
      className={`inline-flex items-center rounded-full ${
        compact ? 'gap-1 py-0.5 pl-0.5 pr-1.5' : 'gap-1.5 py-1 pl-1 pr-2.5'
      }`}
      style={{
        backgroundColor: compact ? 'transparent' : tint(board.color, 0.09),
        border: `1px solid ${compact ? 'var(--color-border)' : tint(board.color, 0.28)}`,
      }}
    >
      <span
        className="grid place-items-center rounded"
        style={{ width: mark, height: mark, backgroundColor: color }}
        aria-hidden="true"
      >
        <span style={{ color: '#fff', fontSize: compact ? 9 : 12, fontWeight: 800, lineHeight: 1, letterSpacing: '-0.04em' }}>
          {board.mark}
        </span>
      </span>
      <span style={{ fontSize: 12, fontWeight: 600, color }}>{board.label}</span>
    </span>
  )
}

function CompanyTag({ compact = false }: { compact?: boolean }) {
  return (
    <span
      className={`inline-flex items-center rounded-full ${
        compact ? 'gap-1 py-0.5 pl-1 pr-1.5' : 'gap-1.5 py-1 pl-1.5 pr-2.5'
      }`}
      style={{
        backgroundColor: compact ? 'transparent' : 'var(--color-surface-2)',
        border: '1px solid var(--color-border)',
      }}
    >
      <Building2 size={compact ? 11 : 13} strokeWidth={2} style={{ color: 'var(--color-ink-muted)' }} aria-hidden="true" />
      <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-ink-muted)' }}>Company site</span>
    </span>
  )
}

/**
 * Where one Role was retrieved from, as a single tag.
 *
 * The detail view answers "which boards is this listed on" and needs the whole
 * set. A card answers the narrower question — where did this row come from —
 * which is `job.source`, the only provenance the list endpoint returns. Reading
 * it through the same BOARDS/OWN_SITE registry is what stops the card growing a
 * second, quietly divergent idea of what a source is called.
 *
 * Unknown sources render nothing rather than throwing, same as the section
 * below: the registry test in tests/test_sources.py is what stops that
 * happening, this is only the backstop.
 */
export function SourceTag({ source }: { source: string }) {
  if (OWN_SITE.has(source)) return <CompanyTag compact />
  const board = BOARDS[source]
  if (!board) return null
  return <BoardTag board={board} compact />
}

export default function SourceBadges({ sources }: { sources: string[] }) {
  const keys = normalise(sources)
  if (keys.length === 0) return null

  return (
    <section aria-label="Listed on">
      <h3
        className="text-xs font-semibold uppercase tracking-widest mb-2.5"
        style={{ color: 'var(--color-ink-faint)' }}
      >
        Listed on
      </h3>
      <div className="flex flex-wrap gap-2">
        {keys.map(k => (k === 'company' ? <CompanyTag key={k} /> : <BoardTag key={k} board={BOARDS[k]} />))}
      </div>
    </section>
  )
}
