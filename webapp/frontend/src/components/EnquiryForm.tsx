import { useState } from 'react'
import { Send, Check, AlertCircle } from 'lucide-react'
import { submitEnquiry, CAREER_STAGES } from '../api/client'

type Status = 'idle' | 'sending' | 'sent' | 'error'

const MAX = { name: 100, email: 200, message: 5000 } as const

/**
 * Executive Career Consultation enquiry form.
 *
 * Four visible fields plus a hidden honeypot. The honeypot ("website") is
 * positioned off-screen rather than display:none — some bots skip hidden inputs
 * but fill positioned ones. A bot that fills it gets a normal-looking success
 * response and no email is sent; telling it that it failed only helps it adapt.
 */
export default function EnquiryForm() {
  const [status, setStatus] = useState<Status>('idle')
  const [error, setError] = useState('')

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (status === 'sending') return

    const data = new FormData(e.currentTarget)
    setStatus('sending')
    setError('')

    try {
      await submitEnquiry({
        name: String(data.get('name') ?? '').trim(),
        email: String(data.get('email') ?? '').trim(),
        career_stage: String(data.get('career_stage') ?? ''),
        message: String(data.get('message') ?? '').trim(),
        website: String(data.get('website') ?? ''),
      })
      setStatus('sent')
    } catch (err) {
      setStatus('error')
      setError(
        err instanceof Error && err.message
          ? err.message
          : 'Something went wrong. Please try again, or email us directly.',
      )
    }
  }

  if (status === 'sent') {
    return (
      <div
        className="rounded-xl p-8 text-center"
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
        <h4
          className="mt-4 text-xl tracking-tight"
          style={{ fontFamily: 'var(--font-display)', fontWeight: 700, color: 'var(--color-ink)' }}
        >
          Enquiry received
        </h4>
        <p className="mt-2 text-sm" style={{ color: 'var(--color-ink-muted)' }}>
          Thank you. We read every enquiry personally and will come back to you shortly.
        </p>
      </div>
    )
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-xl p-6 lg:p-8"
      style={{
        backgroundColor: 'var(--color-surface)',
        border: '1px solid var(--color-border)',
        boxShadow: 'var(--shadow-card)',
      }}
      noValidate
    >
      <div className="grid gap-5 sm:grid-cols-2">
        <Field label="Name" htmlFor="ec-name">
          <input
            id="ec-name" name="name" type="text" required maxLength={MAX.name}
            autoComplete="name" className="finex-input"
          />
        </Field>

        <Field label="Email" htmlFor="ec-email">
          <input
            id="ec-email" name="email" type="email" required maxLength={MAX.email}
            autoComplete="email" className="finex-input"
          />
        </Field>
      </div>

      <div className="mt-5">
        <Field label="Career stage" htmlFor="ec-stage">
          <select id="ec-stage" name="career_stage" required defaultValue="" className="finex-input">
            <option value="" disabled>Select…</option>
            {CAREER_STAGES.map(s => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </Field>
      </div>

      <div className="mt-5">
        <Field label="What would you like help with?" htmlFor="ec-message">
          <textarea
            id="ec-message" name="message" required rows={5} maxLength={MAX.message}
            className="finex-input" style={{ resize: 'vertical' }}
          />
        </Field>
      </div>

      {/* Honeypot — never shown to a human, never focusable. */}
      <div aria-hidden="true" className="honeypot">
        <label htmlFor="ec-website">Website</label>
        <input id="ec-website" name="website" type="text" tabIndex={-1} autoComplete="off" />
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
        className="mt-6 inline-flex w-full items-center justify-center gap-2 rounded px-6 py-3 text-sm font-semibold sm:w-auto"
        style={{
          backgroundColor: 'var(--color-ink)',
          color: 'var(--color-ink-inverse)',
          cursor: status === 'sending' ? 'wait' : 'pointer',
          opacity: status === 'sending' ? 0.7 : 1,
        }}
      >
        {status === 'sending' ? 'Sending…' : 'Send enquiry'}
        {status !== 'sending' && <Send size={15} strokeWidth={2} />}
      </button>

      <p className="mt-3 text-xs" style={{ color: 'var(--color-ink-faint)' }}>
        Your enquiry goes straight to us. We don't add you to a mailing list.
      </p>
    </form>
  )
}

function Field({ label, htmlFor, children }: { label: string; htmlFor: string; children: React.ReactNode }) {
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
    </div>
  )
}
