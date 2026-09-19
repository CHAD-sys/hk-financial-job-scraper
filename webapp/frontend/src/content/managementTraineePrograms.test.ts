import { describe, expect, it } from 'vitest'
import {
  FEATURED_MT_PROGRAMMES,
  LINKED_MT_PROGRAMMES,
  MT_INDUSTRIES,
  MT_PROGRAMMES,
  mtEmployerKey,
  selectMasterApplicationUrl,
  VERIFIED_MT_PROGRAMMES,
} from './managementTraineePrograms'

describe('management trainee programme directory', () => {
  it('publishes only employer links that directly identify a Management Trainee programme', () => {
    expect(MT_PROGRAMMES).toHaveLength(6)
    expect(MT_INDUSTRIES).toHaveLength(4)
    expect(new Set(MT_PROGRAMMES.map(programme => programme.id)).size).toBe(6)
    expect(MT_PROGRAMMES.every(programme => programme.applicationUrls.some(url =>
      /(management|manager)[-_/ ]trainee/i.test(url)
      && !/graduate[-_/ ](?:management|manager)[-_/ ]trainee/i.test(url),
    ))).toBe(true)
  })

  it('keeps one direct programme destination per MT employer', () => {
    expect(LINKED_MT_PROGRAMMES).toHaveLength(6)
    expect(LINKED_MT_PROGRAMMES.every(programme => programme.masterApplicationUrl)).toBe(true)
  })

  it('keeps the two directly verified programme links distinct from workbook-supplied links', () => {
    expect(VERIFIED_MT_PROGRAMMES).toEqual(expect.arrayContaining([
      expect.objectContaining({
        company: 'The Hong Kong Jockey Club (HKJC)',
        programmeName: 'Management Trainee',
        applicationUrls: ['https://careers.hkjc.com/job/Happy-Valley-Management-Trainee-Hong/1366549566/'],
      }),
      expect.objectContaining({
        company: 'Hong Kong Monetary Authority (HKMA)',
        programmeName: 'Manager Trainee Programme',
        applicationUrls: ['https://www.hkma.gov.hk/eng/about-us/join-us/opportunities-for-students-and-graduates-to-join-the-hkma/manager-trainee-programme/'],
      }),
    ]))
    expect(VERIFIED_MT_PROGRAMMES).toHaveLength(2)
    expect(VERIFIED_MT_PROGRAMMES.every(programme => programme.application === undefined)).toBe(true)
  })

  it('keeps the directly verified official MT links in the directory', () => {
    expect(FEATURED_MT_PROGRAMMES.map(programme => programme.company)).toEqual(expect.arrayContaining([
      'The Hong Kong Jockey Club (HKJC)',
      'Hong Kong Monetary Authority (HKMA)',
    ]))
  })

  it('selects one direct programme link rather than exposing a link pile', () => {
    expect(selectMasterApplicationUrl([
      'https://example.com/careers/internships',
      'https://example.com/job/management-trainee',
    ])).toBe('https://example.com/job/management-trainee')
  })

  it('reconciles source-specific employer names to one status identity', () => {
    expect(mtEmployerKey('The Hong Kong Jockey Club (HKJC)')).toBe('hkjc')
    expect(mtEmployerKey('The Hong Kong Jockey Club')).toBe('hkjc')
    expect(mtEmployerKey('Hong Kong Monetary Authority (HKMA)')).toBe('hkma')
    expect(mtEmployerKey('Bank Of China (Hong Kong) Limited')).toBe('bochk')
  })
})
