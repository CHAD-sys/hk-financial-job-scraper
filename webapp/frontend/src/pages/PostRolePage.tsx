import { useState } from 'react'
import { Check, AlertCircle, ShieldCheck, Send } from 'lucide-react'
import Nav from '../components/Nav'
import { submitRole } from '../api/client'

type Status = 'idle' | 'sending' | 'sent' | 'error'

const EMPLOYMENT_TYPES = ['Full-time', 'Contract', 'Part-time', 'Internship'] as const

const MAX = {
  contact_name: 100,
  contact_email: 200,
  company: 150,
  title: 200,
  location: 120,
  salary_range: 100,
  apply_url: 500,
  description: 20000,
} as const

/**
 * Direct role submission for recruiters and employers.
 *
 * This is deliberately NOT the Recruiter Posts tier on the board — that tier is
 * LinkedIn posts we scrape. This is the first route by which a recruiter can put
 * a mandate to us directly.
 *
 * Scope is submission + moderation only. There are no employer accounts, no
 * self-serve editing and no billing; a submission lands pending review and a
 * human approves it before it can appear anywhere. Self-serve and paid inventory
 * are a separate, much larger piece of work.
 */
export default function PostRolePage() {
  const [status, setStatus] = useState<Status>('idle')
  const [error, setError] = useState('')

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (status === 'sending') return

    const d = new FormData(e.currentTarget)
    const str = (k: string) => String(d.get(k) ?? '').trim()

    setStatus('sending')
    setError('')
    try {
      await submitRole({
        contact_name: str('contact_name'),
        contact_email: str('contact_email'),
        company: str('company'),
        title: str('title'),
        location: str('location'),
        employment_type: str('employment_type'),
        salary_range: str('salary_range'),
        description: str('description'),
        apply_url: str('apply_url'),
        website: String(d.get('website') ?? ''),
      })
      setStatus('sent')
      window.scrollTo({ top: 0, behavior: 'smooth' })
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
    <div style={{ backgroundColor: 'var(--color-bg)', minHeight: '100dvh' }}>
      <Nav />
      <main id="main-content" className="mx-auto max-w-3xl px-6 py-14 lg:px-8">
        <span
          className="text-xs font-semibold uppercase"
          style={{ color: 'var(--color-gold)', letterSpacing: '0.14em' }}
        >
          For recruiters &amp; employers
        </span>
        <h1
          className="mt-3 text-3xl lg:text-4xl tracking-tight"
          style={{ fontFamily: 'var(--font-display)', fontWeight: 700, color: 'var(--color-ink)', letterSpacing: '-0.025em' }}
        >
          Post a role
        </h1>
        <p className="mt-4 text-base leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>
          Put a mandate in front of Hong Kong's finance community directly, rather than
          waiting for us to find it. Submissions are reviewed by a person before they appear
          on the board.
        </p>

        {status === 'sent' ? (
          <div
            className="mt-10 rounded-xl p-8 text-center"
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
              <Check size={24} strokeWidth={2.2} style={{ color: 'var(--color-gold)' }} />
            </span>
            <h2
              className="mt-4 text-xl tracking-tight"
              style={{ fontFamily: 'var(--font-display)', fontWeight: 700, color: 'var(--color-ink)' }}
            >
              Role submitted for review
            </h2>
            <p className="mt-2 text-sm" style={{ color: 'var(--color-ink-muted)' }}>
              Thank you. We'll review it and come back to you at the address you gave.
              It won't appear on the board until it has been approved.
            </p>
          </div>
        ) : (
          <>
            <div
              className="mt-8 flex items-start gap-3 rounded-lg p-4"
              style={{ backgroundColor: 'var(--color-gold-light)', border: '1px solid var(--color-gold)' }}
            >
              <ShieldCheck size={18} strokeWidth={2} className="mt-0.5 shrink-0" style={{ color: 'var(--color-gold)' }} />
              <p className="text-sm" style={{ color: 'var(--color-ink)' }}>
                <strong>Nothing publishes automatically.</strong> Every submission is read and
                approved by a person first, so the board stays worth reading.
              </p>
            </div>

            <form
              onSubmit={handleSubmit}
              noValidate
              className="mt-8 rounded-xl p-6 lg:p-8"
              style={{
                backgroundColor: 'var(--color-surface)',
                border: '1px solid var(--color-border)',
                boxShadow: 'var(--shadow-card)',
              }}
            >
              <Legend>About the role</Legend>

              <div className="grid gap-5 sm:grid-cols-2">
                <Field label="Job title" htmlFor="pr-title">
                  <input id="pr-title" name="title" type="text" required maxLength={MAX.title} className="finex-input" />
                </Field>
                <Field label="Company" htmlFor="pr-company">
                  <input id="pr-company" name="company" type="text" required maxLength={MAX.company} className="finex-input" />
                </Field>
                <Field label="Location" htmlFor="pr-location">
                  <input
                    id="pr-location" name="location" type="text" required
                    maxLength={MAX.location} placeholder="Hong Kong" className="finex-input"
                  />
                </Field>
                <Field label="Employment type" htmlFor="pr-type">
                  <select id="pr-type" name="employment_type" required defaultValue="" className="finex-input">
                    <option value="" disabled>Select…</option>
                    {EMPLOYMENT_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                  </select>
                </Field>
              </div>

              <div className="mt-5">
                <Field label="Salary range" htmlFor="pr-salary" hint="Optional, but roles with a range get materially more interest.">
                  <input
                    id="pr-salary" name="salary_range" type="text" maxLength={MAX.salary_range}
                    placeholder="e.g. HKD 80,000 – 110,000 / month" className="finex-input"
                  />
                </Field>
              </div>

              <div className="mt-5">
                <Field label="Role description" htmlFor="pr-desc">
                  <textarea
                    id="pr-desc" name="description" required rows={10} maxLength={MAX.description}
                    className="finex-input" style={{ resize: 'vertical' }}
                    placeholder="Responsibilities, requirements, team and reporting line."
                  />
                </Field>
              </div>

              <div className="mt-5">
                <Field label="Application link" htmlFor="pr-url" hint="Where candidates should apply. Must start with https://">
                  <input
                    id="pr-url" name="apply_url" type="url" required maxLength={MAX.apply_url}
                    placeholder="https://" className="finex-input"
                  />
                </Field>
              </div>

              <Legend className="mt-9">Your details</Legend>

              <div className="grid gap-5 sm:grid-cols-2">
                <Field label="Your name" htmlFor="pr-name">
                  <input
                    id="pr-name" name="contact_name" type="text" required
                    maxLength={MAX.contact_name} autoComplete="name" className="finex-input"
                  />
                </Field>
                <Field label="Your email" htmlFor="pr-email" hint="We reply here. Never published.">
                  <input
                    id="pr-email" name="contact_email" type="email" required
                    maxLength={MAX.contact_email} autoComplete="email" className="finex-input"
                  />
                </Field>
              </div>

              <div aria-hidden="true" className="honeypot">
                <label htmlFor="pr-website">Website</label>
                <input id="pr-website" name="website" type="text" tabIndex={-1} autoComplete="off" />
              </div>

              {status === 'error' && (
                <p
                  className="mt-6 flex items-start gap-2 text-sm"
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
                className="mt-7 inline-flex w-full items-center justify-center gap-2 rounded px-6 py-3 text-sm font-semibold sm:w-auto"
                style={{
                  backgroundColor: 'var(--color-ink)',
                  color: 'var(--color-ink-inverse)',
                  cursor: status === 'sending' ? 'wait' : 'pointer',
                  opacity: status === 'sending' ? 0.7 : 1,
                }}
              >
                {status === 'sending' ? 'Submitting…' : 'Submit for review'}
                {status !== 'sending' && <Send size={15} strokeWidth={2} />}
              </button>
            </form>
          </>
        )}
      </main>
    </div>
  )
}

function Legend({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <h2
      className={`mb-5 pb-2 text-xs font-semibold uppercase ${className}`}
      style={{
        color: 'var(--color-ink-faint)',
        letterSpacing: '0.14em',
        borderBottom: '1px solid var(--color-border)',
      }}
    >
      {children}
    </h2>
  )
}

function Field({
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
