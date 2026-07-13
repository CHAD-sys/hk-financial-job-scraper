import { useEffect, useState } from 'react'
import {
  X, Bookmark, ExternalLink, MapPin, Briefcase,
  GraduationCap, DollarSign, Tag, Calendar,
} from 'lucide-react'
import type { Job, JobDetail } from '../api/client'
import { fetchJobDetail } from '../api/client'
import {
  formatSalary, formatEstimatedSalary, timeAgo, getSectorColor,
  getSeniorityColor, formatRemoteType, shortLocation,
} from '../utils/format'

interface Props {
  job: Job
  saved: boolean
  onToggleSave: (job: Job) => void
  onClose: () => void
}

export default function JobDetailModal({ job, saved, onToggleSave, onClose }: Props) {
  const [detail, setDetail] = useState<JobDetail | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    fetchJobDetail(job.source, job.source_id)
      .then(setDetail)
      .finally(() => setLoading(false))
  }, [job.source, job.source_id])

  // Lock body scroll
  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = '' }
  }, [])

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  const sectorColor = getSectorColor(job.sector)
  const senColor = getSeniorityColor(job.seniority)
  const d = detail ?? job
  // Prefer the AI English title (Chinese postings); fall back to the original.
  const displayTitle = d.title_en || d.title
  const salary = formatSalary(d.salary_hkd_min, d.salary_hkd_max)
  // AI estimate only when no disclosed salary.
  const estimatedSalary = salary
    ? null
    : formatEstimatedSalary(d.salary_estimated_min, d.salary_estimated_max)
  const estConfidence = d.salary_estimated_confidence

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40"
        style={{ backgroundColor: 'rgba(11,22,40,0.55)', backdropFilter: 'blur(2px)' }}
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Panel */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label={displayTitle}
        className="fixed right-0 bottom-0 z-50 flex flex-col overflow-hidden"
        style={{
          top: 'var(--nav-height)',                       // start below the sticky nav
          height: 'calc(100dvh - var(--nav-height))',     // fill the rest of the viewport
          width: 'min(680px, 100vw)',
          backgroundColor: 'var(--color-surface)',
          boxShadow: 'var(--shadow-float)',
          borderLeft: '1px solid var(--color-border)',
        }}
      >
        {/* Sector accent top bar */}
        <div
          className="flex-shrink-0"
          style={{ height: '3px', backgroundColor: sectorColor.accent }}
          aria-hidden="true"
        />

        {/* Header */}
        <div
          className="flex-shrink-0 flex items-start gap-3 px-6 py-5"
          style={{ borderBottom: '1px solid var(--color-border)' }}
        >
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <span
                className="text-xs font-medium px-2 py-0.5 rounded"
                style={{ backgroundColor: sectorColor.bg, color: sectorColor.text }}
              >
                {job.sector}
              </span>
              {job.is_internship && (
                <span
                  className="text-xs px-2 py-0.5 rounded"
                  style={{ backgroundColor: '#FEF9C3', color: '#854D0E' }}
                >
                  Internship
                </span>
              )}
            </div>
            <h2
              className="text-xl font-bold leading-snug mb-1"
              style={{
                fontFamily: 'var(--font-display)',
                color: 'var(--color-ink)',
                letterSpacing: '-0.01em',
              }}
            >
              {displayTitle}
            </h2>
            <p className="text-sm font-medium" style={{ color: 'var(--color-ink-muted)' }}>
              {job.company}
            </p>
          </div>

          <div className="flex items-center gap-2 flex-shrink-0">
            <button
              onClick={() => onToggleSave(job)}
              className="flex items-center gap-1.5 rounded px-3 py-2 text-sm font-medium transition-all duration-150 cursor-pointer"
              style={{
                border: '1px solid var(--color-border)',
                color: saved ? 'var(--color-gold)' : 'var(--color-ink-muted)',
                backgroundColor: saved ? 'var(--color-gold-light)' : 'var(--color-surface)',
              }}
              aria-pressed={saved}
            >
              <Bookmark size={14} fill={saved ? 'currentColor' : 'none'} strokeWidth={1.8} />
              {saved ? 'Saved' : 'Save'}
            </button>
            <button
              onClick={onClose}
              className="p-2 rounded transition-colors duration-150 cursor-pointer"
              style={{ color: 'var(--color-ink-faint)' }}
              onMouseEnter={e => ((e.currentTarget as HTMLButtonElement).style.backgroundColor = 'var(--color-surface-2)')}
              onMouseLeave={e => ((e.currentTarget as HTMLButtonElement).style.backgroundColor = 'transparent')}
              aria-label="Close"
            >
              <X size={18} strokeWidth={1.8} />
            </button>
          </div>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto">
          <div className="px-6 py-5 flex flex-col gap-5">

            {/* Meta grid */}
            <div
              className="grid grid-cols-2 gap-3 rounded-lg p-4"
              style={{ backgroundColor: 'var(--color-surface-2)', border: '1px solid var(--color-border)' }}
            >
              {[
                { icon: MapPin, label: 'Location', val: shortLocation(d.locations) },
                { icon: Briefcase, label: 'Work type', val: formatRemoteType(d.remote_type) || '—' },
                { icon: Tag, label: 'Seniority', val: d.seniority ?? '—' },
                { icon: Tag, label: 'Category', val: d.job_category ?? '—' },
                { icon: GraduationCap, label: 'Experience', val: d.years_experience_required != null ? `${d.years_experience_required}+ yrs` : '—' },
                { icon: Calendar, label: 'Posted', val: timeAgo(d.posted_at) },
              ].map(({ icon: Icon, label, val }) => (
                <div key={label} className="flex items-start gap-2">
                  <Icon size={13} style={{ color: 'var(--color-ink-faint)', marginTop: 2 }} strokeWidth={1.8} />
                  <div>
                    <p className="text-xs" style={{ color: 'var(--color-ink-faint)' }}>{label}</p>
                    <p className="text-sm font-medium capitalize" style={{ color: 'var(--color-ink)' }}>{val}</p>
                  </div>
                </div>
              ))}
            </div>

            {/* Salary — disclosed (gold, authoritative) */}
            {salary && (
              <div
                className="flex items-center gap-3 rounded-lg p-4"
                style={{
                  backgroundColor: 'var(--color-gold-light)',
                  border: '1px solid var(--color-gold)',
                }}
              >
                <DollarSign size={18} style={{ color: 'var(--color-gold)' }} strokeWidth={1.8} />
                <div>
                  <p className="text-xs font-medium uppercase tracking-wider" style={{ color: 'var(--color-gold)' }}>
                    Compensation
                  </p>
                  <p
                    className="text-base font-bold tabular-nums"
                    style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-ink)' }}
                  >
                    {salary} / year
                  </p>
                </div>
              </div>
            )}

            {/* Salary — AI estimate (muted/neutral, clearly not disclosed) */}
            {estimatedSalary && (
              <div
                className="flex items-center gap-3 rounded-lg p-4"
                style={{
                  backgroundColor: 'var(--color-surface-2)',
                  border: '1px dashed var(--color-border-strong)',
                }}
              >
                <DollarSign size={18} style={{ color: 'var(--color-ink-faint)' }} strokeWidth={1.8} />
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <p className="text-xs font-medium uppercase tracking-wider" style={{ color: 'var(--color-ink-faint)' }}>
                      Estimated base salary
                    </p>
                    <span
                      className="rounded px-1.5 py-px text-xs"
                      style={{
                        backgroundColor: 'var(--color-surface)',
                        color: 'var(--color-ink-muted)',
                        border: '1px solid var(--color-border)',
                        fontSize: '10px',
                      }}
                    >
                      AI estimate{estConfidence ? ` · ${estConfidence} confidence` : ''}
                    </span>
                  </div>
                  <p
                    className="text-base font-semibold tabular-nums"
                    style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-ink-muted)' }}
                  >
                    {estimatedSalary}
                  </p>
                  <p className="text-xs mt-0.5" style={{ color: 'var(--color-ink-faint)' }}>
                    Estimated from role, seniority &amp; market — not disclosed by the employer.
                  </p>
                </div>
              </div>
            )}

            {/* Seniority badge */}
            {senColor && job.seniority && (
              <div className="flex items-center gap-2">
                <span
                  className="inline-flex items-center rounded px-3 py-1 text-xs font-semibold uppercase tracking-wider"
                  style={{ backgroundColor: senColor.bg, color: senColor.text }}
                >
                  {job.seniority}
                </span>
              </div>
            )}

            {/* Skills */}
            {d.required_skills.length > 0 && (
              <section aria-labelledby="skills-heading">
                <h3
                  id="skills-heading"
                  className="text-xs font-semibold uppercase tracking-widest mb-2.5"
                  style={{ color: 'var(--color-ink-faint)' }}
                >
                  Required skills
                </h3>
                <div className="flex flex-wrap gap-2">
                  {d.required_skills.map(skill => (
                    <span
                      key={skill}
                      className="text-sm rounded-full px-3 py-1"
                      style={{
                        backgroundColor: 'var(--color-surface-2)',
                        color: 'var(--color-ink-muted)',
                        border: '1px solid var(--color-border)',
                      }}
                    >
                      {skill}
                    </span>
                  ))}
                </div>
              </section>
            )}

            {/* Description */}
            <section aria-labelledby="desc-heading">
              <h3
                id="desc-heading"
                className="text-xs font-semibold uppercase tracking-widest mb-3"
                style={{ color: 'var(--color-ink-faint)' }}
              >
                Job description
              </h3>
              {loading ? (
                <div className="flex flex-col gap-2 animate-pulse">
                  {[100, 80, 95, 70, 85].map((w, i) => (
                    <div
                      key={i}
                      className="h-3.5 rounded"
                      style={{ backgroundColor: 'var(--color-border)', width: `${w}%` }}
                    />
                  ))}
                </div>
              ) : (
                <div
                  className="text-sm leading-relaxed whitespace-pre-wrap"
                  style={{ color: 'var(--color-ink-muted)' }}
                >
                  {/* Show the condensed AI summary. Fall back to the full
                      description (still stored in the backend) when a job has no
                      summary, then to the list excerpt, then a neutral placeholder
                      so the panel is never blank. */}
                  {detail?.description_summary ||
                    detail?.description_clean ||
                    job.description_excerpt ||
                    'No description available.'}
                </div>
              )}
            </section>
          </div>
        </div>

        {/* Sticky apply CTA */}
        <div
          className="flex-shrink-0 px-6 py-4"
          style={{ borderTop: '1px solid var(--color-border)', backgroundColor: 'var(--color-surface)' }}
        >
          <a
            href={job.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex w-full items-center justify-center gap-2 rounded py-3 text-sm font-semibold transition-all duration-200 cursor-pointer"
            style={{ backgroundColor: '#059669', color: '#fff' }}
            onMouseEnter={e => ((e.currentTarget as HTMLAnchorElement).style.backgroundColor = '#047857')}
            onMouseLeave={e => ((e.currentTarget as HTMLAnchorElement).style.backgroundColor = '#059669')}
          >
            Apply on company site
            <ExternalLink size={15} strokeWidth={2} />
          </a>
          <p className="text-center text-xs mt-2" style={{ color: 'var(--color-ink-faint)' }}>
            Opens the employer's careers page in a new tab
          </p>
        </div>
      </div>
    </>
  )
}
