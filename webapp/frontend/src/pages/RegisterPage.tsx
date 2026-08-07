import { useState } from 'react'
import { AlertCircle, Mail, UserPlus } from 'lucide-react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { AuthShell, AuthField, AuthDivider, GoogleButton, LinkedInButton } from '../components/AuthShell'
import { useAuth } from '../auth/useAuth'
import { useReturnTo } from '../auth/useReturnTo'

type Status = 'idle' | 'sending' | 'error' | 'check-inbox'

const MAX = { display_name: 100, email: 200, password: 128 } as const
const MIN_PASSWORD = 8

/**
 * Create a Seeker account.
 *
 * Two details are load-bearing.
 *
 * The honeypot ("website") mirrors the enquiry and post-a-role forms: off-screen
 * rather than display:none, never focusable, and a bot that fills it gets a
 * normal-looking success response.
 *
 * The confirm-password field stays even now that /forgot-password works: a
 * caught typo here is free, where a missed one costs a Seeker a trip through
 * the reset flow before they can sign in at all.
 */
export default function RegisterPage() {
  const { seeker, loading: authLoading, register } = useAuth()
  const navigate = useNavigate()
  const returnTo = useReturnTo()
  const [status, setStatus] = useState<Status>('idle')
  const [error, setError] = useState('')

  if (!authLoading && seeker) return <Navigate to={returnTo} replace />

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (status === 'sending') return

    const d = new FormData(e.currentTarget)
    const displayName = String(d.get('display_name') ?? '').trim()
    const email = String(d.get('email') ?? '').trim()
    const password = String(d.get('password') ?? '')
    const confirm = String(d.get('confirm_password') ?? '')

    if (!displayName || !email) {
      setStatus('error')
      setError('Enter your name and email.')
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
      const created = await register({
        display_name: displayName,
        email,
        password,
        website: String(d.get('website') ?? ''),
      })
      if (created) {
        navigate(returnTo, { replace: true })
        return
      }
      // No session came back. That is what registering an address which already
      // has an account looks like — the endpoint answers like success either
      // way so it cannot be used to test whether an address is registered
      // (PLAN_ACCOUNTS §5). So this message has to be true in both cases and
      // reveal neither.
      setStatus('check-inbox')
      window.scrollTo({ top: 0, behavior: 'smooth' })
    } catch (err) {
      setStatus('error')
      setError(
        err instanceof Error && err.message
          ? err.message
          : 'Something went wrong. Please try again.',
      )
    }
  }

  if (status === 'check-inbox') {
    return (
      <AuthShell eyebrow="Seeker account" title="Check your inbox">
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
            <Mail size={24} strokeWidth={2.2} style={{ color: 'var(--color-gold)' }} />
          </span>
          <p className="mt-4 text-sm" style={{ color: 'var(--color-ink-muted)' }}>
            If we can set up an account for that address, an email is on its way. Follow the
            link in it to finish, then sign in.
          </p>
          <Link
            to="/signin"
            className="mt-6 inline-flex min-h-11 items-center justify-center rounded px-5 py-2.5 text-sm font-semibold no-underline"
            style={{ backgroundColor: 'var(--color-ink)', color: 'var(--color-ink-inverse)' }}
          >
            Go to sign in
          </Link>
        </div>
      </AuthShell>
    )
  }

  return (
    <AuthShell
      eyebrow="Seeker account"
      title="Create an account"
      standfirst={
        <>
          One thing an account does today: it keeps your Saved Roles with you instead of
          with this browser, and keeps them current as roles close. Browsing the board needs
          no account and never will.
        </>
      }
    >
      <div
        className="mt-8 rounded-xl p-6 lg:p-8"
        style={{
          backgroundColor: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          boxShadow: 'var(--shadow-card)',
        }}
      >
        <div className="flex flex-col gap-3">
          <GoogleButton label="Continue with Google" />
          <LinkedInButton label="Continue with LinkedIn" />
        </div>
        <AuthDivider />

        <form onSubmit={handleSubmit} noValidate>
          <AuthField label="Name" htmlFor="rg-name" hint="What we call you on the site. Never published.">
            <input
              id="rg-name" name="display_name" type="text" required maxLength={MAX.display_name}
              autoComplete="name" className="finex-input"
            />
          </AuthField>

          <div className="mt-5">
            <AuthField label="Email" htmlFor="rg-email">
              <input
                id="rg-email" name="email" type="email" required maxLength={MAX.email}
                autoComplete="email" className="finex-input"
              />
            </AuthField>
          </div>

          <div className="mt-5">
            <AuthField
              label="Password"
              htmlFor="rg-password"
              hint={`At least ${MIN_PASSWORD} characters.`}
            >
              <input
                id="rg-password" name="password" type="password" required
                minLength={MIN_PASSWORD} maxLength={MAX.password}
                autoComplete="new-password" className="finex-input"
              />
            </AuthField>
          </div>

          <div className="mt-5">
            <AuthField label="Confirm password" htmlFor="rg-confirm">
              <input
                id="rg-confirm" name="confirm_password" type="password" required
                minLength={MIN_PASSWORD} maxLength={MAX.password}
                autoComplete="new-password" className="finex-input"
              />
            </AuthField>
          </div>

          {/* Honeypot — never shown to a human, never focusable. */}
          <div aria-hidden="true" className="honeypot">
            <label htmlFor="rg-website">Website</label>
            <input id="rg-website" name="website" type="text" tabIndex={-1} autoComplete="off" />
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

        <p className="mt-4 text-xs" style={{ color: 'var(--color-ink-faint)' }}>
          We use your email to sign you in and to reach you about your account. No mailing list.
        </p>
      </div>

      <p className="mt-6 text-sm" style={{ color: 'var(--color-ink-muted)' }}>
        Already have an account?{' '}
        <Link to="/signin" state={{ from: returnTo }} style={{ color: 'var(--color-blue)', fontWeight: 500 }}>
          Sign in
        </Link>
      </p>
    </AuthShell>
  )
}
