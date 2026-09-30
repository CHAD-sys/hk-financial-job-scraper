import { describe, expect, it } from 'vitest'
import { MT_WORKBOOK_PROGRAMMES, mtApplicationRoleLabel } from './mtWorkbookProgrammes'

describe('MT workbook role labels', () => {
  it('uses the meaningful role slug, never a trailing URL locale', () => {
    const jefferies = MT_WORKBOOK_PROGRAMMES.find(programme => programme.id === 'mt-workbook-row-18')

    expect(jefferies).toBeDefined()
    expect(mtApplicationRoleLabel(jefferies!)).toBe('2027 Summer Analyst Program Investment Banking')
  })

  it('uses a provider jobTitle parameter when the role is explicitly supplied', () => {
    const boci = MT_WORKBOOK_PROGRAMMES.find(programme => programme.id === 'mt-workbook-row-10')

    expect(boci).toBeDefined()
    expect(mtApplicationRoleLabel(boci!)).toBe('2027 Management Trainee Programme')
  })
})
