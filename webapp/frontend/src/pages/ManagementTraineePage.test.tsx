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

  it('reconciles directory cards with curated openings for the same employer', async () => {
    fetchManagementTraineeRoles.mockResolvedValue({
      total: 1, page: 1, page_size: 1, total_pages: 1,
      jobs: [{
        source: 'linkedin', source_id: 'hkma-1', company: 'Hong Kong Monetary Authority (HKMA)',
        title: 'Manager Trainee (2027 Intake)', locations: ['Hong Kong'],
        posted_at: '2026-09-12T00:00:00+00:00', url: 'https://example.test/hkma',
      }],
    })

    render(<ManagementTraineePage />)
    expect(await screen.findByText(/1 active role from the careers database/i)).toBeInTheDocument()

    for (const company of [
      'Hang Seng Bank',
      'Hang Lung Properties',
      'The Hong Kong Jockey Club (HKJC)',
      'Hong Kong Monetary Authority (HKMA)',
    ]) {
      const card = screen.getByRole('heading', { name: company }).closest('article')
      expect(card).toHaveTextContent('Open now')
      expect(card).not.toHaveTextContent('Not currently open')
    }
  })

  it('counts one employer once when the two feeds spell its name differently', async () => {
    // The curated openings carry "The Hong Kong Jockey Club"; a scrape of the
    // same programme can arrive as "Hong Kong Jockey Club (HKJC)". Keying the
    // banner on the lowercased name made that two open employers with the
    // programme counted twice, while the directory below — which goes through
    // mtEmployerKey — already treated them as one. MT_EMPLOYER_ALIASES exists
    // for exactly this, and the banner now uses it.
    fetchManagementTraineeRoles.mockResolvedValue({
      total: 1, page: 1, page_size: 1, total_pages: 1,
      jobs: [{
        source: 'linkedin', source_id: 'hkjc-mt', company: 'Hong Kong Jockey Club (HKJC)',
        title: '2027 Management Trainee Programme', locations: ['Hong Kong'],
        posted_at: '2026-09-18T00:00:00+00:00', url: 'https://example.test/hkjc',
      }],
    })

    render(<ManagementTraineePage />)
    await screen.findByRole('heading', { name: 'Active roles in FinEx Careers' })

    const jockeyClubEntries = screen.getAllByRole('link', {
      name: /most urgent active role at .*jockey club/i,
    })
    expect(jockeyClubEntries).toHaveLength(1)
  })
})
