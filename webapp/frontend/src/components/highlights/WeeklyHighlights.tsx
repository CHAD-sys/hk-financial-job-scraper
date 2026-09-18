import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowRight,
  BriefcaseBusiness,
  GraduationCap,
  ListVideo,
  PlayCircle,
  Sparkles,
  TvMinimalPlay,
} from 'lucide-react'
import { fetchWeeklyHighlights, type WeeklyHighlightRole } from '../../api/client'
import {
  COMMITTEE_PLAYLIST_URL,
  COACH_HIGHLIGHTS,
  VIDEO_HIGHLIGHTS,
  YOUTUBE_CHANNEL_URL,
  mergeWeeklyHighlights,
  type CoachHighlight,
  type CourseHighlight,
  type Highlight,
  type RoleHighlight,
  type VideoHighlight,
} from './weeklyHighlights.data'
import { useSwipeableMarquee } from './useSwipeableMarquee'

/**
 * "This week at FinEx" — the rotating highlights band.
 *
 * WHAT IT IS FOR
 * --------------
 * The landing page tells a visitor what FinEx *is*. It never showed them what
 * arrived *this week*, so a returning visitor had no reason to look twice and
 * a first-time visitor had no evidence the index is alive. This band is that
 * evidence, moving: the best new Roles, useful FinEx conversations and the
 * career coaches a visitor can learn from.
 *
 * THE CONVEYOR
 * ------------
 * Cards enter right, cross, leave left, and come back round.
 *
 *   - CSS, not JS. The track holds the list twice and translates by exactly
 *     -50%, so the moment the first copy has fully left, the second sits
 *     precisely where the first began and the loop restarts with no seam.
 *   - `transform` only — composites on the GPU, cannot cause layout shift.
 *   - `linear`, deliberately. A conveyor eased with any curve visibly
 *     accelerates and decelerates once per loop, which is the exact stutter a
 *     marquee must not have. (The remotion-motion-graphics rule "never use
 *     linear" governs ENTRANCES, which here are sprung and eased — see the
 *     stylesheet. A continuous loop is the documented exception.)
 *
 * THE DEPTH, borrowed from remotion-motion-graphics
 * -------------------------------------------------
 * That skill renders video, not DOM, so none of its code applies — but its
 * five-layer scene rule does, and it is what stops this reading flat:
 *
 *     background mesh -> assets -> graphics/type -> colour grade -> grain
 *
 * All five exist here in CSS: drifting mesh blobs behind, the cards over them,
 * a vignette grade, and a grain overlay on top. Its other rules that survived
 * the port: every still gets Ken Burns (the video and course thumbnails
 * slowly scale and pan), entrances animate three properties at once rather
 * than fading, and exactly ONE hero colour glows — the gold, on hover, on one
 * card at a time. Its "idle elements breathe" rule is deliberately NOT applied
 * to the cards: they are already travelling, and the same skill warns that
 * constant motion reads amateur while contrast reads expensive. The breathing
 * lives in the background instead.
 *
 * PAUSE ON HOVER
 * --------------
 * Hover freezes the band so the reader can catch a card. Focus and touch do
 * not: browser Back restores focus to a clicked video link, and a
 * `:focus-within` pause leaves the conveyor frozen with no pointer over it.
 * The system-level `prefers-reduced-motion` preference still replaces the
 * animation with a user-driven horizontal rail.
 */

const SPEED_PX_PER_SECOND = 40

function formatMonth(iso: string) {
  return new Date(iso).toLocaleDateString('en-HK', {
    timeZone: 'Asia/Hong_Kong', month: 'short', year: 'numeric',
  })
}

/** First letters of the first two words — the visual anchor a text-only card
 *  would otherwise lack. Not a logo: we hold no brand assets, and inventing
 *  one would be worse than an honest monogram. */
function monogram(name: string) {
  const words = name.split(/\s+/).filter(Boolean)
  // One word ("UBS", "Schroders") takes its first two letters; anything
  // longer takes one initial per word. Taking initials unconditionally left
  // a lone character rattling around a 2.6rem tile.
  return (words.length === 1
    ? words[0].slice(0, 2)
    : words.slice(0, 2).map(w => w[0]).join('')).toUpperCase()
}

function CardEyebrow({ icon, children }: { icon?: React.ReactNode; children: React.ReactNode }) {
  return <span className="hl-card__eyebrow">{icon}{children}</span>
}

/** The bottom row every card ends on. Consistent by design: as cards travel,
 *  the calls-to-action sit on one baseline, so the eye tracks a line rather
 *  than hunting a new spot on each card. */
function CardAction({ label, meta }: { label: string; meta: string }) {
  return (
    <div className="hl-card__foot">
      <span className="hl-card__meta">{meta}</span>
      <span className="hl-card__cta">
        {label}
        <ArrowRight size={13} strokeWidth={2.4} aria-hidden="true" />
      </span>
    </div>
  )
}

function RoleCard({ item }: { item: RoleHighlight }) {
  return (
    <>
      <div className="hl-card__crest">
        <span className="hl-card__monogram" aria-hidden="true">{monogram(item.company)}</span>
        <div className="min-w-0">
          <CardEyebrow>{item.desk}</CardEyebrow>
          <p className="hl-card__company">{item.company}</p>
        </div>
        <BriefcaseBusiness className="hl-card__corner-icon" size={20} strokeWidth={1.5} aria-hidden="true" />
      </div>
      <h3 className="hl-card__title">{item.title}</h3>
      <CardAction label="View role" meta={item.location} />
    </>
  )
}

function CoachCard({ item }: { item: CoachHighlight }) {
  return (
    <>
      <div className="hl-card__crest">
        <img
          className="hl-card__coach-photo"
          src={item.image}
          alt=""
          loading="lazy"
          width={104}
          height={91}
        />
        <div className="min-w-0">
          <CardEyebrow icon={<Sparkles size={11} strokeWidth={2.5} aria-hidden="true" />}>
            New career coach
          </CardEyebrow>
          <p className="hl-card__company">{item.role}</p>
        </div>
      </div>
      <h3 className="hl-card__title">{item.name}</h3>
      <p className="hl-card__body">{item.focus}</p>
      <CardAction label="Meet the coach" meta="FinEx Club" />
    </>
  )
}

function VideoCard({ item }: { item: VideoHighlight }) {
  return (
    <>
      {/* Ken Burns lives on the img, not the frame, so the frame keeps its
          reserved aspect ratio and nothing shifts while the image drifts. */}
      <div className="hl-card__media">
        <img src={item.thumbnail} alt="" loading="lazy" width={480} height={270} />
        <span className="hl-card__play" aria-hidden="true">
          <PlayCircle size={26} strokeWidth={1.6} />
        </span>
      </div>
      <CardEyebrow>{item.topic}</CardEyebrow>
      <h3 className="hl-card__title hl-card__title--tight">{item.title}</h3>
      <CardAction label="Watch" meta="FinEx Club · YouTube" />
    </>
  )
}

function CourseCard({ item }: { item: CourseHighlight }) {
  return (
    <>
      <div className="hl-card__media">
        <img src={item.image} alt="" loading="lazy" width={480} height={270} />
      </div>
      <CardEyebrow icon={<GraduationCap size={11} strokeWidth={2.5} aria-hidden="true" />}>
        Training
      </CardEyebrow>
      <h3 className="hl-card__title hl-card__title--tight">{item.title}</h3>
      <CardAction label="See the programme" meta={`${item.venue} · ${formatMonth(item.date)}`} />
    </>
  )
}

/**
 * One card — an anchor wrapping the whole tile, so every pixel of it is the
 * link. Not a div with an onClick: this has to be tabbable, middle-clickable
 * and openable in a new tab like any other link on the page.
 */
function HighlightCard({ item, duplicate = false }: { item: Highlight; duplicate?: boolean }) {
  const external = item.href.startsWith('http')
  const contents = (
    <>
      <span className="hl-card__sheen" aria-hidden="true" />
      {item.kind === 'role' && <RoleCard item={item} />}
      {item.kind === 'coach' && <CoachCard item={item} />}
      {item.kind === 'video' && <VideoCard item={item} />}
      {item.kind === 'course' && <CourseCard item={item} />}
    </>
  )
  if (item.kind === 'role') {
    return (
      <Link
        className="hl-card hl-card--role"
        to={item.href}
        state={{ featuredRole: item.job }}
        tabIndex={duplicate ? -1 : undefined}
      >
        {contents}
      </Link>
    )
  }
  return (
    <a
      className={`hl-card hl-card--${item.kind}`}
      href={item.href}
      tabIndex={duplicate ? -1 : undefined}
      {...(external ? { target: '_blank', rel: 'noopener noreferrer' } : {})}
    >
      {contents}
    </a>
  )
}

function RailStatusCard({
  state,
  retry,
  duplicate = false,
}: {
  state: 'loading' | 'error'
  retry: () => void
  duplicate?: boolean
}) {
  if (state === 'loading') {
    return (
      <div className="hl-card hl-card--status" role={duplicate ? undefined : 'status'}>
        <span className="hl-card__status-pulse" aria-hidden="true" />
        <CardEyebrow>Weekly Roles</CardEyebrow>
        <h3 className="hl-card__title">Loading this week’s picks…</h3>
      </div>
    )
  }
  return (
    <div className="hl-card hl-card--status" role={duplicate ? undefined : 'alert'}>
      <CardEyebrow>Weekly Roles</CardEyebrow>
      <h3 className="hl-card__title">Couldn’t load this week’s Roles.</h3>
      <button type="button" className="hl-card__retry" onClick={retry} tabIndex={duplicate ? -1 : undefined}>
        Try again <ArrowRight size={13} aria-hidden="true" />
      </button>
    </div>
  )
}

/** The coach roster is a separate, denser rail. Its compact form makes the
 * people feel like an available network, rather than competing with a featured
 * Role or video for the same amount of editorial attention. */
function CoachRailCard({ item, duplicate = false }: { item: CoachHighlight; duplicate?: boolean }) {
  return (
    <a
      className="hl-coach-card"
      href={item.href}
      tabIndex={duplicate ? -1 : undefined}
      target="_blank"
      rel="noopener noreferrer"
    >
      <span className="hl-coach-card__photo-frame" aria-hidden="true">
        <img className="hl-coach-card__photo" src={item.image} alt="" loading="lazy" width={112} height={112} />
      </span>
      <span className="hl-coach-card__copy">
        <span className="hl-coach-card__name">{item.name}</span>
        <span className="hl-coach-card__role">{item.role}</span>
        <span className="hl-coach-card__focus">{item.focus}</span>
      </span>
      <ArrowRight className="hl-coach-card__arrow" size={16} strokeWidth={2.4} aria-hidden="true" />
    </a>
  )
}

/** A compact landscape treatment keeps the video collection distinct from
 * the large Role tickets while leaving enough of the thumbnail visible to
 * recognise each conversation at marquee speed. */
function VideoRailCard({ item, duplicate = false }: { item: VideoHighlight; duplicate?: boolean }) {
  return (
    <a
      className="hl-video-card"
      href={item.href}
      tabIndex={duplicate ? -1 : undefined}
      target="_blank"
      rel="noopener noreferrer"
    >
      <span className="hl-video-card__media" aria-hidden="true">
        <img src={item.thumbnail} alt="" loading="lazy" width={480} height={270} />
        <span className="hl-video-card__play"><PlayCircle size={24} strokeWidth={1.7} /></span>
      </span>
      <span className="hl-video-card__copy">
        <span className="hl-video-card__topic">{item.topic}</span>
        <span className="hl-video-card__title">{item.title}</span>
        <span className="hl-video-card__action">
          Watch on YouTube <ArrowRight size={13} strokeWidth={2.4} aria-hidden="true" />
        </span>
      </span>
    </a>
  )
}

export default function WeeklyHighlights() {
  const viewportRef = useRef<HTMLDivElement>(null)
  const trackRef = useRef<HTMLDivElement>(null)
  const videoViewportRef = useRef<HTMLDivElement>(null)
  const videoTrackRef = useRef<HTMLDivElement>(null)
  const coachViewportRef = useRef<HTMLDivElement>(null)
  const coachTrackRef = useRef<HTMLDivElement>(null)
  const sectionRef = useRef<HTMLElement>(null)
  const [duration, setDuration] = useState(60)
  const [videoDuration, setVideoDuration] = useState(130)
  const [coachDuration, setCoachDuration] = useState(160)
  const [shown, setShown] = useState(false)
  const [weeklyRoles, setWeeklyRoles] = useState<WeeklyHighlightRole[]>([])
  const [roleState, setRoleState] = useState<'loading' | 'ready' | 'error'>('loading')
  const highlightRequest = useRef(0)

  useSwipeableMarquee(viewportRef, trackRef)
  useSwipeableMarquee(videoViewportRef, videoTrackRef)
  useSwipeableMarquee(coachViewportRef, coachTrackRef)

  const loadWeeklyRoles = useCallback(() => {
    const request = ++highlightRequest.current
    setRoleState('loading')
    fetchWeeklyHighlights()
      .then(response => {
        if (highlightRequest.current !== request) return
        setWeeklyRoles(response.roles)
        setRoleState('ready')
      })
      .catch(() => {
        if (highlightRequest.current !== request) return
        setWeeklyRoles([])
        setRoleState('error')
      })
  }, [])

  useEffect(() => {
    loadWeeklyRoles()
    return () => { highlightRequest.current += 1 }
  }, [loadWeeklyRoles])

  // Duration derives from the real rendered width so the band always travels
  // at ONE readable speed. A fixed duration would make the conveyor faster
  // every time somebody adds a card — it would quietly speed up as it got
  // more useful.
  useEffect(() => {
    const track = trackRef.current
    if (!track) return
    const measure = () => {
      const half = track.scrollWidth / 2
      if (half > 0) setDuration(half / SPEED_PX_PER_SECOND)
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(track)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const track = videoTrackRef.current
    if (!track) return
    const measure = () => {
      const half = track.scrollWidth / 2
      if (half > 0) setVideoDuration(half / (SPEED_PX_PER_SECOND * 0.82))
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(track)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const track = coachTrackRef.current
    if (!track) return
    const measure = () => {
      const half = track.scrollWidth / 2
      if (half > 0) setCoachDuration(half / (SPEED_PX_PER_SECOND * 0.7))
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(track)
    return () => observer.disconnect()
  }, [])

  // The entrance. Three properties at once (opacity + translateY + scale) and
  // staggered head-then-track, per the motion skill's entrance rule — a lone
  // fade is the thing it explicitly forbids.
  useEffect(() => {
    const el = sectionRef.current
    if (!el) return
    const io = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) { setShown(true); io.disconnect() } },
      { threshold: 0.15 },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [])

  const items = mergeWeeklyHighlights(weeklyRoles)
  const videos = VIDEO_HIGHLIGHTS
  const coaches = COACH_HIGHLIGHTS

  return (
    <section className="hl" aria-labelledby="hl-heading" ref={sectionRef} data-shown={shown || undefined}>
      {/* Layer 1 of the five-layer stack: the drifting mesh. Two blobs on long,
          co-prime durations so they never resynchronise into a visible pulse. */}
      <div className="hl__mesh" aria-hidden="true">
        <span className="hl__blob hl__blob--gold" />
        <span className="hl__blob hl__blob--blue" />
      </div>

      <div className="hl__inner">
        <div className="hl__layout">
          <header className="hl__head">
            <div>
              <p className="hl__eyebrow">Weekly highlights</p>
              <span className="hl__edition">Just landed · {items.length} picks</span>
            </div>
            <h2 id="hl-heading" className="hl__title">This week at FinEx.</h2>
          </header>

          {/* Hover holds the rail; browser Back never leaves it frozen. */}
          <div ref={viewportRef} className="hl__viewport">
            <div ref={trackRef} className="hl__track" style={{ animationDuration: `${duration}s` }}>
              {/* Two IDENTICAL groups, and the spacing lives on the cards rather
                  than as flex `gap` on the track. That is what makes -50% land
                  exactly: with a gap on the track, half its width is one group
                  plus half a gap, so the loop would jump by half a gap every
                  cycle — the classic marquee stutter. No gap, no jump. */}
              <div className="hl__group">
                {roleState !== 'ready' && <RailStatusCard state={roleState} retry={loadWeeklyRoles} />}
                {items.map(item => <HighlightCard key={item.id} item={item} />)}
              </div>
              {/* The copy becomes visible for half of every seamless loop, so it
                  must remain pointer-clickable. aria-hidden keeps it out of the
                  accessibility tree and tabIndex=-1 on each link keeps it out
                  of keyboard navigation without disabling mouse/touch clicks. */}
              <div className="hl__group" aria-hidden="true">
                {roleState !== 'ready' && (
                  <RailStatusCard state={roleState} retry={loadWeeklyRoles} duplicate />
                )}
                {items.map(item => <HighlightCard key={`${item.id}-copy`} item={item} duplicate />)}
              </div>
            </div>
          </div>

          <div className="hl__video-band" aria-label="FinEx Club videos">
            <div className="hl__video-band-head">
              <div>
                <span className="hl__video-kicker">
                  <PlayCircle size={13} strokeWidth={2.4} aria-hidden="true" /> Watch FinEx
                </span>
                <p>Conversations, market insight and career perspective.</p>
              </div>
              <div className="hl__video-actions" aria-label="More FinEx Club videos">
                <a href={YOUTUBE_CHANNEL_URL} target="_blank" rel="noopener noreferrer">
                  <TvMinimalPlay size={15} strokeWidth={2.2} aria-hidden="true" /> YouTube channel
                </a>
                <a href={COMMITTEE_PLAYLIST_URL} target="_blank" rel="noopener noreferrer">
                  <ListVideo size={15} strokeWidth={2.2} aria-hidden="true" /> Professional committees
                </a>
              </div>
            </div>

            <div ref={videoViewportRef} className="hl__video-viewport">
              <div
                ref={videoTrackRef}
                className="hl__video-track"
                style={{ animationDuration: `${videoDuration}s` }}
              >
                <div className="hl__video-group">
                  {videos.map(item => <VideoRailCard key={item.id} item={item} />)}
                </div>
                <div className="hl__video-group" aria-hidden="true">
                  {videos.map(item => <VideoRailCard key={`${item.id}-copy`} item={item} duplicate />)}
                </div>
              </div>
            </div>
          </div>

          <div className="hl__coach-band" aria-label="FinEx career coaches">
            <div className="hl__coach-band-head">
              <div>
                <span className="hl__coach-kicker"><Sparkles size={13} strokeWidth={2.4} aria-hidden="true" /> Meet the coaches</span>
                <p>{coaches.length} finance leaders, ready to share what they know.</p>
              </div>
              <Link to="/career-coaches">
                Find the right career counsellor <ArrowRight size={14} aria-hidden="true" />
              </Link>
            </div>

            {/* This rail moves independently from the Role and video rails. Hovering
                it holds only the coaches, so each person remains easy to read. */}
            <div ref={coachViewportRef} className="hl__coach-viewport">
              <div ref={coachTrackRef} className="hl__coach-track" style={{ animationDuration: `${coachDuration}s` }}>
                <div className="hl__coach-group">
                  {coaches.map(item => <CoachRailCard key={item.id} item={item} />)}
                </div>
                <div className="hl__coach-group" aria-hidden="true">
                  {coaches.map(item => <CoachRailCard key={`${item.id}-copy`} item={item} duplicate />)}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Layers 4 and 5: the grade, then the grain. Both sit above the cards
          and ignore pointer events, so they tint without ever intercepting a
          click meant for a card underneath. */}
      <div className="hl__grade" aria-hidden="true" />
      <div className="hl__grain" aria-hidden="true" />
    </section>
  )
}
