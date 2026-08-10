import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertCircle,
  ArrowRight,
  BadgeCheck,
  FileSearch,
  FileText,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
  Trash2,
  Upload,
} from 'lucide-react'
import type { ResumeDocument } from '../api/client'
import { deleteResume, fetchResume, uploadResume } from '../api/client'

const MAX_BYTES = 5 * 1024 * 1024
const ACCEPT = '.pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document'

type Stage = 'loading' | 'idle' | 'uploading' | 'removing' | 'confirming-remove'

export default function ResumeManager() {
  const inputRef = useRef<HTMLInputElement>(null)
  const [resume, setResume] = useState<ResumeDocument | null>(null)
  const [stage, setStage] = useState<Stage>('loading')
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    fetchResume()
      .then(value => { if (!cancelled) setResume(value) })
      .catch(err => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Your resume could not be loaded.')
      })
      .finally(() => { if (!cancelled) setStage('idle') })
    return () => { cancelled = true }
  }, [])

  const chooseFile = () => inputRef.current?.click()

  async function handleFile(file: File | undefined) {
    if (!file) return
    const extension = file.name.split('.').pop()?.toLocaleLowerCase()
    if (extension !== 'pdf' && extension !== 'docx') {
      setError('Choose a PDF or DOCX resume.')
      return
    }
    if (file.size > MAX_BYTES) {
      setError('Your resume must be 5 MB or smaller.')
      return
    }
    setStage('uploading')
    setError('')
    try {
      setResume(await uploadResume(file))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Your resume could not be analysed.')
    } finally {
      setStage('idle')
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  async function remove() {
    setStage('removing')
    setError('')
    try {
      await deleteResume()
      setResume(null)
      setStage('idle')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Your resume could not be removed.')
      setStage('idle')
    }
  }

  const busy = stage === 'loading' || stage === 'uploading' || stage === 'removing'

  return (
    <section className="resume-manager" aria-labelledby="resume-manager-heading">
      <div className="resume-manager__heading">
        <div>
          <div className="resume-manager__kicker">
            <FileSearch size={16} strokeWidth={2.1} aria-hidden="true" />
            Resume intelligence
          </div>
          <h2 id="resume-manager-heading">Put your experience against the whole market.</h2>
          <p>Add one resume and FinEx will surface the live Roles where your skills and experience align—with reasons you can inspect.</p>
        </div>
        <span className="resume-manager__privacy">
          <ShieldCheck size={14} strokeWidth={2.2} aria-hidden="true" />
          Private to your account
        </span>
      </div>

      <ul className="resume-manager__benefits" aria-label="What your resume unlocks">
        <li><BadgeCheck size={16} aria-hidden="true" /><span><strong>Strong matches</strong> ranked from observable evidence</span></li>
        <li><FileSearch size={16} aria-hidden="true" /><span><strong>Clear reasons</strong> for why each Role surfaced</span></li>
        <li><ShieldCheck size={16} aria-hidden="true" /><span><strong>Broader discovery</strong> stays open for career changes</span></li>
      </ul>

      <input
        ref={inputRef}
        className="sr-only"
        type="file"
        accept={ACCEPT}
        aria-label="Upload resume"
        onChange={event => handleFile(event.target.files?.[0])}
      />

      {stage === 'loading' ? (
        <div className="resume-manager__loading" role="status">
          <LoaderCircle size={18} className="animate-spin" aria-hidden="true" />
          Loading your resume…
        </div>
      ) : resume ? (
        <div className="resume-manager__document">
          <div className="resume-manager__file-row">
            <span className="resume-manager__file-mark" aria-hidden="true">
              <FileText size={20} strokeWidth={2} />
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate font-semibold" style={{ color: 'var(--color-ink)' }}>{resume.filename}</p>
              <p className="mt-0.5 text-xs" style={{ color: 'var(--color-ink-muted)' }}>
                {formatFileType(resume.media_type)} · {formatBytes(resume.size_bytes)} · Uploaded {formatDate(resume.uploaded_at)}
              </p>
            </div>
            <span className="resume-manager__analysed">
              <BadgeCheck size={15} strokeWidth={2.2} aria-hidden="true" /> Analysed
            </span>
          </div>

          <ResumeEvidenceSummary resume={resume} />

          {stage === 'confirming-remove' ? (
            <div className="resume-manager__remove-confirm" role="alert">
              <p>Remove this resume and its analysis? Your Saved Roles and account stay unchanged.</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <button type="button" onClick={remove} className="resume-manager__danger-button">
                  <Trash2 size={14} aria-hidden="true" /> Remove resume
                </button>
                <button type="button" onClick={() => setStage('idle')} className="resume-manager__text-button">
                  Keep it
                </button>
              </div>
            </div>
          ) : (
            <div className="resume-manager__actions">
              <button type="button" disabled={busy} onClick={chooseFile} className="resume-manager__secondary-button">
                {stage === 'uploading'
                  ? <LoaderCircle size={15} className="animate-spin" aria-hidden="true" />
                  : <RefreshCw size={15} aria-hidden="true" />}
                {stage === 'uploading' ? 'Analysing…' : 'Replace resume'}
              </button>
              <button type="button" disabled={busy} onClick={() => setStage('confirming-remove')} className="resume-manager__text-button">
                Remove
              </button>
              <Link to="/jobs" className="resume-manager__matches-link">View strong matches</Link>
            </div>
          )}
          <p className="mt-3 text-xs" style={{ color: 'var(--color-ink-muted)' }}>
            A successful replacement permanently removes the previous file.
          </p>
        </div>
      ) : (
        <button type="button" onClick={chooseFile} disabled={busy} className="resume-manager__empty">
          <span className="resume-manager__upload-mark" aria-hidden="true">
            <Upload size={21} strokeWidth={2} />
          </span>
          <span>
            <strong>Upload your resume</strong>
            <small>PDF or DOCX · up to 5 MB · replaces any previous resume</small>
          </span>
          <ArrowRight className="resume-manager__empty-arrow" size={18} aria-hidden="true" />
        </button>
      )}

      {error && (
        <p className="resume-manager__error" role="alert">
          <AlertCircle size={16} className="shrink-0" aria-hidden="true" /> {error}
        </p>
      )}
    </section>
  )
}

function ResumeEvidenceSummary({ resume }: { resume: ResumeDocument }) {
  const { analysis } = resume
  const evidence = [
    analysis.years_experience != null
      ? `${analysis.years_experience} years of experience`
      : analysis.seniority
        ? `${analysis.seniority} career level`
        : null,
    ...analysis.sectors.slice(0, 2),
  ].filter(Boolean) as string[]

  return (
    <div className="resume-manager__evidence">
      <p>Evidence found</p>
      {(analysis.skills.length > 0 || evidence.length > 0) ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {analysis.skills.slice(0, 8).map(skill => <span key={skill}>{skill}</span>)}
          {evidence.map(value => <span key={value}>{value}</span>)}
        </div>
      ) : (
        <p className="mt-1.5 text-sm" style={{ color: 'var(--color-ink-muted)' }}>
          The text was readable, but structured evidence was limited. Strong matches may be broader.
        </p>
      )}
    </div>
  )
}

function formatBytes(bytes: number): string {
  return bytes < 1024 * 1024
    ? `${Math.max(1, Math.round(bytes / 1024))} KB`
    : `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatFileType(mediaType: string): string {
  return mediaType === 'application/pdf' ? 'PDF' : 'DOCX'
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat('en-HK', { day: 'numeric', month: 'short', year: 'numeric' })
    .format(new Date(value))
}
