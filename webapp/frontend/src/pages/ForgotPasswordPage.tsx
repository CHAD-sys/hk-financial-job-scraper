import { useState } from 'react'
import { AlertCircle, Mail, Send } from 'lucide-react'
import { Link, Navigate } from 'react-router-dom'
import { AuthShell, AuthField } from '../components/AuthShell'
import { requestPasswordReset } from '../api/client'
import { useAuth } from '../auth/useAuth'

type Status = 'idle' | 'sending' | 'error' | 'check-inbox'

const MAX_EMAIL = 200

/**
 * Request a password-reset email.
 *
 * Was a stub ("resetting is not switched on yet") from when this page was
 * written — that was true at the time (PLAN_ACCOUNTS phase 3 had not shipped
 * SMTP for Seeker mail yet) and is not true any more: ADR 0009's
 * mail.finexclub.org sender is what /api/auth/register already uses to send
 * the verification email, and /api/auth/forgot-password reuses the exact same
 * sender.
 *
 * The response never says whether the address has an account — same
 * non-enumeration posture as RegisterPage's "check your inbox", for the same
 * reason: a caller who could tell "sent" from "not sent" apart could use this
 * form to test which addresses are registered.
 */
export default function ForgotPasswordPage() {
  const { seeker, loading: authLoading } = useAuth()
  const [status, setStatus] = useState<Status>('idle')
  const [error, setError] = useState('')

  // Already signed in: nothing to reset from here — the account page covers it.
  if (!authLoading && seeker) return <Navigate to="/account" replace />

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (status === 'sending') return

    const email = String(new FormData(e.currentTarget).get('email') ?? '').trim()
    if (!email) {
      setStatus('error')
      setError('Enter your email.')
      return
    }

    setStatus('sending')
    setError('')
    try {
      await requestPasswordReset(email)
      setStatus('check-inbox')
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
            If that address has an account, a reset link is on its way. It works once and
            expires in an hour.
          </p>
          <Link
            to="/signin"
            className="mt-6 inline-flex min-h-11 items-center justify-center rounded px-5 py-2.5 text-sm font-semibold no-underline"
            style={{ backgroundColor: 'var(--color-ink)', color: 'var(--color-ink-inverse)' }}
          >
            Back to sign in
          </Link>
        </div>
      </AuthShell>
    )
  }

  return (
    <AuthShell
      eyebrow="Seeker account"
      title="Reset your password"
      standfirst="Tell us the address you signed up with, and we'll email you a link to choose a new password."
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
          <AuthField label="Email" htmlFor="fp-email">
            <input
              id="fp-email" name="email" type="email" required maxLength={MAX_EMAIL}
              autoComplete="email" className="finex-input"
            />
          </AuthField>

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
            {status === 'sending' ? 'Sending…' : 'Send reset link'}
            {status !== 'sending' && <Send size={15} strokeWidth={2} />}
          </button>
        </form>
      </div>

      <p className="mt-6 text-sm" style={{ color: 'var(--color-ink-muted)' }}>
        Remembered it?{' '}
        <Link to="/signin" style={{ color: 'var(--color-blue)', fontWeight: 500 }}>
          Sign in
        </Link>
      </p>
    </AuthShell>
  )
}
