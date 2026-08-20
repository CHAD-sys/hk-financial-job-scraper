import { describe, expect, it } from 'vitest'
import { primaryLinksFor } from './Nav'

/**
 * The primary row is the same six destinations for everybody. An admin reaches
 * the panel through the AdminModeSwitch button in the utility strip, which is
 * bidirectional; the old seventh "Admin panel" link only went one way and left
 * an admin inside the panel with no nav route back to the product.
 */
describe('primaryLinksFor', () => {
  const SIX = ['Home', 'Careers', 'Consultation', 'Learning', 'Market Research', 'About']

  it('gives administrators the same six destinations as everyone else', () => {
    expect(primaryLinksFor(true).map(link => link.label)).toEqual(SIX)
  })

  it('does not expose an Admin panel link to ordinary seekers', () => {
    expect(primaryLinksFor(false).map(link => link.label)).not.toContain('Admin panel')
  })

  it('no longer routes admins to the panel through the primary row at all', () => {
    expect(primaryLinksFor(true).map(link => link.to)).not.toContain('/admin')
  })
})
