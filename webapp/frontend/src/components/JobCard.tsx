import { Bookmark, MapPin, Briefcase, Clock, Star, Flame, Sparkles, Repeat2, Users, EyeOff, ShieldCheck, Archive, SquarePen } from 'lucide-react'
import type { Job, LinkedInPostSignals } from '../api/client'
import { SourceTag } from './SourceBadges'
import {
  formatSalary, formatEstimatedSalary, timeAgo, monogram, displayCompany,
  getSectorColor,
  formatRemoteType, shortLocation,
} from '../utils/format'

interface Props {
  job: Job
  saved: boolean
  onToggleSave: (job: Job) => void
  onClick: (job: Job) => void
  /**
   * Open the admin edit drawer for this posting.
   *
   * Optional, and absent is the normal case: the board passes it only for a
   * signed-in admin, so an ordinary Seeker's card never renders the control at
   * all. The gate that matters is the server's (`require_admin` on
   * /api/admin/jobs/*) — this prop only decides whether the affordance is
   * drawn, never whether the write is allowed.
   */
  onEdit?: (job: Job) => void
}

type SectorColor = ReturnType<typeof getSectorColor>

/**
 * The palette a closed Role borrows in place of its sector's.
 *
 * The sector is still true, but on a closed card it is competing for the one
 * thing the card needs to say. Substituting it here rather than branching at
 * each use means the monogram, the sector chip and the hover border all go
 * neutral from one line.
 */
const CLOSED_NEUTRAL: SectorColor = {
  bg: 'var(--color-surface-2)',
  // ink-muted, not ink-faint. Draining the colour out of these chips is the
  // point; draining the contrast out of them is not — faint grey on surface-2
  // measures ~2.4:1, and a closed Role's sector and seniority are still facts
  // someone has to be able to read. Muted holds ~5.6:1 and is just as neutral.
  text: 'var(--color-ink-muted)',
  border: 'var(--color-border-strong)',
  accent: 'var(--color-border-strong)',
}

export default function JobCard({ job, saved, onToggleSave, onClick, onEdit }: Props) {
  const sectorColor = job.closed ? CLOSED_NEUTRAL : getSectorColor(job.sector)
  // Prefer the AI English title (Chinese postings); fall back to the original.
  const displayTitle = job.title_en || job.title
  // Masked for Recruiter Posts, which store the recruiter's name in `company`.
  const company = displayCompany(job.company, job.source_tier)

  return (
    <article
      // Still a card, still clickable when closed. Soft-delete keeps the row
      // precisely so a Seeker can revisit a vacancy they applied to after it
      // closed — greying it out and then refusing to open it would defeat the
      // reason the Role is still here at all.
      data-closed={job.closed || undefined}
      // The .job-card class (index.css) already declares its own transition —
      // box-shadow, border-color and transform, the exact three properties
      // onMouseEnter/onMouseLeave below change, with its own easing curve.
      // transition-all here was fully redundant with it (same specificity,
      // .job-card wins on source order) rather than an intentional override.
      className="job-card relative flex flex-col gap-4 rounded-lg p-5 cursor-pointer group"
      style={{
        backgroundColor: job.closed ? 'var(--color-closed-surface)' : 'var(--color-surface)',
        border: `1px solid ${job.closed ? 'var(--color-border-strong)' : 'var(--color-border)'}`,
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
        // Back to whichever resting border this card started with — restoring
        // --color-border unconditionally used to strip a closed card's heavier
        // edge the first time a cursor crossed it.
        el.style.borderColor = job.closed ? 'var(--color-border-strong)' : 'var(--color-border)'
        el.style.transform = 'translateY(0)'
      }}
    >
      {/* The head of the card: a 2px sector accent while the Role is open, a
          full status band once it has closed. Same slot, two very different
          weights — which is the point. */}
      {job.closed ? (
        <ClosedBanner />
      ) : (
        <div
          className="absolute top-0 left-0 right-0 rounded-t-lg"
          style={{ height: '2px', backgroundColor: sectorColor.accent }}
          aria-hidden="true"
        />
      )}

      <CardHeader job={job} sectorColor={sectorColor} saved={saved} onToggleSave={onToggleSave} onEdit={onEdit} />

      {/* Title and the facts that qualify it are ONE group, so they sit closer
          to each other (gap-2) than to anything else (the card's gap-4). The
          card used to space all five blocks equally, which is what made a
          fairly ordinary amount of content read as a wall: with no grouping,
          the eye has to parse every row to find out which ones belong
          together. */}
      <div className="flex flex-col gap-2">
        {/* A real button whose hit-area is stretched over the whole card, so
            the card is clickable AND keyboard/screen-reader operable. */}
        <h3
          className="text-lg font-semibold leading-snug line-clamp-2"
          style={{
            fontFamily: 'var(--font-display)',
            color: job.closed ? 'var(--color-ink-muted)' : 'var(--color-ink)',
            letterSpacing: '-0.01em',
          }}
        >
          <button
            type="button"
            onClick={() => onClick(job)}
            className="text-left cursor-pointer after:absolute after:inset-0 after:content-['']"
            aria-label={`${displayTitle} at ${company}`}
          >
            {displayTitle}
          </button>
        </h3>

        {job.match_reason && <MatchReason reason={job.match_reason} />}

        <MetaRow job={job} />
      </div>

      {/* Market signals — "Urgently hiring", "New", an applicant count — are all
          claims about a vacancy someone can still apply to. On a closed Role
          every one of them is false, so they come off rather than being greyed
          out. Dropping them is also what leaves the closed card with no chroma
          at all.

          A Recruiter Post carries none of these either: they come from job
          boards, and a personal LinkedIn post is not one. */}
      {!job.closed && job.source_tier !== 'social' && (
        <SignalBadges boardSignals={job.board_signals} />
      )}

      <CardFooter job={job} />
    </article>
  )
}

function MatchReason({ reason }: { reason: NonNullable<Job['match_reason']> }) {
  const label = {
    exact_title: 'Exact title match',
    title: 'Title match',
    title_en: 'English title match',
    company: 'Employer match',
    skills: 'Skills match',
    description: 'Related mention',
  }[reason]

  return (
    <span
      className="inline-flex w-fit rounded-sm px-1.5 py-0.5 text-xs font-medium"
      style={{
        color: 'var(--color-ink-muted)',
        backgroundColor: 'var(--color-surface-2)',
        border: '1px solid var(--color-border)',
      }}
    >
      {label}
    </span>
  )
}

// ── Header: monogram + company + sector badges + save ─────────────────────────

function CardHeader({
  job,
  sectorColor,
  saved,
  onToggleSave,
  onEdit,
}: {
  job: Job
  sectorColor: SectorColor
  saved: boolean
  onToggleSave: (job: Job) => void
  onEdit?: (job: Job) => void
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
          {monogram(displayCompany(job.company, job.source_tier))}
        </div>

        <div className="min-w-0">
          <p
            className="text-xs font-medium truncate"
            style={{ color: 'var(--color-ink-muted)' }}
          >
            {displayCompany(job.company, job.source_tier)}
          </p>
          {/* Sector label + tier badges. No Closed chip here any more — the
              band across the head of the card says it at a weight a chip in a
              row of chips never could, and saying it twice is what made the
              old treatment read as small print. */}
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 mt-0.5">
            {/* Sector — the word, not a swatch. The sector is already stated
                three times over: the accent rule at the head of the card, the
                tinted monogram, and this. Two of those are colour, so this one
                can just be text and the sector still reads instantly. */}
            <span
              className="inline-block text-xs font-medium"
              style={{ color: 'var(--color-ink-muted)', fontSize: '12px', letterSpacing: '0.04em' }}
            >
              {job.sector}
            </span>
            {job.source_tier === 'boutique' && (
              <span
                className="inline-flex flex-shrink-0 items-center gap-0.5 whitespace-nowrap rounded-sm px-1.5 py-0.5 font-semibold"
                style={{
                  // Provenance stays true after a Role closes, so the chip
                  // stays — but it gives up its gold. A closed card carries no
                  // chroma; that is the whole signal.
                  backgroundColor: job.closed
                    ? 'var(--color-surface-2)'
                    : 'var(--color-gold-light, rgba(201,162,74,0.12))',
                  color: job.closed ? 'var(--color-ink-muted)' : 'var(--color-gold)',
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
                className="inline-flex flex-shrink-0 items-center gap-0.5 whitespace-nowrap rounded-sm px-1.5 py-0.5 font-semibold"
                style={{
                  // A solid fill, not a tint — this chip has to outrank the
                  // Exclusive chip's gold tint and the plain sector text next
                  // to it, not just differ in hue from them. White-on-#6B4EFF
                  // measures ~5:1 contrast, clearing AA at this size. Same rule
                  // as the Exclusive chip for closed: the fact survives the
                  // Role closing, the colour (and the pop) does not.
                  backgroundColor: job.closed ? 'var(--color-surface-2)' : '#6B4EFF',
                  color: job.closed ? 'var(--color-ink-muted)' : '#FFFFFF',
                  boxShadow: job.closed ? 'none' : '0 1px 3px rgba(107,78,255,0.4)',
                  fontSize: '12px',
                  letterSpacing: '0.04em',
                }}
                title="Recruiter Posts — sourced from a recruiter's LinkedIn post, not a public job board"
              >
                <EyeOff size={10} strokeWidth={2} aria-hidden="true" />
                Hidden market
              </span>
            )}
            {/* Verified asserts the vacancy is "real, currently-open". That is
                exactly the claim a closed Role has stopped being able to make,
                so unlike the two chips above it is suppressed rather than
                greyed. */}
            {!job.closed && job.source_tier === 'social'
              && (job.board_signals?.linkedin_posts as unknown as LinkedInPostSignals | undefined)?.not_a_ghost_job && (
              <span
                className="inline-flex flex-shrink-0 items-center gap-0.5 whitespace-nowrap font-semibold"
                style={{
                  // Was a green fill. The shield already says "checked", and a
                  // card carrying the Hidden-market chip does not need a second
                  // colour arguing with it two millimetres away.
                  color: 'var(--color-ink-muted)',
                  fontSize: '12px',
                  letterSpacing: '0.04em',
                }}
                title="Confirmed: this role also appears on a public job board, so it's a real, currently-open vacancy"
              >
                <ShieldCheck size={10} strokeWidth={2} aria-hidden="true" />
                Verified
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Save, and — for an admin only — edit. Both raised above the card's
          stretched title button, and both stopPropagation: a click here must
          not also open the posting the way a click anywhere else on the card
          does. */}
      <div className="flex flex-shrink-0 items-center gap-0.5">
      {onEdit && (
        <button
          type="button"
          onClick={e => { e.stopPropagation(); onEdit(job) }}
          className="relative z-10 flex-shrink-0 p-1.5 rounded transition-colors duration-150 cursor-pointer"
          style={{ color: 'var(--color-ink-faint)' }}
          onMouseEnter={e => ((e.currentTarget as HTMLButtonElement).style.color = 'var(--color-blue)')}
          onMouseLeave={e => ((e.currentTarget as HTMLButtonElement).style.color = 'var(--color-ink-faint)')}
          aria-label={`Edit ${job.title_en || job.title}`}
          title="Edit this posting"
        >
          <SquarePen size={15} strokeWidth={1.8} />
        </button>
      )}
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
    </div>
  )
}

// ── Meta row: seniority / location / work type / internship ──────────────────

function MetaRow({ job }: { job: Job }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
      {/* Seniority — set, not filled.
          It used to be one of five coloured pills (navy / blue / slate / gold /
          grey), which spent five of the card's colours on a field that is
          already ranked by its own words: nobody needs a hue to know LEAD sits
          above JUNIOR. Small caps with wide tracking gives it the same
          at-a-glance weight typographically, and hands five colours back. */}
      {job.seniority && (
        <span
          className="text-xs font-bold uppercase"
          style={{ color: 'var(--color-ink)', fontSize: '11px', letterSpacing: '0.12em' }}
        >
          {job.seniority}
        </span>
      )}

      {/* Location */}
      <span className="flex items-center gap-1 text-xs" style={{ color: 'var(--color-ink-muted)' }}>
        <MapPin size={11} strokeWidth={1.8} />
        {shortLocation(job.locations)}
      </span>

      {/* Work type. Plain text with an icon — and no longer blue for Hybrid.
          Hybrid is a fact about the role, not a recommendation, and colouring
          one of three possible values made it look like the good one. */}
      {job.remote_type && (
        <span
          className="flex items-center gap-1 text-xs font-medium"
          style={{ color: 'var(--color-ink-muted)' }}
        >
          <Briefcase size={11} strokeWidth={1.8} aria-hidden="true" />
          {formatRemoteType(job.remote_type)}
        </span>
      )}

      {/* Where this Role was retrieved from. Sits at the end of the meta row
          rather than the head of it: provenance qualifies everything to its
          left, and is the last thing you want when scanning, not the first. */}
      <SourceTag source={job.source} />

      {/* Internship — an outline, not amber. It is a category of role, not a
          warning, and it was the only yellow in the interface. */}
      {job.is_internship && (
        <span
          className="text-xs rounded px-1.5 py-0.5"
          style={{ color: 'var(--color-ink-muted)', border: '1px solid var(--color-border)' }}
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

  // Four filled pills in red, green and two greys used to live here — a
  // traffic light's worth of colour for information nobody chooses a job on.
  // They are now set as text with their icons, and only ONE keeps a hue:
  // urgency is the single signal that changes what you do next (apply now
  // rather than later), so it is the only one allowed to shout. The icons carry
  // the meaning alongside the words, so nothing here depends on colour.
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
      {urgent && (
        <span
          className="inline-flex items-center gap-1 font-semibold"
          style={{ color: 'var(--color-destructive)' }}
        >
          <Flame size={11} strokeWidth={2.25} aria-hidden="true" />
          Urgently hiring
        </span>
      )}
      {isNew && (
        <span className="inline-flex items-center gap-1 font-semibold" style={{ color: 'var(--color-ink)' }}>
          <Sparkles size={11} strokeWidth={2.25} aria-hidden="true" />
          New
        </span>
      )}
      {reposted && (
        <span className="inline-flex items-center gap-1" style={{ color: 'var(--color-ink-muted)' }}>
          <Repeat2 size={11} strokeWidth={2} aria-hidden="true" />
          Reposted
        </span>
      )}
      {applicants !== null && (
        <span
          className="inline-flex items-center gap-1 tabular-nums"
          style={{ color: 'var(--color-ink-muted)' }}
          title="Candidates who have started applying (across boards)"
        >
          <Users size={11} strokeWidth={2} aria-hidden="true" />
          {applicants} applicant{applicants === 1 ? '' : 's'}
        </span>
      )}
    </div>
  )
}

// ── Recruiter attribution ────────────────────────────────────────────────────
//
// There isn't any, deliberately.
//
// The card used to carry a "via {recruiter}" chip and a mailto link, and the
// modal a profile link and a "DM {recruiter} to apply" CTA — LP-5 / decision #9
// in docs/PLAN_LINKEDIN_POSTS.md. That is reversed (owner decision, 2026-08-04):
// a Recruiter Post now names nobody and links to no inbox or profile. The only
// route to the person who posted it is the post itself, where they published on
// their own terms and control what happens next.
//
// The consequence to keep in mind: the recruiter's name is still fetched and
// still stored in board_signals. This is a display decision, not a data one, so
// nothing here stops the name reaching a browser through /api/jobs. If it must
// not leave the server at all, that is a change in webapp/backend/job_read.py.

// ── Skills ───────────────────────────────────────────────────────────────────
//
// Not on the card, on any tier.
//
// Five bordered pills of one or two words each was the single densest thing on
// the card and the least useful: a grid is scanned, and nobody compares roles
// on "Python, SQL, Credit Risk, Basel III, +1" at 12px. They were also the row
// that made every card look identical from a distance, because the same handful
// of skills recurs across most of the index.
//
// They remain in the detail view (JobDetailModal → SkillsSection), which is
// where a Seeker has decided to actually read one Role — except on a Recruiter
// Post, where there is no job description to extract them from at all.

// ── Footer: salary + posted date ──────────────────────────────────────────────

function CardFooter({ job }: { job: Job }) {
  const salary = formatSalary(job.salary_hkd_min, job.salary_hkd_max, job.salary_period)
  // Fall back to the AI estimate only when no salary is disclosed.
  const estimatedSalary = salary
    ? null
    : formatEstimatedSalary(job.salary_estimated_min, job.salary_estimated_max)

  return (
    // mt-auto pins the footer to the bottom so salary and date line up across a
    // row of unequal cards. That leaves slack above it on the short ones, and
    // since the skill chips went it is more slack than before — the hairline is
    // what turns it from a gap into a margin. Everything above is the Role;
    // below is what it pays and when it appeared.
    <div
      className="flex items-center justify-between mt-auto pt-3"
      style={{ borderTop: '1px solid var(--color-border)' }}
    >
      {salary ? (
        <span
          className="text-xs font-semibold tabular-nums"
          style={{ color: 'var(--color-ink)', fontFamily: 'var(--font-mono)' }}
        >
          {salary}
        </span>
      ) : estimatedSalary ? (
        // Two different claims wearing the same shape. An untouched figure is
        // the model's guess and stays muted with "AI est." on it. One a human
        // corrected is not a guess any more, so it gets the ink and confidence
        // of a real number and says "Checked" — calling a verified figure an AI
        // estimate is the same error as the reverse, just quieter.
        <span
          className="flex items-center gap-1 text-xs tabular-nums"
          style={{
            color: job.salary_verified ? 'var(--color-ink)' : 'var(--color-ink-faint)',
            fontFamily: 'var(--font-mono)',
            fontWeight: job.salary_verified ? 600 : undefined,
          }}
          title={job.salary_verified
            ? 'Reviewed and corrected by the FinEx team (not disclosed by employer)'
            : 'AI-estimated base salary (not disclosed by employer)'}
        >
          {estimatedSalary}
          <span
            className="rounded px-1 py-px"
            style={{
              fontFamily: 'var(--font-sans)',
              fontSize: '12px',
              letterSpacing: '0.04em',
              backgroundColor: job.salary_verified
                ? 'var(--color-success-bg)' : 'var(--color-surface-2)',
              color: job.salary_verified
                ? 'var(--color-success)' : 'var(--color-ink-faint)',
              border: `1px solid ${job.salary_verified
                ? 'var(--color-success-border)' : 'var(--color-border)'}`,
            }}
          >
            {job.salary_verified ? 'Checked' : 'AI est.'}
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


// ── Closed ────────────────────────────────────────────────────────────────────

/**
 * A Role that is no longer open.
 *
 * This was a chip in the badge row for a long time, sitting ahead of the sector
 * and tier chips so it was read first. The trouble was that it was only ever
 * read at all — at 12px among four other chips of the same size, on a card whose
 * surface was one barely-perceptible step off white, you had to already be
 * looking at that card to find out it had closed. In a grid of Saved Roles the
 * question is which card, and a chip cannot answer that.
 *
 * So it is a band: full card width, dark, at the very top where the eye enters
 * the card, carrying one word at a size that survives peripheral vision. It
 * replaces the 2px sector accent rather than sitting under it, which is why the
 * negative margins are here — the card's own p-5 would otherwise inset it and
 * it would read as another chip, just a wider one.
 *
 * Four channels, none load-bearing alone: value (a dark band on a light card),
 * position (the head of the card, before anything else), pattern (the hatching,
 * from index.css), and the word itself. Nothing here depends on hue, so it holds
 * up in greyscale and for anyone who cannot separate slate from white by tone.
 */
function ClosedBanner() {
  return (
    <div
      className="closed-band -mx-5 -mt-5 flex items-center justify-center gap-2 rounded-t-lg px-4 py-2"
      // Names the fortnight because that is exactly how long the promise holds:
      // a Closed Role drops out of Saved Roles once it has been closed that long
      // (ADR 0011). Saying "it stays saved" flat would have read as a bug the
      // first time one quietly went.
      title="This Role has closed. It stays in your saved roles for two weeks, so you can look back at what you applied to."
    >
      <Archive size={13} strokeWidth={2.5} style={{ color: 'var(--color-ink-inverse)' }} aria-hidden="true" />
      <span
        className="font-bold uppercase"
        style={{
          color: 'var(--color-ink-inverse)',
          fontSize: '13px',
          letterSpacing: '0.16em',
        }}
      >
        Closed
      </span>
    </div>
  )
}
