import { useEffect, type RefObject } from 'react'

interface MarqueeTimeInput {
  currentTime: number
  deltaX: number
  duration: number
  trackDistance: number
  reversed: boolean
}

/** Convert a physical drag into a wrapped point on the CSS marquee timeline.
 * A reversed animation moves visually to the right as its timeline advances;
 * a normal animation moves left, so the same finger motion changes time in the
 * opposite direction. Keeping the result inside one iteration makes crossing
 * the duplicated-list seam invisible. */
export function nextMarqueeTime({
  currentTime,
  deltaX,
  duration,
  trackDistance,
  reversed,
}: MarqueeTimeInput) {
  if (duration <= 0 || trackDistance <= 0) return currentTime
  const deltaTime = deltaX * (duration / trackDistance) * (reversed ? 1 : -1)
  return ((currentTime + deltaTime) % duration + duration) % duration
}

const DRAG_THRESHOLD_PX = 12
const CLICK_SUPPRESSION_MS = 500

/** Make a continuously animated marquee directly scrub-able by mouse, pen or
 * touch. The browser's own CSS Animation remains the clock: dragging pauses
 * and changes its currentTime, then playback resumes from that exact point. */
export function useSwipeableMarquee(
  viewportRef: RefObject<HTMLDivElement | null>,
  trackRef: RefObject<HTMLDivElement | null>,
) {
  useEffect(() => {
    const viewport = viewportRef.current
    const track = trackRef.current
    if (!viewport || !track) return

    let activePointer: number | null = null
    let pointerType = ''
    let lastX = 0
    let totalX = 0
    let dragged = false
    let suppressClick = false
    let animation: Animation | null = null
    let clickResetTimer: number | undefined

    const marqueeAnimation = () => track.getAnimations()[0] ?? null

    const resume = () => {
      if (activePointer !== null) return
      animation?.play()
      animation = null
    }

    const onPointerDown = (event: PointerEvent) => {
      if (!event.isPrimary || (event.pointerType === 'mouse' && event.button !== 0)) return
      animation = marqueeAnimation()
      if (!animation) return

      activePointer = event.pointerId
      pointerType = event.pointerType
      lastX = event.clientX
      totalX = 0
      dragged = false
      animation.pause()
    }

    const onPointerMove = (event: PointerEvent) => {
      if (activePointer !== event.pointerId || !animation) return

      const deltaX = event.clientX - lastX
      lastX = event.clientX
      totalX += deltaX
      let scrubDelta = deltaX
      if (!dragged) {
        if (Math.abs(totalX) < DRAG_THRESHOLD_PX) return
        dragged = true
        scrubDelta = totalX
        viewport.setPointerCapture(event.pointerId)
        viewport.classList.add('is-dragging')
      }
      event.preventDefault()

      const timing = animation.effect?.getTiming()
      const duration = typeof timing?.duration === 'number' ? timing.duration : 0
      const currentTime = typeof animation.currentTime === 'number' ? animation.currentTime : 0
      const reversed = getComputedStyle(track).animationDirection.split(',')[0]?.trim() === 'reverse'

      animation.currentTime = nextMarqueeTime({
        currentTime,
        deltaX: scrubDelta,
        duration,
        trackDistance: track.scrollWidth / 2,
        reversed,
      })
    }

    const finishPointer = (event: PointerEvent) => {
      if (activePointer !== event.pointerId) return

      if (viewport.hasPointerCapture(event.pointerId)) viewport.releasePointerCapture(event.pointerId)
      viewport.classList.remove('is-dragging')
      activePointer = null

      if (dragged) {
        suppressClick = true
        window.clearTimeout(clickResetTimer)
        // Mobile browsers may synthesize `click` after pointerup. Keep the
        // guard alive long enough to catch that delayed event as well.
        clickResetTimer = window.setTimeout(() => { suppressClick = false }, CLICK_SUPPRESSION_MS)
      }

      // A mouse resting over the rail must keep the established hover-pause.
      // Touch and pen have no persistent hover, so they resume immediately.
      if (pointerType === 'mouse' && viewport.matches(':hover')) {
        viewport.addEventListener('pointerleave', resume, { once: true })
      } else {
        resume()
      }
    }

    const onClick = (event: MouseEvent) => {
      if (!suppressClick) return
      event.preventDefault()
      event.stopPropagation()
      suppressClick = false
    }

    const onDragStart = (event: DragEvent) => event.preventDefault()

    viewport.addEventListener('pointerdown', onPointerDown)
    viewport.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', finishPointer)
    window.addEventListener('pointercancel', finishPointer)
    viewport.addEventListener('click', onClick, true)
    viewport.addEventListener('dragstart', onDragStart)

    return () => {
      window.clearTimeout(clickResetTimer)
      viewport.removeEventListener('pointerdown', onPointerDown)
      viewport.removeEventListener('pointermove', onPointerMove)
      window.removeEventListener('pointerup', finishPointer)
      window.removeEventListener('pointercancel', finishPointer)
      viewport.removeEventListener('click', onClick, true)
      viewport.removeEventListener('dragstart', onDragStart)
      viewport.removeEventListener('pointerleave', resume)
    }
  }, [trackRef, viewportRef])
}
