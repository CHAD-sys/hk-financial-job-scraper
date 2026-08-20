import { describe, expect, it } from 'vitest'
import { primaryLinksFor } from './Nav'

/**
 * Admins get one extra destination in the primary row.
 *
 * It coexists with the AdminModeSwitch button rather than being replaced by it:
 * the row lists places you can go, the switch toggles between two of them and
 * is what carries an admin back out of the panel. Briefly (PR #42) the link was
 * dropped in favour of the switch alone, which left the panel absent from the
 * one list every other part of the product appears in.
 */
describe('primaryLinksFor', () => {
  const SIX = ['Home', 'Careers', 'Consultation', 'Learning', 'Market Research', 'About']

  it('adds one Admin panel destination for administrators', () => {
    expect(primaryLinksFor(true).map(link => link.label)).toEqual([...SIX, 'Admin panel'])
  })

  it('points that destination at the panel', () => {
    const admin = primaryLinksFor(true).find(link => link.label === 'Admin panel')
    expect(admin?.to).toBe('/admin')
  })

  it('does not expose the Admin panel destination to ordinary seekers', () => {
    expect(primaryLinksFor(false).map(link => link.label)).toEqual(SIX)
  })

  it('leaves the six shared destinations untouched for admins', () => {
    // The extra entry is an ADDITION. An admin must not lose or reorder the
    // product's own navigation on their way to the panel.
    expect(primaryLinksFor(true).slice(0, 6).map(link => link.label)).toEqual(SIX)
  })
})
