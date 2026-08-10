import { useState } from 'react'
import { AlertCircle, LogIn } from 'lucide-react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { AuthShell, AuthField, AuthDivider, GoogleButton, LinkedInButton } from '../components/AuthShell'
import { useAuth } from '../auth/useAuth'
import { useReturnTo } from '../auth/useReturnTo'

type Status = 'idle' | 'sending' | 'error'

const MAX = { email: 200, password: 128 } as const

/**
 * The ?error= codes main.py's /api/auth/google/callback and
 * /api/auth/linkedin/callback redirect here with, turned into something a
 * Seeker can act on. Anything not in this map (or absent) shows nothing — an
 * unrecognised code is not a licence to guess.
 */
const OAUTH_ERROR_MESSAGES: Record<string, string> = {
  google_unavailable: 'Signing in with Google is not switched on yet. Use email and password below.',
  google_failed: 'Something went wrong signing in with Google. Please try again.',
  google_link_refused:
    'That Google address already has an account here, but Google did not confirm it is verified. ' +
    'Sign in with your password instead, or use "Forgot password?" if you never set one.',
  linkedin_unavailable: 'Signing in with LinkedIn is not switched on yet. Use email and password below.',
  linkedin_failed: 'Something went wrong signing in with LinkedIn. Please try again.',
  linkedin_link_refused:
    'That LinkedIn address already has an account here, but LinkedIn did not confirm it is verified. ' +
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
  const oauthErrorCode = searchParams.get('error')
  const oauthError = oauthErrorCode ? OAUTH_ERROR_MESSAGES[oauthErrorCode] : undefined
  const [status, setStatus] = useState<Status>(oauthError ? 'error' : 'idle')
  const [error, setError] = useState(oauthError ?? '')

  // Already signed in: this page has nothing to offer. An admin goes to the
  // chooser, not straight to /admin — ModeChooserPage.tsx is what asks "which
  // view do you want", every time, rather than assuming last time's answer.
  if (!authLoading && seeker) {
    return <Navigate to={seeker.is_admin ? '/choose-view' : returnTo} state={{ from: returnTo }} replace />
  }

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (status === 'sending') return

    const d = new FormData(e.currentTarget)
    const email = String(d.get('email') ?? '').trim()
    const password = String(d.get('password') ?? '')

    if (!email || !password) {
      setStatus('error')
      setError('Enter your email (or username) and password.')
      return
    }

    setStatus('sending')
    setError('')
    try {
      const me = await login(email, password)
      // Admin Mode is the same sign-in, so the branch happens here rather than
      // at the route level. An admin is ASKED which view they want — every
      // sign-in, not just the first — rather than being dropped straight into
      // /admin on an assumption. ModeChooserPage carries returnTo forward for
      // whichever answer they give.
      navigate(me?.is_admin ? '/choose-view' : returnTo, {
        replace: true,
        state: { from: returnTo },
      })
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
          Sign in to manage your private resume, see strong experience matches, and keep
          Saved Roles across devices. The board stays free and open — you never need an
          account to read a Role.
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
          {/* type="text", not "email": Admin Mode's accounts sign in with a
              plain username (seekers_store.migrate_to_phase_3), and a browser
              enforces email-shaped input client-side on type="email" — it
              would block "kenson" before this form ever saw it. autoComplete
              "username" is the correct token for a login field either way per
              the WHATWG autofill spec; "email" is for account-creation forms. */}
          <AuthField label="Email or username" htmlFor="si-email">
            <input
              id="si-email" name="email" type="text" required maxLength={MAX.email}
              autoComplete="username" className="finex-input"
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
