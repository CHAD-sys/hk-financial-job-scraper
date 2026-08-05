import { useState } from 'react'
import { AlertCircle, Mail, Send } from 'lucide-react'
import { Link } from 'react-router-dom'
import { AuthShell, AuthField } from '../components/AuthShell'
import { requestEmployerPasswordReset } from '../api/client'

type Status = 'idle' | 'sending' | 'error' | 'check-inbox'

const MAX_EMAIL = 200

/**
 * Request an Employer password-reset email. Same shape as
 * ForgotPasswordPage.tsx (Seeker), with one deliberate difference: no
 * "already signed in" redirect, because there is no EmployerAuthContext to
 * ask (see client.ts's Employer section note — v1 pages call the client
 * functions directly rather than through a shared context).
 */
export default function EmployerForgotPasswordPage() {
  const [status, setStatus] = useState<Status>('idle')
  const [error, setError] = useState('')

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
      await requestEmployerPasswordReset(email)
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
      <AuthShell eyebrow="Employer account" title="Check your inbox">
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
            If that address has an employer account, a reset link is on its way. It works once
            and expires in an hour.
          </p>
          <Link
            to="/employer/signin"
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
      eyebrow="Employer account"
      title="Reset your password"
      standfirst="Tell us the address you registered with, and we'll email you a link to choose a new password."
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
          <AuthField label="Work email" htmlFor="efp-email">
            <input
              id="efp-email" name="email" type="email" required maxLength={MAX_EMAIL}
              autoComplete="email" autoFocus className="finex-input"
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
        <Link to="/employer/signin" style={{ color: 'var(--color-blue)', fontWeight: 500 }}>
          Sign in
        </Link>
      </p>
    </AuthShell>
  )
}
