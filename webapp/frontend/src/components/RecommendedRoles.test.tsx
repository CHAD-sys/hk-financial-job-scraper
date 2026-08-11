import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Job, ResumeMatchesResponse, Seeker } from '../api/client'

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
    access_token: 'role-grant-J1',
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
const trackRecommendationClick = vi.fn(async (
  _source: string,
  _sourceId: string,
  _accessToken?: string | null,
) => {})
const submitRecommendationFeedback = vi.fn(async (
  _source: string,
  _sourceId: string,
  _action: string,
  _accessToken?: string | null,
  _detail?: string,
) => {})
const removeRecommendationFeedback = vi.fn(async (
  _source: string,
  _sourceId: string,
  _action: string,
) => {})

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  fetchRecommendations: (...args: unknown[]) => (
    fetchRecommendations(...(args as [number, number]))
  ),
  trackRecommendationClick: (...args: unknown[]) => (
    trackRecommendationClick(...(args as [string, string, string?]))
  ),
  submitRecommendationFeedback: (...args: unknown[]) => (
    submitRecommendationFeedback(...(args as [string, string, string, string?, string?]))
  ),
  removeRecommendationFeedback: (...args: unknown[]) => (
    removeRecommendationFeedback(...(args as [string, string, string]))
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
  personalization_enabled: true,
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
      feedback: [],
    },
  ],
}

function renderSubject(
  onSelect = vi.fn(),
  resumeMatches: ResumeMatchesResponse | null = null,
) {
  return {
    onSelect,
    ...render(
      <MemoryRouter>
        <RecommendedRoles
          saved={() => false}
          onToggleSave={vi.fn()}
          onSelect={onSelect}
          resumeMatches={resumeMatches}
        />
      </MemoryRouter>,
    ),
  }
}

beforeEach(() => {
  authState = { seeker: SEEKER, loading: false }
  fetchRecommendations.mockReset().mockResolvedValue(personalized)
  trackRecommendationClick.mockClear()
  submitRecommendationFeedback.mockClear()
  removeRecommendationFeedback.mockClear()
})

describe('Roles for you', () => {
  it('shows a clean personalized feed without source controls or reason strips', async () => {
    renderSubject()

    expect(await screen.findByRole('heading', { name: 'Roles for you' })).toBeInTheDocument()
    expect(screen.queryByText('Roles to start with')).not.toBeInTheDocument()
    expect(screen.getByText('Private to your account')).toBeInTheDocument()
    expect(screen.getByText('Credit Risk Analyst')).toBeInTheDocument()
    expect(screen.queryByText(/Matches your “credit risk” searches/)).not.toBeInTheDocument()
    expect(screen.queryByText('Market signal')).not.toBeInTheDocument()
    expect(screen.queryByText('Why it fits')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Tune your feed' })).not.toBeInTheDocument()
    expect(screen.queryByText(/Built from/)).not.toBeInTheDocument()
  })

  it('merges resume matches into Roles for you without a second category', async () => {
    const resumeMatches: ResumeMatchesResponse = {
      has_resume: true,
      resume_uploaded_at: '2026-08-10T10:00:00Z',
      model_version: 'resume-signals-v1',
      items: [{
        job: makeJob({ source_id: 'CV1', title: 'Portfolio Risk Manager' }),
        match_score: 88,
        reasons: ['Skills aligned: portfolio risk, sql'],
      }],
    }

    renderSubject(vi.fn(), resumeMatches)

    expect(await screen.findByRole('heading', { name: 'Roles for you' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Where your experience stands out' })).not.toBeInTheDocument()
    expect(screen.getByText('Portfolio Risk Manager')).toBeInTheDocument()
    expect(screen.getByText('88%')).toBeInTheDocument()
    expect(screen.getByText('Skills aligned: portfolio risk, sql')).toBeInTheDocument()
    expect(screen.getByText(/strongest experience matches/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Manage resume' })).toHaveAttribute('href', '/account')
  })

  it('does not expose a generic market feed to an anonymous visitor', async () => {
    authState = { seeker: null, loading: false }

    renderSubject()

    expect(screen.queryByRole('heading', { name: 'Roles for you' })).not.toBeInTheDocument()
    expect(fetchRecommendations).not.toHaveBeenCalled()
  })

  it('records an opened recommendation before showing its detail', async () => {
    const onSelect = vi.fn()
    renderSubject(onSelect)

    const role = await screen.findByRole('button', { name: 'Credit Risk Analyst' })
    fireEvent.click(role)

    await waitFor(() => {
      expect(trackRecommendationClick).toHaveBeenCalledWith(
        'workday',
        'J1',
        'role-grant-J1',
      )
    })
    expect(onSelect).toHaveBeenCalledWith(personalized.items[0].job)
  })

  it('moves to the next recommendation page without reloading the board', async () => {
    renderSubject()
    await screen.findByText('Credit Risk Analyst')

    fireEvent.click(screen.getByRole('button', { name: 'Show me others' }))

    await waitFor(() => expect(fetchRecommendations).toHaveBeenLastCalledWith(2, 6))
  })

  it('lets the Seeker explicitly ask for more similar Roles', async () => {
    renderSubject()

    fireEvent.click(await screen.findByRole('button', { name: 'More like this' }))

    await waitFor(() => {
      expect(submitRecommendationFeedback).toHaveBeenCalledWith(
        'workday',
        'J1',
        'more_like',
        'role-grant-J1',
      )
    })
    expect(screen.getByText(/We’ll show you more Roles like this/)).toBeInTheDocument()
  })

  it('dismisses an unwanted Role directly and offers Undo', async () => {
    renderSubject()

    fireEvent.click(await screen.findByRole('button', { name: 'Not for me' }))

    await waitFor(() => {
      expect(submitRecommendationFeedback).toHaveBeenCalledWith(
        'workday',
        'J1',
        'not_interested',
        'role-grant-J1',
      )
    })
    expect(await screen.findByRole('button', { name: 'Undo' })).toBeInTheDocument()
    expect(screen.queryByText('Credit Risk Analyst')).not.toBeInTheDocument()
  })
})
