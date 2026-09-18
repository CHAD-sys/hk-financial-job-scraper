import { describe, expect, it } from 'vitest'
import { mtCompanyLogo } from './mtCompanyLogos'

describe('MT company logo lookup', () => {
  it('uses an employer domain for known MT employers', () => {
    expect(mtCompanyLogo('Hong Kong Monetary Authority (HKMA)').src).toContain('hkma.gov.hk')
    expect(mtCompanyLogo('Bank Of China (Hong Kong) Limited').src).toContain('BOCHK_Horizontal_Revised.jpg')
  })

  it('has a readable fallback for an employer whose logo is not mapped yet', () => {
    expect(mtCompanyLogo('Example Bank')).toEqual({ wordmark: 'Example Bank' })
  })

  it('uses a clean wordmark for BEA instead of the checkerboard raster', () => {
    expect(mtCompanyLogo('Bank of East Asia (BEA)')).toEqual({ wordmark: 'BEA 東亞銀行' })
  })
})
