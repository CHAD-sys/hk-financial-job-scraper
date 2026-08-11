import {
  Briefcase, Bookmark, Menu, X, ChevronDown, FileText, LogOut, ArrowUpRight, Building2,
} from 'lucide-react'
import { useState, useEffect, useRef } from 'react'
import { useNavigate, useLocation, Link } from 'react-router-dom'
import { scrollToTop, scrollToHash } from '../utils/scroll'
import type { Seeker, Employer } from '../api/client'
import { useAuth } from '../auth/useAuth'
import { useEmployerAuth } from '../auth/useEmployerAuth'
import { useSavedRoles } from '../savedRoles/useSavedRoles'

/**
 * Primary navigation.
 *
 * Consultation points off-site to the Club's mentor programme
 * (finexclub.org/mentor-program) — external, same treatment as Market
 * Research, while the on-page enquiry form it used to open stays in the
 * codebase (EnquiryForm.tsx, POST /api/contact) rather than being deleted.
 * Careers and Learning are real pages (/jobs, /learning) and navigate normally.
 *
 * Home points at the portal (the "Asia's 1st Premier Career Centre" statement).
 * The wordmark also goes there, but an explicit Home is what most people look
 * for, and the two hash links below make it genuinely useful: once you have
 * scrolled to Consultation the URL is still `/`, so Home is the way back up.
 *
 * Six items plus the right-hand cluster (Post a role, Saved, account) no
 * longer fit one desktop row, so on lg+ the bar splits in two: a slim utility
 * strip carrying identity and account actions, and a full-width nav row below
 * it. Nothing is hidden behind an overflow menu — a link the user cannot see
 * is a link they will not click. Mobile keeps its single row and flat menu.
 *
 * "Sign in" points at /get-started, a chooser between the two separate
 * account kinds (SignInChooserPage.tsx), not straight at the Seeker form —
 * this bar cannot know which one a visitor wants before they say so.
 *
 * "Post a role" only renders once an Employer is actually signed in. It used
 * to be a standing link anyone could use anonymously; PostRolePage.tsx now
 * requires an Employer account, so a link nobody-signed-in could click would
 * just be a promise this bar could not keep.
 *
 * Administrators get one additional destination, "Admin panel", in the same
 * navigation hierarchy. There is no separate Seeker/Admin mode: an admin can
 * browse the public product normally and open the panel like any other page.
 */

export type PrimaryLink = { label: string; to: string; external?: boolean }

const LINKS: PrimaryLink[] = [
  { label: 'Home', to: '/' },
  { label: 'Careers', to: '/jobs' },
  { label: 'Consultation', to: 'https://www.finexclub.org/mentor-program', external: true },
  { label: 'Learning', to: '/learning' },
  { label: 'Market Research', to: 'https://www.finexclub.org/research', external: true },
  { label: 'About', to: '/about' },
]

export function primaryLinksFor(isAdmin: boolean): PrimaryLink[] {
  return isAdmin ? [...LINKS, { label: 'Admin panel', to: '/admin' }] : LINKS
}

export default function Nav() {
  // Read the count rather than take it as a prop. As a prop it defaulted to 0,
  // so the four pages that rendered a bare <Nav /> — Home, About, Learning and
  // Post a role — showed a signed-in Seeker a Saved badge of zero. A forgotten
  // prop with a default is a silent wrong number; reading the context is not.
  const { count: savedCount } = useSavedRoles()
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const { pathname, hash } = useLocation()
  const { seeker, loading: authLoading, logout } = useAuth()
  const { employer, loading: employerAuthLoading, logout: employerLogout } = useEmployerAuth()
  const primaryLinks = primaryLinksFor(!authLoading && Boolean(seeker?.is_admin))

  // Where sign-in should return to. The board is public, so nobody is ever sent
  // here by a wall — they came from a page they were reading and should land
  // back on it.
  const returnTo = pathname === '/signin' || pathname === '/register'
    || pathname === '/get-started' ? '/jobs' : pathname + hash

  /**
   * Router state a nav item carries.
   *
   * `/jobs` is two screens behind one route — a search home and a results page
   * (JobBoardPage's discover/board modes) — so "Careers" has to say WHICH of
   * them it means. Without this it means "the route", and the route hands back
   * whatever results you were last looking at.
   */
  const linkState = (to: string) => {
    if (to === '/get-started') return { from: returnTo }
    if (to === '/jobs') return { discover: true }
    return undefined
  }

  async function handleSignOut() {
    setOpen(false)
    await logout()
    navigate('/')
  }

  async function handleEmployerSignOut() {
    setOpen(false)
    await employerLogout()
    navigate('/')
  }

  // A hash link is active only when its fragment is the current one. Home is the
  // portal with NO fragment — otherwise scrolling to a hash-linked section
  // (which leaves pathname as '/') would light up Home at the same time.
  const isActive = (to: string) => {
    if (to.startsWith('/#')) return pathname === '/' && hash === to.slice(1)
    if (to === '/') return pathname === '/' && !hash
    return pathname === to
  }

  /**
   * Clicking a nav item for the page you are already on.
   *
   * React Router treats navigating to the current location as a no-op, so
   * without this the link is dead: you are two screens down the job board,
   * you press "Careers", and nothing at all happens. Every item now does the
   * obvious thing instead — page links return you to the top, hash links
   * re-scroll to their section.
   */
  const handleClick = (e: React.MouseEvent, to: string) => {
    // Let the browser handle modified clicks (new tab, new window, download).
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return

    const isHashLink = to.startsWith('/#')
    const targetPath = isHashLink ? '/' : to
    if (pathname !== targetPath) return // ordinary navigation to another page

    e.preventDefault()
    setOpen(false)

    if (isHashLink) {
      const fragment = to.slice(1)
      // Update the URL, then scroll ourselves rather than leaving it to
      // useHashScroll. That hook exists for *arriving* at /#consultation from
      // another route; relying on it here made the first click set the URL
      // without moving the page, because its effect-and-rAF fires a beat after
      // the click. Scrolling directly is immediate and does not depend on
      // render timing. Also means a second click re-scrolls, which a
      // hash-change-only listener never would.
      if (hash !== fragment) navigate(to)
      scrollToHash(fragment)
      return
    }

    // Careers, pressed while already on the board, means "start over" — not
    // "scroll up". You are two screens into a results page; the thing you are
    // reaching for is the search box you started from, and scrolling to the top
    // of your own results does not get you there. A real navigation (rather
    // than the preventDefault above) is what clears the filters out of the URL
    // and gives JobBoardPage a location it can recognise as a reset.
    if (to === '/jobs') {
      navigate('/jobs', { state: { discover: true } })
      scrollToTop()
      return
    }

    // Any other page link: drop any fragment so the URL matches where we end
    // up, then go to the top.
    if (hash) navigate(to, { replace: true })
    scrollToTop()
  }

  const wordmark = (
    <button
      type="button"
      onClick={() => {
        // Same rule as the Home link: already home means "take me to the top".
        if (pathname === '/') {
          if (hash) navigate('/', { replace: true })
          scrollToTop()
        } else {
          navigate('/')
        }
      }}
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
  )

  return (
    <header
      style={{ backgroundColor: 'var(--color-nav)', zIndex: 200 }}
      className="sticky top-0 w-full border-b border-white/10"
    >
      {/* ── Desktop: two tiers ──────────────────────────────────────────────
          Six links plus the action cluster no longer share one row without
          crowding, so the row splits by *kind* rather than hiding links in an
          overflow menu: identity and account actions sit on a slim utility
          strip, and the nav gets a full-width row to itself. Everything stays
          visible, and the active page earns a real underline rather than a
          shift in text colour alone. */}
      <div className="hidden lg:block">
        <div className="mx-auto max-w-7xl px-8">
          <div className="flex h-11 items-center justify-between gap-4">
            {wordmark}

            <div className="flex shrink-0 items-center gap-3">
              {/* Only for a signed-in Employer now — PostRolePage.tsx redirects
                  anyone else to /employer/signin, so a standing link nobody
                  anonymous could use would be a promise this bar could not keep. */}
              {!employerAuthLoading && employer && (
                <>
                  <Link
                    to="/post-a-role"
                    onClick={e => handleClick(e, '/post-a-role')}
                    className="inline-flex min-h-9 items-center rounded px-3 py-1.5 text-sm font-medium no-underline"
                    style={{
                      color: 'var(--color-ink-inverse)',
                      border: '1px solid rgba(255,255,255,0.25)',
                    }}
                  >
                    Post a role
                  </Link>
                  <EmployerMenu employer={employer} onSignOut={handleEmployerSignOut} />
                </>
              )}

              <SavedButton
                count={savedCount}
                active={pathname === '/saved'}
                compact
                onClick={() => (pathname === '/saved' ? scrollToTop() : navigate('/saved'))}
              />

              {/* Nothing renders until /api/auth/me has answered: flashing
                  "Sign in" at somebody who is signed in is worse than a beat
                  of nothing. */}
              {!authLoading && (
                seeker ? (
                  <SeekerMenu seeker={seeker} onSignOut={handleSignOut} />
                ) : (
                  <Link
                    to="/get-started"
                    state={{ from: returnTo }}
                    className="inline-flex min-h-9 items-center rounded px-3 py-1.5 text-sm font-medium no-underline"
                    style={{ color: 'rgba(248,250,252,0.75)' }}
                  >
                    Sign in
                  </Link>
                )
              )}
            </div>
          </div>
        </div>

        {/* One tonal step lighter than the utility strip above. Two dark
            surfaces of the same value separated by a hairline read as one
            muddy block; lightening the raised tier is how dark themes express
            stacking. Dark page heroes share --color-masthead so the nav row
            and the hero below it form one continuous band. */}
        <div
          className="border-t border-white/10"
          style={{ backgroundColor: 'var(--color-masthead)' }}
        >
          <div className="mx-auto max-w-7xl px-8">
            {/* items-stretch, not items-center: each link fills the row so its
                underline lands on the bar's bottom edge. */}
            <nav className="flex h-11 items-stretch gap-8 xl:gap-10" aria-label="Primary navigation">
              {primaryLinks.map(({ label, to, external }) =>
                external ? (
                  <a
                    key={label}
                    href={to}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1 text-sm font-medium no-underline transition-colors duration-150"
                    style={{
                      color: 'rgba(248,250,252,0.6)',
                      borderBottom: '2px solid transparent',
                    }}
                  >
                    {label}
                    <ArrowUpRight size={13} strokeWidth={2} aria-hidden="true" />
                  </a>
                ) : (
                  <Link
                    key={label}
                    to={to}
                    state={linkState(to)}
                    onClick={e => handleClick(e, to)}
                    className="flex items-center text-sm font-medium no-underline transition-colors duration-150"
                    style={{
                      color: isActive(to) ? 'var(--color-ink-inverse)' : 'rgba(248,250,252,0.6)',
                      // gold-star, not gold: DESIGN.md flags the darker gold as
                      // illegible on the navy bar.
                      borderBottom: `2px solid ${isActive(to) ? 'var(--color-gold-star)' : 'transparent'}`,
                    }}
                  >
                    {label}
                  </Link>
                ),
              )}
            </nav>
          </div>
        </div>
      </div>

      {/* ── Mobile: one row, unchanged ───────────────────────────────────── */}
      <div className="lg:hidden">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <div className="flex h-16 items-center justify-between gap-4">
            {wordmark}

            <div className="flex shrink-0 items-center gap-3">
              <SavedButton
                count={savedCount}
                active={pathname === '/saved'}
                onClick={() => (pathname === '/saved' ? scrollToTop() : navigate('/saved'))}
              />

              <button
                type="button"
                className="flex min-h-11 min-w-11 items-center justify-center rounded cursor-pointer"
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
      </div>

      {/* Mobile menu */}
      {open && (
        <nav
          className="lg:hidden border-t border-white/10 px-6 py-4 flex flex-col gap-4"
          style={{ backgroundColor: 'var(--color-nav)' }}
          aria-label="Mobile navigation"
        >
          {[
            ...primaryLinks,
            { label: 'Saved roles', to: '/saved' },
            // Same rule as the desktop bar: only for a signed-in Employer.
            ...(!employerAuthLoading && employer ? [{ label: 'Post a role', to: '/post-a-role' }] : []),
            // The account item(s), which the desktop bar keeps in its own slot.
            ...(authLoading ? [] : seeker
              ? [{ label: 'Resume & account', to: '/account' }]
              : [{ label: 'Sign in', to: '/get-started' }]),
          ].map(({ label, to, external }) =>
            external ? (
              <a
                key={label}
                href={to}
                target="_blank"
                rel="noopener noreferrer"
                onClick={() => setOpen(false)}
                className="flex min-h-11 items-center text-sm font-medium no-underline"
                style={{ color: 'rgba(248,250,252,0.8)' }}
              >
                {label}
              </a>
            ) : (
              <Link
                key={label}
                to={to}
                state={linkState(to)}
                onClick={e => {
                  setOpen(false)
                  handleClick(e, to)
                }}
                className="flex min-h-11 items-center text-sm font-medium no-underline"
                style={{ color: 'rgba(248,250,252,0.8)' }}
              >
                {label}
              </Link>
            ),
          )}

          {seeker && (
            <button
              type="button"
              onClick={handleSignOut}
              className="flex min-h-11 items-center text-left text-sm font-medium cursor-pointer"
              style={{ color: 'rgba(248,250,252,0.55)', background: 'none', border: 'none', padding: 0 }}
            >
              {/* Both accounts can be signed in at once (main.py) — only say
                  which one this button signs out of when there is a second
                  session it could be confused with. */}
              {employer ? 'Sign out (Seeker)' : 'Sign out'}
            </button>
          )}

          {employer && (
            <button
              type="button"
              onClick={handleEmployerSignOut}
              className="flex min-h-11 items-center text-left text-sm font-medium cursor-pointer"
              style={{ color: 'rgba(248,250,252,0.55)', background: 'none', border: 'none', padding: 0 }}
            >
              {seeker ? 'Sign out (Employer)' : 'Sign out'}
              {' — '}{employer.company_name}
            </button>
          )}
        </nav>
      )}
    </header>
  )
}

/**
 * Saved-jobs button. Shared by both bars, which need different heights: the
 * desktop utility strip is short and mouse-driven, the mobile row has to keep
 * a 44px touch target.
 */
function SavedButton({
  count,
  active,
  compact = false,
  onClick,
}: {
  count: number
  active: boolean
  compact?: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-center gap-1.5 rounded px-3 py-1.5 text-sm font-medium transition-colors duration-150 cursor-pointer ${
        compact ? 'min-h-9' : 'min-h-11'
      }`}
      style={{
        backgroundColor: active ? 'var(--color-gold)' : 'rgba(255,255,255,0.08)',
        color: 'var(--color-ink-inverse)',
        border: '1px solid rgba(255,255,255,0.12)',
      }}
      aria-label={`Saved jobs (${count})`}
    >
      <Bookmark size={14} strokeWidth={1.8} fill={count > 0 ? 'currentColor' : 'none'} />
      <span className="max-[400px]:hidden">Saved</span>
      {count > 0 && (
        <span
          className="flex h-4 w-4 items-center justify-center rounded-full text-xs font-bold"
          style={{ backgroundColor: 'var(--color-gold)', color: '#fff' }}
        >
          {count}
        </span>
      )}
    </button>
  )
}

/**
 * The signed-in menu in the desktop bar.
 *
 * A disclosure button plus a short list — not a hover menu. Hover menus are
 * unreachable by keyboard and unusable by touch, and this one holds "Sign out",
 * which nobody should trigger by drifting a cursor. Escape closes it and returns
 * focus to the button; a click anywhere else closes it too.
 */
function SeekerMenu({ seeker, onSignOut }: { seeker: Seeker; onSignOut: () => void }) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)

  const name = seeker.display_name?.trim() || seeker.email
  const initial = name.slice(0, 1).toUpperCase()

  useEffect(() => {
    if (!open) return

    const onPointerDown = (e: PointerEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      setOpen(false)
      buttonRef.current?.focus()
    }

    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  return (
    // No breakpoint class of its own — the desktop utility strip that renders
    // this is already lg-only.
    <div ref={wrapRef} className="relative">
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen(o => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex min-h-9 items-center gap-2 rounded px-2.5 py-1.5 text-sm font-medium cursor-pointer"
        style={{
          color: 'var(--color-ink-inverse)',
          backgroundColor: open ? 'rgba(255,255,255,0.08)' : 'transparent',
          border: '1px solid rgba(255,255,255,0.12)',
        }}
      >
        <span
          className="flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold"
          style={{ backgroundColor: 'var(--color-gold)', color: '#fff' }}
          aria-hidden="true"
        >
          {initial}
        </span>
        <span className="max-w-[10rem] truncate">{name}</span>
        <ChevronDown size={14} strokeWidth={2} aria-hidden="true" />
      </button>

      {open && (
        <div
          role="menu"
          aria-label="Account"
          className="absolute right-0 mt-2 w-56 overflow-hidden rounded-lg py-1"
          style={{
            backgroundColor: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
            boxShadow: 'var(--shadow-float)',
          }}
        >
          <p
            className="px-3 py-2 text-xs break-words"
            style={{ color: 'var(--color-ink-faint)', borderBottom: '1px solid var(--color-border)' }}
          >
            {seeker.email}
          </p>
          <Link
            role="menuitem"
            to="/account"
            onClick={() => setOpen(false)}
            className="flex min-h-11 items-center gap-2 px-3 text-sm font-medium no-underline"
            style={{ color: 'var(--color-ink)' }}
          >
            <FileText size={15} strokeWidth={2} />
            Resume &amp; account
          </Link>
          <Link
            role="menuitem"
            to="/saved"
            onClick={() => setOpen(false)}
            className="flex min-h-11 items-center gap-2 px-3 text-sm font-medium no-underline"
            style={{ color: 'var(--color-ink)' }}
          >
            <Bookmark size={15} strokeWidth={2} />
            Saved Roles
          </Link>
          <button
            role="menuitem"
            type="button"
            onClick={() => { setOpen(false); onSignOut() }}
            className="flex min-h-11 w-full items-center gap-2 px-3 text-left text-sm font-medium cursor-pointer"
            style={{
              color: 'var(--color-ink-muted)',
              background: 'none',
              border: 'none',
              borderTop: '1px solid var(--color-border)',
            }}
          >
            <LogOut size={15} strokeWidth={2} />
            Sign out
          </button>
        </div>
      )}
    </div>
  )
}

/**
 * The signed-in Employer's slot in the desktop bar — SeekerMenu's shape,
 * deliberately smaller: there is no /employer/account or Saved-Roles
 * equivalent to link to (employers_store.py: v1 is identity plus the
 * submission form, nothing else), so this is company name in, sign out out,
 * and nothing invented in between.
 */
function EmployerMenu({ employer, onSignOut }: { employer: Employer; onSignOut: () => void }) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return

    const onPointerDown = (e: PointerEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      setOpen(false)
      buttonRef.current?.focus()
    }

    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  return (
    <div ref={wrapRef} className="relative">
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen(o => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex min-h-9 items-center gap-2 rounded px-2.5 py-1.5 text-sm font-medium cursor-pointer"
        style={{
          color: 'var(--color-ink-inverse)',
          backgroundColor: open ? 'rgba(255,255,255,0.08)' : 'transparent',
          border: '1px solid rgba(255,255,255,0.12)',
        }}
      >
        <span
          className="flex h-6 w-6 items-center justify-center rounded-full"
          style={{ backgroundColor: 'var(--color-gold)' }}
          aria-hidden="true"
        >
          <Building2 size={13} strokeWidth={2} color="#fff" />
        </span>
        <span className="max-w-[10rem] truncate">{employer.company_name}</span>
        <ChevronDown size={14} strokeWidth={2} aria-hidden="true" />
      </button>

      {open && (
        <div
          role="menu"
          aria-label="Employer account"
          className="absolute right-0 mt-2 w-56 overflow-hidden rounded-lg py-1"
          style={{
            backgroundColor: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
            boxShadow: 'var(--shadow-float)',
          }}
        >
          <p
            className="px-3 py-2 text-xs break-words"
            style={{ color: 'var(--color-ink-faint)', borderBottom: '1px solid var(--color-border)' }}
          >
            {employer.email}
          </p>
          <button
            role="menuitem"
            type="button"
            onClick={() => { setOpen(false); onSignOut() }}
            className="flex min-h-11 w-full items-center gap-2 px-3 text-left text-sm font-medium cursor-pointer"
            style={{ color: 'var(--color-ink-muted)', background: 'none', border: 'none' }}
          >
            <LogOut size={15} strokeWidth={2} />
            Sign out
          </button>
        </div>
      )}
    </div>
  )
}
