import { describe, expect, it } from 'vitest'
import { accountSlotFor, primaryLinksFor } from './Nav'

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

/**
 * Who the account slot says you are.
 *
 * Seeker and Employer are separate accounts with separate sessions (ADR 0001)
 * and both can be signed in at once. This slot used to be decided from the
 * Seeker session alone, inline, in the desktop bar AND again in the mobile
 * menu — so a signed-in Employer got their company chip and a bare "Sign in"
 * link side by side, in both menus, which reads as "you are not signed in".
 */
describe('accountSlotFor', () => {
  const settled = { authLoading: false, employerAuthLoading: false }

  it('does not ask a signed-in employer to sign in', () => {
    // The reported bug, exactly: employer session, no seeker session.
    expect(accountSlotFor({ ...settled, hasSeeker: false, hasEmployer: true }))
      .toBe('employer')
  })

  it('still asks a visitor with neither account to sign in', () => {
    expect(accountSlotFor({ ...settled, hasSeeker: false, hasEmployer: false }))
      .toBe('sign-in')
  })

  it('shows the seeker menu to a signed-in seeker', () => {
    expect(accountSlotFor({ ...settled, hasSeeker: true, hasEmployer: false }))
      .toBe('seeker')
  })

  it('gives the slot to the seeker when both accounts are signed in', () => {
    // The bar renders the Employer's "Post a role" button and EmployerMenu
    // independently, so the Employer is still represented either way.
    expect(accountSlotFor({ ...settled, hasSeeker: true, hasEmployer: true }))
      .toBe('seeker')
  })

  it('waits for the EMPLOYER session before offering "Sign in"', () => {
    // The half of the gate that was missing. With only the seeker session
    // resolved, an employer would see "Sign in" flash before their own chip
    // arrived — the same contradiction, just briefer.
    expect(accountSlotFor({
      authLoading: false, hasSeeker: false,
      employerAuthLoading: true, hasEmployer: false,
    })).toBe('pending')
  })

  it('waits for the seeker session too', () => {
    expect(accountSlotFor({
      authLoading: true, hasSeeker: false,
      employerAuthLoading: false, hasEmployer: false,
    })).toBe('pending')
  })
})
