import { render, screen } from '@testing-library/react'
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
    posted_at: '2026-08-10',
    url: 'https://example.test/j1',
    is_internship: false,
    description_excerpt: '',
    closed: false,
    board_signals: {},
    ...overrides,
  }
}

const fetchResumeMatches = vi.fn<(limit?: number) => Promise<ResumeMatchesResponse>>()
let seeker: Seeker | null = SEEKER

vi.mock('../auth/useAuth', () => ({ useAuth: () => ({ seeker, loading: false }) }))
vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  fetchResumeMatches: (limit: number) => fetchResumeMatches(limit),
}))
vi.mock('./JobCard', () => ({
  default: ({ job }: { job: Job }) => <div>{job.title}</div>,
}))

const { default: ResumeMatches } = await import('./ResumeMatches')

function renderSubject() {
  return render(
    <MemoryRouter>
      <ResumeMatches saved={() => false} onToggleSave={vi.fn()} onSelect={vi.fn()} />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  seeker = SEEKER
  fetchResumeMatches.mockReset()
})

describe('Strong matches for your experience', () => {
  it('offers a concise opt-in path before a resume exists', async () => {
    fetchResumeMatches.mockResolvedValue({
      has_resume: false,
      resume_uploaded_at: null,
      model_version: 'resume-signals-v1',
      items: [],
    })
    renderSubject()

    expect(await screen.findByRole('heading', { name: /Find Roles that fit you/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Upload your resume/ })).toHaveAttribute('href', '/account')
  })

  it('shows evidence-led matches without making an eligibility claim', async () => {
    fetchResumeMatches.mockResolvedValue({
      has_resume: true,
      resume_uploaded_at: '2026-08-10T10:00:00Z',
      model_version: 'resume-signals-v1',
      items: [{
        job: makeJob(),
        match_score: 85,
        reasons: ['Skills aligned: credit risk, sql'],
      }],
    })
    renderSubject()

    expect(await screen.findByRole('heading', { name: 'Where your experience stands out' })).toBeInTheDocument()
    expect(screen.getByText(/not an eligibility decision/)).toBeInTheDocument()
    expect(screen.getByText('85%')).toBeInTheDocument()
    expect(screen.getByText('Credit Risk Analyst')).toBeInTheDocument()
    expect(screen.getByText('Skills aligned: credit risk, sql')).toBeInTheDocument()
    expect(fetchResumeMatches).toHaveBeenCalledWith(3)
  })

  it('advertises the private feature without calling the account API for anonymous visitors', () => {
    seeker = null
    renderSubject()
    expect(screen.getByRole('heading', { name: 'Find Roles that fit you.' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Create account/ })).toHaveAttribute('href', '/register')
    expect(fetchResumeMatches).not.toHaveBeenCalled()
  })
})
