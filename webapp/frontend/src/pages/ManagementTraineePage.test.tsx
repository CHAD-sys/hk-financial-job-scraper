import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const fetchManagementTraineeRoles = vi.fn()

vi.mock('../api/client', () => ({
  fetchManagementTraineeRoles: () => fetchManagementTraineeRoles(),
}))
vi.mock('../components/Nav', () => ({ default: () => <nav>Navigation</nav> }))

const { default: ManagementTraineePage } = await import('./ManagementTraineePage')

describe('ManagementTraineePage live board feed', () => {
  beforeEach(() => fetchManagementTraineeRoles.mockReset())

  it('shows active MT roles from jobs.db above the curated application links', async () => {
    fetchManagementTraineeRoles.mockResolvedValue({
      total: 1, page: 1, page_size: 1, total_pages: 1,
      jobs: [{
        source: 'jobsdb', source_id: 'mt-1', company: 'Example Bank',
        title: '2027 Management Trainee Programme', locations: ['Hong Kong'],
        posted_at: '2026-09-12T00:00:00+00:00', url: 'https://example.test/apply',
      }],
    })

    render(<ManagementTraineePage />)

    expect(await screen.findByRole('heading', { name: 'Active roles in FinEx Careers' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'View the most urgent active role at Example Bank' })).toHaveAttribute('href', '#mt-opening-jobsdb-mt-1')
    fireEvent.click(screen.getByRole('link', { name: 'View the most urgent active role at Example Bank' }))
    expect(screen.getByText('Selected from employer gallery')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /view or apply: 2027 management trainee/i })).toHaveAttribute(
      'href', 'https://example.test/apply',
    )
    expect(screen.queryByText('Listed on: jobsdb')).not.toBeInTheDocument()
    expect(screen.queryByText('Prototype')).not.toBeInTheDocument()
    expect(screen.queryByText('Industries')).not.toBeInTheDocument()
    expect(document.querySelector('.mt-logo-band__track')).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: 'Career coaching' }).length).toBeGreaterThan(0)
    expect(screen.getByText(/1 active role from the careers database/i)).toBeInTheDocument()
  })
})
