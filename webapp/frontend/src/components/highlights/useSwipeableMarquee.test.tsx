import { fireEvent, render } from '@testing-library/react'
import { useRef } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { nextMarqueeTime, useSwipeableMarquee } from './useSwipeableMarquee'

function dispatchPointer(
  target: Element,
  type: 'pointerdown' | 'pointermove' | 'pointerup',
  clientX: number,
) {
  const event = new Event(type, { bubbles: true, cancelable: true })
  Object.defineProperties(event, {
    pointerId: { value: 7 },
    pointerType: { value: 'touch' },
    isPrimary: { value: true },
    button: { value: 0 },
    clientX: { value: clientX },
  })
  fireEvent(target, event)
  return event
}

function GestureHarness({ onOpen, native = false }: { onOpen: () => void; native?: boolean }) {
  const viewportRef = useRef<HTMLDivElement>(null)
  const trackRef = useRef<HTMLDivElement>(null)
  useSwipeableMarquee(viewportRef, trackRef)
  return (
    <div ref={viewportRef} data-testid="viewport" style={native ? { overflowX: 'auto' } : undefined}>
      <div ref={trackRef} data-testid="track">
        <a href="/jobs" onClick={(event) => { event.preventDefault(); onOpen() }}>Open Role</a>
      </div>
    </div>
  )
}

function arrangeGesture(native = false) {
  const onOpen = vi.fn()
  const view = render(<GestureHarness onOpen={onOpen} native={native} />)
  const viewport = view.getByTestId('viewport') as HTMLDivElement
  const track = view.getByTestId('track') as HTMLDivElement
  const animation = {
    currentTime: 100,
    pause: vi.fn(),
    play: vi.fn(),
    effect: { getTiming: () => ({ duration: 1_000 }) },
  }
  Object.defineProperty(track, 'getAnimations', { configurable: true, value: () => [animation] })
  Object.defineProperty(track, 'scrollWidth', { value: 1_000 })
  viewport.setPointerCapture = vi.fn()
  viewport.releasePointerCapture = vi.fn()
  viewport.hasPointerCapture = vi.fn(() => true)
  return { ...view, animation, onOpen, viewport }
}

describe('marquee swipe scrubbing', () => {
  it('moves a reversed marquee in the direction of the drag', () => {
    expect(nextMarqueeTime({
      currentTime: 200,
      deltaX: 50,
      duration: 1_000,
      trackDistance: 500,
      reversed: true,
    })).toBe(300)
  })

  it('wraps cleanly through the infinite loop in both directions', () => {
    expect(nextMarqueeTime({
      currentTime: 40,
      deltaX: -50,
      duration: 1_000,
      trackDistance: 500,
      reversed: true,
    })).toBe(940)
    expect(nextMarqueeTime({
      currentTime: 960,
      deltaX: -50,
      duration: 1_000,
      trackDistance: 500,
      reversed: false,
    })).toBe(60)
  })

  it('keeps a short touch movement available as a card tap', () => {
    const { getByRole, onOpen, viewport } = arrangeGesture()

    dispatchPointer(viewport, 'pointerdown', 100)
    dispatchPointer(viewport, 'pointermove', 108)
    dispatchPointer(viewport, 'pointerup', 108)
    fireEvent.click(getByRole('link', { name: 'Open Role' }))

    expect(viewport.setPointerCapture).not.toHaveBeenCalled()
    expect(onOpen).toHaveBeenCalledOnce()
  })

  it('takes over only after a horizontal touch swipe and scrubs the rail', () => {
    const { getByRole, animation, onOpen, viewport } = arrangeGesture()

    dispatchPointer(viewport, 'pointerdown', 140)
    expect(viewport.setPointerCapture).not.toHaveBeenCalled()

    const move = dispatchPointer(viewport, 'pointermove', 100)
    dispatchPointer(viewport, 'pointerup', 100)
    fireEvent.click(getByRole('link', { name: 'Open Role' }))

    expect(move.defaultPrevented).toBe(true)
    expect(viewport.setPointerCapture).toHaveBeenCalledWith(7)
    expect(animation.pause).toHaveBeenCalledOnce()
    expect(animation.currentTime).not.toBe(100)
    expect(animation.play).toHaveBeenCalledOnce()
    expect(onOpen).not.toHaveBeenCalled()
  })

  it('keeps a native mobile rail centred so past and future cards remain swipeable', () => {
    const { animation, viewport } = arrangeGesture(true)

    dispatchPointer(viewport, 'pointerdown', 140)
    const move = dispatchPointer(viewport, 'pointermove', 100)

    viewport.scrollLeft = 5
    fireEvent.scroll(viewport)
    dispatchPointer(viewport, 'pointerup', 100)

    expect(move.defaultPrevented).toBe(false)
    expect(viewport.setPointerCapture).not.toHaveBeenCalled()
    expect(animation.pause).toHaveBeenCalledOnce()
    expect(viewport.scrollLeft).toBe(505)
    expect(animation.play).toHaveBeenCalledOnce()
  })
})
