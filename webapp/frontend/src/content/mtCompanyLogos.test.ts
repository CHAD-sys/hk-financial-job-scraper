import { describe, expect, it } from 'vitest'
import { mtCompanyLogo } from './mtCompanyLogos'

describe('MT company logo lookup', () => {
  it('uses locally compressed colour assets for active MT employers', () => {
    expect(mtCompanyLogo('Goldman Sachs').src).toBe('/company-logos/goldman-sachs.webp')
    expect(mtCompanyLogo('Bank of China (Hong Kong) [BOCHK]').src).toBe('/company-logos/bochk.webp')
    expect(mtCompanyLogo('Standard Chartered').src).toBe('/company-logos/standard-chartered.png')
  })

  it('has a readable fallback for an employer whose logo is not mapped yet', () => {
    expect(mtCompanyLogo('Example Bank')).toEqual({ wordmark: 'Example Bank' })
  })

  it('keeps the company name as a readable fallback when an image cannot load', () => {
    expect(mtCompanyLogo('The Bank of East Asia (BEA)')).toEqual({
      src: '/company-logos/bea.webp',
      wordmark: 'The Bank of East Asia (BEA)',
    })
  })
})
