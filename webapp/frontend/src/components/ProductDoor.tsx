import { ArrowRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { ReactNode } from 'react'

// Module scope, not rebuilt per render: these depend on no props or state, and a
// fresh object every render defeats memoisation downstream for no benefit.
const DOOR_CLASS =
  'product-door relative flex flex-col h-full p-7 lg:p-8 rounded-xl text-left no-underline'

const DOOR_STYLE = {
  backgroundColor: 'var(--color-surface)',
  border: '1px solid var(--color-border)',
  boxShadow: 'var(--shadow-card)',
} as const

interface Props {
  /** "01" / "02" / "03" — editorial numbering, decorative. */
  index: string
  eyebrow: string
  title: string
  description: string
  /**
   * A short credential line sitting between the title and the description —
   * a standing fact about the door (e.g. who the Club partners with), not the
   * live figure below. Optional; only the consultation door carries one today.
   */
  note?: ReactNode
  /** Live figure (e.g. "3,612 live roles"). Rendered in mono. Optional. */
  figure?: ReactNode
  /** Internal route ("/jobs"), same-page anchor ("#consultation"), or an external URL ("https://..."). */
  href: string
}

/**
 * One of the three doors on the portal.
 *
 * Rendered as a real anchor, not a div with onClick, so it is keyboard
 * reachable, middle-clickable, and crawlable. Internal routes go through
 * react-router's Link; same-page anchors stay plain <a href="#..."> and rely on
 * the native smooth scrolling already set on `html` in index.css. An external
 * URL also stays a plain <a> — react-router's <Link> resolves `to` against the
 * current route, so a full https:// URL passed to it would be treated as an
 * (nonexistent) internal path rather than actually leaving the site.
 */
export default function ProductDoor({ index, eyebrow, title, description, note, figure, href }: Props) {
  const isExternal = href.startsWith('http')
  const isAnchor = href.startsWith('#')

  const body = (
    <>
      {/* Gold rule along the top edge — the FT accent, one per door */}
      <span
        aria-hidden="true"
        className="absolute inset-x-0 top-0 h-0.5"
        style={{ backgroundColor: 'var(--color-gold)' }}
      />

      <span
        aria-hidden="true"
        className="text-xs font-semibold tabular-nums"
        style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-ink-faint)' }}
      >
        {index}
      </span>

      <span
        className="mt-5 text-xs font-semibold uppercase"
        style={{ color: 'var(--color-gold)', letterSpacing: '0.14em' }}
      >
        {eyebrow}
      </span>

      <h3
        className="mt-2 text-2xl leading-tight tracking-tight"
        style={{ fontFamily: 'var(--font-display)', fontWeight: 700, color: 'var(--color-ink)', letterSpacing: '-0.02em' }}
      >
        {title}
      </h3>

      {note && (
        <p className="mt-3 text-sm leading-relaxed" style={{ color: 'var(--color-ink)' }}>
          {note}
        </p>
      )}

      <p className="mt-3 text-sm leading-relaxed grow" style={{ color: 'var(--color-ink-muted)' }}>
        {description}
      </p>

      {/* Figure sits directly above the arrow so all three doors align on a
          baseline even when their descriptions differ in length. */}
      <span
        className="mt-6 block min-h-5 text-sm font-semibold tabular-nums"
        style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-ink)' }}
      >
        {figure}
      </span>

      <span
        className="mt-4 inline-flex items-center gap-1.5 text-sm font-semibold"
        style={{ color: 'var(--color-blue)' }}
      >
        Enter
        <ArrowRight size={15} strokeWidth={2} className="door-arrow" />
      </span>
    </>
  )

  if (isExternal) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" className={DOOR_CLASS} style={DOOR_STYLE}>
        {body}
      </a>
    )
  }

  if (isAnchor) {
    return (
      <a href={href} className={DOOR_CLASS} style={DOOR_STYLE}>
        {body}
      </a>
    )
  }

  return (
    <Link to={href} className={DOOR_CLASS} style={DOOR_STYLE}>
      {body}
    </Link>
  )
}
