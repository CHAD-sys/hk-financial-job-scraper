import {
  Briefcase, Bookmark, Menu, X, ChevronDown, FileText, LogOut, ArrowUpRight, Building2,
  Eye, LayoutDashboard, Search, UserRound,
} from 'lucide-react'
import { useState, useEffect, useRef } from 'react'
import { useNavigate, useLocation, Link } from 'react-router-dom'
import { scrollToTop, scrollToHash } from '../utils/scroll'
import type { Seeker, Employer } from '../api/client'
import { useAuth } from '../auth/useAuth'
import { useAdminMode } from '../adminMode/useAdminMode'
import { useEmployerView } from '../employerView/useEmployerView'
import { useEmployerAuth } from '../auth/useEmployerAuth'
import { useSavedRoles } from '../savedRoles/useSavedRoles'

/**
 * Primary navigation.
 *
 * Consultation points off-site to the Club's mentor programme
 * (finexclub.org/mentor-program) — external, with the same treatment as Market
 * Research. Careers and Learning are real pages and navigate normally.
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
 * `AdminModeSwitch` is the admin privilege one step further in: a single
 * button, not a seventh link in the row, because it is not a destination among
 * equals — it is the one control an admin needs reachable from every page, in
 * BOTH directions. Which direction it points is read from the CURRENT route
 * rather than stored anywhere: on /admin (or under it) it goes to the board;
 * everywhere else it goes to /admin. ModeChooserPage.tsx is the one-time fork
 * right after signing in; this button covers every visit after that.
 *
 * It sits ALONGSIDE the "Admin panel" entry in the primary row, not instead of
 * it. The link is a destination among destinations; the switch is the one
 * control that also carries an admin back OUT of the panel, which a one-way
 * link never did.
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

/**
 * The primary row, plus one destination for admins and, for Ultimate Admin
 * specifically, one more.
 *
 * "Admin panel" sits in the row alongside Home/Careers/About because that is
 * where a destination belongs — it is a place you go, listed with the other
 * places you can go. AdminModeSwitch is a different thing and they are not
 * redundant: the switch is a TOGGLE, it changes meaning with the route, and it
 * is what carries an admin back OUT of the panel to the board. This is what
 * puts the panel in the same list the rest of the product is in.
 *
 * ASF (Audit Salary Fixing) is deliberately gated on `isSuperAdmin` alone, NOT
 * on `isAdmin` the way "Admin panel" is — and not on the `adminMode` toggle
 * either, so it does not disappear just because an Ultimate Admin has Admin
 * Mode switched off. It carries an admin's read/edit access to every job's
 * salary; a plain `is_admin` account must never see the entry point, same bar
 * as the Accounts Directory in AdminPage.tsx.
 *
 * Kept as a function (rather than inlining LINKS) because the mobile menu and
 * the desktop row must not be able to drift apart on what "primary" means —
 * both call this.
 */
/**
 * What the account slot shows: the Seeker's menu, the Employer's, a "Sign in"
 * prompt, or nothing yet.
 *
 * Seeker and Employer are separate accounts with separate sessions (ADR 0001),
 * and BOTH can be signed in at once. The slot used to be decided inline from
 * the Seeker session alone, in two places — the desktop bar and the mobile
 * menu — which is how the same bug reached both: a signed-in Employer was shown
 * their own company chip and a bare "Sign in" link side by side, which reads as
 * "you are not signed in" whatever else is on the bar.
 *
 * A function, for the same reason `primaryLinksFor` is one: the two menus must
 * not be able to disagree about who is signed in. `'pending'` until BOTH
 * sessions have answered — flashing "Sign in" at somebody who is signed in is
 * worse than a beat of nothing, and that is true of either account.
 */
export type AccountSlot = 'pending' | 'seeker' | 'employer' | 'sign-in'

export function accountSlotFor(
  { authLoading, hasSeeker, employerAuthLoading, hasEmployer }: {
    authLoading: boolean
    hasSeeker: boolean
    employerAuthLoading: boolean
    hasEmployer: boolean
  },
): AccountSlot {
  if (authLoading || employerAuthLoading) return 'pending'
  // Seeker wins the slot when both are signed in: this bar's other Employer
  // affordances (the "Post a role" button, EmployerMenu) render independently,
  // so the Employer is still represented — see the desktop bar.
  if (hasSeeker) return 'seeker'
  if (hasEmployer) return 'employer'
  return 'sign-in'
}


export function primaryLinksFor(isAdmin: boolean, isSuperAdmin: boolean): PrimaryLink[] {
  const links = isAdmin ? [...LINKS, { label: 'Admin panel', to: '/admin' }] : [...LINKS]
  if (isSuperAdmin) links.push({ label: 'ASF', to: '/asf' })
  return links
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
  //: One decision, read by both the desktop bar and the mobile menu.
  const accountSlot = accountSlotFor({
    authLoading, hasSeeker: Boolean(seeker),
    employerAuthLoading, hasEmployer: Boolean(employer),
  })
  // Both bits, for the same reason JobBoardPage reads both: seekers_store's
  // set_super_admin() writes only its own column, so an Ultimate Admin granted
  // that bit alone would otherwise get no way back to the panel.
  const { adminMode, canUseAdminMode, setAdminMode } = useAdminMode()
  // The Employer PREVIEW (employerView/EmployerViewProvider.tsx). Kept
  // strictly separate from `employer` below it: that is a real session and
  // this is an Ultimate Admin looking at the shell. Anywhere the two could
  // be confused, the real session wins — the provider makes the preview
  // unavailable while one exists.
  const { employerView, canUseEmployerView, setEmployerView } = useEmployerView()
  // The panel is an admin-view destination, so the row only carries it in admin
  // view. In Seeker view an admin's nav is a Seeker's nav, entry for entry.
  // ASF is the one exception: it reads seeker.is_super_admin directly, not
  // adminMode, so it stays visible to Ultimate Admin regardless of the toggle.
  const primaryLinks = primaryLinksFor(
    !authLoading && adminMode, !authLoading && Boolean(seeker?.is_super_admin),
  )

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
      {/* Unmissable, and above BOTH bars rather than inside either: an admin
          who forgets they are in the preview will read every employer-shaped
          affordance below as their own. Says what the preview is not, because
          "you are an Employer" is exactly the wrong thing to infer. */}
      {employerView && (
        <div
          role="status"
          className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 px-4 py-1.5 text-center text-xs font-medium"
          style={{ backgroundColor: 'var(--color-gold)', color: '#1F1300' }}
        >
          <span className="inline-flex items-center gap-1.5">
            <Eye size={13} strokeWidth={2.5} aria-hidden="true" />
            <strong>Employer view</strong> — previewing what an Employer sees. You are not
            signed in as one, and submissions are disabled.
          </span>
          <button
            type="button"
            onClick={() => setEmployerView(false)}
            className="cursor-pointer rounded px-2 py-0.5 text-xs font-semibold underline"
            style={{ background: 'none', border: 'none', color: '#1F1300' }}
          >
            Leave Employer view
          </button>
        </div>
      )}

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
              {!authLoading && canUseAdminMode && (
                <AdminModeSwitch
                  adminMode={adminMode}
                  onToggle={setAdminMode}
                  onNavigate={() => setOpen(false)}
                  compact
                />
              )}

              {/* Ultimate Admin only, and never alongside a real Employer
                  session (useEmployerView's own guard) — the entry AND exit
                  for the preview, same shape as AdminModeSwitch beside it. This
                  is the ONE control that turns the preview on or off; nothing
                  else in the bar repeats that job, so there is exactly one
                  place to look for it. */}
              {!authLoading && !employerAuthLoading && canUseEmployerView && (
                <EmployerViewSwitch
                  employerView={employerView}
                  onToggle={setEmployerView}
                  onNavigate={() => setOpen(false)}
                  backTo={adminMode ? '/admin' : '/jobs'}
                  compact
                />
              )}

              {/* Only for a signed-in Employer now — PostRolePage.tsx redirects
                  anyone else to /employer/signin, so a standing link nobody
                  anonymous could use would be a promise this bar could not keep.
                  Rendered in preview too, so there is something for the switch
                  above to actually preview — but the preview carries no
                  identity, so it gets no EmployerMenu: the switch above is
                  already this bar's one way out of it. */}
              {!employerAuthLoading && (employer || employerView) && (
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
              )}
              {employer && <EmployerMenu employer={employer} onSignOut={handleEmployerSignOut} />}

              <SavedButton
                count={savedCount}
                active={pathname === '/saved'}
                compact
                onClick={() => (pathname === '/saved' ? scrollToTop() : navigate('/saved'))}
              />

              {/* Nothing renders until BOTH /api/auth/me and the employer's
                  equivalent have answered: flashing "Sign in" at somebody who
                  is signed in is worse than a beat of nothing.

                  The employer half of that gate was missing, and it is the bug
                  this fixes. Seeker and Employer are separate accounts (ADR
                  0001) with separate sessions, and this slot only ever asked
                  about the Seeker — so a signed-in Employer saw their own
                  company chip and a "Sign in" link side by side, which reads as
                  "you are not signed in" no matter what else is on the bar.

                  An Employer who also wants a Seeker account is not stranded:
                  the chooser is still at /get-started, and EmployerMenu links
                  to it. What is gone is the bare prompt that contradicted the
                  chip beside it. */}
              {accountSlot === 'seeker' && seeker && (
                <SeekerMenu seeker={seeker} onSignOut={handleSignOut} />
              )}
              {accountSlot === 'sign-in' && (
                <Link
                  to="/get-started"
                  state={{ from: returnTo }}
                  className="inline-flex min-h-9 items-center rounded px-3 py-1.5 text-sm font-medium no-underline"
                  style={{ color: 'rgba(248,250,252,0.75)' }}
                >
                  Sign in
                </Link>
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
              {!authLoading && canUseAdminMode && (
                <AdminModeSwitch
                  adminMode={adminMode}
                  onToggle={setAdminMode}
                  onNavigate={() => setOpen(false)}
                  compact
                  iconOnly
                />
              )}

              {!authLoading && !employerAuthLoading && canUseEmployerView && (
                <EmployerViewSwitch
                  employerView={employerView}
                  onToggle={setEmployerView}
                  onNavigate={() => setOpen(false)}
                  backTo={adminMode ? '/admin' : '/jobs'}
                  compact
                  iconOnly
                />
              )}

              <SavedButton
                count={savedCount}
                active={pathname === '/saved'}
                iconOnly
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
            ...(!employerAuthLoading && (employer || employerView) ? [{ label: 'Post a role', to: '/post-a-role' }] : []),
            // The account item(s), which the desktop bar keeps in its own slot.
            // Same `accountSlot` the desktop bar reads, so the two menus cannot
            // disagree about who is signed in — an Employer's own sign-out sits
            // at the bottom of this menu, so 'employer' contributes nothing here.
            ...(accountSlot === 'seeker' ? [{ label: 'Resume & account', to: '/account' }]
              : accountSlot === 'sign-in' ? [{ label: 'Sign in', to: '/get-started' }]
              : []),
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
  iconOnly = false,
  onClick,
}: {
  count: number
  active: boolean
  compact?: boolean
  // Icon + count only, no "Saved" text — deterministic per call site (the
  // mobile row passes this) rather than a CSS width breakpoint. A pixel
  // threshold has to guess every real phone's width; iPhones alone split
  // 375-430 CSS px across current models, and 414/428/430-wide phones
  // (Plus/Max lines) still overflowed the row under the old `max-
  // [400px]:hidden` cutoff even though the mobile block genuinely never
  // has room for this label wherever it renders.
  iconOnly?: boolean
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
      {!iconOnly && <span>Saved</span>}
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
 * The Admin ⇄ Seeker toggle.
 *
 * It used to derive its direction from the CURRENT ROUTE and do nothing but
 * navigate, which made it decorative: the board's admin powers were on in both
 * "modes", so the button announced a state change that never happened. It now
 * flips the real flag (adminMode/AdminModeProvider.tsx) and navigates as a
 * consequence — turning it on takes you to the panel, turning it off returns
 * you to the board you would see as a Seeker.
 *
 * Rendered whenever the account COULD use Admin Mode, not only when it is
 * already on: this is the way in as well as the way out. A <button> rather than
 * a <Link> because its primary effect is the state change; the navigation is
 * the follow-through.
 *
 * `state={{ discover: true }}` on the way back to /jobs is load-bearing:
 * JobBoardPage reads it to return to discover mode rather than whatever
 * research the admin had open before they entered the panel.
 *
 * Solid gold rather than the outline/ghost treatment every other item in this
 * bar gets — the five people who ever see this button need it to read as "the
 * special control", not blend into ordinary nav.
 */
function AdminModeSwitch({
  adminMode,
  onToggle,
  onNavigate,
  compact = false,
  iconOnly = false,
}: {
  adminMode: boolean
  onToggle: (on: boolean) => void
  onNavigate: () => void
  compact?: boolean
  // See SavedButton's iconOnly doc — same fix, same reason: a CSS width
  // breakpoint has to guess every real phone's viewport width, and several
  // common ones (414/428/430 CSS px — the Plus/Max iPhone lines) sit above
  // any threshold narrow enough to still fit a 375px phone, so the row kept
  // overflowing on exactly the devices the breakpoint was meant to catch.
  iconOnly?: boolean
}) {
  const navigate = useNavigate()
  const label = adminMode ? 'Seeker view' : 'Admin Mode'
  const Icon = adminMode ? Search : LayoutDashboard

  return (
    <button
      type="button"
      onClick={() => {
        const next = !adminMode
        onToggle(next)
        onNavigate()
        navigate(next ? '/admin' : '/jobs', {
          state: next ? undefined : { discover: true },
        })
      }}
      aria-pressed={adminMode}
      aria-label={label}
      title={adminMode
        ? 'Leave Admin Mode — see the board exactly as a Seeker does'
        : 'Enter Admin Mode — edit Roles and browse the whole catalogue'}
      className={`flex cursor-pointer items-center gap-1.5 rounded font-semibold transition-colors duration-150 ${
        compact ? 'min-h-9 px-3 py-1.5 text-sm' : 'min-h-11 px-3 text-sm'
      }`}
      style={{ backgroundColor: 'var(--color-gold)', color: '#fff' }}
    >
      <Icon size={14} strokeWidth={2} aria-hidden="true" />
      {/* iconOnly drops this from the DOM entirely on the mobile row, which
          is also why aria-label above (not just this text) carries the name
          there — matching SavedButton's own explicit aria-label. */}
      {!iconOnly && <span>{label}</span>}
    </button>
  )
}

/**
 * The Employer view ⇄ leave toggle — AdminModeSwitch's twin, sitting right
 * beside it.
 *
 * This is the fix for "where can I even switch it": the preview used to have
 * no entry point in the bar at all, only a launcher buried inside the
 * Employer view panel on /admin. One button now does what AdminModeSwitch
 * does for Admin Mode — it IS the toggle, on and off, always visible to
 * whoever could use it, not only once the preview is already running.
 *
 * Deliberately NOT solid gold. Admin Mode's gold means "a real privilege is
 * active"; this is a preview of somebody else's product, and dressing it in
 * the same color would claim more than it is. Same outline treatment as
 * "Post a role" instead — present, not urgent.
 *
 * `backTo` is the page to land on when the switch goes OFF: PostRolePage
 * redirects anyone with neither a real Employer session nor the preview flag
 * straight to /employer/signin, so leaving the preview while sitting on
 * /post-a-role must navigate away in the same click, or the very next render
 * would bounce to a sign-in page nobody asked for. The caller passes whichever
 * page makes sense for who is asking — see the two call sites in this file.
 */
function EmployerViewSwitch({
  employerView,
  onToggle,
  onNavigate,
  backTo,
  compact = false,
  iconOnly = false,
}: {
  employerView: boolean
  onToggle: (on: boolean) => void
  onNavigate: () => void
  backTo: string
  compact?: boolean
  iconOnly?: boolean
}) {
  const navigate = useNavigate()
  const label = employerView ? 'Leave preview' : 'Employer view'

  return (
    <button
      type="button"
      onClick={() => {
        const next = !employerView
        onToggle(next)
        onNavigate()
        navigate(next ? '/post-a-role' : backTo)
      }}
      aria-pressed={employerView}
      aria-label={label}
      title={employerView
        ? 'Leave Employer view — return to your own view'
        : 'See the site as an Employer — a preview, no account and no submissions'}
      className={`flex cursor-pointer items-center gap-1.5 rounded font-medium transition-colors duration-150 ${
        compact ? 'min-h-9 px-3 py-1.5 text-sm' : 'min-h-11 px-3 text-sm'
      }`}
      style={{
        backgroundColor: employerView ? 'rgba(255,255,255,0.16)' : 'rgba(255,255,255,0.08)',
        color: 'var(--color-ink-inverse)',
        border: '1px solid rgba(255,255,255,0.25)',
      }}
    >
      <Eye size={14} strokeWidth={2} aria-hidden="true" />
      {!iconOnly && <span>{label}</span>}
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
          {/* The one route to the Seeker side for someone already signed in
              as an Employer. The bar's "Sign in" link is hidden for them (it
              contradicted the chip this menu hangs off), so without this the
              two accounts would have no door between them. Worded as the
              separate thing it is, never as a bare "Sign in". */}
          <Link
            role="menuitem"
            to="/get-started"
            onClick={() => setOpen(false)}
            className="flex min-h-11 w-full items-center gap-2 px-3 text-left text-sm font-medium no-underline"
            style={{ color: 'var(--color-ink-muted)' }}
          >
            <UserRound size={15} strokeWidth={2} />
            Seeker account
          </Link>
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
