import { useState } from 'react'
import { AlertCircle, CheckCircle2, Mail, UserPlus } from 'lucide-react'
import { Link, Navigate } from 'react-router-dom'
import { AuthShell, AuthField, AuthDivider, GoogleButton } from '../components/AuthShell'
import { ApiError, isPersonalEmailDomain, EMPLOYER_GOOGLE_SIGN_IN_PATH } from '../api/client'
import { useEmployerAuth } from '../auth/useEmployerAuth'
import { useReturnTo } from '../auth/useReturnTo'

type Status = 'idle' | 'sending' | 'error' | 'done'

const MAX = { company_name: 150, contact_name: 100, email: 200, password: 128 } as const
const MIN_PASSWORD = 8

/**
 * Create an Employer account — the v1 identity ADR 0001 deferred until now.
 *
 * Now linked from the "Sign in" chooser (SignInChooserPage.tsx) — it was
 * deliberately unlinked while /post-a-role worked identically signed in or
 * not, which stopped being true once that page started requiring an Employer
 * (its own docstring covers why: posting on a company's behalf is now a
 * thing an account owns, not an anonymous form).
 */
export default function EmployerRegisterPage() {
  const { employer, loading: authLoading, register } = useEmployerAuth()
  const returnTo = useReturnTo('/post-a-role')
  const [status, setStatus] = useState<Status>('idle')
  const [error, setError] = useState('')
  // Drives the "use your work email" nudge below the field — advisory only,
  // never blocks handleSubmit. A candidate reading a role posted from a
  // recognisable company address trusts it faster than one from a personal
  // inbox; Google sign-in a few lines up is unaffected either way, since
  // signing in with Gmail and registering FROM a gmail.com address are
  // different things (see client.ts's isPersonalEmailDomain docstring).
  const [emailHint, setEmailHint] = useState(false)

  // Already signed in: nothing left for this page to do.
  if (!authLoading && employer) return <Navigate to={returnTo} replace />

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (status === 'sending') return

    const d = new FormData(e.currentTarget)
    const companyName = String(d.get('company_name') ?? '').trim()
    const contactName = String(d.get('contact_name') ?? '').trim()
    const email = String(d.get('email') ?? '').trim()
    const password = String(d.get('password') ?? '')
    const confirm = String(d.get('confirm_password') ?? '')

    if (!companyName || !email) {
      setStatus('error')
      setError('Enter your company name and email.')
      return
    }
    if (password.length < MIN_PASSWORD) {
      setStatus('error')
      setError(`Choose a password of at least ${MIN_PASSWORD} characters.`)
      return
    }
    if (password !== confirm) {
      setStatus('error')
      setError('The two passwords do not match.')
      return
    }

    setStatus('sending')
    setError('')
    try {
      await register({
        company_name: companyName,
        contact_name: contactName,
        email,
        password,
        website: String(d.get('website') ?? ''),
      })
      setStatus('done')
      window.scrollTo({ top: 0, behavior: 'smooth' })
    } catch (err) {
      setStatus('error')
      setError(
        err instanceof ApiError && err.status === 409
          ? 'That email already has an employer account.'
          : err instanceof Error && err.message
            ? err.message
            : 'Something went wrong. Please try again.',
      )
    }
  }

  if (status === 'done') {
    return (
      <AuthShell eyebrow="Employer account" title="You're in">
        <div
          className="mt-8 rounded-xl p-8 text-center"
          style={{
            backgroundColor: 'var(--color-surface)',
            border: '1px solid var(--color-gold)',
            boxShadow: 'var(--shadow-card)',
          }}
          role="status"
        >
          <span
            className="mx-auto flex h-12 w-12 items-center justify-center rounded-full"
            style={{ backgroundColor: 'var(--color-gold-light)' }}
          >
            <CheckCircle2 size={24} strokeWidth={2.2} style={{ color: 'var(--color-gold)' }} />
          </span>
          <p className="mt-4 text-sm" style={{ color: 'var(--color-ink-muted)' }}>
            Your employer account is set up. There is no dashboard here yet — for now, post a
            role the same way you always could.
          </p>
          <Link
            to="/post-a-role"
            className="mt-6 inline-flex min-h-11 items-center justify-center rounded px-5 py-2.5 text-sm font-semibold no-underline"
            style={{ backgroundColor: 'var(--color-ink)', color: 'var(--color-ink-inverse)' }}
          >
            Post a role
          </Link>
        </div>
      </AuthShell>
    )
  }

  return (
    <AuthShell
      eyebrow="Employer account"
      title="Create an employer account"
      standfirst="For recruiters and employers posting roles directly. This is separate from a Seeker account — the two share nothing."
    >
      <div
        className="mt-8 rounded-xl p-6 lg:p-8"
        style={{
          backgroundColor: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          boxShadow: 'var(--shadow-card)',
        }}
      >
        <GoogleButton label="Continue with Google" href={EMPLOYER_GOOGLE_SIGN_IN_PATH} />
        <p className="mt-2.5 text-xs" style={{ color: 'var(--color-ink-faint)' }}>
          Only for signing back in to an account that already exists — Google can't set up
          your company name, so start with the form below the first time.
        </p>
        <AuthDivider />

        <form onSubmit={handleSubmit} noValidate>
          <AuthField label="Company name" htmlFor="er-company">
            <input
              id="er-company" name="company_name" type="text" required maxLength={MAX.company_name}
              autoComplete="organization" className="finex-input"
            />
          </AuthField>

          <div className="mt-5">
            <AuthField label="Your name" htmlFor="er-name" hint="Optional.">
              <input
                id="er-name" name="contact_name" type="text" maxLength={MAX.contact_name}
                autoComplete="name" className="finex-input"
              />
            </AuthField>
          </div>

          <div className="mt-5">
            <AuthField label="Work email" htmlFor="er-email">
              <input
                id="er-email" name="email" type="email" required maxLength={MAX.email}
                autoComplete="email" className="finex-input"
                onChange={e => setEmailHint(isPersonalEmailDomain(e.currentTarget.value))}
              />
            </AuthField>
            {emailHint && (
              <p className="mt-1.5 flex items-start gap-1.5 text-xs" style={{ color: 'var(--color-ink-faint)' }}>
                <Mail size={13} strokeWidth={2} className="mt-0.5 shrink-0" />
                A company address builds more trust with candidates than a personal one — but
                this works fine too.
              </p>
            )}
          </div>

          <div className="mt-5">
            <AuthField
              label="Password"
              htmlFor="er-password"
              hint={`At least ${MIN_PASSWORD} characters.`}
            >
              <input
                id="er-password" name="password" type="password" required
                minLength={MIN_PASSWORD} maxLength={MAX.password}
                autoComplete="new-password" className="finex-input"
              />
            </AuthField>
          </div>

          <div className="mt-5">
            <AuthField label="Confirm password" htmlFor="er-confirm">
              <input
                id="er-confirm" name="confirm_password" type="password" required
                minLength={MIN_PASSWORD} maxLength={MAX.password}
                autoComplete="new-password" className="finex-input"
              />
            </AuthField>
          </div>

          {/* Honeypot — never shown to a human, never focusable. */}
          <div aria-hidden="true" className="honeypot">
            <label htmlFor="er-website">Website</label>
            <input id="er-website" name="website" type="text" tabIndex={-1} autoComplete="off" />
          </div>

          {status === 'error' && (
            <p
              className="mt-5 flex items-start gap-2 text-sm"
              style={{ color: 'var(--color-destructive)' }}
              role="alert"
            >
              <AlertCircle size={16} strokeWidth={2} className="mt-0.5 shrink-0" />
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={status === 'sending'}
            className="mt-6 inline-flex min-h-11 w-full items-center justify-center gap-2 rounded px-6 py-3 text-sm font-semibold"
            style={{
              backgroundColor: 'var(--color-ink)',
              color: 'var(--color-ink-inverse)',
              cursor: status === 'sending' ? 'wait' : 'pointer',
              opacity: status === 'sending' ? 0.7 : 1,
            }}
          >
            {status === 'sending' ? 'Creating…' : 'Create account'}
            {status !== 'sending' && <UserPlus size={15} strokeWidth={2} />}
          </button>
        </form>
      </div>

      <p className="mt-6 text-sm" style={{ color: 'var(--color-ink-muted)' }}>
        Already have an employer account?{' '}
        <Link to="/employer/signin" style={{ color: 'var(--color-blue)', fontWeight: 500 }}>
          Sign in
        </Link>
      </p>
    </AuthShell>
  )
}
