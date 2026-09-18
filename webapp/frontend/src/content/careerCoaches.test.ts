import { describe, expect, it } from 'vitest'
import {
  CAREER_COACHES,
  CAREER_COACH_GROUPS,
  COACH_DOMAINS,
  COACH_SPECIALTIES,
  coachesForDomain,
  coachesForFilters,
} from './careerCoaches'

describe('career coach directory data', () => {
  it('assigns every public coach to one primary expertise group', () => {
    expect(CAREER_COACHES).toHaveLength(32)
    expect(COACH_DOMAINS).toHaveLength(11)
    expect(CAREER_COACH_GROUPS.flatMap(group => group.coaches)).toHaveLength(32)
    expect(new Set(CAREER_COACH_GROUPS.flatMap(group => group.coaches.map(coach => coach.id))).size).toBe(32)

    for (const coach of CAREER_COACHES) {
      expect(COACH_DOMAINS).toContain(coach.primaryDomain)
      expect(coach.domains).toContain(coach.primaryDomain)
      expect(coach.href).toMatch(/^https:\/\/www\.finexclub\.org\//)
      expect(coach.appointmentUrl).toBe('https://www.finexclub.org/mentor-program')
    }
  })

  it('supports the requested cross-domain expertise filters', () => {
    expect(coachesForDomain('Digital Assets & FinTech').map(coach => coach.name)).toEqual(expect.arrayContaining([
      'Hannah Hui',
      'John Wong',
      'Nicholas Yip',
      'Raymong Chung',
    ]))
    expect(coachesForDomain('Investment Banking').map(coach => coach.name)).toEqual(expect.arrayContaining([
      'Apple Lo',
      'Morris Hui, CFA',
      'Simon Tung',
    ]))
    expect(coachesForDomain('All expertise')).toEqual(CAREER_COACHES)
  })

  it('filters by the coaches’ stated specialties and searchable profile text', () => {
    expect(COACH_SPECIALTIES).toContain('Web3')
    expect(coachesForFilters({ specialty: 'Web3' }).map(coach => coach.name)).toEqual(['John Wong'])
    expect(coachesForFilters({ query: 'global markets' }).map(coach => coach.name)).toEqual(expect.arrayContaining([
      'Ken Cheung',
      'Timothy Chan',
    ]))
    expect(coachesForFilters({ domain: 'Digital Assets & FinTech', query: 'Hannah' }).map(coach => coach.name)).toEqual(['Hannah Hui'])
  })
})
