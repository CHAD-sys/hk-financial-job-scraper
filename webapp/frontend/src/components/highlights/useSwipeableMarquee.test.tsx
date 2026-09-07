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
}

function GestureHarness({ onOpen }: { onOpen: () => void }) {
  const viewportRef = useRef<HTMLDivElement>(null)
  const trackRef = useRef<HTMLDivElement>(null)
  useSwipeableMarquee(viewportRef, trackRef)
  return (
    <div ref={viewportRef} data-testid="viewport">
      <div ref={trackRef} data-testid="track">
        <a href="/jobs" onClick={(event) => { event.preventDefault(); onOpen() }}>Open Role</a>
      </div>
    </div>
  )
}

function arrangeGesture() {
  const onOpen = vi.fn()
  const view = render(<GestureHarness onOpen={onOpen} />)
  const viewport = view.getByTestId('viewport') as HTMLDivElement
  const track = view.getByTestId('track') as HTMLDivElement
  const animation = {
    currentTime: 100,
    pause: vi.fn(),
    play: vi.fn(),
    effect: { getTiming: () => ({ duration: 1_000 }) },
  }
  Object.defineProperty(track, 'getAnimations', { value: () => [animation] })
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
      duration: 1000,
      trackDistance: 500,
      reversed: true,
    })).toBe(300)
  })

  it('wraps cleanly through the infinite loop in both directions', () => {
    expect(nextMarqueeTime({
      currentTime: 40,
      deltaX: -50,
      duration: 1000,
      trackDistance: 500,
      reversed: true,
    })).toBe(940)
    expect(nextMarqueeTime({
      currentTime: 960,
      deltaX: -50,
      duration: 1000,
      trackDistance: 500,
      reversed: false,
    })).toBe(60)
  })

  it('keeps a slightly moving tap clickable and does not capture it', () => {
    const { getByRole, onOpen, viewport } = arrangeGesture()

    dispatchPointer(viewport, 'pointerdown', 100)
    dispatchPointer(viewport, 'pointermove', 108)
    dispatchPointer(viewport, 'pointerup', 108)
    fireEvent.click(getByRole('link', { name: 'Open Role' }))

    expect(viewport.setPointerCapture).not.toHaveBeenCalled()
    expect(onOpen).toHaveBeenCalledOnce()
  })

  it('captures only after an intentional swipe and suppresses its trailing click', () => {
    const { getByRole, onOpen, viewport } = arrangeGesture()

    dispatchPointer(viewport, 'pointerdown', 100)
    expect(viewport.setPointerCapture).not.toHaveBeenCalled()
    dispatchPointer(viewport, 'pointermove', 113)
    dispatchPointer(viewport, 'pointerup', 113)
    fireEvent.click(getByRole('link', { name: 'Open Role' }))

    expect(viewport.setPointerCapture).toHaveBeenCalledOnce()
    expect(onOpen).not.toHaveBeenCalled()
  })
})
