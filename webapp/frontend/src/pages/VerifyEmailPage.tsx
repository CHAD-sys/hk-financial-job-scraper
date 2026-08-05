import { useEffect, useRef, useState } from 'react'
import { CheckCircle2, XCircle, Loader2 } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import { AuthShell } from '../components/AuthShell'
import { verifyEmail } from '../api/client'
import { useAuth } from '../auth/useAuth'

type Status = 'checking' | 'done' | 'error'

/**
 * Where the link in "Confirm your email — FinEx Careers" lands.
 *
 * Fires the verify call itself, from script, rather than being a GET the
 * backend answers directly — see client.ts's verifyEmail() docstring: some
 * mail clients pre-fetch links to scan them, which would otherwise burn the
 * single-use token before a human ever clicked it.
 *
 * No token in the URL, or a spent/expired one, reads as the same quiet
 * failure a Seeker cannot do anything about except ask for a fresh link from
 * their account page — there is nothing to distinguish for them here.
 */
export default function VerifyEmailPage() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') ?? ''
  const { refresh } = useAuth()
  const [status, setStatus] = useState<Status>(token ? 'checking' : 'error')
  const attempted = useRef(false)

  useEffect(() => {
    if (!token || attempted.current) return
    attempted.current = true
    verifyEmail(token)
      .then(() => refresh())
      .then(() => setStatus('done'))
      .catch(() => setStatus('error'))
  }, [token, refresh])

  return (
    <AuthShell eyebrow="Seeker account" title="Confirm your email">
      <div
        className="mt-8 rounded-xl p-6 text-center lg:p-8"
        style={{
          backgroundColor: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          boxShadow: 'var(--shadow-card)',
        }}
        role="status"
      >
        {status === 'checking' && (
          <>
            <Loader2
              size={28}
              strokeWidth={2}
              className="mx-auto animate-spin"
              style={{ color: 'var(--color-ink-faint)' }}
            />
            <p className="mt-4 text-sm" style={{ color: 'var(--color-ink-muted)' }}>
              Confirming your address…
            </p>
          </>
        )}

        {status === 'done' && (
          <>
            <span
              className="mx-auto flex h-12 w-12 items-center justify-center rounded-full"
              style={{ backgroundColor: 'var(--color-gold-light)' }}
            >
              <CheckCircle2 size={24} strokeWidth={2.2} style={{ color: 'var(--color-gold)' }} />
            </span>
            <p className="mt-4 text-sm" style={{ color: 'var(--color-ink-muted)' }}>
              Your email is confirmed.
            </p>
            <Link
              to="/account"
              className="mt-6 inline-flex min-h-11 items-center justify-center rounded px-5 py-2.5 text-sm font-semibold no-underline"
              style={{ backgroundColor: 'var(--color-ink)', color: 'var(--color-ink-inverse)' }}
            >
              Go to your account
            </Link>
          </>
        )}

        {status === 'error' && (
          <>
            <span
              className="mx-auto flex h-12 w-12 items-center justify-center rounded-full"
              style={{ backgroundColor: 'var(--color-surface-2)' }}
            >
              <XCircle size={24} strokeWidth={2.2} style={{ color: 'var(--color-ink-muted)' }} />
            </span>
            <p className="mt-4 text-sm" style={{ color: 'var(--color-ink-muted)' }}>
              This link is no longer valid — it may have already been used or expired.
            </p>
            <Link
              to="/signin"
              className="mt-6 inline-flex min-h-11 items-center justify-center rounded px-5 py-2.5 text-sm font-semibold no-underline"
              style={{ backgroundColor: 'var(--color-ink)', color: 'var(--color-ink-inverse)' }}
            >
              Back to sign in
            </Link>
          </>
        )}
      </div>
    </AuthShell>
  )
}
