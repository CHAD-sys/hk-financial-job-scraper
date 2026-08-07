import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Job, Seeker } from '../api/client'

const SEEKER: Seeker = {
  id: 's-1',
  email: 'seeker@example.com',
  display_name: 'Ada',
  email_verified: true,
  is_admin: false,
  is_super_admin: false,
}

function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    source: 'workday',
    source_id: 'J1',
    company: 'HSBC',
    sector: 'Banking',
    title: 'Credit Risk Analyst',
    title_en: null,
    source_tier: 'mainstream',
    locations: ['Hong Kong'],
    seniority: 'mid',
    job_category: 'Risk',
    remote_type: 'hybrid',
    required_skills: ['credit risk'],
    salary_hkd_min: null,
    salary_hkd_max: null,
    salary_estimated_min: null,
    salary_estimated_max: null,
    salary_estimated_confidence: null,
    years_experience_required: 3,
    posted_at: '2026-08-06',
    url: 'https://example.test/j1',
    is_internship: false,
    description_excerpt: '',
    closed: false,
    board_signals: {},
    ...overrides,
  }
}

let authState: { seeker: Seeker | null; loading: boolean } = {
  seeker: SEEKER,
  loading: false,
}

vi.mock('../auth/useAuth', () => ({
  useAuth: () => ({
    ...authState,
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
    refresh: vi.fn(),
  }),
}))

const fetchRecommendations = vi.fn<(page?: number, pageSize?: number) => Promise<unknown>>()
const trackRecommendationClick = vi.fn(async (_source: string, _sourceId: string) => {})

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  fetchRecommendations: (...args: unknown[]) => (
    fetchRecommendations(...(args as [number, number]))
  ),
  trackRecommendationClick: (...args: unknown[]) => (
    trackRecommendationClick(...(args as [string, string]))
  ),
}))

vi.mock('./JobCard', () => ({
  default: ({ job, onClick }: { job: Job; onClick: (job: Job) => void }) => (
    <button type="button" onClick={() => onClick(job)}>{job.title}</button>
  ),
}))

const { default: RecommendedRoles } = await import('./RecommendedRoles')

const personalized = {
  personalized: true,
  signal_count: 6,
  saved_role_count: 2,
  activity_count: 4,
  eligible_count: 24,
  model_version: 'signals-v1',
  page: 1,
  page_size: 6,
  total_pages: 3,
  generated_at: '2026-08-07T12:00:00Z',
  batch_id: 'batch-1',
  items: [
    {
      job: makeJob(),
      score: 8.4,
      reasons: ['Matches your “credit risk” searches', 'Similar to a Saved Role'],
    },
  ],
}

function renderSubject(onSelect = vi.fn()) {
  return {
    onSelect,
    ...render(
      <MemoryRouter>
        <RecommendedRoles
          saved={() => false}
          onToggleSave={vi.fn()}
          onSelect={onSelect}
          onExploreAll={vi.fn()}
        />
      </MemoryRouter>,
    ),
  }
}

beforeEach(() => {
  authState = { seeker: SEEKER, loading: false }
  fetchRecommendations.mockReset().mockResolvedValue(personalized)
  trackRecommendationClick.mockClear()
})

describe('Roles for you', () => {
  it('shows a signed-in Seeker why each Role was recommended', async () => {
    renderSubject()

    expect(await screen.findByRole('heading', { name: 'Roles for you' })).toBeInTheDocument()
    expect(screen.queryByText('Roles to start with')).not.toBeInTheDocument()
    expect(screen.getByText('Private to your account')).toBeInTheDocument()
    expect(screen.getByText(/Matches your “credit risk” searches/)).toBeInTheDocument()
    expect(screen.getByText('Credit Risk Analyst')).toBeInTheDocument()
  })

  it('is honest about the market fallback for an anonymous visitor', async () => {
    authState = { seeker: null, loading: false }
    fetchRecommendations.mockResolvedValue({
      ...personalized,
      personalized: false,
      saved_role_count: 0,
      activity_count: 0,
    })

    renderSubject()

    expect(await screen.findByText(/Sign in to shape this with Saved Roles and searches/)).toBeInTheDocument()
    expect(screen.getByText('Market signal')).toBeInTheDocument()
    expect(screen.queryByText('Why it fits')).not.toBeInTheDocument()
  })

  it('records an opened recommendation before showing its detail', async () => {
    const onSelect = vi.fn()
    renderSubject(onSelect)

    const role = await screen.findByRole('button', { name: 'Credit Risk Analyst' })
    fireEvent.click(role)

    await waitFor(() => {
      expect(trackRecommendationClick).toHaveBeenCalledWith('workday', 'J1')
    })
    expect(onSelect).toHaveBeenCalledWith(personalized.items[0].job)
  })

  it('moves to the next recommendation page without reloading the board', async () => {
    renderSubject()
    await screen.findByText('Credit Risk Analyst')

    fireEvent.click(screen.getByRole('button', { name: 'Show me others' }))

    await waitFor(() => expect(fetchRecommendations).toHaveBeenLastCalledWith(2, 6))
  })
})
