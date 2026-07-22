import { Bookmark, MapPin, Clock, Star, Flame, Sparkles, Repeat2, Users, EyeOff, UserRound, Mail } from 'lucide-react'
import type { Job, LinkedInPostSignals } from '../api/client'
import {
  formatSalary, formatEstimatedSalary, timeAgo, monogram,
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

type SectorColor = ReturnType<typeof getSectorColor>

export default function JobCard({ job, saved, onToggleSave, onClick }: Props) {
  const sectorColor = getSectorColor(job.sector)
  // Prefer the AI English title (Chinese postings); fall back to the original.
  const displayTitle = job.title_en || job.title

  return (
    <article
      className="job-card relative flex flex-col gap-3 rounded-lg p-5 cursor-pointer transition-all duration-200 group"
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
    >
      {/* Sector accent bar */}
      <div
        className="absolute top-0 left-0 right-0 rounded-t-lg"
        style={{ height: '2px', backgroundColor: sectorColor.accent }}
        aria-hidden="true"
      />

      <CardHeader job={job} sectorColor={sectorColor} saved={saved} onToggleSave={onToggleSave} />

      {/* Title — a real button whose hit-area is stretched over the whole card,
          so the card is clickable AND keyboard/screen-reader operable. */}
      <h3
        className="text-base font-semibold leading-snug line-clamp-2"
        style={{
          fontFamily: 'var(--font-display)',
          color: 'var(--color-ink)',
          letterSpacing: '-0.01em',
        }}
      >
        <button
          type="button"
          onClick={() => onClick(job)}
          className="text-left cursor-pointer after:absolute after:inset-0 after:content-['']"
          aria-label={`${displayTitle} at ${job.company}`}
        >
          {displayTitle}
        </button>
      </h3>

      <MetaRow job={job} />
      {job.source_tier === 'social' ? (
        <RecruiterBadge signals={job.board_signals?.linkedin_posts as unknown as LinkedInPostSignals | undefined} />
      ) : (
        <SignalBadges boardSignals={job.board_signals} />
      )}
      <SkillChips skills={job.required_skills} />
      <CardFooter job={job} />
    </article>
  )
}

// ── Header: monogram + company + sector badges + save ─────────────────────────

function CardHeader({
  job,
  sectorColor,
  saved,
  onToggleSave,
}: {
  job: Job
  sectorColor: SectorColor
  saved: boolean
  onToggleSave: (job: Job) => void
}) {
  return (
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
          {/* Sector label + Exclusive badge */}
          <div className="flex items-center gap-1.5 mt-0.5">
            <span
              className="inline-block text-xs font-medium rounded-sm px-1.5 py-0.5"
              style={{
                backgroundColor: sectorColor.bg,
                color: sectorColor.text,
                fontSize: '12px',
                letterSpacing: '0.04em',
              }}
            >
              {job.sector}
            </span>
            {job.source_tier === 'boutique' && (
              <span
                className="inline-flex items-center gap-0.5 rounded-sm px-1.5 py-0.5 font-semibold"
                style={{
                  backgroundColor: 'var(--color-gold-light, rgba(201,162,74,0.12))',
                  color: 'var(--color-gold)',
                  fontSize: '12px',
                  letterSpacing: '0.04em',
                }}
                title="Exclusive listing — sourced directly from a boutique firm's careers page"
              >
                <Star size={10} strokeWidth={2} fill="currentColor" aria-hidden="true" />
                Exclusive
              </span>
            )}
            {job.source_tier === 'social' && (
              <span
                className="inline-flex items-center gap-0.5 rounded-sm px-1.5 py-0.5 font-semibold"
                style={{
                  backgroundColor: 'rgba(107,78,255,0.12)',
                  color: '#6B4EFF',
                  fontSize: '12px',
                  letterSpacing: '0.04em',
                }}
                title="Secret Market — sourced from a recruiter's LinkedIn post, not a public job board"
              >
                <EyeOff size={10} strokeWidth={2} aria-hidden="true" />
                Hidden market
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Save button — raised above the card's stretched title button */}
      <button
        type="button"
        onClick={e => { e.stopPropagation(); onToggleSave(job) }}
        className="relative z-10 flex-shrink-0 p-1.5 rounded transition-colors duration-150 cursor-pointer"
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
  )
}

// ── Meta row: seniority / location / work type / internship ──────────────────

function MetaRow({ job }: { job: Job }) {
  const senColor = getSeniorityColor(job.seniority)
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
      {/* Seniority badge */}
      {senColor && job.seniority && (
        <span
          className="inline-flex items-center rounded px-2 py-0.5 text-xs font-semibold uppercase tracking-wide"
          style={{
            backgroundColor: senColor.bg,
            color: senColor.text,
            fontSize: '12px',
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
  )
}

// ── Market-signal badges (from the boards this vacancy is on) ─────────────────

function SignalBadges({ boardSignals }: { boardSignals: Job['board_signals'] }) {
  // Market signals, merged across every board this vacancy appears on.
  const signalSets = Object.values(boardSignals || {})
  const urgent = signalSets.some(s => s?.urgently_hiring)
  const isNew = signalSets.some(s => s?.new_job)
  const reposted = signalSets.some(s => s?.reposted)
  // Single pass: track the highest applicant count seen across boards.
  let applicants: number | null = null
  for (const s of signalSets) {
    const n = Number(s?.applicant_count)
    if (Number.isFinite(n) && n > 0 && (applicants === null || n > applicants)) applicants = n
  }

  if (!urgent && !isNew && !reposted && applicants === null) return null

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {urgent && (
        <span
          className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-semibold"
          style={{ backgroundColor: '#FEE2E2', color: '#B91C1C', border: '1px solid #FECACA', fontSize: '12px' }}
        >
          <Flame size={11} strokeWidth={2} aria-hidden="true" />
          Urgently hiring
        </span>
      )}
      {isNew && (
        <span
          className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-semibold"
          style={{ backgroundColor: '#DCFCE7', color: '#15803D', border: '1px solid #BBF7D0', fontSize: '12px' }}
        >
          <Sparkles size={11} strokeWidth={2} aria-hidden="true" />
          New
        </span>
      )}
      {reposted && (
        <span
          className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-medium"
          style={{ backgroundColor: 'var(--color-surface-2)', color: 'var(--color-ink-muted)', border: '1px solid var(--color-border)', fontSize: '12px' }}
        >
          <Repeat2 size={11} strokeWidth={2} aria-hidden="true" />
          Reposted
        </span>
      )}
      {applicants !== null && (
        <span
          className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-medium tabular-nums"
          style={{ backgroundColor: 'var(--color-surface-2)', color: 'var(--color-ink-muted)', border: '1px solid var(--color-border)', fontSize: '12px' }}
          title="Candidates who have started applying (across boards)"
        >
          <Users size={11} strokeWidth={2} aria-hidden="true" />
          {applicants} applicant{applicants === 1 ? '' : 's'}
        </span>
      )}
    </div>
  )
}

// ── Recruiter attribution (Secret Market / source_tier === 'social') ─────────

function RecruiterBadge({ signals }: { signals: LinkedInPostSignals | undefined }) {
  if (!signals?.recruiter_name) return null
  const likes = signals.engagement?.likes
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span
        className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-medium"
        style={{
          backgroundColor: 'rgba(107,78,255,0.08)',
          color: '#6B4EFF',
          border: '1px solid rgba(107,78,255,0.22)',
          fontSize: '12px',
        }}
        title="Posted by this recruiter on LinkedIn — not a formal job board listing"
      >
        <UserRound size={11} strokeWidth={2} aria-hidden="true" />
        via {signals.recruiter_name}
      </span>
      {signals.recruiter_email && (
        <a
          href={`mailto:${signals.recruiter_email}`}
          onClick={e => e.stopPropagation()}
          className="relative z-10 inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-medium"
          style={{
            backgroundColor: 'var(--color-surface-2)',
            color: 'var(--color-ink-muted)',
            border: '1px solid var(--color-border)',
            fontSize: '12px',
          }}
          title={`Email ${signals.recruiter_name}: ${signals.recruiter_email}`}
        >
          <Mail size={11} strokeWidth={2} aria-hidden="true" />
          Email
        </a>
      )}
      {typeof likes === 'number' && likes > 0 && (
        <span className="text-xs" style={{ color: 'var(--color-ink-faint)' }}>
          {likes} like{likes === 1 ? '' : 's'}
        </span>
      )}
    </div>
  )
}

// ── Skill chips with overflow count ───────────────────────────────────────────

function SkillChips({ skills }: { skills: string[] }) {
  const visibleSkills = skills.slice(0, SKILL_LIMIT)
  const overflowCount = skills.length - SKILL_LIMIT

  if (visibleSkills.length === 0) return null

  return (
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
  )
}

// ── Footer: salary + posted date ──────────────────────────────────────────────

function CardFooter({ job }: { job: Job }) {
  const salary = formatSalary(job.salary_hkd_min, job.salary_hkd_max)
  // Fall back to the AI estimate only when no salary is disclosed.
  const estimatedSalary = salary
    ? null
    : formatEstimatedSalary(job.salary_estimated_min, job.salary_estimated_max)

  return (
    <div className="flex items-center justify-between mt-auto pt-1">
      {salary ? (
        <span
          className="text-xs font-semibold tabular-nums"
          style={{ color: 'var(--color-ink)', fontFamily: 'var(--font-mono)' }}
        >
          {salary}
        </span>
      ) : estimatedSalary ? (
        // AI estimate — muted + "AI est." tag so it never reads as disclosed pay
        <span
          className="flex items-center gap-1 text-xs tabular-nums"
          style={{ color: 'var(--color-ink-faint)', fontFamily: 'var(--font-mono)' }}
          title="AI-estimated base salary (not disclosed by employer)"
        >
          {estimatedSalary}
          <span
            className="rounded px-1 py-px"
            style={{
              fontFamily: 'var(--font-sans)',
              fontSize: '12px',
              letterSpacing: '0.04em',
              backgroundColor: 'var(--color-surface-2)',
              color: 'var(--color-ink-faint)',
              border: '1px solid var(--color-border)',
            }}
          >
            AI est.
          </span>
        </span>
      ) : (
        <span />
      )}
      <span className="flex items-center gap-1 text-xs" style={{ color: 'var(--color-ink-faint)' }}>
        <Clock size={10} strokeWidth={1.8} />
        {timeAgo(job.posted_at)}
      </span>
    </div>
  )
}
