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

/**
 * Lets a reader take over any highlights conveyor with the same pointer-event
 * path that powers the public site. In particular, capture starts only once a
 * horizontal intent is clear. Capturing on touch-down (or competing with a
 * second TouchEvent listener) prevents iOS Safari from handing the animated
 * rail a usable drag stream.
 */
export function useSwipeableMarquee(
  viewportRef: RefObject<HTMLElement | null>,
  trackRef: RefObject<HTMLElement | null>,
) {
  useEffect(() => {
    const viewport = viewportRef.current
    const track = trackRef.current
    if (!viewport || !track) return

    const marqueeAnimation = () => track.getAnimations()[0] ?? null
    const overflowX = getComputedStyle(viewport).overflowX
    const usesNativeScroll = overflowX === 'auto' || overflowX === 'scroll'
    const visibilityObserver = typeof IntersectionObserver === 'undefined'
      ? null
      : new IntersectionObserver(([entry]) => {
          viewport.classList.toggle('is-offscreen', !entry.isIntersecting)
        }, { rootMargin: '160px 0px' })
    visibilityObserver?.observe(viewport)

    /* iOS is considerably more reliable when the browser owns the horizontal
     * gesture. The duplicated marquee track lets us wrap scrollLeft at either
     * seam, so readers can pull old cards back or reveal future cards without
     * reaching an end. Desktop rails retain the timeline-scrubbing path below. */
    if (usesNativeScroll) {
      let trackDistance = 0
      let heldAnimation: Animation | null = null

      const measure = () => {
        const nextDistance = track.scrollWidth / 2
        if (nextDistance <= 0) return

        if (trackDistance <= 0) {
          viewport.scrollLeft = nextDistance / 2
        } else if (Math.abs(nextDistance - trackDistance) > 1) {
          viewport.scrollLeft = (viewport.scrollLeft / trackDistance) * nextDistance
        }
        trackDistance = nextDistance
      }

      const wrap = () => {
        // ResizeObserver owns the layout read. Scroll events can fire every
        // frame on iOS, so keep this path to cheap cached-number comparisons.
        const distance = trackDistance || track.scrollWidth / 2
        if (distance <= 0) return
        if (trackDistance <= 0) trackDistance = distance

        if (viewport.scrollLeft < distance * 0.15) {
          viewport.scrollLeft += distance
        } else if (viewport.scrollLeft > distance * 1.15) {
          viewport.scrollLeft -= distance
        }
      }

      const hold = (event: PointerEvent) => {
        if (!event.isPrimary || (event.pointerType === 'mouse' && event.button !== 0)) return
        heldAnimation = marqueeAnimation()
        heldAnimation?.pause()
      }

      const release = () => {
        heldAnimation?.play()
        heldAnimation = null
      }

      measure()
      const resizeObserver = typeof ResizeObserver === 'undefined'
        ? null
        : new ResizeObserver(measure)
      resizeObserver?.observe(track)
      viewport.addEventListener('scroll', wrap, { passive: true })
      viewport.addEventListener('pointerdown', hold)
      window.addEventListener('pointerup', release)
      window.addEventListener('pointercancel', release)

      return () => {
        visibilityObserver?.disconnect()
        resizeObserver?.disconnect()
        viewport.removeEventListener('scroll', wrap)
        viewport.removeEventListener('pointerdown', hold)
        window.removeEventListener('pointerup', release)
        window.removeEventListener('pointercancel', release)
      }
    }

    let activePointer: number | null = null
    let pointerType = ''
    let lastX = 0
    let totalX = 0
    let dragged = false
    let suppressClick = false
    let animation: Animation | null = null
    let clickResetTimer: number | undefined

    const resume = () => {
      if (activePointer === null) {
        animation?.play()
        animation = null
      }
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

      if (viewport.hasPointerCapture?.(event.pointerId)) viewport.releasePointerCapture?.(event.pointerId)
      viewport.classList.remove('is-dragging')
      activePointer = null

      if (dragged) {
        suppressClick = true
        window.clearTimeout(clickResetTimer)
        clickResetTimer = window.setTimeout(() => { suppressClick = false }, CLICK_SUPPRESSION_MS)
      }

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
      visibilityObserver?.disconnect()
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
