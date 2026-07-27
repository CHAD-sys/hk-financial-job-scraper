import { Briefcase, Bookmark, Menu, X } from 'lucide-react'
import { useState } from 'react'
import { useNavigate, useLocation, Link } from 'react-router-dom'

interface Props {
  savedCount?: number
}

/**
 * Primary navigation.
 *
 * Consultation and Learning are sections on `/`, not routes, so they are hash
 * links. From `/` the browser scrolls natively; from any other route this is a
 * client-side navigation and LandingPage's useHashScroll() does the scrolling on
 * arrival.
 *
 * "Home" is deliberately absent — the wordmark is the home link, and dropping it
 * buys the width the two new products need.
 */

const LINKS: { label: string; to: string }[] = [
  { label: 'Careers', to: '/jobs' },
  { label: 'Consultation', to: '/#consultation' },
  { label: 'Learning', to: '/#learning' },
  { label: 'About', to: '/about' },
]

export default function Nav({ savedCount = 0 }: Props) {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const { pathname, hash } = useLocation()

  const isActive = (to: string) =>
    to.startsWith('/#') ? pathname === '/' && hash === to.slice(1) : pathname === to

  return (
    <header
      style={{ backgroundColor: 'var(--color-nav)', zIndex: 200 }}
      className="sticky top-0 w-full border-b border-white/10"
    >
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="flex h-16 items-center justify-between gap-4">

          {/* Wordmark */}
          <button
            type="button"
            onClick={() => navigate('/')}
            className="flex shrink-0 items-center gap-2.5 cursor-pointer"
            aria-label="FinEx Careers home"
          >
            <span
              className="flex h-8 w-8 items-center justify-center rounded"
              style={{ backgroundColor: 'var(--color-gold)' }}
            >
              <Briefcase size={16} color="#fff" strokeWidth={2} />
            </span>
            <span
              className="text-lg font-semibold tracking-tight select-none"
              style={{ fontFamily: 'var(--font-display)', color: 'var(--color-ink-inverse)' }}
            >
              FinEx{' '}
              <em className="not-italic" style={{ color: 'var(--color-gold)', fontStyle: 'italic' }}>
                Careers
              </em>
            </span>
          </button>

          {/* Desktop nav. Breaks at lg, not md — five items plus the right-hand
              cluster crowd badly between 768px and 1024px. */}
          <nav className="hidden lg:flex items-center gap-6" aria-label="Primary navigation">
            {LINKS.map(({ label, to }) => (
              <Link
                key={label}
                to={to}
                className="text-sm font-medium no-underline transition-colors duration-150"
                style={{ color: isActive(to) ? 'var(--color-ink-inverse)' : 'rgba(248,250,252,0.6)' }}
              >
                {label}
              </Link>
            ))}
          </nav>

          <div className="flex shrink-0 items-center gap-3">
            {/* Employer CTA — quiet on purpose; candidates are the main audience */}
            <Link
              to="/post-a-role"
              className="hidden lg:inline-flex min-h-9 items-center rounded px-3 py-1.5 text-sm font-medium no-underline"
              style={{
                color: 'var(--color-ink-inverse)',
                border: '1px solid rgba(255,255,255,0.25)',
              }}
            >
              Post a role
            </Link>

            {/* Saved jobs */}
            <button
              type="button"
              onClick={() => navigate('/saved')}
              className="flex min-h-11 items-center gap-1.5 rounded px-3 py-1.5 text-sm font-medium transition-colors duration-150 cursor-pointer"
              style={{
                backgroundColor: pathname === '/saved' ? 'var(--color-gold)' : 'rgba(255,255,255,0.08)',
                color: 'var(--color-ink-inverse)',
                border: '1px solid rgba(255,255,255,0.12)',
              }}
              aria-label={`Saved jobs (${savedCount})`}
            >
              <Bookmark size={14} strokeWidth={1.8} fill={savedCount > 0 ? 'currentColor' : 'none'} />
              <span className="max-[400px]:hidden">Saved</span>
              {savedCount > 0 && (
                <span
                  className="flex h-4 w-4 items-center justify-center rounded-full text-xs font-bold"
                  style={{ backgroundColor: 'var(--color-gold)', color: '#fff' }}
                >
                  {savedCount}
                </span>
              )}
            </button>

            {/* Reserved: sign-in lands here when accounts ship. Deliberately
                renders nothing — a button that does not work is worse than none.
                Keeping the slot means the Nav does not need re-composition. */}

            {/* Mobile toggle */}
            <button
              type="button"
              className="lg:hidden flex min-h-11 min-w-11 items-center justify-center rounded cursor-pointer"
              style={{ color: 'var(--color-ink-inverse)' }}
              onClick={() => setOpen(o => !o)}
              aria-label="Toggle menu"
              aria-expanded={open}
            >
              {open ? <X size={20} /> : <Menu size={20} />}
            </button>
          </div>
        </div>
      </div>

      {/* Mobile menu */}
      {open && (
        <nav
          className="lg:hidden border-t border-white/10 px-6 py-4 flex flex-col gap-4"
          style={{ backgroundColor: 'var(--color-nav)' }}
          aria-label="Mobile navigation"
        >
          {[...LINKS, { label: 'Saved roles', to: '/saved' }, { label: 'Post a role', to: '/post-a-role' }].map(
            ({ label, to }) => (
              <Link
                key={label}
                to={to}
                onClick={() => setOpen(false)}
                className="flex min-h-11 items-center text-sm font-medium no-underline"
                style={{ color: 'rgba(248,250,252,0.8)' }}
              >
                {label}
              </Link>
            ),
          )}
        </nav>
      )}
    </header>
  )
}
