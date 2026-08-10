import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import AdminSectionNav from './AdminSectionNav'

beforeEach(() => window.history.replaceState(null, '', '/admin#operations-center'))

describe('AdminSectionNav', () => {
  it('makes every ordinary-admin section prominent without exposing the job editor', () => {
    render(<AdminSectionNav isSuperAdmin={false} />)

    expect(screen.getByRole('navigation', { name: 'Admin page sections' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Operations center/ })).toHaveAttribute('aria-current', 'location')
    expect(screen.getByRole('link', { name: /Market intelligence/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Daily collection/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Verification/ })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Job editor/ })).not.toBeInTheDocument()
  })

  it('shows the privileged editor only to the Ultimate Admin and marks a selected section', () => {
    render(<AdminSectionNav isSuperAdmin />)
    const market = screen.getByRole('link', { name: /Market intelligence/ })

    expect(screen.getByRole('link', { name: /Job editor/ })).toBeInTheDocument()
    fireEvent.click(market)
    expect(market).toHaveAttribute('aria-current', 'location')
  })
})
