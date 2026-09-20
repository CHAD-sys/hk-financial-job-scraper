import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const fetchRecruiterRoles = vi.hoisted(() => vi.fn())
const useAuth = vi.hoisted(() => vi.fn())

vi.mock('../api/client', async importOriginal => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  fetchRecruiterRoles,
}))
vi.mock('../components/Nav', () => ({ default: () => <nav>Navigation</nav> }))
vi.mock('../auth/useAuth', () => ({ useAuth }))

const { default: RecruiterDeskPage } = await import('./RecruiterDeskPage')

function role(over: Record<string, unknown> = {}) {
  return {
    source: 'linkedin_posts',
    source_id: 'P1',
    company: 'Confidential via Acme Search',
    title: 'Head of Credit Risk',
    source_tier: 'social',
    locations: ['Hong Kong'],
    seniority: 'lead',
    required_skills: [],
    salary_hkd_min: null,
    salary_hkd_max: null,
    salary_estimated_min: 90_000,
    salary_estimated_max: 120_000,
    salary_estimated_confidence: 'medium',
    salary_verified: false,
    is_new: false,
    years_experience_required: null,
    // Deliberately older than the board's one-month window: the whole point of
    // this desk is that the board cannot show it.
    posted_at: '2026-03-02T00:00:00+00:00',
    url: 'https://example.test/post/P1',
    is_internship: false,
    description_excerpt: '',
    closed: false,
    board_signals: {},
    ...over,
  }
}

function renderPage() {
  return render(
    <MemoryRouter>
      <RecruiterDeskPage />
    </MemoryRouter>,
  )
}

describe('RecruiterDeskPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuth.mockReturnValue({ seeker: { is_super_admin: true }, loading: false })
    fetchRecruiterRoles.mockResolvedValue({
      total: 1, page: 1, page_size: 24, total_pages: 1, jobs: [role()],
    })
  })

  it('lists recruiter posts the public board cannot show', async () => {
    renderPage()

    expect(await screen.findByText('Head of Credit Risk')).toBeInTheDocument()
    expect(screen.getByText('Confidential via Acme Search')).toBeInTheDocument()
    // An AI estimate is labelled as one — a headhunter's advert rarely states pay.
    expect(screen.getByText(/90k–120k est\./)).toBeInTheDocument()
  })

  it('never fetches for an admin who is not Ultimate Admin', async () => {
    // is_admin alone must not reach this desk; the route is require_super_admin
    // server-side, and the page redirects rather than rendering an empty shell.
    useAuth.mockReturnValue({ seeker: { is_super_admin: false }, loading: false })

    renderPage()

    await waitFor(() => expect(fetchRecruiterRoles).not.toHaveBeenCalled())
    expect(screen.queryByText('Recruiter desk')).not.toBeInTheDocument()
  })

  it('says how to diagnose an empty desk rather than showing a bare nothing', async () => {
    fetchRecruiterRoles.mockResolvedValue({
      total: 0, page: 1, page_size: 24, total_pages: 0, jobs: [],
    })

    renderPage()

    expect(await screen.findByText(/No recruiter posts found/)).toBeInTheDocument()
    expect(screen.getByText(/linkedin_fetch/)).toBeInTheDocument()
  })
})
