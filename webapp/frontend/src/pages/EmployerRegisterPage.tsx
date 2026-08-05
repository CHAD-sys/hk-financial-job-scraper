import { useState } from 'react'
import { AlertCircle, CheckCircle2, UserPlus } from 'lucide-react'
import { Link } from 'react-router-dom'
import { AuthShell, AuthField } from '../components/AuthShell'
import { registerEmployer, ApiError } from '../api/client'

type Status = 'idle' | 'sending' | 'error' | 'done'

const MAX = { company_name: 150, contact_name: 100, email: 200, password: 128 } as const
const MIN_PASSWORD = 8

/**
 * Create an Employer account — the v1 identity ADR 0001 deferred until now.
 *
 * Not linked from anywhere in the public UI yet, on purpose: there is no
 * dashboard behind this account today (see employers_store.py's module
 * docstring), so advertising "sign in" with no payoff would be the kind of
 * vague promise the design conventions here rule out. /post-a-role works
 * identically signed in or not until that connect work happens. This page
 * exists so the gate can be tested end-to-end; where and how to surface it is
 * an open product decision, not a code gap.
 */
export default function EmployerRegisterPage() {
  const [status, setStatus] = useState<Status>('idle')
  const [error, setError] = useState('')

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
      await registerEmployer({
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
              />
            </AuthField>
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
