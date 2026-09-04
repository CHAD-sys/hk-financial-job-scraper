import { describe, expect, it } from 'vitest'
import { nextMarqueeTime } from './useSwipeableMarquee'

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
})
