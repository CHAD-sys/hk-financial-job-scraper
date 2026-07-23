import { useEffect, useRef, useState } from 'react'
import {
  X, Bookmark, ExternalLink, MapPin, Briefcase,
  GraduationCap, DollarSign, Tag, Calendar, MessageCircle, UserRound, EyeOff, Mail, ShieldCheck,
} from 'lucide-react'
import type { Job, JobDetail, LinkedInPostSignals } from '../api/client'
import { fetchJobDetail } from '../api/client'
import SourceBadges from './SourceBadges'
import { useModalHistoryGuard } from '../hooks/useModalHistoryGuard'
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
  const dialogRef = useRef<HTMLDialogElement>(null)
  const [detail, setDetail] = useState<JobDetail | null>(null)
  const [loading, setLoading] = useState(true)
  // Drives the enter/exit transition defined in .job-detail-dialog (index.css):
  // 'entering' is the initial (off-screen) paint, flipped to 'entered' a frame
  // after mount so the transition actually plays; 'closing' plays the exit
  // transition before the parent's onClose actually unmounts this component.
  const [visualState, setVisualState] = useState<'entering' | 'entered' | 'closing'>('entering')
  const closingRef = useRef(false)

  const requestClose = () => {
    if (closingRef.current) return
    closingRef.current = true
    setVisualState('closing')
    window.setTimeout(onClose, 200) // exit is faster than the 300ms enter
  }

  // Phone/browser back gesture closes the modal instead of leaving /jobs.
  useModalHistoryGuard(requestClose)

  useEffect(() => {
    setLoading(true)
    fetchJobDetail(job.source, job.source_id)
      .then(setDetail)
      .finally(() => setLoading(false))
  }, [job.source, job.source_id])

  // Open as a modal: the native <dialog> gives us focus trapping and the
  // ::backdrop layer for free. Clicks on the ::backdrop are delivered with
  // the dialog itself as target, so backdrop-click-to-close (a pointer-only
  // convenience — keyboard users dismiss with Escape) is wired here rather
  // than in the markup. 'cancel' (Escape) is intercepted so it plays the same
  // exit animation as every other close path instead of closing instantly.
  useEffect(() => {
    const dlg = dialogRef.current
    if (!dlg) return
    dlg.showModal()
    // Double rAF: the initial off-screen style must actually paint before we
    // flip to 'entered', or the browser collapses the transition to a no-op.
    // Both ids are local to this effect run, so the cleanup below can read
    // them directly without the staleness a ref would introduce.
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

  // Lock body scroll
  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = '' }
  }, [])

  const sectorColor = getSectorColor(job.sector)
  const d = detail ?? job
  // Prefer the AI English title (Chinese postings); fall back to the original.
  const displayTitle = d.title_en || d.title
  const salary = formatSalary(d.salary_hkd_min, d.salary_hkd_max)
  // AI estimate only when no disclosed salary.
  const estimatedSalary = salary
    ? null
    : formatEstimatedSalary(d.salary_estimated_min, d.salary_estimated_max)

  return (
    <dialog
      ref={dialogRef}
      data-state={visualState}
      aria-label={displayTitle}
      className="job-detail-dialog"
    >
      <div className="flex h-full flex-col overflow-hidden">
        {/* Sector accent top bar */}
        <div
          className="flex-shrink-0"
          style={{ height: '3px', backgroundColor: sectorColor.accent }}
          aria-hidden="true"
        />

        <ModalHeader
          job={job}
          displayTitle={displayTitle}
          sectorColor={sectorColor}
          saved={saved}
          onToggleSave={onToggleSave}
          onClose={requestClose}
        />

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto">
          <div className="px-6 py-5 flex flex-col gap-5">

            {/* Job boards this vacancy is listed on (detail view only) */}
            <SourceBadges sources={detail?.sources ?? [job.source]} />

            {job.source_tier === 'social' && (
              <RecruiterAttribution
                signals={job.board_signals?.linkedin_posts as unknown as LinkedInPostSignals | undefined}
              />
            )}

            <MetaGrid d={d} />

            {salary && <DisclosedSalary salary={salary} />}
            {estimatedSalary && (
              <EstimatedSalary
                estimatedSalary={estimatedSalary}
                confidence={d.salary_estimated_confidence}
              />
            )}

            <SeniorityBadge seniority={job.seniority} />
            <SkillsSection skills={d.required_skills} />
            <DescriptionSection
              loading={loading}
              text={
                detail?.description_summary ||
                detail?.description_clean ||
                job.description_excerpt ||
                'No description available.'
              }
            />
          </div>
        </div>

        <ApplyFooter job={job} />
      </div>
    </dialog>
  )
}

// ── Header: badges + title + save/close ───────────────────────────────────────

function ModalHeader({
  job,
  displayTitle,
  sectorColor,
  saved,
  onToggleSave,
  onClose,
}: {
  job: Job
  displayTitle: string
  sectorColor: ReturnType<typeof getSectorColor>
  saved: boolean
  onToggleSave: (job: Job) => void
  onClose: () => void
}) {
  return (
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
              style={{ backgroundColor: 'var(--color-internship-light)', color: 'var(--color-internship)' }}
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
          type="button"
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
          type="button"
          onClick={onClose}
          className="flex min-h-11 min-w-11 items-center justify-center rounded transition-colors duration-150 cursor-pointer"
          style={{ color: 'var(--color-ink-faint)' }}
          onMouseEnter={e => ((e.currentTarget as HTMLButtonElement).style.backgroundColor = 'var(--color-surface-2)')}
          onMouseLeave={e => ((e.currentTarget as HTMLButtonElement).style.backgroundColor = 'transparent')}
          aria-label="Close"
        >
          <X size={18} strokeWidth={1.8} />
        </button>
      </div>
    </div>
  )
}

// ── Recruiter attribution (Recruiter Posts / source_tier === 'social') ───────
//
// company is already "Confidential via {recruiter}" when no employer was named
// (hk_jobs/posts/promote.py) — this section adds the WHY: this is a personal
// LinkedIn post by a recruiter, not a formal board listing, plus a link back
// to the original post and (via ApplyFooter) a "DM to apply" CTA, per
// PLAN_LINKEDIN_POSTS.md decision #9.

function RecruiterAttribution({ signals }: { signals: LinkedInPostSignals | undefined }) {
  if (!signals?.recruiter_name) return null
  return (
    <div
      className="flex items-start gap-3 rounded-lg p-4"
      style={{ backgroundColor: 'color-mix(in srgb, var(--color-recruiter) 6%, transparent)', border: '1px solid color-mix(in srgb, var(--color-recruiter) 22%, transparent)' }}
    >
      <EyeOff size={16} style={{ color: 'var(--color-recruiter)', marginTop: 2 }} strokeWidth={1.8} aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <p className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--color-recruiter)' }}>
            Recruiter Posts listing
          </p>
          {signals.not_a_ghost_job && (
            <span
              className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider"
              style={{ backgroundColor: 'var(--color-success-light)', color: 'var(--color-success)', border: '1px solid var(--color-success-border)' }}
              title="Confirmed: this role also appears on a public job board, so it's a real, currently-open vacancy"
            >
              <ShieldCheck size={10} strokeWidth={2.5} aria-hidden="true" />
              Verified
            </span>
          )}
        </div>
        <p className="text-sm mt-1" style={{ color: 'var(--color-ink)' }}>
          Sourced from a LinkedIn post by{' '}
          {signals.recruiter_profile_url ? (
            <a
              href={signals.recruiter_profile_url}
              target="_blank"
              rel="noopener noreferrer"
              className="font-semibold underline"
              style={{ color: 'var(--color-recruiter)' }}
            >
              {signals.recruiter_name}
            </a>
          ) : (
            <span className="font-semibold">{signals.recruiter_name}</span>
          )}
          {signals.employer_hint ? ` — described only as "${signals.employer_hint}"` : ''}.
          This role doesn't appear on any public job board.
        </p>
        {signals.recruiter_email && (
          <a
            href={`mailto:${signals.recruiter_email}`}
            className="inline-flex items-center gap-1.5 text-sm font-medium mt-2"
            style={{ color: 'var(--color-recruiter)' }}
          >
            <Mail size={13} strokeWidth={2} aria-hidden="true" />
            {signals.recruiter_email}
          </a>
        )}
      </div>
    </div>
  )
}

// ── Meta grid: location / work type / seniority / etc. ───────────────────────

function MetaGrid({ d }: { d: Job | JobDetail }) {
  return (
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
  )
}

// ── Salary — disclosed (gold, authoritative) ──────────────────────────────────

function DisclosedSalary({ salary }: { salary: string }) {
  return (
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
  )
}

// ── Salary — AI estimate (muted/neutral, clearly not disclosed) ──────────────

function EstimatedSalary({
  estimatedSalary,
  confidence,
}: {
  estimatedSalary: string
  confidence: string | null | undefined
}) {
  return (
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
              fontSize: '12px',
            }}
          >
            AI estimate{confidence ? ` · ${confidence} confidence` : ''}
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
  )
}

// ── Seniority badge ───────────────────────────────────────────────────────────

function SeniorityBadge({ seniority }: { seniority: string | null }) {
  const senColor = getSeniorityColor(seniority)
  if (!senColor || !seniority) return null
  return (
    <div className="flex items-center gap-2">
      <span
        className="inline-flex items-center rounded px-3 py-1 text-xs font-semibold uppercase tracking-wider"
        style={{ backgroundColor: senColor.bg, color: senColor.text }}
      >
        {seniority}
      </span>
    </div>
  )
}

// ── Skills ────────────────────────────────────────────────────────────────────

function SkillsSection({ skills }: { skills: string[] }) {
  if (skills.length === 0) return null
  return (
    <section aria-labelledby="skills-heading">
      <h3
        id="skills-heading"
        className="text-xs font-semibold uppercase tracking-widest mb-2.5"
        style={{ color: 'var(--color-ink-faint)' }}
      >
        Required skills
      </h3>
      <div className="flex flex-wrap gap-2">
        {skills.map(skill => (
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
  )
}

// ── Description (AI summary with fallbacks) ───────────────────────────────────

function DescriptionSection({ loading, text }: { loading: boolean; text: string }) {
  return (
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
          {/* Condensed AI summary, falling back to the full description (still
              stored in the backend), then the list excerpt, then a neutral
              placeholder so the panel is never blank. */}
          {text}
        </div>
      )}
    </section>
  )
}

// ── Sticky apply CTA ──────────────────────────────────────────────────────────
//
// For source_tier === 'social', job.url is the LinkedIn POST permalink (set
// in hk_jobs/posts/promote.py), not a company careers page — there's no
// formal "apply" flow, so the primary CTA is "DM to apply" (message the
// recruiter), with the original post as a secondary link, per decision #9.

function ApplyFooter({ job }: { job: Job }) {
  const signals = job.board_signals?.linkedin_posts as unknown as LinkedInPostSignals | undefined
  const profileUrl = job.source_tier === 'social' ? signals?.recruiter_profile_url : null

  if (profileUrl) {
    return (
      <div
        className="flex-shrink-0 px-6 py-4 flex flex-col gap-2"
        style={{ borderTop: '1px solid var(--color-border)', backgroundColor: 'var(--color-surface)' }}
      >
        <a
          href={profileUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="flex w-full items-center justify-center gap-2 rounded py-3 text-sm font-semibold transition-all duration-200 cursor-pointer"
          style={{ backgroundColor: 'var(--color-recruiter)', color: 'var(--color-ink-inverse)' }}
          onMouseEnter={e => ((e.currentTarget as HTMLAnchorElement).style.backgroundColor = 'var(--color-recruiter-hover)')}
          onMouseLeave={e => ((e.currentTarget as HTMLAnchorElement).style.backgroundColor = 'var(--color-recruiter)')}
        >
          <MessageCircle size={15} strokeWidth={2} />
          DM {signals?.recruiter_name ?? 'the recruiter'} to apply
        </a>
        {signals?.recruiter_email && (
          <a
            href={`mailto:${signals.recruiter_email}`}
            className="flex w-full items-center justify-center gap-2 rounded py-2.5 text-sm font-medium transition-all duration-200 cursor-pointer"
            style={{
              backgroundColor: 'var(--color-surface)',
              color: 'var(--color-recruiter)',
              border: '1px solid color-mix(in srgb, var(--color-recruiter) 35%, transparent)',
            }}
          >
            <Mail size={14} strokeWidth={2} />
            Email {signals.recruiter_name}
          </a>
        )}
        {job.url && (
          <a
            href={job.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center justify-center gap-1.5 text-xs font-medium py-1"
            style={{ color: 'var(--color-ink-faint)' }}
          >
            <UserRound size={12} strokeWidth={1.8} />
            View original LinkedIn post
          </a>
        )}
      </div>
    )
  }

  return (
    <div
      className="flex-shrink-0 px-6 py-4"
      style={{ borderTop: '1px solid var(--color-border)', backgroundColor: 'var(--color-surface)' }}
    >
      <a
        href={job.url}
        target="_blank"
        rel="noopener noreferrer"
        className="flex w-full items-center justify-center gap-2 rounded py-3 text-sm font-semibold transition-all duration-200 cursor-pointer"
        style={{ backgroundColor: 'var(--color-apply)', color: 'var(--color-ink-inverse)' }}
        onMouseEnter={e => ((e.currentTarget as HTMLAnchorElement).style.backgroundColor = 'var(--color-apply-hover)')}
        onMouseLeave={e => ((e.currentTarget as HTMLAnchorElement).style.backgroundColor = 'var(--color-apply)')}
      >
        Apply on company site
        <ExternalLink size={15} strokeWidth={2} />
      </a>
      <p className="text-center text-xs mt-2" style={{ color: 'var(--color-ink-faint)' }}>
        Opens the employer's careers page in a new tab
      </p>
    </div>
  )
}
