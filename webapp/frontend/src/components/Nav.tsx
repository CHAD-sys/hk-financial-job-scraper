import {
  Bookmark, Menu, X, Eye, LayoutDashboard, Search, ArrowUpRight,
} from 'lucide-react'
import { useState } from 'react'
import { useNavigate, useLocation, Link } from 'react-router-dom'
import finexAiJobsMark from '../assets/finex-ai-jobs-mark.png'
import { scrollToTop, scrollToHash } from '../utils/scroll'
import { useAuth } from '../auth/useAuth'
import { useAdminMode } from '../adminMode/useAdminMode'
import { useEmployerView } from '../employerView/useEmployerView'
import { useEmployerAuth } from '../auth/useEmployerAuth'
import { useSavedRoles } from '../savedRoles/useSavedRoles'

/**
 * Primary navigation.
 *
 * The persistent Career development menu keeps Management Trainee programmes
 * and Career coaches together as local FinEx Careers destinations. Market
 * Research is the one outbound destination and is visibly treated as an
 * external link.
 *
 * Home and the wordmark lead to the discovery home. The same single-row
 * navigation and menu are used at every screen width.
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
 * It sits alongside the "Admin panel" entry in the menu. The link is a
 * destination among destinations; the switch is the one
 * control that also carries an admin back OUT of the panel, which a one-way
 * link never did.
 */

export type PrimaryLink = { label: string; to: string; external?: boolean }

export const MARKET_RESEARCH_LINK: PrimaryLink = {
  label: 'Market Research',
  to: 'https://www.finexclub.org/research',
  external: true,
}

const LINKS: PrimaryLink[] = [
  { label: 'Home', to: '/' },
  { label: 'Careers', to: '/jobs' },
  { label: 'Learning', to: '/learning' },
  MARKET_RESEARCH_LINK,
  { label: 'About', to: '/about' },
]

export const CAREER_DEVELOPMENT_LINKS: PrimaryLink[] = [
  { label: 'Management Trainee programmes', to: '/management-trainee' },
  { label: 'Career coaches', to: '/career-coaches' },
]

/**
 * The primary menu, plus one destination for admins and, for Ultimate Admin
 * specifically, one more.
 *
 * "Admin panel" sits alongside Home/Careers/About because that is
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
 * Kept as a function so privileged destinations are assembled in one place.
 */
/**
 * What the account slot shows: the Seeker's link, the Employer's, a "Sign in"
 * prompt, or nothing yet.
 *
 * Seeker and Employer are separate accounts with separate sessions (ADR 0001),
 * and BOTH can be signed in at once. The slot used to be decided inline from
 * the Seeker session alone, which gave a signed-in Employer a contradictory
 * "Sign in" link.
 *
 * `'pending'` until both sessions have answered — flashing "Sign in" at somebody who is signed in is
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
  // Seeker wins the account link when both are signed in. The Employer's
  // "Post a role" link and separate sign-out action remain available.
  if (hasSeeker) return 'seeker'
  if (hasEmployer) return 'employer'
  return 'sign-in'
}


export function primaryLinksFor(isAdmin: boolean, isSuperAdmin: boolean): PrimaryLink[] {
  const links = isAdmin ? [...LINKS, { label: 'Admin panel', to: '/admin' }] : [...LINKS]
  if (isSuperAdmin) {
    links.push({ label: 'Validate', to: '/validate' })
    links.push({ label: 'Recruiter desk', to: '/recruiter-desk' })
  }
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
  // One account decision for the shared menu.
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
  // Career development belongs directly after the job board: it is the natural
  // next step after finding a role. The remaining product links support that
  // journey, with Market Research retaining its explicit external treatment.
  const corePrimaryLinks = primaryLinks.filter(link => link.label === 'Home' || link.label === 'Careers')
  const supportingPrimaryLinks = primaryLinks.filter(link => link.label !== 'Home' && link.label !== 'Careers')
  const mobileUtilityLinks: PrimaryLink[] = [
    { label: 'Saved roles', to: '/saved' },
    ...(!employerAuthLoading && (employer || employerView) ? [{ label: 'Post a role', to: '/post-a-role' }] : []),
    ...(accountSlot === 'seeker' ? [{ label: 'Resume & account', to: '/account' }]
      : accountSlot === 'employer' ? [{ label: 'Seeker account', to: '/get-started' }]
      : accountSlot === 'sign-in' ? [{ label: 'Sign in', to: '/get-started' }]
      : []),
  ]

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
      <span className="h-8 w-10 shrink-0" aria-hidden="true">
        <img
          src={finexAiJobsMark}
          alt=""
          width={256}
          height={213}
          className="block h-full w-full object-contain"
        />
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

      {/* One row on every device. */}
      <div>
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
                aria-controls="site-navigation-panel"
              >
                {open ? <X size={20} /> : <Menu size={20} />}
              </button>
            </div>
          </div>
        </div>
        </div>

      {/* Navigation menu */}
      {open && (
        <nav
          id="site-navigation-panel"
          className="site-navigation-panel border-t border-white/10 px-6 py-4 flex flex-col gap-4"
          style={{ backgroundColor: 'var(--color-nav)' }}
          aria-label="Site navigation"
        >
          {corePrimaryLinks.map(link => (
            <MobileNavigationLink key={link.label} link={link} linkState={linkState} onNavigate={() => setOpen(false)} onLinkClick={handleClick} />
          ))}

          <MobileNavigationGroup
            label="Career development"
            links={CAREER_DEVELOPMENT_LINKS}
            linkState={linkState}
            onLinkClick={(event, to) => {
              setOpen(false)
              handleClick(event, to)
            }}
          />
          {supportingPrimaryLinks.map(link => (
            <MobileNavigationLink key={link.label} link={link} linkState={linkState} onNavigate={() => setOpen(false)} onLinkClick={handleClick} />
          ))}
          {mobileUtilityLinks.map(link => (
            <MobileNavigationLink key={link.label} link={link} linkState={linkState} onNavigate={() => setOpen(false)} onLinkClick={handleClick} />
          ))}

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

function MobileNavigationGroup({
  label,
  links,
  linkState,
  onLinkClick,
}: {
  label: string
  links: PrimaryLink[]
  linkState: (to: string) => Record<string, unknown> | undefined
  onLinkClick: (event: React.MouseEvent, to: string) => void
}) {
  return (
    <section className="border-t border-white/10 pt-3" aria-label={label}>
      <h2 className="mb-1 text-xs font-semibold uppercase tracking-[0.1em]" style={{ color: 'rgba(248,250,252,0.48)' }}>{label}</h2>
      {links.map(link => link.external ? (
        <a
          key={link.label}
          href={link.to}
          target="_blank"
          rel="noopener noreferrer"
          className="flex min-h-11 items-center justify-between text-sm font-medium no-underline"
          style={{ color: 'rgba(248,250,252,0.8)' }}
        >
          {link.label}
          <ArrowUpRight size={14} strokeWidth={2} aria-hidden="true" />
        </a>
      ) : (
        <Link
          key={link.label}
          to={link.to}
          state={linkState(link.to)}
          onClick={event => onLinkClick(event, link.to)}
          className="flex min-h-11 items-center text-sm font-medium no-underline"
          style={{ color: 'rgba(248,250,252,0.8)' }}
        >
          {link.label}
        </Link>
      ))}
    </section>
  )
}

function MobileNavigationLink({
  link,
  linkState,
  onNavigate,
  onLinkClick,
}: {
  link: PrimaryLink
  linkState: (to: string) => Record<string, unknown> | undefined
  onNavigate: () => void
  onLinkClick: (event: React.MouseEvent, to: string) => void
}) {
  if (link.external) {
    return (
      <a
        href={link.to}
        target="_blank"
        rel="noopener noreferrer"
        onClick={onNavigate}
        className="flex min-h-11 items-center justify-between text-sm font-medium no-underline"
        style={{ color: 'rgba(248,250,252,0.8)' }}
      >
        {link.label}
        <ArrowUpRight size={14} strokeWidth={2} aria-hidden="true" />
      </a>
    )
  }

  return (
    <Link
      to={link.to}
      state={linkState(link.to)}
      onClick={event => {
        onNavigate()
        onLinkClick(event, link.to)
      }}
      className="flex min-h-11 items-center text-sm font-medium no-underline"
      style={{ color: 'rgba(248,250,252,0.8)' }}
    >
      {link.label}
    </Link>
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
