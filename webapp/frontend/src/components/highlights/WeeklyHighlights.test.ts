import { describe, expect, it } from 'vitest'
import { COACH_HIGHLIGHTS, WEEKLY_HIGHLIGHTS } from './weeklyHighlights.data'

describe('weekly highlight destinations', () => {
  it('opens each featured Role inside Careers with a related-role search', () => {
    const roles = WEEKLY_HIGHLIGHTS.filter(item => item.kind === 'role')

    expect(roles.length).toBeGreaterThan(0)
    for (const role of roles) {
      const destination = new URL(role.href, 'https://www.finexcareers.com')

      expect(destination.pathname).toBe('/jobs')
      expect(destination.searchParams.get('q')).toBe(role.desk)
      expect(destination.searchParams.get('role_source')).toBeTruthy()
      expect(destination.searchParams.get('role_id')).toBeTruthy()
      expect(destination.searchParams.get('role_lookup')).toBeTruthy()
    }
  })

  it('keeps coaches out of the editorial rail and exposes the full public roster separately', () => {
    expect(WEEKLY_HIGHLIGHTS.some(item => item.kind === 'coach')).toBe(false)
    expect(COACH_HIGHLIGHTS).toHaveLength(32)
    expect(COACH_HIGHLIGHTS.map(coach => coach.name)).toContain('Andrew Chan')
    expect(COACH_HIGHLIGHTS.every(coach => coach.href.startsWith('https://www.finexclub.org/'))).toBe(true)
  })
})
