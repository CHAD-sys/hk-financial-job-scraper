import { useState } from 'react'
import { AlertCircle, LogIn } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { AuthShell, AuthField } from '../components/AuthShell'
import { loginEmployer } from '../api/client'

type Status = 'idle' | 'sending' | 'error'

const MAX = { email: 200, password: 128 } as const

/** Sign in to an existing Employer account. See EmployerRegisterPage.tsx for
 * why this is not linked from the public UI yet. */
export default function EmployerSignInPage() {
  const navigate = useNavigate()
  const [status, setStatus] = useState<Status>('idle')
  const [error, setError] = useState('')

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
