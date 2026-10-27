import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { fetchHighPayingRoles } from '../api/client'

vi.mock('../api/client', () => ({
  fetchHighPayingRoles: vi.fn().mockResolvedValue([]),
  fetchManagementTraineeRoles: vi.fn().mockResolvedValue({ jobs: [] }),
}))
vi.mock('./JobCard', () => ({ default: () => null }))
vi.mock('./highlights/WeeklyHighlights', () => ({ default: () => null }))

const { default: MobileDiscoveryHome } = await import('./MobileDiscoveryHome')

describe('MobileDiscoveryHome', () => {
  it('loads the salary desk from its quality-checked feed', async () => {
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

    await waitFor(() => expect(fetchHighPayingRoles).toHaveBeenCalled())
  })

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

    expect(screen.getByRole('heading', { name: 'Active MT openings' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: /Management Trainee employer logos/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Show previous Management Trainee employers' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Show next Management Trainee employers' })).toBeVisible()
    expect(await screen.findAllByRole('article')).toHaveLength(8)
    expect(screen.getByRole('heading', { name: 'Goldman Sachs' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Morgan Stanley' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'View all application links at Bank of America (BofA)' }))
      .toHaveAttribute('href', '/management-trainee/bank-of-america-bofa')
  })

  it('keeps the landing message about the whole site when a destination changes', () => {
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

    const landingTitle = screen.getByRole('heading', { level: 1, name: 'Find your next move in Hong Kong finance.' })
    fireEvent.click(screen.getByRole('tab', { name: 'Coaching' }))

    expect(landingTitle).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1 })).toBe(landingTitle)
  })
})
