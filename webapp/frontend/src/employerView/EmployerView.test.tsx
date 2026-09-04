import { render, screen, act } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import EmployerViewProvider from './EmployerViewProvider'
import { useEmployerView } from './useEmployerView'

/**
 * Employer view is a PREVIEW, and the tests that matter are the ones pinning
 * what it must never become.
 *
 * A stale `true` in localStorage is the shared risk with Admin Mode: left by an
 * Ultimate Admin who used this browser before, or hand-set by anyone curious
 * enough to open devtools. For Admin Mode that would draw controls whose
 * requests 403 anyway. Here it would put a visitor inside another product's
 * shell, so `canUseEmployerView` is recomputed every render rather than read
 * once at sign-in.
 *
 * The rule with no counterpart in Admin Mode is the real-session one: an
 * Ultimate Admin who is ALSO signed in as an Employer must not get the preview.
 * Two employer identities in one nav — one real, one previewed — is worse than
 * having neither, because nothing on the bar would say which is which.
 */

const KEY = 'finex_employer_view:v1'

const authValue = { seeker: null as Record<string, unknown> | null, loading: false }
const employerAuthValue = { employer: null as Record<string, unknown> | null, loading: false }
vi.mock('../auth/useAuth', () => ({ useAuth: () => authValue }))
vi.mock('../auth/useEmployerAuth', () => ({ useEmployerAuth: () => employerAuthValue }))

function Probe() {
  const { employerView, canUseEmployerView, setEmployerView } = useEmployerView()
  return (
    <div>
      <span data-testid="mode">{employerView ? 'on' : 'off'}</span>
      <span data-testid="can">{canUseEmployerView ? 'yes' : 'no'}</span>
      <button type="button" onClick={() => setEmployerView(true)}>enter</button>
      <button type="button" onClick={() => setEmployerView(false)}>leave</button>
    </div>
  )
}

function renderProbe() {
  return render(<EmployerViewProvider><Probe /></EmployerViewProvider>)
}

const mode = () => screen.getByTestId('mode').textContent
const can = () => screen.getByTestId('can').textContent

beforeEach(() => {
  window.localStorage.clear()
  authValue.seeker = null
  authValue.loading = false
  employerAuthValue.employer = null
  employerAuthValue.loading = false
})
afterEach(() => window.localStorage.clear())

describe('Employer view', () => {
  it('is off for an Ultimate Admin who has not asked for it', () => {
    authValue.seeker = { is_super_admin: true, is_admin: true }
    renderProbe()
    expect(mode()).toBe('off')
    expect(can()).toBe('yes')
  })

  it('turns on and off, and survives a reload', () => {
    authValue.seeker = { is_super_admin: true, is_admin: true }
    const { unmount } = renderProbe()
    act(() => screen.getByText('enter').click())
    expect(mode()).toBe('on')

    unmount()
    renderProbe()
    expect(mode()).toBe('on')

    act(() => screen.getByText('leave').click())
    expect(mode()).toBe('off')
  })

  it('is unavailable to an ordinary admin', () => {
    // Ultimate Admin only, unlike Admin Mode — the other four admins have no
    // reason to be inside another product's shell.
    authValue.seeker = { is_admin: true }
    renderProbe()
    expect(can()).toBe('no')
  })

  it('is unavailable to a plain Seeker, and a stale stored flag does not survive', () => {
    window.localStorage.setItem(KEY, '1')
    authValue.seeker = { is_admin: false }
    renderProbe()

    expect(can()).toBe('no')
    expect(mode()).toBe('off')
    expect(window.localStorage.getItem(KEY)).toBeNull()
  })

  it('is unavailable to a signed-out visitor who hand-set the flag', () => {
    window.localStorage.setItem(KEY, '1')
    authValue.seeker = null
    renderProbe()

    expect(can()).toBe('no')
    expect(mode()).toBe('off')
  })

  it('gives way to a real Employer session rather than previewing over it', () => {
    // The rule with no Admin Mode counterpart. Previewing "what an Employer
    // sees" while BEING one is not a preview, and the nav would carry two
    // competing employer identities with nothing to tell them apart.
    authValue.seeker = { is_super_admin: true, is_admin: true }
    employerAuthValue.employer = { id: 'emp-1', company_name: 'Acme Capital' }
    renderProbe()

    expect(can()).toBe('no')
    expect(mode()).toBe('off')
  })

  it('ends an active preview the moment a real Employer signs in here', () => {
    authValue.seeker = { is_super_admin: true, is_admin: true }
    const { unmount } = renderProbe()
    act(() => screen.getByText('enter').click())
    expect(mode()).toBe('on')
    unmount()

    employerAuthValue.employer = { id: 'emp-1', company_name: 'Acme Capital' }
    renderProbe()

    expect(mode()).toBe('off')
    // Cleared, not merely ignored: signing out of the Employer account later
    // must not silently restore a preview nobody asked for again.
    expect(window.localStorage.getItem(KEY)).toBeNull()
  })

  it('stays off while either session is still loading', () => {
    // Same reasoning as the nav's 'pending' account slot: acting on a
    // half-answered pair of sessions is how a preview flashes at a real
    // Employer mid-load.
    authValue.seeker = { is_super_admin: true }
    employerAuthValue.loading = true
    window.localStorage.setItem(KEY, '1')
    renderProbe()

    // The employer session has not answered, so it cannot yet be ruled out.
    expect(can()).toBe('yes')
    // But nothing has been cleared on the strength of an unanswered session.
    expect(window.localStorage.getItem(KEY)).toBe('1')
  })
})
