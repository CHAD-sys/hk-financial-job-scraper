import { LayoutDashboard, Search, ArrowRight } from 'lucide-react'
import { Link, Navigate, useLocation } from 'react-router-dom'
import Nav from '../components/Nav'
import { useAuth } from '../auth/useAuth'

/**
 * Where an admin lands right after signing in — SignInChooserPage.tsx's
 * pattern, one level further in.
 *
 * Asked on every sign-in, deliberately, rather than remembered: these five
 * accounts move between "look at the business" and "look at the board like
 * anyone else" often enough that defaulting to last time's answer would
 * itself be a surprise half the time. Nav.tsx's persistent switch button
 * covers every visit after this one — this page only exists for the moment
 * right after signing in, when there is no "current view" yet to switch away
 * from.
 *
 * Unreachable by anyone without is_admin: typing the URL directly just sends
 * you back to the board, the same as SignInChooserPage does for an already-
 * decided Seeker or Employer.
 */
export default function ModeChooserPage() {
  const { seeker, loading } = useAuth()
  const { state } = useLocation()
  const from = (state as { from?: string } | null)?.from || '/jobs'

  if (!loading && (!seeker || !seeker.is_admin)) return <Navigate to="/" replace />

  return (
    <div style={{ backgroundColor: 'var(--color-bg)', minHeight: '100dvh' }}>
      <Nav />
      <main id="main-content" className="mx-auto max-w-4xl px-6 py-14 lg:py-20">
        <div className="mx-auto max-w-xl text-center">
          <span
            className="text-xs font-semibold uppercase"
            style={{ color: 'var(--color-gold)', letterSpacing: '0.14em' }}
          >
            Admin Mode
          </span>
          <h1
            className="mt-3 text-3xl tracking-tight"
            style={{
              fontFamily: 'var(--font-display)',
              fontWeight: 700,
              color: 'var(--color-ink)',
              letterSpacing: '-0.025em',
            }}
          >
            How do you want to look at FinEx today?
          </h1>
          <p className="mt-4 text-sm leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>
            You can switch back and forth any time — a button stays at the top of every page.
          </p>
        </div>

        <div className="mt-10 grid gap-5 sm:grid-cols-2">
          <ChoiceCard
            icon={<LayoutDashboard size={22} strokeWidth={2} style={{ color: 'var(--color-gold)' }} />}
            title="Admin Mode"
            body="Today's run, recruiter verification, and the full data analytics dashboard."
            to="/admin"
            cta="Enter Admin Mode"
          />
          <ChoiceCard
            icon={<Search size={22} strokeWidth={2} style={{ color: 'var(--color-gold)' }} />}
            title="Seeker view"
            body="Browse the board and your Saved Roles exactly like any other Seeker."
            to={from}
            cta="Continue as Seeker"
          />
        </div>
      </main>
    </div>
  )
}

function ChoiceCard({
  icon, title, body, to, cta,
}: {
  icon: React.ReactNode
  title: string
  body: string
  to: string
  cta: string
}) {
  return (
    <Link
      to={to}
      className="flex flex-col rounded-xl p-6 text-left no-underline transition-shadow duration-150 lg:p-7"
      style={{
        backgroundColor: 'var(--color-surface)',
        border: '1px solid var(--color-border)',
        boxShadow: 'var(--shadow-card)',
      }}
    >
      <span
        className="flex h-11 w-11 items-center justify-center rounded-full"
        style={{ backgroundColor: 'var(--color-gold-light)' }}
      >
        {icon}
      </span>
      <h2
        className="mt-4 text-lg tracking-tight"
        style={{ fontFamily: 'var(--font-display)', fontWeight: 700, color: 'var(--color-ink)' }}
      >
        {title}
      </h2>
      <p className="mt-2 flex-1 text-sm leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>
        {body}
      </p>
      <span
        className="mt-5 inline-flex items-center gap-1.5 text-sm font-semibold"
        style={{ color: 'var(--color-blue)' }}
      >
        {cta}
        <ArrowRight size={15} strokeWidth={2} />
      </span>
    </Link>
  )
}
