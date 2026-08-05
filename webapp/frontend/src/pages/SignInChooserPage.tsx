import { Building2, Search, ArrowRight } from 'lucide-react'
import { Link, Navigate, useLocation } from 'react-router-dom'
import Nav from '../components/Nav'
import { useAuth } from '../auth/useAuth'
import { useEmployerAuth } from '../auth/useEmployerAuth'

/**
 * Where Nav's "Sign in" now points, instead of straight at the Seeker form.
 *
 * Two entirely separate account systems share this one nav button (docs/adr/
 * 0001: Seeker and Employer are a separate aggregate, not a role flag on one
 * table), and a visitor who lands here has not told us yet which one they
 * are. Guessing wrong used to mean a candidate landing on a recruiter form or
 * vice versa with no way back except the browser's back button — this page
 * is the fork instead of a coin flip.
 *
 * Skipped entirely if either account is already signed in: there is nothing
 * to choose once you are one of the two things this page is choosing between.
 */
export default function SignInChooserPage() {
  const { seeker, loading: seekerLoading } = useAuth()
  const { employer, loading: employerLoading } = useEmployerAuth()
  const { state } = useLocation()
  // Carried through from wherever "Sign in" was pressed, same shape as
  // useReturnTo() reads elsewhere — passed on to whichever form is chosen so
  // the eventual sign-in still lands back where the visitor started.
  const from = (state as { from?: string } | null)?.from

  if (!seekerLoading && seeker) return <Navigate to="/account" replace />
  if (!employerLoading && employer) return <Navigate to="/post-a-role" replace />

  return (
    <div style={{ backgroundColor: 'var(--color-bg)', minHeight: '100dvh' }}>
      <Nav />
      <main id="main-content" className="mx-auto max-w-4xl px-6 py-14 lg:py-20">
        <div className="mx-auto max-w-xl text-center">
          <span
            className="text-xs font-semibold uppercase"
            style={{ color: 'var(--color-gold)', letterSpacing: '0.14em' }}
          >
            Sign in
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
            Which one are you?
          </h1>
          <p className="mt-4 text-sm leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>
            Two separate kinds of account, sharing nothing — pick the one that's yours.
          </p>
        </div>

        <div className="mt-10 grid gap-5 sm:grid-cols-2">
          <ChoiceCard
            icon={<Search size={22} strokeWidth={2} style={{ color: 'var(--color-gold)' }} />}
            title="I'm looking for a role"
            body="Keep your Saved Roles with your account instead of just this browser. Browsing and applying never require one."
            to="/signin"
            state={{ from }}
            cta="Continue as a Seeker"
          />
          <ChoiceCard
            icon={<Building2 size={22} strokeWidth={2} style={{ color: 'var(--color-gold)' }} />}
            title="I'm hiring"
            body="Sign in to post a role directly to the board. For recruiters and employers only."
            to="/employer/signin"
            state={{ from }}
            cta="Continue as an Employer"
          />
        </div>
      </main>
    </div>
  )
}

function ChoiceCard({
  icon, title, body, to, state, cta,
}: {
  icon: React.ReactNode
  title: string
  body: string
  to: string
  state: { from?: string }
  cta: string
}) {
  return (
    <Link
      to={to}
      state={state}
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
