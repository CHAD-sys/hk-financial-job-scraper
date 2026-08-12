import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { AdminAccountsResponse } from '../../api/client'
import AccountsDirectory from './AccountsDirectory'

const DATA: AdminAccountsResponse = {
  seekers: [
    {
      id: 's1', email: 'amy@example.com', display_name: 'Amy Chan', username: null,
      email_verified: true, is_admin: false, is_super_admin: false,
      created_at: '2026-08-01T00:00:00+00:00', last_login_at: '2026-08-10T00:00:00+00:00',
    },
    {
      id: 's2', email: 'root@example.com', display_name: null, username: 'root',
      email_verified: true, is_admin: true, is_super_admin: true,
      created_at: '2026-07-01T00:00:00+00:00', last_login_at: null,
    },
  ],
  employers: [
    {
      id: 'e1', email: 'recruiter@acme.test', company_name: 'Acme Capital', contact_name: 'Jamie Lee',
      email_verified: false, created_at: '2026-08-05T00:00:00+00:00', last_login_at: null,
    },
  ],
}

describe('AccountsDirectory', () => {
  it('lists every Seeker and Employer with their status flags', () => {
    render(<AccountsDirectory data={DATA} />)

    expect(screen.getByRole('heading', { name: 'Seekers' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Employers' })).toBeInTheDocument()
    expect(screen.getByText('amy@example.com')).toBeInTheDocument()
    expect(screen.getByText('recruiter@acme.test')).toBeInTheDocument()
    expect(screen.getByText('Acme Capital')).toBeInTheDocument()

    const rootRow = screen.getByText('root@example.com').closest('tr')!
    expect(within(rootRow).getByText('Ultimate Admin')).toBeInTheDocument()
    expect(within(rootRow).queryByText('Admin')).not.toBeInTheDocument() // superseded by the higher flag
  })

  it('filters both tables together by email, name or company', () => {
    render(<AccountsDirectory data={DATA} />)

    fireEvent.change(screen.getByLabelText('Filter accounts by email or name'), { target: { value: 'acme' } })

    expect(screen.queryByText('amy@example.com')).not.toBeInTheDocument()
    expect(screen.queryByText('root@example.com')).not.toBeInTheDocument()
    expect(screen.getByText('recruiter@acme.test')).toBeInTheDocument()
  })

  it('never renders a password_hash field even if one slipped through', () => {
    render(<AccountsDirectory data={DATA} />)
    expect(screen.queryByText(/password/i)).not.toBeInTheDocument()
  })
})
