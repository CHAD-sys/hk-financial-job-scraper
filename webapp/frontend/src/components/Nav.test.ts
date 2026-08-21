import { describe, expect, it } from 'vitest'
import { primaryLinksFor } from './Nav'

/**
 * Admins get one extra destination in the primary row; Ultimate Admin gets a
 * second, independent one.
 *
 * "Admin panel" coexists with the AdminModeSwitch button rather than being
 * replaced by it: the row lists places you can go, the switch toggles between
 * two of them and is what carries an admin back out of the panel. Briefly
 * (PR #42) the link was dropped in favour of the switch alone, which left the
 * panel absent from the one list every other part of the product appears in.
 *
 * "ASF" (Audit Salary Fixing, 2026-08-21) is gated on `isSuperAdmin` alone —
 * deliberately independent of `isAdmin`, so a plain admin never sees it even
 * though they see "Admin panel".
 */
describe('primaryLinksFor', () => {
  const SIX = ['Home', 'Careers', 'Consultation', 'Learning', 'Market Research', 'About']

  it('adds one Admin panel destination for administrators', () => {
    expect(primaryLinksFor(true, false).map(link => link.label)).toEqual([...SIX, 'Admin panel'])
  })

  it('points that destination at the panel', () => {
    const admin = primaryLinksFor(true, false).find(link => link.label === 'Admin panel')
    expect(admin?.to).toBe('/admin')
  })

  it('does not expose the Admin panel destination to ordinary seekers', () => {
    expect(primaryLinksFor(false, false).map(link => link.label)).toEqual(SIX)
  })

  it('leaves the six shared destinations untouched for admins', () => {
    // The extra entry is an ADDITION. An admin must not lose or reorder the
    // product's own navigation on their way to the panel.
    expect(primaryLinksFor(true, false).slice(0, 6).map(link => link.label)).toEqual(SIX)
  })

  it('adds ASF for Ultimate Admin, after Admin panel', () => {
    expect(primaryLinksFor(true, true).map(link => link.label))
      .toEqual([...SIX, 'Admin panel', 'ASF'])
  })

  it('points ASF at /asf', () => {
    const asf = primaryLinksFor(true, true).find(link => link.label === 'ASF')
    expect(asf?.to).toBe('/asf')
  })

  it('adds ASF even when isAdmin is false — the two bits are independent', () => {
    // A super-admin-only account (is_super_admin without is_admin) must still
    // see ASF, even though it would not see "Admin panel".
    expect(primaryLinksFor(false, true).map(link => link.label)).toEqual([...SIX, 'ASF'])
  })

  it('never exposes ASF to a plain administrator', () => {
    expect(primaryLinksFor(true, false).map(link => link.label)).not.toContain('ASF')
  })
})
