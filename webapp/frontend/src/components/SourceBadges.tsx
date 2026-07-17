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
}

// Sources that are the employer's own careers page rather than a job board.
const OWN_SITE = new Set(['workday', 'eightfold', 'longtail'])

// Display order: own site first, then boards by preference.
const ORDER = ['company', 'efinancialcareers', 'indeed', 'jobsdb', 'linkedin']

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

function BoardTag({ board }: { board: Board }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full py-1 pl-1 pr-2.5"
      style={{ backgroundColor: tint(board.color, 0.09), border: `1px solid ${tint(board.color, 0.28)}` }}
    >
      <span
        className="grid place-items-center rounded"
        style={{ width: 18, height: 18, backgroundColor: board.color }}
        aria-hidden="true"
      >
        <span style={{ color: '#fff', fontSize: 12, fontWeight: 800, lineHeight: 1, letterSpacing: '-0.04em' }}>
          {board.mark}
        </span>
      </span>
      <span style={{ fontSize: 12, fontWeight: 600, color: board.color }}>{board.label}</span>
    </span>
  )
}

function CompanyTag() {
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full py-1 pl-1.5 pr-2.5"
      style={{ backgroundColor: 'var(--color-surface-2)', border: '1px solid var(--color-border)' }}
    >
      <Building2 size={13} strokeWidth={2} style={{ color: 'var(--color-ink-muted)' }} aria-hidden="true" />
      <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-ink-muted)' }}>Company site</span>
    </span>
  )
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
