import { useRef } from 'react'
import { ArrowRight, BriefcaseBusiness } from 'lucide-react'
import { MT_INDUSTRIES, MT_PROGRAMMES } from '../content/managementTraineePrograms'
import { useSwipeableMarquee } from './highlights/useSwipeableMarquee'

function TapeMessage() {
  return (
    <span className="mt-announcement__run">
      <span className="mt-announcement__badge">New directory</span>
      <strong>Management Trainee programmes</strong>
      <i className="mt-announcement__dot" aria-hidden="true" />
      <span><b>{MT_PROGRAMMES.length}</b> employers · <b>{MT_INDUSTRIES.length}</b> industries</span>
      <i className="mt-announcement__dot" aria-hidden="true" />
      <span>Deadlines at a glance</span>
      <span className="mt-announcement__cta">
        Explore the desk <ArrowRight size={14} strokeWidth={2.25} />
      </span>
    </span>
  )
}

/**
 * Two identical groups make the tape seamless: translating the track by half
 * its width lands group two exactly where group one began. Each group contains
 * two messages and spans at least one viewport, so no wide screen can expose a
 * blank gap between copies.
 */
export default function MTAnnouncementBand() {
  const viewportRef = useRef<HTMLAnchorElement>(null)
  const trackRef = useRef<HTMLSpanElement>(null)

  // This tape is content, not decoration. Like every auto-moving rail, it is
  // directly scrub-able on touch and pauses while the visitor is in control.
  useSwipeableMarquee(viewportRef, trackRef)

  return (
    <div className="mt-announcement-row">
      <a
        ref={viewportRef}
        className="mt-announcement"
        href="#mt-programmes"
        aria-label="Explore Management Trainee programmes. Swipe left or right to browse."
      >
        <span className="sr-only">Management Trainee programmes are here. Jump to the featured programmes.</span>
        <span ref={trackRef} className="mt-announcement__track" aria-hidden="true">
          <span className="mt-announcement__group"><TapeMessage /><TapeMessage /></span>
          <span className="mt-announcement__group"><TapeMessage /><TapeMessage /></span>
        </span>
      </a>
      <a className="mt-announcement-post" href="/post-a-role">
        <BriefcaseBusiness size={17} strokeWidth={2} aria-hidden="true" />
        Post a job for free
        <ArrowRight size={15} strokeWidth={2.25} aria-hidden="true" />
      </a>
    </div>
  )
}
