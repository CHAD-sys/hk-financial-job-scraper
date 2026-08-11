import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import MemberRoleNotice from './MemberRoleNotice'

describe('MemberRoleNotice', () => {
  it('advertises exclusive roles and preserves the current research for both account paths', () => {
    render(
      <MemoryRouter>
        <MemberRoleNotice returnTo="/jobs?q=risk&sort=relevance" />
      </MemoryRouter>,
    )

    expect(screen.getByRole('heading', { name: /register to unlock exclusive jobs/i })).toBeInTheDocument()
    expect(screen.getByText(/recruiter-posted roles and opportunities from medium-sized companies/i)).toBeInTheDocument()

    const register = screen.getByRole('link', { name: /create free account/i })
    expect(register).toHaveAttribute('href', '/register')

    const signIn = screen.getByRole('link', { name: /already registered\? sign in/i })
    expect(signIn).toHaveAttribute('href', '/signin')
  })
})
