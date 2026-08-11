import { ArrowRight, BriefcaseBusiness, Check } from 'lucide-react'
import { Link } from 'react-router-dom'

export default function MemberRoleNotice({ returnTo }: { returnTo: string }) {
  return (
    <aside
      aria-label="Exclusive roles for registered Seekers"
      className="mb-6 overflow-hidden rounded-lg"
      style={{
        backgroundColor: 'var(--color-surface)',
        border: '1px solid var(--color-border-strong)',
        boxShadow: 'var(--shadow-card)',
      }}
    >
      <div className="h-1" style={{ backgroundColor: 'var(--color-gold)' }} aria-hidden="true" />
      <div className="flex flex-col gap-5 px-5 py-5 sm:px-6 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex max-w-2xl items-start gap-4">
          <span
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full"
            style={{ backgroundColor: 'var(--color-gold-light)', color: 'var(--color-gold)' }}
          >
            <BriefcaseBusiness size={21} strokeWidth={2} aria-hidden="true" />
          </span>
          <div>
            <h2
              className="text-lg font-semibold leading-snug"
              style={{ color: 'var(--color-ink)', letterSpacing: '-0.015em' }}
            >
              Register to unlock exclusive jobs
            </h2>
            <p className="mt-1 text-sm leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>
              See recruiter-posted roles and opportunities from medium-sized companies alongside
              your current search results.
            </p>
            <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5" aria-label="Account benefits">
              {['Exclusive roles', 'Saved jobs across devices', 'Personalised recommendations'].map(benefit => (
                <li
                  key={benefit}
                  className="flex items-center gap-1.5 text-xs font-semibold"
                  style={{ color: 'var(--color-ink-muted)' }}
                >
                  <Check size={14} strokeWidth={2.5} style={{ color: 'var(--color-gold)' }} aria-hidden="true" />
                  {benefit}
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="flex shrink-0 flex-col items-stretch gap-2 sm:flex-row sm:items-center lg:flex-col lg:items-stretch xl:flex-row xl:items-center">
          <Link
            to="/register"
            state={{ from: returnTo }}
            className="inline-flex min-h-11 items-center justify-center gap-2 rounded px-5 text-sm font-semibold no-underline transition-colors duration-150"
            style={{ backgroundColor: 'var(--color-ink)', color: 'var(--color-ink-inverse)' }}
          >
            Create free account
            <ArrowRight size={15} strokeWidth={2.5} aria-hidden="true" />
          </Link>
          <Link
            to="/signin"
            state={{ from: returnTo }}
            className="inline-flex min-h-11 items-center justify-center px-3 text-sm font-semibold no-underline hover:underline"
            style={{ color: 'var(--color-blue)', textUnderlineOffset: '3px' }}
          >
            Already registered? Sign in
          </Link>
        </div>
      </div>
    </aside>
  )
}
