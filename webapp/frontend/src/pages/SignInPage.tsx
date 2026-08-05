import { useState } from 'react'
import { AlertCircle, LogIn } from 'lucide-react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { AuthShell, AuthField, AuthDivider, GoogleButton } from '../components/AuthShell'
import { useAuth } from '../auth/useAuth'
import { useReturnTo } from '../auth/useReturnTo'

type Status = 'idle' | 'sending' | 'error'

const MAX = { email: 200, password: 128 } as const

/**
 * The ?error= codes main.py's /api/auth/google/callback redirects here with,
 * turned into something a Seeker can act on. Anything not in this map (or
 * absent) shows nothing — an unrecognised code is not a licence to guess.
 */
const GOOGLE_ERROR_MESSAGES: Record<string, string> = {
  google_unavailable: 'Signing in with Google is not switched on yet. Use email and password below.',
  google_failed: 'Something went wrong signing in with Google. Please try again.',
  google_link_refused:
    'That Google address already has an account here, but Google did not confirm it is verified. ' +
    'Sign in with your password instead, or use "Forgot password?" if you never set one.',
}

/**
 * Sign in to an existing Seeker account.
 *
 * Nothing on the board requires this page (docs/adr/0002) — the standfirst says
 * so plainly, because a sign-in screen that arrives unasked reads as a wall
 * unless it tells you it is not one.
 */
export default function SignInPage() {
  const { seeker, loading: authLoading, login } = useAuth()
  const navigate = useNavigate()
  const returnTo = useReturnTo()
  const [searchParams] = useSearchParams()
  const googleErrorCode = searchParams.get('error')
  const googleError = googleErrorCode ? GOOGLE_ERROR_MESSAGES[googleErrorCode] : undefined
  const [status, setStatus] = useState<Status>(googleError ? 'error' : 'idle')
  const [error, setError] = useState(googleError ?? '')

  // Already signed in: this page has nothing to offer.
  if (!authLoading && seeker) return <Navigate to={returnTo} replace />

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (status === 'sending') return

    const d = new FormData(e.currentTarget)
    const email = String(d.get('email') ?? '').trim()
    const password = String(d.get('password') ?? '')

    if (!email || !password) {
      setStatus('error')
      setError('Enter your email and password.')
      return
    }

    setStatus('sending')
    setError('')
    try {
      await login(email, password)
      navigate(returnTo, { replace: true })
    } catch (err) {
      setStatus('error')
      setError(
        err instanceof Error && err.message
          ? err.message
          : 'Something went wrong. Please try again.',
      )
    }
  }

  return (
    <AuthShell
      eyebrow="Seeker account"
      title="Sign in"
      standfirst={
        <>
          Signing in keeps your Saved Roles with your account rather than this browser.
          The board itself stays free and open — you never need an account to read a Role.
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
        <GoogleButton label="Continue with Google" />
        <AuthDivider />

        <form onSubmit={handleSubmit} noValidate>
          <AuthField label="Email" htmlFor="si-email">
            <input
              id="si-email" name="email" type="email" required maxLength={MAX.email}
              autoComplete="email" autoFocus className="finex-input"
            />
          </AuthField>

          <div className="mt-5">
            <AuthField label="Password" htmlFor="si-password">
              <input
                id="si-password" name="password" type="password" required maxLength={MAX.password}
                autoComplete="current-password" className="finex-input"
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
            {status === 'sending' ? 'Signing in…' : 'Sign in'}
            {status !== 'sending' && <LogIn size={15} strokeWidth={2} />}
          </button>
        </form>

        <p className="mt-4 text-xs" style={{ color: 'var(--color-ink-faint)' }}>
          <Link to="/forgot-password" style={{ color: 'var(--color-blue)' }}>
            Forgot password?
          </Link>
        </p>
      </div>

      <p className="mt-6 text-sm" style={{ color: 'var(--color-ink-muted)' }}>
        No account yet?{' '}
        <Link to="/register" state={{ from: returnTo }} style={{ color: 'var(--color-blue)', fontWeight: 500 }}>
          Create one
        </Link>
      </p>
    </AuthShell>
  )
}
