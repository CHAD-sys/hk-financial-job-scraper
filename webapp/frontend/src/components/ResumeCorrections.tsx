import { useMemo, useState } from 'react'
import { AlertCircle, Check, LoaderCircle, Pencil, Plus, RotateCcw, X } from 'lucide-react'
import type { ResumeAnalysis, ResumeAnalysisOverride, ResumeDocument } from '../api/client'
import { SENIORITY_CHOICES, correctResumeAnalysis } from '../api/client'

/**
 * Lets a Seeker correct what was read from their own resume.
 *
 * Extraction is a rules engine over an arbitrary PDF, so it is sometimes wrong
 * in ways only the author can settle — a second-year student read as "senior",
 * a career treasurer read as nothing at all. Every field here shows what was
 * extracted next to what the Seeker said, because a correction is only
 * trustworthy if you can see what it replaced.
 */

const MAX_SKILLS = 32
const MAX_CERTIFICATIONS = 12

type Draft = {
  seniority: string
  years: string
  skills: string[]
  certifications: string[]
}

function toDraft(resume: ResumeDocument): Draft {
  const { analysis, analysis_override: override } = resume
  return {
    seniority: override.seniority ?? '',
    years: override.years_experience != null ? String(override.years_experience) : '',
    skills: override.skills ?? analysis.skills,
    certifications: override.certifications ?? analysis.certifications ?? [],
  }
}

/** Only send fields the Seeker actually changed; the rest stay automatic. */
function toOverride(draft: Draft, extracted: ResumeAnalysis): ResumeAnalysisOverride {
  const sameList = (a: string[], b: string[]) =>
    a.length === b.length && a.every((value, index) => value === b[index])
  return {
    seniority: draft.seniority || null,
    years_experience: draft.years.trim() === '' ? null : Number(draft.years),
    skills: sameList(draft.skills, extracted.skills) ? null : draft.skills,
    certifications: sameList(draft.certifications, extracted.certifications ?? [])
      ? null
      : draft.certifications,
  }
}

export default function ResumeCorrections({
  resume,
  onSaved,
}: {
  resume: ResumeDocument
  onSaved: (updated: ResumeDocument) => void
}) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<Draft>(() => toDraft(resume))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)

  const extracted = resume.analysis_extracted
  const override = resume.analysis_override
  const correctedCount = useMemo(
    () => Object.values(override).filter(value => value != null).length,
    [override],
  )

  function start() {
    setDraft(toDraft(resume))
    setError('')
    setSaved(false)
    setOpen(true)
  }

  async function save() {
    const years = draft.years.trim()
    if (years !== '' && !/^\d{1,2}$/.test(years)) {
      setError('Years of experience must be a whole number between 0 and 60.')
      return
    }
    if (years !== '' && Number(years) > 60) {
      setError('Years of experience must be a whole number between 0 and 60.')
      return
    }
    setSaving(true)
    setError('')
    try {
      onSaved(await correctResumeAnalysis(toOverride(draft, extracted)))
      setSaved(true)
      setOpen(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Your corrections could not be saved.')
    } finally {
      setSaving(false)
    }
  }

  if (!open) {
    return (
      <div className="resume-corrections__bar">
        <button type="button" onClick={start} className="resume-corrections__open">
          <Pencil size={14} strokeWidth={2.2} aria-hidden="true" />
          {correctedCount > 0 ? 'Edit your corrections' : 'Something wrong? Correct it'}
        </button>
        {correctedCount > 0 && (
          <span className="resume-corrections__flag">
            <Check size={13} strokeWidth={2.6} aria-hidden="true" />
            {correctedCount} {correctedCount === 1 ? 'field' : 'fields'} corrected by you
          </span>
        )}
        {saved && (
          <span className="resume-corrections__saved" role="status">
            Saved — your matches now use this.
          </span>
        )}
      </div>
    )
  }

  return (
    <div className="resume-corrections">
      <div className="resume-corrections__intro">
        <h3>Correct what we found</h3>
        <p>
          We read your resume with rules, not a person, so it can misread things. Your answer
          wins — and it is kept even when we improve the reader.
        </p>
      </div>

      <div className="resume-corrections__grid">
        <Field
          label="Career level"
          htmlFor="correction-seniority"
          read={extracted.seniority ?? 'nothing'}
          corrected={Boolean(draft.seniority)}
          onReset={() => setDraft({ ...draft, seniority: '' })}
        >
          <select
            id="correction-seniority"
            className="resume-corrections__input"
            value={draft.seniority}
            onChange={event => setDraft({ ...draft, seniority: event.target.value })}
          >
            <option value="">Use what we read</option>
            {SENIORITY_CHOICES.map(choice => (
              <option key={choice} value={choice}>
                {choice.charAt(0).toUpperCase() + choice.slice(1)}
              </option>
            ))}
          </select>
        </Field>

        <Field
          label="Years of experience"
          htmlFor="correction-years"
          read={extracted.years_experience != null ? String(extracted.years_experience) : 'nothing'}
          corrected={draft.years.trim() !== ''}
          onReset={() => setDraft({ ...draft, years: '' })}
        >
          <input
            id="correction-years"
            className="resume-corrections__input"
            type="number"
            inputMode="numeric"
            min={0}
            max={60}
            placeholder="Use what we read"
            value={draft.years}
            onChange={event => setDraft({ ...draft, years: event.target.value })}
          />
        </Field>
      </div>

      <ChipField
        label="Skills"
        name="skills"
        placeholder="Add a skill"
        limit={MAX_SKILLS}
        values={draft.skills}
        onChange={skills => setDraft({ ...draft, skills })}
      />
      <ChipField
        label="Certifications"
        name="certifications"
        placeholder="Add a certification (CFA, FRM…)"
        limit={MAX_CERTIFICATIONS}
        values={draft.certifications}
        onChange={certifications => setDraft({ ...draft, certifications })}
      />

      {error && (
        <p className="resume-corrections__error" role="alert">
          <AlertCircle size={15} className="shrink-0" aria-hidden="true" /> {error}
        </p>
      )}

      <div className="resume-corrections__actions">
        <button
          type="button"
          onClick={save}
          disabled={saving}
          className="resume-corrections__save"
        >
          {saving ? (
            <LoaderCircle size={15} className="animate-spin" aria-hidden="true" />
          ) : (
            <Check size={15} strokeWidth={2.4} aria-hidden="true" />
          )}
          {saving ? 'Saving…' : 'Save corrections'}
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          disabled={saving}
          className="resume-corrections__cancel"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

function Field({
  label,
  htmlFor,
  read,
  corrected,
  onReset,
  children,
}: {
  label: string
  htmlFor: string
  read: string
  corrected: boolean
  onReset: () => void
  children: React.ReactNode
}) {
  return (
    <div className="resume-corrections__field">
      <div className="resume-corrections__field-head">
        <label htmlFor={htmlFor}>{label}</label>
        {corrected && (
          <button type="button" onClick={onReset} className="resume-corrections__reset">
            <RotateCcw size={12} strokeWidth={2.4} aria-hidden="true" />
            Use ours
          </button>
        )}
      </div>
      {children}
      <p className="resume-corrections__read">We read: {read}</p>
    </div>
  )
}

function ChipField({
  label,
  name,
  placeholder,
  limit,
  values,
  onChange,
}: {
  label: string
  name: string
  placeholder: string
  limit: number
  values: string[]
  onChange: (values: string[]) => void
}) {
  const [entry, setEntry] = useState('')
  const inputId = `correction-${name}`

  function add() {
    const value = entry.trim().toLocaleLowerCase()
    if (!value || values.includes(value) || values.length >= limit) {
      setEntry('')
      return
    }
    onChange([...values, value])
    setEntry('')
  }

  return (
    <div className="resume-corrections__field resume-corrections__field--wide">
      <div className="resume-corrections__field-head">
        <label htmlFor={inputId}>{label}</label>
        <span className="resume-corrections__count">
          {values.length}/{limit}
        </span>
      </div>
      {values.length > 0 && (
        <ul className="resume-corrections__chips">
          {values.map(value => (
            <li key={value}>
              <span>{value}</span>
              <button
                type="button"
                onClick={() => onChange(values.filter(item => item !== value))}
                aria-label={`Remove ${value}`}
              >
                <X size={12} strokeWidth={2.8} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="resume-corrections__add">
        <input
          id={inputId}
          className="resume-corrections__input"
          value={entry}
          placeholder={placeholder}
          onChange={event => setEntry(event.target.value)}
          onKeyDown={event => {
            if (event.key === 'Enter') {
              event.preventDefault()
              add()
            }
          }}
        />
        <button
          type="button"
          onClick={add}
          disabled={!entry.trim() || values.length >= limit}
          className="resume-corrections__add-button"
          aria-label={`Add ${name === 'skills' ? 'skill' : 'certification'}`}
        >
          <Plus size={14} strokeWidth={2.6} aria-hidden="true" />
          Add
        </button>
      </div>
    </div>
  )
}
