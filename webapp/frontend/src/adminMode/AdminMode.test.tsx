import { render, screen, act } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AdminModeProvider from './AdminModeProvider'
import { useAdminMode } from './useAdminMode'

/**
 * Admin Mode is a mode, not a label.
 *
 * The switch used to navigate and nothing else, while the board's admin powers
 * stayed on in both "modes" — so the button announced a state change that never
 * happened, and Seeker view was Seeker view in name only. These tests pin the
 * property that makes it real: OFF means an admin sees what a Seeker sees.
 */

const KEY = 'finex_admin_mode:v1'

// The provider reads the signed-in Seeker to decide whether the mode is even
// available, so useAuth is the one thing that has to be stood in for.
const authValue = { seeker: null as Record<string, unknown> | null, loading: false }
vi.mock('../auth/useAuth', () => ({ useAuth: () => authValue }))

function Probe() {
  const { adminMode, canUseAdminMode, setAdminMode } = useAdminMode()
  return (
    <div>
      <span data-testid="mode">{adminMode ? 'on' : 'off'}</span>
      <span data-testid="can">{canUseAdminMode ? 'yes' : 'no'}</span>
      <button type="button" onClick={() => setAdminMode(true)}>enter</button>
      <button type="button" onClick={() => setAdminMode(false)}>leave</button>
    </div>
  )
}

function renderProbe() {
  return render(<AdminModeProvider><Probe /></AdminModeProvider>)
}

const mode = () => screen.getByTestId('mode').textContent

beforeEach(() => {
  window.localStorage.clear()
  authValue.seeker = null
  authValue.loading = false
})
afterEach(() => window.localStorage.clear())

describe('Admin Mode', () => {
  it('is off for an admin who has not asked for it', () => {
    // The default has to be OFF, or "Seeker view" would never be the state an
    // admin actually browses in and the mode would be decorative again.
    authValue.seeker = { is_admin: true }
    renderProbe()
    expect(mode()).toBe('off')
    expect(screen.getByTestId('can').textContent).toBe('yes')
  })

  it('turns on and off', () => {
    authValue.seeker = { is_admin: true }
    renderProbe()
    act(() => screen.getByText('enter').click())
    expect(mode()).toBe('on')
    act(() => screen.getByText('leave').click())
    expect(mode()).toBe('off')
  })

  it('survives a reload, so the choice does not reset mid-task', () => {
    authValue.seeker = { is_admin: true }
    const { unmount } = renderProbe()
    act(() => screen.getByText('enter').click())
    unmount()

    renderProbe()
    expect(mode()).toBe('on')
  })

  it('is available to an Ultimate Admin carrying only the stronger bit', () => {
    // seekers_store.set_super_admin() writes only its own column, so the two
    // bits are independent in the data model — reading just is_admin would
    // strand that account outside Admin Mode entirely.
    authValue.seeker = { is_super_admin: true }
    renderProbe()
    expect(screen.getByTestId('can').textContent).toBe('yes')
  })

  it('is never on for someone who is not an admin', () => {
    authValue.seeker = { is_admin: false }
    renderProbe()
    expect(mode()).toBe('off')
    expect(screen.getByTestId('can').textContent).toBe('no')
  })

  it('ignores a stale flag left in this browser by a previous admin', () => {
    // A shared machine, or a curious visitor setting the key by hand. Either
    // way a Seeker must not end up with admin controls drawn at them, whose
    // requests would only 403.
    window.localStorage.setItem(KEY, '1')
    authValue.seeker = { is_admin: false }
    renderProbe()
    expect(mode()).toBe('off')
  })

  it('clears that stale flag rather than leaving it to be inherited again', () => {
    window.localStorage.setItem(KEY, '1')
    authValue.seeker = null
    renderProbe()
    expect(window.localStorage.getItem(KEY)).toBeNull()
  })
})
