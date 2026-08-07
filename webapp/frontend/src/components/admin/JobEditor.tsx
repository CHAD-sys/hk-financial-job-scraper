import { useState } from 'react'
import { AlertCircle, CheckCircle2, Loader2, Pencil, Search } from 'lucide-react'
import {
  DEFAULT_FILTERS, fetchAdminJob, fetchJobs, patchAdminJob,
  type AdminJobRecord, type Job,
} from '../../api/client'

const EMPLOYMENT_TYPES = ['Full-time', 'Contract', 'Part-time', 'Internship']
const CONFIDENCE_LEVELS = ['high', 'medium', 'low']

/** Editable job-table fields this form exposes. The backend's allowlist
 * (job_edit.JOB_FIELDS) covers more than this — locations, required_skills,
 * title_en and raw description are left out of the UI for now, not the API. */
interface JobFormState {
  title: string
  company: string
  employment_type: string
  seniority: string
  remote_type: string
  category: string
  source_tier: string
  salary_min: string
  salary_max: string
  salary_currency: string
  is_active: boolean
  description_clean: string
}

interface EnrichmentFormState {
  e_seniority: string
  e_remote_type: string
  salary_estimated_min: string
  salary_estimated_max: string
  salary_estimated_confidence: string
  job_category: string
  years_experience_required: string
  description_summary: string
}

function toJobForm(job: AdminJobRecord): JobFormState {
  return {
    title: job.title ?? '',
    company: job.company ?? '',
    employment_type: job.employment_type ?? '',
    seniority: job.seniority ?? '',
    remote_type: job.remote_type ?? '',
    category: job.category ?? '',
    source_tier: job.source_tier ?? '',
    salary_min: job.salary_min?.toString() ?? '',
    salary_max: job.salary_max?.toString() ?? '',
    salary_currency: job.salary_currency ?? '',
    is_active: !!job.is_active,
    description_clean: job.description_clean ?? '',
  }
}

function toEnrichmentForm(job: AdminJobRecord): EnrichmentFormState {
  return {
    e_seniority: job.e_seniority ?? '',
    e_remote_type: job.e_remote_type ?? '',
    salary_estimated_min: job.salary_estimated_min?.toString() ?? '',
    salary_estimated_max: job.salary_estimated_max?.toString() ?? '',
    salary_estimated_confidence: job.salary_estimated_confidence ?? '',
    job_category: job.job_category ?? '',
    years_experience_required: job.years_experience_required?.toString() ?? '',
    description_summary: job.description_summary ?? '',
  }
}

/** '' means "clear it" (None); a number string parses; text passes through. */
function toWireValue(raw: string, numeric: boolean): unknown {
  if (raw.trim() === '') return null
  return numeric ? Number(raw) : raw
}

export default function JobEditor() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Job[] | null>(null)
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState('')

  const [selected, setSelected] = useState<AdminJobRecord | null>(null)
  const [jobForm, setJobForm] = useState<JobFormState | null>(null)
  const [enrichForm, setEnrichForm] = useState<EnrichmentFormState | null>(null)
  const [loadError, setLoadError] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [saved, setSaved] = useState(false)

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault()
    if (!query.trim()) return
    setSearching(true)
    setSearchError('')
    try {
      const res = await fetchJobs({ ...DEFAULT_FILTERS, search: query.trim() }, 'relevance', 1, 12)
      setResults(res.jobs)
    } catch (err) {
      setSearchError(err instanceof Error ? err.message : 'Search failed.')
    } finally {
      setSearching(false)
    }
  }

  async function openJob(job: Job) {
    setLoadError('')
    setSaved(false)
    setSaveError('')
    try {
      const full = await fetchAdminJob(job.source, job.source_id)
      setSelected(full)
      setJobForm(toJobForm(full))
      setEnrichForm(toEnrichmentForm(full))
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'Could not load that job.')
    }
  }

  async function handleSave() {
    if (!selected || !jobForm || !enrichForm) return
    setSaving(true)
    setSaveError('')
    setSaved(false)
    try {
      const updated = await patchAdminJob(selected.source, selected.source_id, {
        job: {
          title: jobForm.title,
          company: jobForm.company,
          employment_type: jobForm.employment_type,
          seniority: jobForm.seniority || null,
          remote_type: jobForm.remote_type || null,
          category: jobForm.category || null,
          source_tier: jobForm.source_tier,
          salary_min: toWireValue(jobForm.salary_min, true),
          salary_max: toWireValue(jobForm.salary_max, true),
          salary_currency: jobForm.salary_currency || null,
          is_active: jobForm.is_active,
          description_clean: jobForm.description_clean,
        },
        enrichment: {
          seniority: enrichForm.e_seniority || null,
          remote_type: enrichForm.e_remote_type || null,
          salary_estimated_min: toWireValue(enrichForm.salary_estimated_min, true),
          salary_estimated_max: toWireValue(enrichForm.salary_estimated_max, true),
          salary_estimated_confidence: enrichForm.salary_estimated_confidence || null,
          job_category: enrichForm.job_category || null,
          years_experience_required: toWireValue(enrichForm.years_experience_required, true),
          description_summary: enrichForm.description_summary,
        },
      })
      setSelected(updated)
      setJobForm(toJobForm(updated))
      setEnrichForm(toEnrichmentForm(updated))
      setSaved(true)
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Could not save that job.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      className="rounded-lg p-5"
      style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-gold)', boxShadow: 'var(--shadow-card)' }}
    >
      <h3
        className="text-xs font-semibold uppercase tracking-widest mb-1"
        style={{ color: 'var(--color-gold)', letterSpacing: '0.08em' }}
      >
        Ultimate Admin — Job Editor
      </h3>
      <p className="text-xs mb-4" style={{ color: 'var(--color-ink-faint)' }}>
        Writes directly to the database, immediately — this bypasses the pipeline. Find a job, then edit anything below.
      </p>

      <form onSubmit={handleSearch} className="flex gap-2 mb-4">
        <label htmlFor="admin-job-search" className="sr-only">
          Search jobs by title or company
        </label>
        <input
          id="admin-job-search"
          className="finex-input flex-1"
          placeholder="Search by title or company…"
          value={query}
          onChange={e => setQuery(e.target.value)}
        />
        <button
          type="submit"
          disabled={searching}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded text-sm font-semibold"
          style={{ backgroundColor: 'var(--color-ink)', color: '#fff', opacity: searching ? 0.6 : 1 }}
        >
          {searching ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
          Search
        </button>
      </form>

      {searchError && <p className="text-sm mb-3" style={{ color: 'var(--color-destructive)' }}>{searchError}</p>}

      {results && results.length > 0 && (
        <ul className="flex flex-col gap-1.5 mb-5">
          {results.map(job => (
            <li key={`${job.source}/${job.source_id}`}>
              <button
                type="button"
                onClick={() => openJob(job)}
                className="w-full flex items-center justify-between gap-3 rounded px-3 py-2 text-left text-sm"
                style={{ backgroundColor: 'var(--color-surface-2)', border: '1px solid var(--color-border)' }}
              >
                <span>
                  <strong style={{ color: 'var(--color-ink)' }}>{job.title}</strong>
                  <span style={{ color: 'var(--color-ink-muted)' }}> @ {job.company}</span>
                </span>
                <span className="inline-flex items-center gap-1 text-xs shrink-0" style={{ color: 'var(--color-blue)' }}>
                  <Pencil size={12} /> Edit
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {results && results.length === 0 && (
        <p className="text-sm mb-5" style={{ color: 'var(--color-ink-faint)' }}>No matches.</p>
      )}

      {loadError && <p className="text-sm mb-3" style={{ color: 'var(--color-destructive)' }}>{loadError}</p>}

      {selected && jobForm && enrichForm && (
        <div className="pt-4" style={{ borderTop: '1px solid var(--color-border)' }}>
          <div className="flex items-baseline justify-between mb-3">
            <p className="text-sm font-semibold" style={{ color: 'var(--color-ink)' }}>
              Editing {selected.source}/{selected.source_id}
            </p>
            {selected.manually_edited_at && (
              <span className="text-xs" style={{ color: 'var(--color-ink-faint)' }}>
                Last hand-edited {new Date(selected.manually_edited_at).toLocaleString()}
              </span>
            )}
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
            <Field label="Title">
              <input className="finex-input" value={jobForm.title}
                     onChange={e => setJobForm({ ...jobForm, title: e.target.value })} />
            </Field>
            <Field label="Company">
              <input className="finex-input" value={jobForm.company}
                     onChange={e => setJobForm({ ...jobForm, company: e.target.value })} />
            </Field>
            <Field label="Employment type">
              <select className="finex-input" value={jobForm.employment_type}
                      onChange={e => setJobForm({ ...jobForm, employment_type: e.target.value })}>
                {EMPLOYMENT_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </Field>
            <Field label="Category (sector)">
              <input className="finex-input" value={jobForm.category}
                     onChange={e => setJobForm({ ...jobForm, category: e.target.value })} />
            </Field>
            <Field label="Salary min (raw)">
              <input className="finex-input" type="number" value={jobForm.salary_min}
                     onChange={e => setJobForm({ ...jobForm, salary_min: e.target.value })} />
            </Field>
            <Field label="Salary max (raw)">
              <input className="finex-input" type="number" value={jobForm.salary_max}
                     onChange={e => setJobForm({ ...jobForm, salary_max: e.target.value })} />
            </Field>
            <label className="flex items-center gap-2 text-sm sm:col-span-2" style={{ color: 'var(--color-ink)' }}>
              <input type="checkbox" checked={jobForm.is_active}
                     onChange={e => setJobForm({ ...jobForm, is_active: e.target.checked })} />
              Active (visible on the board)
            </label>
          </div>

          <Field label="Description">
            <textarea className="finex-input" rows={3} value={jobForm.description_clean}
                      onChange={e => setJobForm({ ...jobForm, description_clean: e.target.value })} />
          </Field>

          <p
            className="text-xs font-semibold uppercase tracking-widest mt-5 mb-3"
            style={{ color: 'var(--color-ink-muted)', letterSpacing: '0.08em' }}
          >
            AI enrichment (drives board filters — editing here sets manually_edited_at)
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
            <Field label="Seniority">
              <input className="finex-input" value={enrichForm.e_seniority}
                     onChange={e => setEnrichForm({ ...enrichForm, e_seniority: e.target.value })} />
            </Field>
            <Field label="Remote type">
              <input className="finex-input" value={enrichForm.e_remote_type}
                     onChange={e => setEnrichForm({ ...enrichForm, e_remote_type: e.target.value })} />
            </Field>
            <Field label="Estimated salary min (HK$/mo)">
              <input className="finex-input" type="number" value={enrichForm.salary_estimated_min}
                     onChange={e => setEnrichForm({ ...enrichForm, salary_estimated_min: e.target.value })} />
            </Field>
            <Field label="Estimated salary max (HK$/mo)">
              <input className="finex-input" type="number" value={enrichForm.salary_estimated_max}
                     onChange={e => setEnrichForm({ ...enrichForm, salary_estimated_max: e.target.value })} />
            </Field>
            <Field label="Confidence">
              <select className="finex-input" value={enrichForm.salary_estimated_confidence}
                      onChange={e => setEnrichForm({ ...enrichForm, salary_estimated_confidence: e.target.value })}>
                <option value="">—</option>
                {CONFIDENCE_LEVELS.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </Field>
            <Field label="Job category">
              <input className="finex-input" value={enrichForm.job_category}
                     onChange={e => setEnrichForm({ ...enrichForm, job_category: e.target.value })} />
            </Field>
          </div>

          <Field label="Description summary (shown on job cards)">
            <textarea className="finex-input" rows={2} value={enrichForm.description_summary}
                      onChange={e => setEnrichForm({ ...enrichForm, description_summary: e.target.value })} />
          </Field>

          {saveError && (
            <p className="mt-3 flex items-center gap-1.5 text-sm" style={{ color: 'var(--color-destructive)' }}>
              <AlertCircle size={14} /> {saveError}
            </p>
          )}
          {saved && (
            <p className="mt-3 flex items-center gap-1.5 text-sm" style={{ color: '#15803D' }}>
              <CheckCircle2 size={14} /> Saved.
            </p>
          )}

          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="mt-4 inline-flex items-center gap-1.5 px-4 py-2 rounded text-sm font-semibold"
            style={{ backgroundColor: 'var(--color-gold)', color: '#fff', opacity: saving ? 0.6 : 1 }}
          >
            {saving ? <Loader2 size={14} className="animate-spin" /> : null}
            {saving ? 'Saving…' : 'Save changes'}
          </button>
        </div>
      )}
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs font-medium" style={{ color: 'var(--color-ink-muted)' }}>
      {label}
      {children}
    </label>
  )
}
