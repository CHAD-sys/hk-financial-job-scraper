import { useEffect, useState } from 'react'
import { ExternalLink, Loader2 } from 'lucide-react'
import { fetchCapstoneQueue, reviewCapstone, type CapstoneQueueItem } from '../../api/client'

/**
 * Capstone reviews — learners' final projects from the course pages, waiting
 * for written feedback and a score. Unreviewed submissions come first. A
 * learner who resubmits clears the earlier review, so a row reappears here.
 */
export default function CapstoneReviews() {
  const [rows, setRows] = useState<CapstoneQueueItem[] | null>(null)
  const [error, setError] = useState('')
  const [open, setOpen] = useState<string | null>(null)
  const [feedback, setFeedback] = useState('')
  const [score, setScore] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    fetchCapstoneQueue()
      .then(setRows)
      .catch(err => setError(err instanceof Error ? err.message : 'Could not load capstone submissions.'))
  }, [])

  const keyOf = (row: CapstoneQueueItem) => `${row.seeker_id}:${row.course_id}`

  function start(row: CapstoneQueueItem) {
    setOpen(keyOf(row))
    setFeedback(row.feedback ?? '')
    setScore(row.score === null ? '' : String(row.score))
    setError('')
  }

  async function save(row: CapstoneQueueItem) {
    setSaving(true)
    try {
      const saved = await reviewCapstone(row.seeker_id, row.course_id, { feedback: feedback.trim(), score: Number(score) })
      setRows(current => current?.map(r => (keyOf(r) === keyOf(row) ? { ...r, ...saved } : r)) ?? null)
      setOpen(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save the review.')
    } finally {
      setSaving(false)
    }
  }

  const pending = rows?.filter(r => !r.reviewed_at).length ?? 0
  const link = (href: string | null, label: string) =>
    href ? (
      <a href={href} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1" style={{ color: 'var(--color-blue)' }}>
        {label} <ExternalLink size={12} />
      </a>
    ) : null

  return (
    <div className="rounded-lg p-5" style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)', boxShadow: 'var(--shadow-card)' }}>
      <div className="mb-4 flex items-baseline justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-widest" style={{ color: 'var(--color-ink-muted)', letterSpacing: '0.08em' }}>
          Capstone submissions
        </h3>
        {rows && <span className="text-xs" style={{ color: 'var(--color-ink-faint)' }}>{pending} awaiting review</span>}
      </div>
      {error && <p className="mb-3 text-sm" role="alert" style={{ color: 'var(--color-destructive)' }}>{error}</p>}
      {rows === null ? (
        !error && <p className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-ink-faint)' }}><Loader2 size={14} className="animate-spin" /> Loading…</p>
      ) : rows.length === 0 ? (
        <p className="text-sm" style={{ color: 'var(--color-ink-faint)' }}>No capstones submitted yet.</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {rows.map(row => (
            <li key={keyOf(row)} className="rounded-md p-4" style={{ border: '1px solid var(--color-border)', backgroundColor: 'var(--color-surface-2)' }}>
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-sm font-semibold" style={{ color: 'var(--color-ink)' }}>
                  {row.display_name || row.email}{' '}
                  <span style={{ color: 'var(--color-ink-muted)', fontWeight: 400 }}>· {row.email} · {row.course_id}</span>
                </p>
                <span className="text-xs" style={{ color: row.reviewed_at ? 'var(--color-ink-faint)' : 'var(--color-gold)' }}>
                  {row.reviewed_at ? `Reviewed · ${row.score}/100` : 'Awaiting review'} · submitted {new Date(row.submitted_at).toLocaleDateString('en-HK')}
                </span>
              </div>
              <p className="mt-2 flex flex-wrap gap-4 text-xs">
                {link(row.notebook_url, 'Notebook')}
                {link(row.memo_url, 'Memo')}
                {link(row.slides_url, 'Slides')}
              </p>
              {row.note && <p className="mt-2 text-sm" style={{ color: 'var(--color-ink-muted)' }}>“{row.note}”</p>}
              {open === keyOf(row) ? (
                <div className="mt-3 grid gap-2">
                  <label className="grid gap-1 text-xs" style={{ color: 'var(--color-ink-muted)' }}>
                    Written feedback (at least 20 characters)
                    <textarea value={feedback} onChange={e => setFeedback(e.target.value)} rows={5} className="rounded-md px-3 py-2 text-sm" style={{ border: '1px solid var(--color-border)', backgroundColor: 'var(--color-surface)', color: 'var(--color-ink)' }} />
                  </label>
                  <label className="grid w-32 gap-1 text-xs" style={{ color: 'var(--color-ink-muted)' }}>
                    Score (0–100)
                    <input type="number" min={0} max={100} value={score} onChange={e => setScore(e.target.value)} className="rounded-md px-3 py-2 text-sm" style={{ border: '1px solid var(--color-border)', backgroundColor: 'var(--color-surface)', color: 'var(--color-ink)' }} />
                  </label>
                  <div className="flex gap-2">
                    <button type="button" disabled={saving || feedback.trim().length < 20 || score === ''} onClick={() => save(row)} className="cursor-pointer rounded-md px-3 py-1.5 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50" style={{ backgroundColor: 'var(--color-gold)', color: '#1F1300', border: 'none' }}>
                      {saving ? 'Saving…' : 'Send feedback'}
                    </button>
                    <button type="button" onClick={() => setOpen(null)} className="cursor-pointer rounded-md px-3 py-1.5 text-xs" style={{ border: '1px solid var(--color-border)', background: 'none', color: 'var(--color-ink-muted)' }}>
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <button type="button" onClick={() => start(row)} className="mt-3 cursor-pointer rounded-md px-3 py-1.5 text-xs font-semibold" style={{ border: '1px solid var(--color-border)', background: 'none', color: 'var(--color-ink)' }}>
                  {row.reviewed_at ? 'Edit review' : 'Write review'}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
