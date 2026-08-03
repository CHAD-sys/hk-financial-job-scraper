import { Clock } from 'lucide-react'
import { Link } from 'react-router-dom'
import { AuthShell } from '../components/AuthShell'

/**
 * A stub, on purpose.
 *
 * Password reset needs outbound email, which is a separate piece of work
 * (PLAN_ACCOUNTS phase 3 — Resend plus DNS records that are still propagating).
 * The link exists on the sign-in page because people look for it there and a
 * missing link reads as a broken product; this page then says plainly that the
 * flow is not ready rather than pretending to send anything.
 */
export default function ForgotPasswordPage() {
  return (
    <AuthShell eyebrow="Seeker account" title="Password reset">
      <div
        className="mt-8 rounded-xl p-6 lg:p-8"
        style={{
          backgroundColor: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          boxShadow: 'var(--shadow-card)',
        }}
      >
        <span
          className="flex h-10 w-10 items-center justify-center rounded-full"
          style={{ backgroundColor: 'var(--color-gold-light)' }}
        >
          <Clock size={20} strokeWidth={2} style={{ color: 'var(--color-gold)' }} />
        </span>
        <p className="mt-4 text-sm leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>
          Resetting a password by email is not switched on yet — we are still finishing our
          email set-up. It is coming shortly.
        </p>
        <p className="mt-3 text-sm leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>
          In the meantime, if you signed up with a Google address you can use{' '}
          <strong style={{ color: 'var(--color-ink)' }}>Continue with Google</strong> on the sign-in
          page, which needs no password at all. Otherwise, get in touch and we will sort it out
          with you.
        </p>

        <div className="mt-6 flex flex-wrap gap-3">
          <Link
            to="/signin"
            className="inline-flex min-h-11 items-center justify-center rounded px-5 py-2.5 text-sm font-semibold no-underline"
            style={{ backgroundColor: 'var(--color-ink)', color: 'var(--color-ink-inverse)' }}
          >
            Back to sign in
          </Link>
          <Link
            to="/#consultation"
            className="inline-flex min-h-11 items-center justify-center rounded px-5 py-2.5 text-sm font-semibold no-underline"
            style={{
              backgroundColor: 'var(--color-surface)',
              color: 'var(--color-ink)',
              border: '1px solid var(--color-border-strong)',
            }}
          >
            Get in touch
          </Link>
        </div>
      </div>
    </AuthShell>
  )
}
