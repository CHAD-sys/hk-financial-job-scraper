import { useState } from 'react'
import { AlertCircle, LogIn } from 'lucide-react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { AuthShell, AuthField, AuthDivider, GoogleButton } from '../components/AuthShell'
import { loginEmployer, EMPLOYER_GOOGLE_SIGN_IN_PATH } from '../api/client'

type Status = 'idle' | 'sending' | 'error'

const MAX = { email: 200, password: 128 } as const

/**
 * The ?error= codes main.py's /api/employer/auth/google/callback redirects
 * here with — same map shape as SignInPage.tsx's Seeker version, but
 * google_link_refused reads differently: auth.link_or_create_employer()
 * never creates an account, so "refused" here always means "register first."
 */
const GOOGLE_ERROR_MESSAGES: Record<string, string> = {
  google_unavailable: 'Signing in with Google is not switched on yet. Use email and password below.',
  google_failed: 'Something went wrong signing in with Google. Please try again.',
  google_link_refused:
    'No employer account matches that Google address yet. Register your company first, ' +
    'then connect Google from your account.',
}

/** Sign in to an existing Employer account. See EmployerRegisterPage.tsx for
 * why this is not linked from the public UI yet. */
export default function EmployerSignInPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const googleErrorCode = searchParams.get('error')
  const googleError = googleErrorCode ? GOOGLE_ERROR_MESSAGES[googleErrorCode] : undefined
  const [status, setStatus] = useState<Status>(googleError ? 'error' : 'idle')
  const [error, setError] = useState(googleError ?? '')

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
      await loginEmployer(email, password)
      navigate('/post-a-role', { replace: true })
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
      eyebrow="Employer account"
      title="Sign in"
      standfirst="For recruiters and employers posting roles directly. This is separate from a Seeker account."
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
        <AuthDivider />

        <form onSubmit={handleSubmit} noValidate>
          <AuthField label="Work email" htmlFor="es-email">
            <input
              id="es-email" name="email" type="email" required maxLength={MAX.email}
              autoComplete="email" autoFocus className="finex-input"
            />
          </AuthField>

          <div className="mt-5">
            <AuthField label="Password" htmlFor="es-password">
              <input
                id="es-password" name="password" type="password" required maxLength={MAX.password}
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
          <Link to="/employer/forgot-password" style={{ color: 'var(--color-blue)' }}>
            Forgot password?
          </Link>
        </p>
      </div>

      <p className="mt-6 text-sm" style={{ color: 'var(--color-ink-muted)' }}>
        No employer account yet?{' '}
        <Link to="/employer/register" style={{ color: 'var(--color-blue)', fontWeight: 500 }}>
          Create one
        </Link>
      </p>
    </AuthShell>
  )
}
