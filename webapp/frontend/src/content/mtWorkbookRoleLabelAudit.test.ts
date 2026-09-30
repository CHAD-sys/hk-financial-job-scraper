import { describe, expect, it } from 'vitest'
import { MT_WORKBOOK_PROGRAMMES, mtApplicationRoleLabel } from './mtWorkbookProgrammes'

describe('MT workbook role-label audit', () => {
  it('keeps every workbook route free of raw provider metadata and numbered placeholders', () => {
    const labels = MT_WORKBOOK_PROGRAMMES.map(mtApplicationRoleLabel)

    expect(labels).toHaveLength(169)
    expect(labels).not.toContain('Application link')
    expect(labels).toContain('Rotational Analyst 2027 Leadership Development Program')
    for (const label of labels) {
      expect(label).not.toMatch(/\b(?:en gb|homewithpreload|jobdetail|mgttrainee|recruitdetail|searchjobs|sol)\b/i)
      expect(label).not.toMatch(/\s[1-9]$/)
      expect(label).not.toMatch(/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}/i)
    }
  })
})
