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
  it('assigns every public coach to one or more visible expertise groups', () => {
    expect(CAREER_COACHES).toHaveLength(32)
    expect(COACH_DOMAINS).toHaveLength(9)
    expect(new Set(CAREER_COACH_GROUPS.flatMap(group => group.coaches.map(coach => coach.id))).size).toBe(32)

    for (const coach of CAREER_COACHES) {
      expect(COACH_DOMAINS).toContain(coach.primaryDomain)
      expect(coach.domains).toContain(coach.primaryDomain)
      expect(new Set(coach.domains).size).toBe(coach.domains.length)
      expect(coach.href).toMatch(/^https:\/\/www\.finexclub\.org\//)
      expect(coach.appointmentUrl).toBe('https://www.finexclub.org/mentor-program')
    }
  })

  it('uses the requested public category names and hides paused categories', () => {
    expect(COACH_DOMAINS).toContain('Custody, Funds, and Assets Servicing')
    expect(COACH_DOMAINS).toContain('Private Equity, Family Offices, Wealth')
    expect(COACH_DOMAINS).toContain('Strategy, Transformation & Consulting')
    expect(COACH_DOMAINS).not.toContain('Private Banking & Wealth')
    expect(COACH_DOMAINS).not.toContain('Insurance & Actuarial')
    expect(COACH_DOMAINS).not.toContain('Investment Banking')
  })

  it('supports the requested cross-domain expertise groups and filters', () => {
    expect(coachesForDomain('Digital Assets & FinTech').map(coach => coach.name)).toEqual(expect.arrayContaining([
      'Hannah Hui',
      'John Wong',
      'Nicholas Yip',
    ]))
    expect(coachesForDomain('Investment').map(coach => coach.name)).toEqual(expect.arrayContaining([
      'Apple Lo',
      'Morris Hui, CFA',
    ]))
    expect(coachesForDomain('Treasury & Markets').map(coach => coach.name)).toContain('Morris Hui, CFA')
    expect(coachesForDomain('Institutional Banking & Sales').map(coach => coach.name)).toEqual(expect.arrayContaining([
      'John Wong',
      'Morris Hui, CFA',
    ]))
    expect(coachesForDomain('Custody, Funds, and Assets Servicing').map(coach => coach.name)).toContain('Katherine Lee')
    expect(coachesForDomain('Strategy, Transformation & Consulting').map(coach => coach.name)).toEqual(expect.arrayContaining([
      'Biswajyoti (BJ) Upadhyay',
      'Cammy Tong',
      'Doris Kuo',
      'Edward Lee',
      'Lawrence Au',
      'Vincent Huen',
    ]))

    const accountingCoaches = coachesForDomain('Accounting & Finance').map(coach => coach.name)
    expect(accountingCoaches).not.toContain('Nelson Chau')
    expect(accountingCoaches).not.toContain('Patrick Leung')
    expect(coachesForDomain('Risk & Compliance').map(coach => coach.name)).not.toContain('Margaret Chan')
    const investmentCoaches = coachesForDomain('Investment').map(coach => coach.name)
    expect(investmentCoaches).not.toContain('Benjamin Chung')
    expect(investmentCoaches).not.toContain('Nelson Chau')
    const institutionalCoaches = coachesForDomain('Institutional Banking & Sales').map(coach => coach.name)
    expect(institutionalCoaches).not.toContain('Byron Gardiner')
    expect(institutionalCoaches).not.toContain('Connie Mak')
    expect(institutionalCoaches).not.toContain('Hannah Hui')
    expect(coachesForDomain('Digital Assets & FinTech').map(coach => coach.name)).not.toContain('Raymong Chung')
    expect(coachesForDomain('Private Equity, Family Offices, Wealth').map(coach => coach.name)).toEqual([
      'Edward Lee',
      'Patrick Leung',
      'Shannon Chow',
    ])
    expect(coachesForDomain('Strategy, Transformation & Consulting').map(coach => coach.name)).not.toContain('Calvin Lee')

    for (const group of CAREER_COACH_GROUPS) {
      expect(group.coaches).toEqual(coachesForDomain(group.domain))
    }
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
