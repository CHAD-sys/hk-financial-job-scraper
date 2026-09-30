import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const resetEmployerPassword = vi.hoisted(() => vi.fn())
const acceptAuthenticatedEmployer = vi.hoisted(() => vi.fn())

vi.mock('../api/client', async importOriginal => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  resetEmployerPassword,
}))
vi.mock('../auth/useEmployerAuth', () => ({
  useEmployerAuth: () => ({ acceptAuthenticatedEmployer }),
}))
vi.mock('../components/AuthShell', () => ({
  AuthShell: ({ children }: { children: React.ReactNode }) => <main>{children}</main>,
  AuthField: ({ label, htmlFor, children }: { label: string; htmlFor: string; children: React.ReactNode }) => (
    <div><label htmlFor={htmlFor}>{label}</label>{children}</div>
  ),
}))

const { default: EmployerResetPasswordPage } = await import('./EmployerResetPasswordPage')

const employer = {
  id: 'employer-1',
  email: 'people@example.com',
  company_name: 'Example Capital',
  contact_name: 'Jamie Lee',
  email_verified: true,
}

beforeEach(() => {
  resetEmployerPassword.mockReset()
  resetEmployerPassword.mockResolvedValue(employer)
  acceptAuthenticatedEmployer.mockReset()
})

describe('Employer password reset', () => {
  it('adopts the authenticated session before entering Post a role', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/employer/reset-password?token=valid-token']}>
        <Routes>
          <Route path="/employer/reset-password" element={<EmployerResetPasswordPage />} />
          <Route path="/post-a-role" element={<div>Post a role destination</div>} />
        </Routes>
      </MemoryRouter>,
    )

    await user.type(screen.getByLabelText('New password'), 'new-password')
    await user.type(screen.getByLabelText('Confirm new password'), 'new-password')
    await user.click(screen.getByRole('button', { name: /Save new password/ }))

    expect(resetEmployerPassword).toHaveBeenCalledWith('valid-token', 'new-password')
    expect(acceptAuthenticatedEmployer).toHaveBeenCalledWith(employer)
    expect(await screen.findByText('Post a role destination')).toBeInTheDocument()
  })
})
