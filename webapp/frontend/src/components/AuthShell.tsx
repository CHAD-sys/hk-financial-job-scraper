import Nav from './Nav'
import { GOOGLE_SIGN_IN_PATH } from '../api/client'

/**
 * The frame the three account screens share: nav, a narrow centred column, an
 * eyebrow / title / standfirst, then whatever the page puts in the card.
 *
 * Deliberately narrow (max-w-md). These pages ask for two or three fields and
 * nothing else — an account here unlocks durable Saved Roles and no more, so
 * the page should not look like it is asking for a commitment.
 */
export function AuthShell({
  eyebrow, title, standfirst, children,
}: {
  eyebrow: string
  title: string
  standfirst?: React.ReactNode
  children: React.ReactNode
}) {

  return (
    <div style={{ backgroundColor: 'var(--color-bg)', minHeight: '100dvh' }}>
      <Nav />
      <main id="main-content" className="mx-auto max-w-md px-6 py-14 lg:py-20">
        <span
          className="text-xs font-semibold uppercase"
          style={{ color: 'var(--color-gold)', letterSpacing: '0.14em' }}
        >
          {eyebrow}
        </span>
        <h1
          className="mt-3 text-3xl tracking-tight"
          style={{
            fontFamily: 'var(--font-display)',
            fontWeight: 700,
            color: 'var(--color-ink)',
            letterSpacing: '-0.025em',
          }}
        >
          {title}
        </h1>
        {standfirst && (
          <p className="mt-4 text-sm leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>
            {standfirst}
          </p>
        )}
        {children}
      </main>
    </div>
  )
}

/** Label + control + optional hint. Mirrors the Field in EnquiryForm/PostRolePage. */
export function AuthField({
  label, htmlFor, hint, children,
}: { label: string; htmlFor: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <label
        htmlFor={htmlFor}
        className="mb-1.5 block text-xs font-semibold uppercase"
        style={{ color: 'var(--color-ink-muted)', letterSpacing: '0.1em' }}
      >
        {label}
      </label>
      {children}
      {hint && (
        <p className="mt-1.5 text-xs" style={{ color: 'var(--color-ink-faint)' }}>{hint}</p>
      )}
    </div>
  )
}

/**
 * "Continue with Google".
 *
 * A plain <a>, not a fetch: the backend answers with a redirect to Google's
 * consent screen, and a full page navigation is the only thing that can follow
 * it. Google is the only third-party provider — LinkedIn is a deliberate
 * fast-follow, not a v1 button (docs/adr/0003).
 *
 * `href` defaults to the Seeker path; the Employer pages pass
 * EMPLOYER_GOOGLE_SIGN_IN_PATH explicitly — a separate registered redirect
 * URI on Google's side, not just a separate frontend route (see main.py's
 * Employer Google section for why one callback branching on account type
 * was rejected in favour of two).
 */
export function GoogleButton({ label, href = GOOGLE_SIGN_IN_PATH }: { label: string; href?: string }) {
  return (
    <a
      href={href}
      className="flex min-h-11 w-full items-center justify-center gap-2.5 rounded px-6 py-3 text-sm font-semibold no-underline"
      style={{
        backgroundColor: 'var(--color-surface)',
        color: 'var(--color-ink)',
        border: '1px solid var(--color-border-strong)',
      }}
    >
      <GoogleMark />
      {label}
    </a>
  )
}

/**
 * Google's four-colour G. The literal hex values here are the one sanctioned
 * exception to "no raw hex in components" (DESIGN.md) — they are another
 * company's trademark, not our palette, and must not shift with our tokens.
 */
function GoogleMark() {
  return (
    <svg width="16" height="16" viewBox="0 0 48 48" aria-hidden="true" focusable="false">
      <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.6l6.7-6.7C35.6 2.6 30.2 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.8 6.1C12.3 13.2 17.6 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.9 24.5c0-1.6-.1-3.2-.4-4.7H24v9h12.9c-.6 3-2.3 5.5-4.8 7.2l7.5 5.8c4.4-4.1 6.9-10.1 6.9-17.3z" />
      <path fill="#FBBC05" d="M10.4 28.7c-.5-1.5-.8-3-.8-4.7s.3-3.2.8-4.7l-7.8-6.1C1 16.3 0 20 0 24s1 7.7 2.6 10.8l7.8-6.1z" />
      <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.5-5.8c-2.1 1.4-4.8 2.2-8.4 2.2-6.4 0-11.7-3.7-13.6-9.9l-7.8 6.1C6.5 42.6 14.6 48 24 48z" />
    </svg>
  )
}

/** The "or" rule between the Google button and the email form. */
export function AuthDivider() {
  return (
    <div className="my-6 flex items-center gap-3" aria-hidden="true">
      <span className="h-px flex-1" style={{ backgroundColor: 'var(--color-border)' }} />
      <span className="text-xs uppercase" style={{ color: 'var(--color-ink-faint)', letterSpacing: '0.14em' }}>
        or
      </span>
      <span className="h-px flex-1" style={{ backgroundColor: 'var(--color-border)' }} />
    </div>
  )
}
