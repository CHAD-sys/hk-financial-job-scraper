import { Bookmark, MapPin, Clock } from 'lucide-react'
import type { Job } from '../api/client'
import {
  formatSalary, timeAgo, monogram,
  getSectorColor, getSeniorityColor,
  formatRemoteType, shortLocation,
} from '../utils/format'

interface Props {
  job: Job
  saved: boolean
  onToggleSave: (job: Job) => void
  onClick: (job: Job) => void
}

const SKILL_LIMIT = 4

export default function JobCard({ job, saved, onToggleSave, onClick }: Props) {
  const sectorColor = getSectorColor(job.sector)
  const senColor = getSeniorityColor(job.seniority)
  const salary = formatSalary(job.salary_hkd_min, job.salary_hkd_max)
  const visibleSkills = job.required_skills.slice(0, SKILL_LIMIT)
  const overflowCount = job.required_skills.length - SKILL_LIMIT

  return (
    <article
      onClick={() => onClick(job)}
      className="relative flex flex-col gap-3 rounded-lg p-5 cursor-pointer transition-all duration-200 group"
      style={{
        backgroundColor: 'var(--color-surface)',
        border: '1px solid var(--color-border)',
        boxShadow: 'var(--shadow-card)',
      }}
      onMouseEnter={e => {
        const el = e.currentTarget as HTMLElement
        el.style.boxShadow = 'var(--shadow-raised)'
        el.style.borderColor = sectorColor.accent
        el.style.transform = 'translateY(-2px)'
      }}
      onMouseLeave={e => {
        const el = e.currentTarget as HTMLElement
        el.style.boxShadow = 'var(--shadow-card)'
        el.style.borderColor = 'var(--color-border)'
        el.style.transform = 'translateY(0)'
      }}
      aria-label={`${job.title} at ${job.company}`}
    >
      {/* Sector accent bar */}
      <div
        className="absolute top-0 left-0 right-0 rounded-t-lg"
        style={{ height: '2px', backgroundColor: sectorColor.accent }}
        aria-hidden="true"
      />

      {/* Header row */}
      <div className="flex items-start justify-between gap-3 pt-1">
        <div className="flex items-center gap-3 min-w-0">
          {/* Company monogram */}
          <div
            className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-md text-sm font-bold select-none"
            style={{
              backgroundColor: sectorColor.bg,
              color: sectorColor.text,
              border: `1px solid ${sectorColor.border}`,
              fontFamily: 'var(--font-mono)',
              letterSpacing: '0.05em',
            }}
            aria-hidden="true"
          >
            {monogram(job.company)}
          </div>

          <div className="min-w-0">
            <p
              className="text-xs font-medium truncate"
              style={{ color: 'var(--color-ink-muted)' }}
            >
              {job.company}
            </p>
            {/* Sector label */}
            <span
              className="inline-block mt-0.5 text-xs font-medium rounded-sm px-1.5 py-0.5"
              style={{
                backgroundColor: sectorColor.bg,
                color: sectorColor.text,
                fontSize: '10px',
                letterSpacing: '0.04em',
              }}
            >
              {job.sector}
            </span>
          </div>
        </div>

        {/* Save button */}
        <button
          onClick={e => { e.stopPropagation(); onToggleSave(job) }}
          className="flex-shrink-0 p-1.5 rounded transition-colors duration-150 cursor-pointer"
          style={{
            color: saved ? 'var(--color-gold)' : 'var(--color-ink-faint)',
          }}
          onMouseEnter={e => ((e.currentTarget as HTMLButtonElement).style.color = 'var(--color-gold)')}
          onMouseLeave={e => {
            if (!saved)
              (e.currentTarget as HTMLButtonElement).style.color = 'var(--color-ink-faint)'
          }}
          aria-label={saved ? 'Unsave job' : 'Save job'}
          aria-pressed={saved}
        >
          <Bookmark
            size={16}
            strokeWidth={1.8}
            fill={saved ? 'currentColor' : 'none'}
          />
        </button>
      </div>

      {/* Title */}
      <h3
        className="text-base font-semibold leading-snug line-clamp-2"
        style={{
          fontFamily: 'var(--font-display)',
          color: 'var(--color-ink)',
          letterSpacing: '-0.01em',
        }}
      >
        {job.title}
      </h3>

      {/* Meta row */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        {/* Seniority badge */}
        {senColor && job.seniority && (
          <span
            className="inline-flex items-center rounded px-2 py-0.5 text-xs font-semibold uppercase tracking-wide"
            style={{
              backgroundColor: senColor.bg,
              color: senColor.text,
              fontSize: '10px',
              letterSpacing: '0.06em',
            }}
          >
            {job.seniority}
          </span>
        )}

        {/* Location */}
        <span className="flex items-center gap-1 text-xs" style={{ color: 'var(--color-ink-muted)' }}>
          <MapPin size={11} strokeWidth={1.8} />
          {shortLocation(job.locations)}
        </span>

        {/* Work type */}
        {job.remote_type && (
          <span
            className="text-xs rounded px-1.5 py-0.5"
            style={{
              backgroundColor: job.remote_type === 'hybrid' ? 'var(--color-blue-light)' : 'var(--color-surface-2)',
              color: job.remote_type === 'hybrid' ? 'var(--color-blue)' : 'var(--color-ink-muted)',
              border: '1px solid var(--color-border)',
            }}
          >
            {formatRemoteType(job.remote_type)}
          </span>
        )}

        {/* Internship badge */}
        {job.is_internship && (
          <span
            className="text-xs rounded px-1.5 py-0.5"
            style={{ backgroundColor: '#FEF9C3', color: '#854D0E', border: '1px solid #FDE68A' }}
          >
            Internship
          </span>
        )}
      </div>

      {/* Skills */}
      {visibleSkills.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {visibleSkills.map(skill => (
            <span
              key={skill}
              className="text-xs rounded-full px-2.5 py-0.5"
              style={{
                backgroundColor: 'var(--color-surface-2)',
                color: 'var(--color-ink-muted)',
                border: '1px solid var(--color-border)',
              }}
            >
              {skill}
            </span>
          ))}
          {overflowCount > 0 && (
            <span
              className="text-xs rounded-full px-2.5 py-0.5"
              style={{
                backgroundColor: 'var(--color-border)',
                color: 'var(--color-ink-muted)',
              }}
            >
              +{overflowCount}
            </span>
          )}
        </div>
      )}

      {/* Footer: salary + date */}
      <div className="flex items-center justify-between mt-auto pt-1">
        {salary ? (
          <span
            className="text-xs font-semibold tabular-nums"
            style={{ color: 'var(--color-ink)', fontFamily: 'var(--font-mono)' }}
          >
            {salary}
          </span>
        ) : (
          <span />
        )}
        <span className="flex items-center gap-1 text-xs" style={{ color: 'var(--color-ink-faint)' }}>
          <Clock size={10} strokeWidth={1.8} />
          {timeAgo(job.posted_at)}
        </span>
      </div>
    </article>
  )
}
