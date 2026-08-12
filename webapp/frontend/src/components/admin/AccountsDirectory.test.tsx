import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { AdminAccountsResponse, AdminSeekerInterests } from '../../api/client'

const fetchSeekerInterests = vi.fn<(seekerId: string) => Promise<AdminSeekerInterests>>()

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  fetchSeekerInterests: (seekerId: string) => fetchSeekerInterests(seekerId),
}))

const { default: AccountsDirectory } = await import('./AccountsDirectory')

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

const EMPTY_INTERESTS: AdminSeekerInterests = {
  resume_skills: [], resume_role_families: [], resume_sectors: [], resume_seniority: null,
  searched_sectors: [], searched_skills: [], searched_seniority: [], recent_search_terms: [],
  saved_roles_count: 0,
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

  it('fetches a Seeker\'s interests only once their row is expanded', async () => {
    fetchSeekerInterests.mockResolvedValue({
      ...EMPTY_INTERESTS,
      resume_skills: ['sql'],
      resume_sectors: ['Banking'],
      resume_seniority: 'mid',
      searched_sectors: ['Banking'],
      recent_search_terms: ['credit analyst'],
      saved_roles_count: 2,
    })
    render(<AccountsDirectory data={DATA} />)
    expect(fetchSeekerInterests).not.toHaveBeenCalled()

    fireEvent.click(screen.getByLabelText('Show interests for amy@example.com'))

    expect(fetchSeekerInterests).toHaveBeenCalledWith('s1')
    await waitFor(() => expect(screen.getByText('sql')).toBeInTheDocument())
    expect(screen.getByText('credit analyst')).toBeInTheDocument()
    expect(screen.getByText('2 saved Roles')).toBeInTheDocument()
  })

  it('shows a plain message when a Seeker has no interest signal on file', async () => {
    fetchSeekerInterests.mockResolvedValue(EMPTY_INTERESTS)
    render(<AccountsDirectory data={DATA} />)

    fireEvent.click(screen.getByLabelText('Show interests for amy@example.com'))

    await waitFor(() =>
      expect(screen.getByText(/No resume, search, or saved-Role activity/)).toBeInTheDocument(),
    )
  })

  it('collapses a Seeker\'s interests when toggled again', async () => {
    fetchSeekerInterests.mockResolvedValue(EMPTY_INTERESTS)
    render(<AccountsDirectory data={DATA} />)

    const toggle = screen.getByLabelText('Show interests for amy@example.com')
    fireEvent.click(toggle)
    await waitFor(() => expect(screen.getByText(/No resume, search, or saved-Role activity/)).toBeInTheDocument())

    fireEvent.click(screen.getByLabelText('Hide interests for amy@example.com'))

    expect(screen.queryByText(/No resume, search, or saved-Role activity/)).not.toBeInTheDocument()
  })
})
