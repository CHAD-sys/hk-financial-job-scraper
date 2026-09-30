import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../api/client', () => ({
  DEFAULT_FILTERS: {},
  fetchJobs: vi.fn().mockResolvedValue({ jobs: [] }),
  fetchManagementTraineeRoles: vi.fn().mockResolvedValue({ jobs: [] }),
}))
vi.mock('./JobCard', () => ({ default: () => null }))
vi.mock('./highlights/WeeklyHighlights', () => ({ default: () => null }))

const { default: MobileDiscoveryHome } = await import('./MobileDiscoveryHome')

describe('MobileDiscoveryHome', () => {
  it('starts directly with search and discovery controls, without the legacy hero or employer CTA', () => {
    render(
      <MemoryRouter>
        <MobileDiscoveryHome
          onSearch={vi.fn()}
          saved={() => false}
          onToggleSave={vi.fn()}
          onSelect={vi.fn()}
        />
      </MemoryRouter>,
    )

    expect(screen.getByRole('searchbox', { name: 'Search roles, skills or employers' })).toBeInTheDocument()
    expect(screen.getByRole('tablist', { name: 'FinEx discovery destinations' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /asia.s 1st premier career centre/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /post a job for free/i })).not.toBeInTheDocument()
  })

  it('shows a compact set of eight workbook-backed open MT employers, not only the live-board result', async () => {
    render(
      <MemoryRouter>
        <MobileDiscoveryHome
          onSearch={vi.fn()}
          saved={() => false}
          onToggleSave={vi.fn()}
          onSelect={vi.fn()}
        />
      </MemoryRouter>,
    )

    fireEvent.click(screen.getByRole('tab', { name: 'MT' }))

    expect(screen.getByRole('group', { name: 'Swipe through Management Trainee employer logos' })).toBeInTheDocument()
    expect(await screen.findAllByRole('article')).toHaveLength(8)
    expect(screen.getByRole('heading', { name: 'Goldman Sachs' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Morgan Stanley' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'View all application links at Bank of America (BofA)' }))
      .toHaveAttribute('href', '/management-trainee/bank-of-america-bofa')
  })
})
