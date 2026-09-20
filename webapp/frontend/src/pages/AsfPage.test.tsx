import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const fetchBannerValidationQueue = vi.hoisted(() => vi.fn())
const fetchMTAmbiguousCandidates = vi.hoisted(() => vi.fn())
const saveBannerCandidates = vi.hoisted(() => vi.fn())

vi.mock('../api/client', async importOriginal => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  fetchBannerValidationQueue,
  fetchMTAmbiguousCandidates,
  saveBannerCandidates,
}))
vi.mock('../components/Nav', () => ({ default: () => <nav>Navigation</nav> }))
vi.mock('../auth/useAuth', () => ({
  useAuth: () => ({ seeker: { is_super_admin: true }, loading: false }),
}))

const { default: AsfPage } = await import('./AsfPage')

const ROLES = [
  {
    source: 'workday', source_id: 'risk-director', company: 'HSBC',
    title: 'Regional Risk Director', category: 'Risk', seniority: 'Director',
    posted_at: '2026-09-18T12:00:00+00:00', salary_min: 100_000, salary_max: 130_000,
    salary_confidence: 'high',
    description_summary: 'Lead regional risk governance and advise senior stakeholders across Asia.',
    apply_url: 'https://careers.example.test/roles/risk-director',
  },
  {
    source: 'workday', source_id: 'markets-vp', company: 'Citi',
    title: 'Markets Vice President', category: 'Markets', seniority: 'VP',
    posted_at: '2026-09-17', salary_min: 85_000, salary_max: 110_000,
    salary_confidence: 'medium', description_summary: '',
    apply_url: 'https://careers.example.test/roles/markets-vp',
  },
]

function queue(approved = [{
  source: 'workday', source_id: 'risk-director', related_search: 'Risk', position: 0,
}]) {
  return {
    week_start: '2026-09-21', week_end: '2026-09-27', saved: true, roles: ROLES, approved,
  }
}

function renderPage() {
  return render(<MemoryRouter><AsfPage /></MemoryRouter>)
}

beforeEach(() => {
  fetchBannerValidationQueue.mockReset()
  fetchMTAmbiguousCandidates.mockReset()
  saveBannerCandidates.mockReset()
  fetchBannerValidationQueue.mockResolvedValue(queue())
  fetchMTAmbiguousCandidates.mockResolvedValue({ roles: [] })
  saveBannerCandidates.mockResolvedValue(queue())
})

describe('Ultimate Admin publication validation', () => {
  it('shows enough evidence to review each Role without opening the public board first', async () => {
    renderPage()

    const risk = await screen.findByRole('checkbox', { name: /Regional Risk Director/ })
    const markets = screen.getByRole('checkbox', { name: /Markets Vice President/ })
    expect(risk).toBeChecked()
    expect(markets).not.toBeChecked()
    expect(screen.getByText(/posted 18 Sept/)).toBeInTheDocument()
    expect(screen.getByText(/Lead regional risk governance/)).toBeInTheDocument()
    expect(screen.getByText('No description summary available yet.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Check live posting for Regional Risk Director/ }))
      .toHaveAttribute('href', 'https://careers.example.test/roles/risk-director')
  })

  it('keeps the selection editable after every save', async () => {
    renderPage()
    const list = await screen.findByRole('group', { name: 'Banner Role selection' })

    fireEvent.click(within(list).getByRole('checkbox', { name: /Markets Vice President/ }))
    fireEvent.click(within(list).getByRole('checkbox', { name: /Regional Risk Director/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Save 1 Role' }))

    await waitFor(() => expect(saveBannerCandidates).toHaveBeenCalledWith([ROLES[1]]))
    expect(screen.getByRole('group', { name: 'Banner Role selection' })).toBeInTheDocument()
    expect(screen.queryByText(/locked/i)).not.toBeInTheDocument()
  })
})
