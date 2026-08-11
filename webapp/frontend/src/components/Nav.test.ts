import { describe, expect, it } from 'vitest'
import { primaryLinksFor } from './Nav'

describe('primaryLinksFor', () => {
  it('adds one Admin panel destination for administrators', () => {
    expect(primaryLinksFor(true).map(link => link.label)).toEqual([
      'Home',
      'Careers',
      'Consultation',
      'Learning',
      'Market Research',
      'About',
      'Admin panel',
    ])
  })

  it('does not expose the Admin panel destination to ordinary seekers', () => {
    expect(primaryLinksFor(false).map(link => link.label)).not.toContain('Admin panel')
  })
})
