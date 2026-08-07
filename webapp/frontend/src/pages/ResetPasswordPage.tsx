import { useState } from 'react'
import { AlertCircle, KeyRound } from 'lucide-react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { AuthShell, AuthField } from '../components/AuthShell'
import { resetPassword } from '../api/client'
import { useAuth } from '../auth/useAuth'

type Status = 'idle' | 'sending' | 'error' | 'invalid-link'

const MAX_PASSWORD = 128
const MIN_PASSWORD = 8

/**
 * Where the link in "Reset your password — FinEx Careers" lands.
 *
 * A missing token means the page was opened without following a real link —
 * treated the same as a spent or expired one (reset-password answers 400 for
 * all three, on purpose, per auth.consume_email_token's docstring): there is
 * nothing here worth telling those cases apart for.
 */
export default function ResetPasswordPage() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') ?? ''
  const navigate = useNavigate()
  const { refresh } = useAuth()
  const [status, setStatus] = useState<Status>(token ? 'idle' : 'invalid-link')
  const [error, setError] = useState('')

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (status === 'sending') return

    const d = new FormData(e.currentTarget)
    const password = String(d.get('password') ?? '')
    const confirm = String(d.get('confirm_password') ?? '')

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
      await resetPassword(token, password)
      await refresh()
      navigate('/account', { replace: true })
    } catch {
      // consume_email_token collapses every failure — unknown, expired,
      // already used — to the same answer, so this page does too.
      setStatus('invalid-link')
    }
  }

  if (status === 'invalid-link') {
    return (
      <AuthShell eyebrow="Seeker account" title="Link no longer valid">
        <div
          className="mt-8 rounded-xl p-6 text-center lg:p-8"
          style={{
            backgroundColor: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
            boxShadow: 'var(--shadow-card)',
          }}
          role="status"
        >
          <p className="text-sm" style={{ color: 'var(--color-ink-muted)' }}>
            This reset link has already been used or has expired. Reset links work once and
            expire after an hour.
          </p>
          <Link
            to="/forgot-password"
            className="mt-6 inline-flex min-h-11 items-center justify-center rounded px-5 py-2.5 text-sm font-semibold no-underline"
            style={{ backgroundColor: 'var(--color-ink)', color: 'var(--color-ink-inverse)' }}
          >
            Request a new link
          </Link>
        </div>
      </AuthShell>
    )
  }

  return (
    <AuthShell eyebrow="Seeker account" title="Choose a new password">
      <div
        className="mt-8 rounded-xl p-6 lg:p-8"
        style={{
          backgroundColor: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          boxShadow: 'var(--shadow-card)',
        }}
      >
        <form onSubmit={handleSubmit} noValidate>
          <AuthField
            label="New password"
            htmlFor="rp-password"
            hint={`At least ${MIN_PASSWORD} characters.`}
          >
            <input
              id="rp-password" name="password" type="password" required
              minLength={MIN_PASSWORD} maxLength={MAX_PASSWORD}
              autoComplete="new-password" className="finex-input"
            />
          </AuthField>

          <div className="mt-5">
            <AuthField label="Confirm new password" htmlFor="rp-confirm">
              <input
                id="rp-confirm" name="confirm_password" type="password" required
                minLength={MIN_PASSWORD} maxLength={MAX_PASSWORD}
                autoComplete="new-password" className="finex-input"
              />
            </AuthField>
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
            {status === 'sending' ? 'Saving…' : 'Save new password'}
            {status !== 'sending' && <KeyRound size={15} strokeWidth={2} />}
          </button>
        </form>

        <p className="mt-4 text-xs" style={{ color: 'var(--color-ink-faint)' }}>
          This signs you out everywhere else — anyone who had your old session loses it too.
        </p>
      </div>
    </AuthShell>
  )
}
