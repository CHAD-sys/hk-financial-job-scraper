import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * The Employer view switch — the fix for "where can I even switch it".
 *
 * The preview used to have no entry point in the bar at all, only a launcher
 * buried inside the Employer view panel on /admin (an Ultimate Admin has to
 * already know that panel exists to find it). This pins the fix at the level
 * it was reported at: the switch renders in the SAME row as Admin Mode and
 * Saved, is the one control that turns the preview on and off, and does not
 * strand an admin on /post-a-role — leaving the preview from there must
 * navigate away, or PostRolePage's own guard would immediately bounce to
 * /employer/signin.
 */

const navigateSpy = vi.hoisted(() => vi.fn())
vi.mock('react-router-dom', async importOriginal => ({
  ...(await importOriginal<typeof import('react-router-dom')>()),
  useNavigate: () => navigateSpy,
}))

const authValue = vi.hoisted(() => ({
  seeker: null as Record<string, unknown> | null, loading: false, logout: vi.fn(),
}))
const employerAuthValue = vi.hoisted(() => ({
  employer: null as Record<string, unknown> | null, loading: false, logout: vi.fn(),
}))
const adminModeValue = vi.hoisted(() => ({
  adminMode: false, canUseAdminMode: false, setAdminMode: vi.fn(),
}))
const employerViewValue = vi.hoisted(() => ({
  employerView: false, canUseEmployerView: false, setEmployerView: vi.fn(),
}))

vi.mock('../auth/useAuth', () => ({ useAuth: () => authValue }))
vi.mock('../auth/useEmployerAuth', () => ({ useEmployerAuth: () => employerAuthValue }))
vi.mock('../adminMode/useAdminMode', () => ({ useAdminMode: () => adminModeValue }))
vi.mock('../employerView/useEmployerView', () => ({ useEmployerView: () => employerViewValue }))
vi.mock('../savedRoles/useSavedRoles', () => ({ useSavedRoles: () => ({ count: 0 }) }))
vi.mock('../hooks/useRecordVisit', () => ({}))

const { default: Nav } = await import('./Nav')

function renderNav() {
  return render(<MemoryRouter><Nav /></MemoryRouter>)
}

beforeEach(() => {
  navigateSpy.mockClear()
  authValue.seeker = null
  authValue.loading = false
  employerAuthValue.employer = null
  employerAuthValue.loading = false
  adminModeValue.adminMode = false
  adminModeValue.canUseAdminMode = false
  employerViewValue.employerView = false
  employerViewValue.canUseEmployerView = false
})

describe('Nav — Employer view switch', () => {
  it('is absent for anyone who could not use it', () => {
    renderNav()
    expect(screen.queryByRole('button', { name: /Employer view/ })).not.toBeInTheDocument()
  })

  it('sits beside Admin Mode for an eligible Ultimate Admin', () => {
    adminModeValue.canUseAdminMode = true
    employerViewValue.canUseEmployerView = true
    renderNav()

    // Both present in the same bar — this is "add it up top with the two
    // others", not a replacement for either.
    expect(screen.getAllByRole('button', { name: 'Admin Mode' }).length).toBeGreaterThan(0)
    expect(screen.getAllByRole('button', { name: 'Employer view' }).length).toBeGreaterThan(0)
  })

  it('turns on and navigates straight to Post a role', async () => {
    employerViewValue.canUseEmployerView = true
    renderNav()

    await userEvent.click(screen.getAllByRole('button', { name: 'Employer view' })[0])

    expect(employerViewValue.setEmployerView).toHaveBeenCalledWith(true)
    expect(navigateSpy).toHaveBeenCalledWith('/post-a-role')
  })

  it('relabels to "Leave preview" once on, and reads that on the button', () => {
    employerViewValue.canUseEmployerView = true
    employerViewValue.employerView = true
    renderNav()

    expect(screen.getAllByRole('button', { name: 'Leave preview' }).length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: 'Employer view' })).not.toBeInTheDocument()
  })

  it('leaving navigates to the board when not in Admin Mode', async () => {
    // Went RED with no navigation on the OFF click: leaving while sitting on
    // /post-a-role would otherwise strand the admin on a page that redirects
    // anyone without the preview flag to /employer/signin.
    employerViewValue.canUseEmployerView = true
    employerViewValue.employerView = true
    adminModeValue.adminMode = false
    renderNav()

    await userEvent.click(screen.getAllByRole('button', { name: 'Leave preview' })[0])

    expect(employerViewValue.setEmployerView).toHaveBeenCalledWith(false)
    expect(navigateSpy).toHaveBeenCalledWith('/jobs')
  })

  it('leaving returns to the admin panel when in Admin Mode', async () => {
    employerViewValue.canUseEmployerView = true
    employerViewValue.employerView = true
    adminModeValue.adminMode = true
    renderNav()

    await userEvent.click(screen.getAllByRole('button', { name: 'Leave preview' })[0])

    expect(navigateSpy).toHaveBeenCalledWith('/admin')
  })

  it('shows Post a role while previewing, with no invented Employer identity beside it', () => {
    // The preview reuses the real Employer's "Post a role" slot so there is
    // something to look at, but it must never render EmployerMenu — that
    // component shows a real company name and a real sign-out, neither of
    // which exist for a preview.
    employerViewValue.canUseEmployerView = true
    employerViewValue.employerView = true
    renderNav()

    expect(screen.getAllByRole('link', { name: 'Post a role' }).length).toBeGreaterThan(0)
    expect(screen.queryByText(/Sign out \(Employer\)/)).not.toBeInTheDocument()
  })
})
