import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import AdminSectionNav from './AdminSectionNav'

beforeEach(() => window.history.replaceState(null, '', '/admin#operations-center'))

describe('AdminSectionNav', () => {
  it('makes every ordinary-admin section prominent, the job editor included', () => {
    render(<AdminSectionNav isSuperAdmin={false} />)

    expect(screen.getByRole('navigation', { name: 'Admin page sections' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Operations center/ })).toHaveAttribute('aria-current', 'location')
    expect(screen.getByRole('link', { name: /Market intelligence/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Daily collection/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Verification/ })).toBeInTheDocument()
  })

  it('gives an ordinary admin the category that reaches the job editor', () => {
    // ADR 0019 widened /api/admin/jobs to every admin. Leaving the panel's
    // category behind the stricter bit meant an admin in Admin Mode had the
    // permission and no way in the panel to use it. Went RED before the
    // superAdminOnly flag came off.
    render(<AdminSectionNav isSuperAdmin={false} />)
    expect(screen.getByRole('link', { name: /Job editor/ })).toBeInTheDocument()
  })

  it('still keeps the account directory to the Ultimate Admin', () => {
    // The half of the split that did NOT move. Widening job editing must not
    // quietly widen access to Seeker accounts and their stored resumes.
    render(<AdminSectionNav isSuperAdmin={false} />)
    expect(screen.queryByRole('link', { name: /Account directory/ })).not.toBeInTheDocument()
  })

  it('shows the account directory to the Ultimate Admin and marks a selected section', () => {
    render(<AdminSectionNav isSuperAdmin />)
    const market = screen.getByRole('link', { name: /Market intelligence/ })

    expect(screen.getByRole('link', { name: /Job editor/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Account directory/ })).toBeInTheDocument()
    fireEvent.click(market)
    expect(market).toHaveAttribute('aria-current', 'location')
  })
})
