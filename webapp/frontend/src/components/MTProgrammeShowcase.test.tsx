import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

const fetchManagementTraineeRoles = vi.fn()
vi.mock('../api/client', () => ({ fetchManagementTraineeRoles }))

const { default: MTProgrammeShowcase } = await import('./MTProgrammeShowcase')

describe('MTProgrammeShowcase', () => {
  it('shows only the three highest-ranked open MT roles in the homepage spotlight', async () => {
    fetchManagementTraineeRoles.mockResolvedValue({ jobs: [
      { source: 'a', source_id: '1', company: 'FinEx Select One', title: 'Management Trainee', closed: false, job_category: null, locations: ['Hong Kong'], url: 'https://example.com/1', application_label: 'View employer vacancies' },
      { source: 'a', source_id: '2', company: 'Closed One', title: 'Management Trainee', closed: true, job_category: null, locations: ['Hong Kong'], url: 'https://example.com/2' },
      { source: 'a', source_id: '3', company: 'FinEx Select Two', title: 'Management Trainee', closed: false, job_category: null, locations: ['Hong Kong'], url: 'https://example.com/3' },
      { source: 'a', source_id: '4', company: 'FinEx Select Three', title: 'Manager Trainee', closed: false, job_category: null, locations: ['Hong Kong'], url: 'https://example.com/4' },
      { source: 'a', source_id: '5', company: 'Not Spotlighted', title: 'Management Trainee', closed: false, job_category: null, locations: ['Hong Kong'], url: 'https://example.com/5' },
    ] })
    render(<MemoryRouter><MTProgrammeShowcase /></MemoryRouter>)
    await waitFor(() => expect(screen.getByText('FinEx Select One')).toBeInTheDocument())
    expect(screen.getByText('FinEx Select Two')).toBeInTheDocument()
    expect(screen.getByText('FinEx Select Three')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /view employer vacancies/i })).toHaveAttribute('href', 'https://example.com/1')
    expect(screen.queryByText('Closed One')).not.toBeInTheDocument()
    expect(screen.queryByText('Not Spotlighted')).not.toBeInTheDocument()
    expect(screen.getAllByText('Active')).toHaveLength(3)
  })
})
