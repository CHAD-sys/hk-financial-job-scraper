import { describe, expect, it } from 'vitest'
import { MT_OPENINGS } from './mtOpenings'

describe('curated MT openings', () => {
  it('prefers an official employer route whenever current evidence supports one', () => {
    const employerFirst = MT_OPENINGS.filter(opening => opening.applicationDestination === 'employer_role' || opening.applicationDestination === 'employer_vacancies')

    expect(employerFirst).toHaveLength(7)
    expect(employerFirst.every(opening => opening.source === 'Official careers')).toBe(true)
    expect(MT_OPENINGS.find(opening => opening.company === 'The Hong Kong Jockey Club')?.applicationUrl).toContain('careers.hkjc.com')
    expect(MT_OPENINGS.find(opening => opening.company === 'SmarTone')?.applicationUrl).toContain('smartoneholdings.com')
  })
})
