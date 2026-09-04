import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import EmployerPerspective from './EmployerPerspective'
import type { AdminEmployerAccount, EmployerActivity } from '../../api/client'

/**
 * What this panel has to get right, and why each is worth a test:
 *
 *   - It must never call a Role live that a visitor cannot open. The board is
 *     capped at 60 Roles per employer (ADR 0035), so "62 open Roles" and "60 a
 *     Seeker can browse to" are different numbers and the panel exists partly
 *     to say so.
 *   - It must never present an attribution as fact. A submission is tied to an
 *     account by verified address or by company name alone, and the second is
 *     a weaker claim that the row has to disclose.
 *   - Moving the lens to another company must not carry across when the admin
 *     switches Employer — that would attribute one employer's Roles to another,
 *     the exact mistake the panel is built to prevent.
 */

const fetchEmployerActivity = vi.hoisted(() => vi.fn())
vi.mock('../../api/client', () => ({ fetchEmployerActivity }))

// The Employer-view launcher at the top of this panel reads the preview mode.
// Stubbed rather than wrapped in the real provider: this file's subject is the
// perspective tables, and the mode has its own tests in employerView/.
const employerViewValue = vi.hoisted(() => ({
  employerView: false, canUseEmployerView: false, setEmployerView: vi.fn(),
}))
vi.mock('../../employerView/useEmployerView', () => ({
  useEmployerView: () => employerViewValue,
}))

const EMPLOYERS: AdminEmployerAccount[] = [
  {
    id: 'emp-1', email: 'hr@acmecapital.com', company_name: 'Acme Capital',
    contact_name: 'Jamie Lee', email_verified: true,
    created_at: '2026-08-01T09:00:00+00:00', last_login_at: '2026-09-01T09:00:00+00:00',
  },
  {
    id: 'emp-2', email: 'hr@rivalbank.com', company_name: 'Rival Bank',
    contact_name: null, email_verified: false,
    created_at: '2026-08-02T09:00:00+00:00', last_login_at: null,
  },
]

function renderPanel() {
  return render(
    <MemoryRouter>
      <EmployerPerspective employers={EMPLOYERS} />
    </MemoryRouter>,
  )
}

function activity(over: Partial<EmployerActivity> = {}): EmployerActivity {
  return {
    employer: {
      id: 'emp-1', email: 'hr@acmecapital.com', company_name: 'Acme Capital',
      contact_name: 'Jamie Lee', email_verified: true,
      created_at: '2026-08-01T09:00:00+00:00', last_login_at: '2026-09-01T09:00:00+00:00',
    },
    lens: { company: 'Acme Capital', overridden: false, matched_spellings: ['Acme Capital'] },
    submissions: [],
    standing: {
      on_board: 60, capped: 2, aged_out: 1, undated: 0, hidden: 1, duplicate: 0, closed: 3,
    },
    board_roles: [],
    board_sample_size: 12,
    ...over,
  }
}

function submission(over: Partial<EmployerActivity['submissions'][number]> = {}) {
  return {
    id: 's1', title: 'Credit Analyst', company: 'Acme Capital',
    location: 'Central, Hong Kong', employment_type: 'Full-time', salary_range: '',
    apply_url: 'https://example.test/apply', contact_email: 'hr@acmecapital.com',
    contact_name: 'Jamie Lee', received_at: '2026-08-05T09:00:00+00:00',
    status: 'pending', rejected_reason: null, approved_source_id: null,
    matched_by: 'email' as const,
    ...over,
  }
}

async function choose(company: string) {
  await userEvent.selectOptions(screen.getByLabelText('Employer'), [
    screen.getByRole('option', { name: new RegExp(company) }),
  ])
}

beforeEach(() => {
  fetchEmployerActivity.mockReset()
  fetchEmployerActivity.mockResolvedValue(activity())
})

describe('EmployerPerspective', () => {
  it('asks for nothing until an Employer is chosen', () => {
    renderPanel()
    expect(fetchEmployerActivity).not.toHaveBeenCalled()
    expect(screen.getByText(/2 accounts registered/)).toBeInTheDocument()
  })

  it('separates the Roles a visitor can open from the ones the cap withholds', async () => {
    // The number that matters. 60 on the board and 2 capped is the answer to
    // "why can't I see my role?", and a panel that merged them into "62 live"
    // would be the same non-answer the admin had before this existed.
    renderPanel()
    await choose('Acme Capital')

    const board = await screen.findByText('On the board')
    expect(board.parentElement).toHaveTextContent('60')
    expect(screen.getByText('Capped out').parentElement).toHaveTextContent('2')
  })

  it('discloses that a submission was matched on the company name alone', async () => {
    fetchEmployerActivity.mockResolvedValue(activity({
      submissions: [submission({ matched_by: 'company', contact_email: 'colleague@acmecapital.com' })],
    }))
    renderPanel()
    await choose('Acme Capital')

    expect(await screen.findByText('Company name only')).toBeInTheDocument()
  })

  it('marks a submission from the account’s own address as the stronger claim', async () => {
    fetchEmployerActivity.mockResolvedValue(activity({ submissions: [submission()] }))
    renderPanel()
    await choose('Acme Capital')

    expect(await screen.findByText('Their address')).toBeInTheDocument()
  })

  it('shows a rejected submission’s reason, which is what the Employer was told', async () => {
    fetchEmployerActivity.mockResolvedValue(activity({
      submissions: [submission({ status: 'rejected', rejected_reason: 'Not a HK role' })],
    }))
    renderPanel()
    await choose('Acme Capital')

    expect(await screen.findByText('Not a HK role')).toBeInTheDocument()
  })

  it('says so when no company in the catalogue matches the account', async () => {
    fetchEmployerActivity.mockResolvedValue(activity({
      lens: { company: 'Nowhere Ltd', overridden: false, matched_spellings: [] },
      standing: { on_board: 0, capped: 0, aged_out: 0, undated: 0, hidden: 0, duplicate: 0, closed: 0 },
    }))
    renderPanel()
    await choose('Acme Capital')

    expect(await screen.findByText(/No company in the catalogue is spelled/)).toBeInTheDocument()
    // Not "no data" — the honest answer is that nothing is attributed yet.
    expect(screen.getByText(/No Role in the catalogue is attributed/)).toBeInTheDocument()
  })

  it('drops the company lens when the admin switches Employer', async () => {
    // Carrying "Rival Bank" onto the next account would attribute one
    // employer's Roles to another. Went RED before the reset effect existed.
    renderPanel()
    await choose('Acme Capital')
    await screen.findByText('On the board')

    const lens = screen.getByLabelText('Override the company name Roles are attributed by')
    await userEvent.type(lens, 'Rival Bank')
    await waitFor(() => expect(fetchEmployerActivity).toHaveBeenCalledWith('emp-1', 'Rival Bank'))

    await choose('Rival Bank')
    await waitFor(() => expect(fetchEmployerActivity).toHaveBeenLastCalledWith('emp-2', ''))
    expect(lens).toHaveValue('')
  })

  it('surfaces a failed load in place instead of an empty panel', async () => {
    fetchEmployerActivity.mockRejectedValue(new Error('Could not load this Employer’s activity (403).'))
    renderPanel()
    await choose('Acme Capital')

    expect(await screen.findByRole('alert')).toHaveTextContent('403')
  })
})
