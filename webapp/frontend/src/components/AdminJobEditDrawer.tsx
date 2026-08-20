import { useEffect, useRef, useState } from 'react'
import { AlertCircle, Check, Loader2, Pin, X } from 'lucide-react'
import {
  fetchAdminJob, patchAdminJob,
  type AdminJobRecord, type Job,
} from '../api/client'
import { formatEstimatedSalary, formatSalary } from '../utils/format'

/**
 * In-place correction of one posting, opened from the pencil on its card.
 *
 * WHY THIS EXISTS SEPARATELY FROM THE ADMIN PAGE'S <JobEditor>
 * -----------------------------------------------------------
 * They call the same two endpoints and enforce the same allowlist. What differs
 * is where the admin already is. JobEditor is a destination: you go to /admin,
 * you search for a posting by title, you pick it out of results, you edit it.
 * That is the right shape for "I have a list of corrections to work through".
 *
 * It is the wrong shape for the way a wrong salary is actually noticed — while
 * browsing the board, on a card, mid-scroll. Making that admin retype the title
 * into a different page's search box to fix what is already on screen is the
 * step this drawer removes. Same power, different entry point.
 *
 * TWO THINGS TO KNOW ABOUT THE WRITE
 * ----------------------------------
 * 1. Saving PINS the row (`job_enrichments.manually_edited_at`). Re-enrichment
 *    and the nightly salary audit both skip a pinned row unconditionally, so a
 *    correction made here survives every future pipeline run. That is the point
 *    — but it also means a careless edit is permanent until someone edits it
 *    again, which is why the drawer says so above the Save button rather than
 *    burying it.
 * 2. Every changed field is logged to `admin_edits` against the signed-in
 *    admin's own id. Widening this from Ultimate Admin to every admin
 *    (2026-08-20) rests on that log already existing.
 */

interface Props {
  job: Job
  onClose: () => void
  /** The saved record, so the board can repaint the card without a refetch. */
  onSaved?: (record: AdminJobRecord) => void
}

const SENIORITY = ['', 'intern', 'junior', 'mid', 'senior', 'lead', 'executive']
const REMOTE_TYPES = ['', 'onsite', 'hybrid', 'remote']
const EMPLOYMENT_TYPES = ['', 'Full-time', 'Contract', 'Part-time', 'Internship']
const CONFIDENCE = ['', 'high', 'medium', 'low']

/** Every field this drawer can write, flattened. `e_` = the job_enrichments side. */
interface FormState {
  // jobs
  title: string
  company: string
  employment_type: string
  seniority: string
  remote_type: string
  category: string
  salary_min: string
  salary_max: string
  salary_currency: string
  is_active: boolean
  // job_enrichments
  e_seniority: string
  e_remote_type: string
  job_category: string
  salary_estimated_min: string
  salary_estimated_max: string
  salary_estimated_confidence: string
  years_experience_required: string
  description_summary: string
}

const JOB_KEYS = [
  'title', 'company', 'employment_type', 'seniority', 'remote_type',
  'category', 'salary_min', 'salary_max', 'salary_currency', 'is_active',
] as const

const ENRICHMENT_KEYS = [
  'e_seniority', 'e_remote_type', 'job_category', 'salary_estimated_min',
  'salary_estimated_max', 'salary_estimated_confidence',
  'years_experience_required', 'description_summary',
] as const

/** Wire names differ from form names only where the two tables collide. */
const ENRICHMENT_WIRE_NAME: Record<string, string> = {
  e_seniority: 'seniority',
  e_remote_type: 'remote_type',
}

const NUMERIC = new Set([
  'salary_min', 'salary_max', 'salary_estimated_min', 'salary_estimated_max',
  'years_experience_required',
])

function toForm(rec: AdminJobRecord): FormState {
  const str = (v: string | number | null | undefined) => (v === null || v === undefined ? '' : String(v))
  return {
    title: str(rec.title),
    company: str(rec.company),
    employment_type: str(rec.employment_type),
    seniority: str(rec.seniority),
    remote_type: str(rec.remote_type),
    category: str(rec.category),
    salary_min: str(rec.salary_min),
    salary_max: str(rec.salary_max),
    salary_currency: str(rec.salary_currency),
    is_active: !!rec.is_active,
    e_seniority: str(rec.e_seniority),
    e_remote_type: str(rec.e_remote_type),
    job_category: str(rec.job_category),
    salary_estimated_min: str(rec.salary_estimated_min),
    salary_estimated_max: str(rec.salary_estimated_max),
    salary_estimated_confidence: str(rec.salary_estimated_confidence),
    years_experience_required: str(rec.years_experience_required),
    description_summary: str(rec.description_summary),
  }
}

/** '' clears the column (null); anything numeric is sent as a number. */
function toWire(key: string, raw: string | boolean): unknown {
  if (typeof raw === 'boolean') return raw
  if (raw.trim() === '') return null
  return NUMERIC.has(key) ? Number(raw) : raw
}

export default function AdminJobEditDrawer({ job, onClose, onSaved }: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const [record, setRecord] = useState<AdminJobRecord | null>(null)
  const [form, setForm] = useState<FormState | null>(null)
  const [baseline, setBaseline] = useState<FormState | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [savedAt, setSavedAt] = useState(0)

  // Same enter/exit state machine as .job-detail-dialog — see JobDetailModal.
  const [visualState, setVisualState] = useState<'entering' | 'entered' | 'closing'>('entering')
  const closingRef = useRef(false)

  const requestClose = () => {
    if (closingRef.current) return
    closingRef.current = true
    setVisualState('closing')
    window.setTimeout(onClose, 200)
  }

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetchAdminJob(job.source, job.source_id)
      .then(rec => {
        if (cancelled) return
        setRecord(rec)
        setForm(toForm(rec))
        setBaseline(toForm(rec))
      })
      .catch(err => {
        if (!cancelled) setLoadError(err instanceof Error ? err.message : 'Could not load this posting.')
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [job.source, job.source_id])

  useEffect(() => {
    const dlg = dialogRef.current
    if (!dlg) return
    dlg.showModal()
    const rafIds: number[] = []
    rafIds.push(requestAnimationFrame(() => {
      rafIds.push(requestAnimationFrame(() => setVisualState('entered')))
    }))
    const onBackdropClick = (e: MouseEvent) => { if (e.target === dlg) requestClose() }
    const onCancel = (e: Event) => { e.preventDefault(); requestClose() }
    dlg.addEventListener('click', onBackdropClick)
    dlg.addEventListener('cancel', onCancel)
    return () => {
      rafIds.forEach(cancelAnimationFrame)
      dlg.removeEventListener('click', onBackdropClick)
      dlg.removeEventListener('cancel', onCancel)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = '' }
  }, [])

  const set = (patch: Partial<FormState>) => {
    setForm(prev => (prev ? { ...prev, ...patch } : prev))
    setSavedAt(0)
    setSaveError('')
  }

  // Only genuinely-changed fields go on the wire. The backend diffs again and
  // would drop the rest anyway — but sending the whole form means an admin who
  // opened the drawer and changed one number cannot be shown, in the audit log,
  // as having "edited" seventeen fields.
  const dirtyKeys = form && baseline
    ? ([...JOB_KEYS, ...ENRICHMENT_KEYS] as readonly string[]).filter(
        k => form[k as keyof FormState] !== baseline[k as keyof FormState],
      )
    : []

  async function handleSave() {
    if (!form || dirtyKeys.length === 0) return
    setSaving(true)
    setSaveError('')
    const jobChanges: Record<string, unknown> = {}
    const enrichmentChanges: Record<string, unknown> = {}
    for (const key of dirtyKeys) {
      const value = toWire(key, form[key as keyof FormState])
      if ((JOB_KEYS as readonly string[]).includes(key)) jobChanges[key] = value
      else enrichmentChanges[ENRICHMENT_WIRE_NAME[key] ?? key] = value
    }
    try {
      const updated = await patchAdminJob(job.source, job.source_id, {
        job: jobChanges,
        enrichment: enrichmentChanges,
      })
      setRecord(updated)
      setForm(toForm(updated))
      setBaseline(toForm(updated))
      setSavedAt(Date.now())
      onSaved?.(updated)
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Could not save.')
    } finally {
      setSaving(false)
    }
  }

  const boardSalary = record
    ? formatSalary(record.salary_hkd_min, record.salary_hkd_max)
      ?? formatEstimatedSalary(record.salary_estimated_min, record.salary_estimated_max)
      ?? 'No salary on the board'
    : ''

  return (
    <dialog
      ref={dialogRef}
      data-state={visualState}
      aria-label={`Edit ${job.title}`}
      className="admin-edit-dialog"
    >
      <div className="flex h-full flex-col overflow-hidden">
        <Header
          title={job.title_en || job.title}
          company={job.company}
          onClose={requestClose}
        />

        {loading ? (
          <div className="flex flex-1 items-center justify-center" style={{ color: 'var(--color-ink-faint)' }}>
            <Loader2 size={20} className="animate-spin" aria-label="Loading posting" />
          </div>
        ) : loadError ? (
          <Banner tone="error" icon={<AlertCircle size={15} />}>{loadError}</Banner>
        ) : form && record ? (
          <>
            <div className="flex-1 overflow-y-auto px-5 py-5">
              {/* What the board shows right now — the thing being corrected,
                  quoted back so the admin is not editing numbers blind. */}
              <div
                className="mb-6 rounded-md px-4 py-3"
                style={{ backgroundColor: 'var(--color-surface-2)', border: '1px solid var(--color-border)' }}
              >
                <FieldLabel>On the board now</FieldLabel>
                <p
                  className="mt-1 text-lg font-semibold"
                  style={{ fontFamily: 'var(--font-display)', color: 'var(--color-ink)' }}
                >
                  {boardSalary}
                </p>
                {record.manually_edited_at && (
                  <p
                    className="mt-1.5 inline-flex items-center gap-1 text-xs"
                    style={{ color: 'var(--color-ink-muted)' }}
                  >
                    <Pin size={11} aria-hidden="true" />
                    Already hand-corrected {new Date(record.manually_edited_at).toLocaleDateString()}
                  </p>
                )}
              </div>

              {/* Salary leads: it is why this drawer exists. */}
              <Section title="Salary" hint="Monthly HKD. The estimate is what the board shows when no salary is disclosed.">
                <Row>
                  <NumberField
                    label="Estimate min" value={form.salary_estimated_min}
                    onChange={v => set({ salary_estimated_min: v })}
                  />
                  <NumberField
                    label="Estimate max" value={form.salary_estimated_max}
                    onChange={v => set({ salary_estimated_max: v })}
                  />
                </Row>
                <SelectField
                  label="Estimate confidence" value={form.salary_estimated_confidence}
                  options={CONFIDENCE} onChange={v => set({ salary_estimated_confidence: v })}
                />
                <Row>
                  <NumberField
                    label="Disclosed min" value={form.salary_min}
                    onChange={v => set({ salary_min: v })}
                  />
                  <NumberField
                    label="Disclosed max" value={form.salary_max}
                    onChange={v => set({ salary_max: v })}
                  />
                </Row>
                <TextField
                  label="Currency" value={form.salary_currency} placeholder="HKD"
                  onChange={v => set({ salary_currency: v })}
                />
              </Section>

              <Section title="Classification" hint="The AI columns are the ones the board filters and sorts by.">
                <Row>
                  <SelectField
                    label="Seniority (AI)" value={form.e_seniority}
                    options={SENIORITY} onChange={v => set({ e_seniority: v })}
                  />
                  <SelectField
                    label="Work type (AI)" value={form.e_remote_type}
                    options={REMOTE_TYPES} onChange={v => set({ e_remote_type: v })}
                  />
                </Row>
                <Row>
                  <TextField
                    label="Category (AI)" value={form.job_category}
                    onChange={v => set({ job_category: v })}
                  />
                  <NumberField
                    label="Years experience" value={form.years_experience_required}
                    onChange={v => set({ years_experience_required: v })}
                  />
                </Row>
                <Row>
                  <SelectField
                    label="Seniority (scraped)" value={form.seniority}
                    options={SENIORITY} onChange={v => set({ seniority: v })}
                  />
                  <SelectField
                    label="Work type (scraped)" value={form.remote_type}
                    options={REMOTE_TYPES} onChange={v => set({ remote_type: v })}
                  />
                </Row>
                <Row>
                  <SelectField
                    label="Employment type" value={form.employment_type}
                    options={EMPLOYMENT_TYPES} onChange={v => set({ employment_type: v })}
                  />
                  <TextField
                    label="Category (scraped)" value={form.category}
                    onChange={v => set({ category: v })}
                  />
                </Row>
              </Section>

              <Section title="Posting">
                <TextField label="Title" value={form.title} onChange={v => set({ title: v })} />
                <TextField label="Company" value={form.company} onChange={v => set({ company: v })} />
                <TextAreaField
                  label="Card summary" value={form.description_summary}
                  onChange={v => set({ description_summary: v })}
                />
                <label className="flex items-center gap-2.5 pt-1 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={form.is_active}
                    onChange={e => set({ is_active: e.target.checked })}
                    style={{ accentColor: 'var(--color-blue)', width: 15, height: 15 }}
                  />
                  <span className="text-sm" style={{ color: 'var(--color-ink)' }}>
                    Live on the board
                  </span>
                </label>
              </Section>
            </div>

            <Footer
              dirtyCount={dirtyKeys.length}
              saving={saving}
              saved={savedAt > 0}
              error={saveError}
              onSave={handleSave}
              onCancel={requestClose}
            />
          </>
        ) : null}
      </div>
    </dialog>
  )
}

// ── Chrome ────────────────────────────────────────────────────────────────────

function Header({ title, company, onClose }: { title: string; company: string; onClose: () => void }) {
  return (
    <div className="flex-shrink-0">
      {/* Blue rather than the card's sector accent. This panel is an admin
          surface over the Seeker-facing board, and the one thing it must never
          be mistaken for is the job detail panel that opens from the same card. */}
      <div style={{ height: '3px', backgroundColor: 'var(--color-blue)' }} aria-hidden="true" />
      <div
        className="flex items-start justify-between gap-3 px-5 py-4"
        style={{ borderBottom: '1px solid var(--color-border)' }}
      >
        <div className="min-w-0">
          <p
            className="text-[11px] font-semibold uppercase"
            style={{ color: 'var(--color-blue)', letterSpacing: '0.1em' }}
          >
            Admin · edit posting
          </p>
          <h2
            className="mt-1 truncate text-base font-semibold"
            style={{ fontFamily: 'var(--font-display)', color: 'var(--color-ink)' }}
          >
            {title}
          </h2>
          <p className="truncate text-sm" style={{ color: 'var(--color-ink-muted)' }}>{company}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded cursor-pointer"
          style={{ color: 'var(--color-ink-faint)' }}
          aria-label="Close editor"
        >
          <X size={18} />
        </button>
      </div>
    </div>
  )
}

function Footer({
  dirtyCount, saving, saved, error, onSave, onCancel,
}: {
  dirtyCount: number
  saving: boolean
  saved: boolean
  error: string
  onSave: () => void
  onCancel: () => void
}) {
  return (
    <div
      className="flex-shrink-0 px-5 py-4"
      style={{ borderTop: '1px solid var(--color-border)', backgroundColor: 'var(--color-surface-2)' }}
    >
      {error && (
        <p
          className="mb-2.5 flex items-start gap-1.5 text-sm"
          style={{ color: 'var(--color-destructive)' }}
          role="alert"
        >
          <AlertCircle size={14} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
          {error}
        </p>
      )}

      {/* Stated, not buried: this write outranks every future pipeline run. */}
      <p className="mb-3 flex items-start gap-1.5 text-xs" style={{ color: 'var(--color-ink-muted)' }}>
        <Pin size={12} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
        Saving pins these values — re-enrichment and the nightly salary audit will
        leave them alone from now on.
      </p>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onSave}
          disabled={saving || dirtyCount === 0}
          className="inline-flex items-center gap-2 rounded-md px-4 py-2 text-sm font-semibold cursor-pointer disabled:cursor-not-allowed"
          style={{
            backgroundColor: dirtyCount === 0 ? 'var(--color-border)' : 'var(--color-blue)',
            color: dirtyCount === 0 ? 'var(--color-ink-faint)' : '#FFFFFF',
          }}
        >
          {saving && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
          {saving
            ? 'Saving…'
            : dirtyCount === 0
              ? 'No changes'
              : `Save ${dirtyCount} change${dirtyCount === 1 ? '' : 's'}`}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md px-3 py-2 text-sm cursor-pointer"
          style={{ color: 'var(--color-ink-muted)' }}
        >
          Close
        </button>
        {saved && dirtyCount === 0 && (
          <span
            className="inline-flex items-center gap-1 text-sm font-medium"
            style={{ color: 'var(--color-success)' }}
            role="status"
          >
            <Check size={14} aria-hidden="true" /> Saved
          </span>
        )}
      </div>
    </div>
  )
}

// ── Field primitives ──────────────────────────────────────────────────────────

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="mb-7">
      <h3
        className="text-[11px] font-semibold uppercase"
        style={{ color: 'var(--color-ink-muted)', letterSpacing: '0.1em' }}
      >
        {title}
      </h3>
      {hint && (
        <p className="mt-1 text-xs" style={{ color: 'var(--color-ink-faint)' }}>{hint}</p>
      )}
      <div className="mt-3 flex flex-col gap-3">{children}</div>
    </section>
  )
}

function Row({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-2 gap-3">{children}</div>
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <span
      className="text-[11px] font-semibold uppercase"
      style={{ color: 'var(--color-ink-muted)', letterSpacing: '0.06em' }}
    >
      {children}
    </span>
  )
}

const inputStyle: React.CSSProperties = {
  border: '1px solid var(--color-border-strong)',
  backgroundColor: 'var(--color-surface)',
  color: 'var(--color-ink)',
}

function TextField({
  label, value, placeholder, onChange,
}: { label: string; value: string; placeholder?: string; onChange: (v: string) => void }) {
  return (
    <label className="flex flex-col gap-1">
      <FieldLabel>{label}</FieldLabel>
      <input
        type="text"
        value={value}
        placeholder={placeholder}
        onChange={e => onChange(e.target.value)}
        className="rounded-md px-2.5 py-2 text-sm"
        style={inputStyle}
      />
    </label>
  )
}

function NumberField({
  label, value, onChange,
}: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <label className="flex flex-col gap-1">
      <FieldLabel>{label}</FieldLabel>
      <input
        type="number"
        value={value}
        onChange={e => onChange(e.target.value)}
        className="rounded-md px-2.5 py-2 text-sm"
        style={{ ...inputStyle, fontFamily: 'var(--font-mono)' }}
      />
    </label>
  )
}

function SelectField({
  label, value, options, onChange,
}: { label: string; value: string; options: string[]; onChange: (v: string) => void }) {
  // A value the pipeline wrote that is not in our list must still be shown, or
  // simply opening the drawer would silently reset it on the next save.
  const opts = options.includes(value) ? options : [...options, value]
  return (
    <label className="flex flex-col gap-1">
      <FieldLabel>{label}</FieldLabel>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        className="rounded-md px-2.5 py-2 text-sm cursor-pointer"
        style={inputStyle}
      >
        {opts.map(o => <option key={o} value={o}>{o === '' ? '—' : o}</option>)}
      </select>
    </label>
  )
}

function TextAreaField({
  label, value, onChange,
}: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <label className="flex flex-col gap-1">
      <FieldLabel>{label}</FieldLabel>
      <textarea
        value={value}
        rows={4}
        onChange={e => onChange(e.target.value)}
        className="rounded-md px-2.5 py-2 text-sm resize-y"
        style={inputStyle}
      />
    </label>
  )
}

function Banner({
  tone, icon, children,
}: { tone: 'error'; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div
      className="m-5 flex items-start gap-2 rounded-md px-3 py-2.5 text-sm"
      style={{
        backgroundColor: 'var(--color-danger-bg)',
        border: '1px solid var(--color-danger-border)',
        color: 'var(--color-destructive)',
      }}
      role="alert"
    >
      <span className="mt-0.5 flex-shrink-0" aria-hidden="true">{icon}</span>
      {tone === 'error' && children}
    </div>
  )
}
