import { useEffect, useState } from 'react'
import { CheckCircle2, ExternalLink, Loader2, XCircle } from 'lucide-react'
import {
  approveSubmission, fetchAdminSubmissions, rejectSubmission,
  type AdminSubmission,
} from '../../api/client'

type RowState = 'idle' | 'approving' | 'rejecting' | 'error'

/**
 * Verification — validating recruiters' job-post submissions (/api/post-role)
 * from the browser instead of `python scripts/review_submissions.py` over SSH.
 *
 * Approving calls the exact same webapp/backend/submissions.py code path the
 * CLI script now delegates to — there is one definition of "how a submission
 * becomes a board row," this panel and the script are just two front ends
 * onto it.
 */
export default function SubmissionsPanel() {
  const [rows, setRows] = useState<AdminSubmission[] | null>(null)
  const [error, setError] = useState('')
  const [rowState, setRowState] = useState<Record<string, RowState>>({})
  const [rejecting, setRejecting] = useState<string | null>(null)
  const [reason, setReason] = useState('')

  async function load() {
    try {
      setRows(await fetchAdminSubmissions('pending'))
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load submissions.')
    }
  }

  useEffect(() => { load() }, [])

  async function handleApprove(id: string) {
    setRowState(s => ({ ...s, [id]: 'approving' }))
    try {
      await approveSubmission(id)
      setRows(r => r?.filter(row => row.id !== id) ?? null)
    } catch (err) {
      setRowState(s => ({ ...s, [id]: 'error' }))
      setError(err instanceof Error ? err.message : 'Could not approve that submission.')
    }
  }

  async function handleReject(id: string) {
    setRowState(s => ({ ...s, [id]: 'rejecting' }))
    try {
      await rejectSubmission(id, reason.trim())
      setRows(r => r?.filter(row => row.id !== id) ?? null)
      setRejecting(null)
      setReason('')
    } catch (err) {
      setRowState(s => ({ ...s, [id]: 'error' }))
      setError(err instanceof Error ? err.message : 'Could not reject that submission.')
    }
  }

  return (
    <div
      className="rounded-lg p-5"
      style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)', boxShadow: 'var(--shadow-card)' }}
    >
      <div className="flex items-baseline justify-between mb-4">
        <h3
          className="text-xs font-semibold uppercase tracking-widest"
          style={{ color: 'var(--color-ink-muted)', letterSpacing: '0.08em' }}
        >
          Pending submissions
        </h3>
        {rows && (
          <span className="text-xs" style={{ color: 'var(--color-ink-faint)' }}>
            {rows.length} pending
          </span>
        )}
      </div>

      {error && (
        <p className="text-sm mb-3" style={{ color: 'var(--color-destructive)' }}>{error}</p>
      )}

      {rows === null ? (
        <p className="text-sm flex items-center gap-2" style={{ color: 'var(--color-ink-faint)' }}>
          <Loader2 size={14} className="animate-spin" /> Loading…
        </p>
      ) : rows.length === 0 ? (
        <p className="text-sm" style={{ color: 'var(--color-ink-faint)' }}>
          Nothing waiting on review.
        </p>
      ) : (
        <ul className="flex flex-col gap-3">
          {rows.map(row => {
            const state = rowState[row.id] ?? 'idle'
            const busy = state === 'approving' || state === 'rejecting'
            return (
              <li
                key={row.id}
                className="rounded-md p-4"
                style={{ border: '1px solid var(--color-border)', backgroundColor: 'var(--color-surface-2)' }}
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <div>
                    <p className="font-semibold text-sm" style={{ color: 'var(--color-ink)' }}>
                      {row.title} <span style={{ color: 'var(--color-ink-muted)', fontWeight: 400 }}>@ {row.company}</span>
                    </p>
                    <p className="text-xs mt-0.5" style={{ color: 'var(--color-ink-faint)' }}>
                      {row.location} · {row.employment_type}
                      {row.salary_range ? ` · ${row.salary_range}` : ''} · submitted by {row.contact_name} ({row.contact_email})
                    </p>
                  </div>
                  <a
                    href={row.apply_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs inline-flex items-center gap-1 shrink-0"
                    style={{ color: 'var(--color-blue)' }}
                  >
                    Apply link <ExternalLink size={12} />
                  </a>
                </div>

                <p className="text-sm mt-2 line-clamp-3" style={{ color: 'var(--color-ink-muted)' }}>
                  {row.description}
                </p>

                {rejecting === row.id ? (
                  <div className="mt-3 flex items-center gap-2">
                    <label htmlFor={`reject-reason-${row.id}`} className="sr-only">
                      Reason for rejecting this submission
                    </label>
                    <input
                      id={`reject-reason-${row.id}`}
                      autoFocus
                      className="finex-input flex-1 text-sm"
                      placeholder="Reason (optional)"
                      value={reason}
                      onChange={e => setReason(e.target.value)}
                    />
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => handleReject(row.id)}
                      className="text-xs font-semibold px-3 py-2 rounded"
                      style={{ backgroundColor: 'var(--color-destructive)', color: 'white', opacity: busy ? 0.6 : 1 }}
                    >
                      {state === 'rejecting' ? 'Rejecting…' : 'Confirm reject'}
                    </button>
                    <button
                      type="button"
                      onClick={() => { setRejecting(null); setReason('') }}
                      className="text-xs px-2 py-2"
                      style={{ color: 'var(--color-ink-faint)' }}
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <div className="mt-3 flex items-center gap-2">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => handleApprove(row.id)}
                      className="text-xs font-semibold inline-flex items-center gap-1.5 px-3 py-2 rounded"
                      style={{ backgroundColor: '#15803D', color: 'white', opacity: busy ? 0.6 : 1 }}
                    >
                      <CheckCircle2 size={13} /> {state === 'approving' ? 'Publishing…' : 'Approve & publish'}
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => setRejecting(row.id)}
                      className="text-xs font-semibold inline-flex items-center gap-1.5 px-3 py-2 rounded"
                      style={{ border: '1px solid var(--color-border-strong)', color: 'var(--color-ink-muted)', opacity: busy ? 0.6 : 1 }}
                    >
                      <XCircle size={13} /> Reject
                    </button>
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
