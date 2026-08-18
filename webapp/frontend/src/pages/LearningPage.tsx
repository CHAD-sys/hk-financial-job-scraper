import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowUpRight, Clock, GraduationCap, MapPin, Radio } from 'lucide-react'
import Nav from '../components/Nav'
import VideoFacade from '../components/VideoFacade'
import { fetchLearningContent, type LearningContentResponse } from '../api/client'
import {
  FEATURED_VIDEOS, CHANNEL_URL, PLATFORM_URL, SUBSCRIBER_LINE, type FeaturedVideo,
} from '../content/featuredVideos'
import {
  MISSION, STRANDS, COURSES, TRAINER, EVENTS,
  EDUCATION_URL, TECH_TRAINING_URL, EVENTS_URL, type ClubEvent,
} from '../content/learning'

/**
 * Learning — the third product, as its own route.
 *
 * It used to be a section on the portal, which put it in a different class from
 * Careers (a real page at /jobs): a door that only scrolled you further down the
 * page you were already on. It is now a page, so all three doors behave alike.
 *
 * The page is built on credentials rather than persuasion — named trainer with
 * listed certifications, real venues, a curated shelf of actual sessions. That is
 * what an executive audience checks, and it is the only claim we can fully back:
 * every figure and title here is the Club's own (see content/learning.ts).
 */

/** Phones show this many videos; `sm` and up show the full shelf. */
const MOBILE_VIDEO_COUNT = 3

/**
 * Gold for use on the navy hero.
 *
 * The page gold (--color-gold, #9A6F00) is tuned for the light surfaces the rest
 * of the site uses; on #0B1628 it measures 4.01:1, which clears AA for the large
 * heading but fails the 4.5:1 floor for the small eyebrow above it. The token set
 * already carries a brighter gold for exactly this situation — it reads 7.99:1 on
 * the same navy — so the dark band uses that one throughout rather than mixing
 * two golds in a single hero.
 */
const GOLD_ON_NAVY = 'var(--color-gold-star)'

/**
 * Format an ISO date without constructing a Date.
 *
 * `new Date('2026-07-16')` is parsed as UTC midnight, so a viewer west of UTC
 * would render it as the 15th. These are published event dates — they must read
 * the same in Hong Kong and New York.
 */
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
function formatDate(iso: string): string {
  const [y, m, d] = iso.split('-')
  return `${Number(d)} ${MONTHS[Number(m) - 1]} ${y}`
}

type LearningEventView = ClubEvent & { id?: string; detail_url?: string }

function formatRefreshDate(iso: string): string {
  return new Intl.DateTimeFormat('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Asia/Hong_Kong',
  }).format(new Date(iso))
}

function hongKongToday(): string {
  const parts = new Intl.DateTimeFormat('en', {
    year: 'numeric', month: '2-digit', day: '2-digit', timeZone: 'Asia/Hong_Kong',
  }).formatToParts(new Date())
  const value = Object.fromEntries(parts.map(part => [part.type, part.value]))
  return `${value.year}-${value.month}-${value.day}`
}

export default function LearningPage() {
  const [live, setLive] = useState<LearningContentResponse | null>(null)

  useEffect(() => {
    let active = true
    fetchLearningContent()
      .then(content => {
        if (active && content.available) setLive(content)
      })
      .catch(() => undefined) // the compiled curated shelf remains the safe fallback
    return () => { active = false }
  }, [])

  const videos: FeaturedVideo[] = live?.videos.length
    ? live.videos.slice(0, 6).map(({ id, title, topic }) => ({ id, title, topic }))
    : FEATURED_VIDEOS
  const events: LearningEventView[] = live?.events.length
    ? live.events
    : EVENTS

  return (
    <div style={{ backgroundColor: 'var(--color-surface-2)', minHeight: '100dvh' }}>
      <title>Learning &amp; Events for HK Finance — FinEx Careers</title>
      <meta
        name="description"
        content="Professional learning from the Financial Executive Club: training strands, a video library and upcoming events for Hong Kong finance professionals."
      />
      <Nav />
      <main>
        <LearningHero eventCount={events.length} />
        <StrandsSection />
        <LibrarySection videos={videos} updatedAt={live?.sources.videos?.last_success_at} />
        <TrainingSection />
        <EventsSection events={events} updatedAt={live?.sources.events?.last_success_at} />
      </main>
      <LearningFooter />
    </div>
  )
}

// ── Hero ──────────────────────────────────────────────────────────────────────

/**
 * Navy band, matching /about. The portal and the job board are light; giving the
 * page a dark opening is what makes it read as its own destination rather than a
 * continuation of wherever you came from.
 */
function LearningHero({ eventCount }: { eventCount: number }) {
  return (
    <section aria-labelledby="learning-heading" style={{ backgroundColor: 'var(--color-masthead)' }}>
      <div className="mx-auto max-w-7xl px-6 py-16 lg:px-8 lg:py-20">
        <p
          className="text-xs font-semibold uppercase"
          style={{ color: GOLD_ON_NAVY, letterSpacing: '0.14em' }}
        >
          03 &middot; Professional L&amp;D
        </p>

        <h1
          id="learning-heading"
          className="mt-4 max-w-4xl leading-[1.08] tracking-tight text-balance"
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 'clamp(2.1rem, 4.4vw, 3.5rem)',
            fontWeight: 700,
            color: 'var(--color-ink-inverse)',
            letterSpacing: '-0.025em',
          }}
        >
          Education &amp;{' '}
          <em className="not-italic" style={{ color: GOLD_ON_NAVY }}>
            Professional Development
          </em>
        </h1>

        <p
          className="mt-6 max-w-2xl text-lg leading-relaxed"
          style={{ color: 'rgba(248,250,252,0.72)' }}
        >
          {MISSION}
        </p>

        {/* Four figures, all of them backed by something on this page — the shelf
            below, the catalogue below that, the venue list at the bottom. */}
        <dl className="mt-10 flex flex-wrap gap-x-10 gap-y-5">
          <Stat value={SUBSCRIBER_LINE.replace(' subscribers', '')} label="Subscribers" />
          <Stat value={String(STRANDS.length)} label="Programme strands" />
          <Stat value={String(COURSES.length)} label="AI / Tech courses" />
          <Stat value={String(eventCount)} label="Sessions listed" />
        </dl>
      </div>
    </section>
  )
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div>
      <dt className="sr-only">{label}</dt>
      <dd
        className="text-2xl font-semibold tabular-nums"
        style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-ink-inverse)' }}
      >
        {value}
      </dd>
      <span
        className="mt-1 block text-xs font-semibold uppercase"
        style={{ color: 'rgba(248,250,252,0.55)', letterSpacing: '0.1em' }}
      >
        {label}
      </span>
    </div>
  )
}

// ── Section furniture ─────────────────────────────────────────────────────────

/**
 * One section head. Every section on the page opens the same way — gold eyebrow,
 * display heading, one line of standfirst — so the page reads as one document
 * rather than four stitched-together blocks.
 */
function SectionHead({
  eyebrow, title, children, id,
}: { eyebrow: string; title: string; children?: React.ReactNode; id: string }) {
  return (
    <>
      <p
        className="text-xs font-semibold uppercase"
        style={{ color: 'var(--color-gold)', letterSpacing: '0.14em' }}
      >
        {eyebrow}
      </p>
      <h2
        id={id}
        className="mt-3 text-3xl tracking-tight lg:text-4xl"
        style={{
          fontFamily: 'var(--font-display)',
          fontWeight: 700,
          color: 'var(--color-ink)',
          letterSpacing: '-0.025em',
        }}
      >
        {title}
      </h2>
      {children && (
        <p className="mt-4 max-w-2xl text-base leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>
          {children}
        </p>
      )}
    </>
  )
}

/** Small outbound link, used once per section to point at the Club's own page. */
function SourceLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="mt-8 inline-flex items-center gap-1.5 text-sm font-semibold"
      style={{ color: 'var(--color-blue)' }}
    >
      {children}
      <ArrowUpRight size={15} strokeWidth={2} />
    </a>
  )
}

// ── 01 · The three strands ────────────────────────────────────────────────────

function StrandsSection() {
  return (
    <section
      aria-labelledby="strands-heading"
      style={{ backgroundColor: 'var(--color-surface)', borderBottom: '1px solid var(--color-border)' }}
    >
      <div className="mx-auto max-w-7xl px-6 py-16 lg:px-8 lg:py-20">
        {/* No SectionHead here: this section's heading and lead were dropped, so
            the eyebrow alone carries the section's accessible name. */}
        <p
          id="strands-heading"
          className="text-xs font-semibold uppercase"
          style={{ color: 'var(--color-gold)', letterSpacing: '0.14em' }}
        >
          The programme
        </p>

        <div className="mt-10 grid gap-6 lg:grid-cols-3">
          {STRANDS.map(s => (
            <article
              key={s.index}
              className="relative flex flex-col rounded-xl p-7 lg:p-8"
              style={{
                backgroundColor: 'var(--color-surface)',
                border: '1px solid var(--color-border)',
                boxShadow: 'var(--shadow-card)',
              }}
            >
              {/* Gold rule along the top edge — same accent as the portal doors. */}
              <span
                aria-hidden="true"
                className="absolute inset-x-0 top-0 h-0.5 rounded-t-xl"
                style={{ backgroundColor: 'var(--color-gold)' }}
              />
              <span
                aria-hidden="true"
                className="text-xs font-semibold tabular-nums"
                style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-ink-faint)' }}
              >
                {s.index}
              </span>
              <span
                className="mt-5 text-xs font-semibold uppercase"
                style={{ color: 'var(--color-gold)', letterSpacing: '0.14em' }}
              >
                {s.format}
              </span>
              <h3
                className="mt-2 text-2xl leading-tight tracking-tight"
                style={{
                  fontFamily: 'var(--font-display)',
                  fontWeight: 700,
                  color: 'var(--color-ink)',
                  letterSpacing: '-0.02em',
                }}
              >
                {s.name}
              </h3>
              <p className="mt-3 grow text-sm leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>
                {s.body}
              </p>

              <ul className="mt-6 flex flex-wrap gap-2" aria-label={`${s.name} topics`}>
                {s.topics.map(t => (
                  <li
                    key={t}
                    className="rounded-full px-2.5 py-1 text-xs font-medium"
                    style={{
                      backgroundColor: 'var(--color-surface-2)',
                      border: '1px solid var(--color-border)',
                      color: 'var(--color-ink-muted)',
                    }}
                  >
                    {t}
                  </li>
                ))}
              </ul>
            </article>
          ))}
        </div>

        <SourceLink href={EDUCATION_URL}>See the full programme</SourceLink>
      </div>
    </section>
  )
}

// ── 02 · The video shelf ──────────────────────────────────────────────────────

function LibrarySection({
  videos,
  updatedAt,
}: {
  videos: FeaturedVideo[]
  updatedAt?: string | null
}) {
  return (
    <section
      aria-labelledby="library-heading"
      style={{ borderBottom: '1px solid var(--color-border)' }}
    >
      <div className="mx-auto max-w-7xl px-6 py-16 lg:px-8 lg:py-20">
        <div className="flex flex-wrap items-end justify-between gap-6">
          <div>
            <SectionHead id="library-heading" eyebrow="Online platform" title="Latest from FinEx Club">
              Interviews, training sessions and market analysis from the Club&rsquo;s channel.
            </SectionHead>
          </div>
          <span
            className="shrink-0 text-sm font-semibold tabular-nums"
            style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-ink)' }}
          >
            {updatedAt ? `Updated ${formatRefreshDate(updatedAt)}` : SUBSCRIBER_LINE}
          </span>
        </div>

        {/* Phones show the first three. Hidden with CSS rather than a sliced array
            so the markup is identical at every width — no resize listener, and
            `display:none` grid items collapse their row gap too. */}
        <div className="mt-10 grid gap-x-6 gap-y-9 sm:grid-cols-2 lg:grid-cols-3">
          {videos.map((v, i) => (
            <div key={v.id} className={i >= MOBILE_VIDEO_COUNT ? 'hidden sm:block' : undefined}>
              <VideoFacade video={v} />
            </div>
          ))}
        </div>

        <div className="flex flex-wrap gap-x-8">
          <SourceLink href={PLATFORM_URL}>The full library</SourceLink>
          <SourceLink href={CHANNEL_URL}>Visit the channel</SourceLink>
        </div>
      </div>
    </section>
  )
}

// ── 03 · AI/Tech training ─────────────────────────────────────────────────────

function TrainingSection() {
  return (
    <section
      aria-labelledby="training-heading"
      style={{ backgroundColor: 'var(--color-surface)', borderBottom: '1px solid var(--color-border)' }}
    >
      <div className="mx-auto max-w-7xl px-6 py-16 lg:px-8 lg:py-20">
        <SectionHead id="training-heading" eyebrow="AI / Tech training" title="On-demand technical upskilling">
          Custom workshops delivered with a master trainer, sized to a half day or a full day
          and run for a team rather than a public cohort.
        </SectionHead>

        <div className="mt-10 grid gap-10 lg:grid-cols-[1.4fr_1fr] lg:gap-14">
          {/* Catalogue — a list, not cards. Five items that differ only in subject
              read better as rows; cards would imply they are alternatives. */}
          <ol className="flex flex-col">
            {COURSES.map((c, i) => (
              <li
                key={c.index}
                className="flex gap-5 py-6"
                style={{ borderTop: i === 0 ? 'none' : '1px solid var(--color-border)' }}
              >
                <span
                  aria-hidden="true"
                  className="shrink-0 pt-1 text-xs font-semibold tabular-nums"
                  style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-ink-faint)' }}
                >
                  {c.index}
                </span>
                <div className="min-w-0">
                  <h3
                    className="text-lg leading-snug tracking-tight"
                    style={{
                      fontFamily: 'var(--font-display)',
                      fontWeight: 700,
                      color: 'var(--color-ink)',
                      letterSpacing: '-0.015em',
                    }}
                  >
                    {c.title}
                  </h3>
                  <p
                    className="mt-1 text-xs font-semibold uppercase"
                    style={{ color: 'var(--color-gold)', letterSpacing: '0.1em' }}
                  >
                    {c.lede}
                  </p>
                  <p className="mt-2 text-sm leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>
                    {c.body}
                  </p>
                  <p
                    className="mt-3 inline-flex items-center gap-1.5 text-xs font-medium"
                    style={{ color: 'var(--color-ink-faint)' }}
                  >
                    <Clock size={13} strokeWidth={2} aria-hidden="true" />
                    {c.duration}
                  </p>
                </div>
              </li>
            ))}
          </ol>

          {/* Trainer credentials. This is the section's trust signal, so it sits
              beside the catalogue at desktop width rather than below it. */}
          <aside
            className="h-fit rounded-xl p-7"
            style={{
              backgroundColor: 'var(--color-surface-2)',
              border: '1px solid var(--color-border)',
            }}
          >
            <span
              className="inline-flex items-center gap-2 text-xs font-semibold uppercase"
              style={{ color: 'var(--color-gold)', letterSpacing: '0.12em' }}
            >
              <GraduationCap size={14} strokeWidth={2} aria-hidden="true" />
              {TRAINER.role}
            </span>
            <p
              className="mt-3 text-2xl tracking-tight"
              style={{
                fontFamily: 'var(--font-display)',
                fontWeight: 700,
                color: 'var(--color-ink)',
                letterSpacing: '-0.02em',
              }}
            >
              {TRAINER.name}
            </p>

            <CredentialList title="Education" items={[...TRAINER.education]} />
            <CredentialList title="Certifications" items={[...TRAINER.certifications]} />
          </aside>
        </div>

        <SourceLink href={TECH_TRAINING_URL}>Enquire about training</SourceLink>
      </div>
    </section>
  )
}

function CredentialList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="mt-6">
      <p
        className="text-xs font-semibold uppercase"
        style={{ color: 'var(--color-ink-faint)', letterSpacing: '0.1em' }}
      >
        {title}
      </p>
      <ul className="mt-2 flex flex-col gap-1.5">
        {items.map(c => (
          <li key={c} className="text-sm leading-snug" style={{ color: 'var(--color-ink-muted)' }}>
            {c}
          </li>
        ))}
      </ul>
    </div>
  )
}

// ── 04 · Where the Club has convened ──────────────────────────────────────────

/**
 * Past sessions, explicitly framed as a track record.
 *
 * Every event the Club lists has already happened (the most recent ran 16 July
 * 2026), so labelling this "Upcoming" would advertise seminars nobody can attend.
 * As a record of where the Club has convened — State Street, Baker Tilly, JW
 * Marriott — it is doing the job the "Trust & Authority" pattern wants anyway:
 * industry recognition, verifiable.
 */
function EventsSection({
  events,
  updatedAt,
}: {
  events: LearningEventView[]
  updatedAt?: string | null
}) {
  const today = hongKongToday()
  const { upcoming, recent } = useMemo(() => ({
    upcoming: events.filter(event => event.date >= today).sort((a, b) => a.date.localeCompare(b.date)),
    recent: events.filter(event => event.date < today).sort((a, b) => b.date.localeCompare(a.date)),
  }), [events, today])
  const visibleEvents = [...upcoming, ...recent.slice(0, 7)]
  const hasUpcoming = upcoming.length > 0

  return (
    <section aria-labelledby="events-heading">
      <div className="mx-auto max-w-7xl px-6 py-16 lg:px-8 lg:py-20">
        <SectionHead
          id="events-heading"
          eyebrow="Seminars &amp; events"
          title={hasUpcoming ? 'Coming up at FinEx Club' : 'Where the Club has convened'}
        >
          {hasUpcoming
            ? 'Upcoming seminars and events, followed by the Club’s most recent sessions.'
            : 'Recent sessions hosted with partner institutions across Hong Kong.'}
        </SectionHead>

        {updatedAt && (
          <p className="mt-4 text-xs font-medium" style={{ color: 'var(--color-ink-faint)' }}>
            Updated automatically {formatRefreshDate(updatedAt)}
          </p>
        )}

        <ul className="mt-10 flex flex-col">
          {visibleEvents.map((e, i) => (
            <li
              key={e.id ?? `${e.date}:${e.title}`}
              className="flex flex-col gap-2 py-5 sm:flex-row sm:items-baseline sm:gap-8"
              style={{ borderTop: i === 0 ? 'none' : '1px solid var(--color-border)' }}
            >
              <time
                dateTime={e.date}
                className="shrink-0 text-sm font-semibold tabular-nums sm:w-32"
                style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-ink)' }}
              >
                {formatDate(e.date)}
              </time>
              <div className="min-w-0">
                {e.detail_url ? (
                  <a
                    href={e.detail_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-base font-medium leading-snug no-underline hover:underline"
                    style={{ color: 'var(--color-ink)' }}
                  >
                    {e.title}
                  </a>
                ) : (
                  <p className="text-base leading-snug" style={{ color: 'var(--color-ink)', fontWeight: 500 }}>
                    {e.title}
                  </p>
                )}
                <p
                  className="mt-1.5 flex items-center gap-1.5 text-sm"
                  style={{ color: 'var(--color-ink-muted)' }}
                >
                  {e.online
                    ? <Radio size={13} strokeWidth={2} aria-hidden="true" />
                    : <MapPin size={13} strokeWidth={2} aria-hidden="true" />}
                  {e.venue}
                </p>
              </div>
            </li>
          ))}
        </ul>

        <SourceLink href={EVENTS_URL}>All events</SourceLink>
      </div>
    </section>
  )
}

// ── Footer ────────────────────────────────────────────────────────────────────

function LearningFooter() {
  return (
    <footer style={{ borderTop: '1px solid var(--color-border)' }}>
      <div className="mx-auto flex max-w-7xl flex-col gap-4 px-6 py-8 sm:flex-row sm:items-center sm:justify-between lg:px-8">
        <span className="text-sm font-semibold tracking-tight" style={{ fontFamily: 'var(--font-display)', color: 'var(--color-ink)' }}>
          FinEx <em className="not-italic" style={{ color: 'var(--color-gold)' }}>Careers</em>
          <span className="ml-2 text-xs font-normal" style={{ color: 'var(--color-ink-faint)' }}>
            &mdash; a Financial Executive Club platform
          </span>
        </span>
        <nav className="flex flex-wrap gap-x-6 gap-y-2" aria-label="Footer navigation">
          <Link to="/jobs" className="text-xs font-medium no-underline" style={{ color: 'var(--color-ink-faint)' }}>Browse roles</Link>
          <a
            href="https://www.finexclub.org/mentor-program"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-xs font-medium no-underline"
            style={{ color: 'var(--color-ink-faint)' }}
          >
            Consultation
            <ArrowUpRight size={11} strokeWidth={2} aria-hidden="true" />
          </a>
          <Link to="/about" className="text-xs font-medium no-underline" style={{ color: 'var(--color-ink-faint)' }}>About</Link>
        </nav>
      </div>
    </footer>
  )
}
