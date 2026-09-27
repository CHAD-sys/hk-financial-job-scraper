import { describe, expect, it } from 'vitest'
import { openingDeadlineState } from './ManagementTraineePage'

describe('openingDeadlineState', () => {
  it('calls a passed deadline closed rather than Open forever', () => {
    // The badge was hardcoded to "Open": a 31 Oct deadline still claimed Open
    // in November, which is the one thing a deadline desk must never do.
    expect(openingDeadlineState('2026-10-31', new Date('2026-11-01T00:00:00+08:00'))).toBe('closed')
  })

  it('keeps an intake open through the whole of its deadline day in Hong Kong', () => {
    expect(openingDeadlineState('2026-10-31', new Date('2026-10-31T09:00:00+08:00'))).toBe('open')
    expect(openingDeadlineState('2026-10-31', new Date('2026-10-31T23:58:00+08:00'))).toBe('open')
  })

  it('claims nothing when the employer stated no deadline', () => {
    // mtApplicationStatus.ts's rule: a status is publishable only when
    // something actually says so.
    expect(openingDeadlineState(undefined, new Date('2026-09-27T00:00:00+08:00'))).toBe('unstated')
  })
})
