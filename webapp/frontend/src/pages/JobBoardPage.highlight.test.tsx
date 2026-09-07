import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Job, JobDetail } from '../api/client'

const fetchJobs = vi.fn()
const fetchJobDetail = vi.fn()
const fetchWeeklyHighlightRole = vi.fn()

vi.mock('../api/client', async importOriginal => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  fetchJobs: (...args: unknown[]) => fetchJobs(...args),
  fetchJobDetail: (...args: unknown[]) => fetchJobDetail(...args),
  fetchWeeklyHighlightRole: (...args: unknown[]) => fetchWeeklyHighlightRole(...args),
  fetchFilters: vi.fn().mockResolvedValue({ research_total: 1 }),
  fetchStats: vi.fn().mockResolvedValue({
    total_active_jobs: 100,
    employer_count: 40,
    by_sector: { Banking: 50 },
  }),
  recordDiscovery: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('../auth/useAuth', () => ({
  useAuth: () => ({ seeker: null, loading: false }),
}))
vi.mock('../adminMode/useAdminMode', () => ({
  useAdminMode: () => ({ adminMode: false }),
}))
vi.mock('../savedRoles/useSavedRoles', () => ({
  useSavedRoles: () => ({ toggle: vi.fn(), isSaved: () => false }),
}))
vi.mock('../hooks/useDebounce', () => ({ useDebounce: (value: string) => value }))

vi.mock('../components/Nav', () => ({ default: () => <nav>Navigation</nav> }))
vi.mock('../components/FilterBar', () => ({ default: () => <div>Filters</div> }))
vi.mock('../components/JobCard', () => ({
  default: ({ job }: { job: Job }) => <article>{job.title}</article>,
}))
vi.mock('../components/SkeletonCard', () => ({ default: () => <div>Loading role</div> }))
vi.mock('../components/EmptyState', () => ({ default: () => <div>No roles</div> }))
vi.mock('../components/Pagination', () => ({ default: () => null }))
vi.mock('../components/StatCard', () => ({ default: () => null }))
vi.mock('../components/SearchHero', () => ({ default: () => <div>Search</div> }))
vi.mock('../components/RecommendedRoles', () => ({ default: () => null }))
vi.mock('../components/ResumeMatches', () => ({ default: () => null }))
vi.mock('../components/MemberRoleNotice', () => ({ default: () => null }))
vi.mock('../components/AdminJobEditDrawer', () => ({ default: () => null }))
vi.mock('../components/JobDetailModal', () => ({
  default: ({ job }: { job: Job }) => <aside aria-label="Open role">{job.title}</aside>,
}))

const featuredRole: JobDetail = {
  source: 'linkedin',
  source_id: '4443781178',
  company: 'JPMorganChase',
  sector: 'Banking',
  title: 'International Private Bank, Investor for China Market, Managing Director',
  title_en: null,
  source_tier: 'primary',
  locations: ['Hong Kong'],
  seniority: 'Managing Director',
  job_category: 'Private Banking',
  remote_type: 'on-site',
  required_skills: [],
  salary_hkd_min: null,
  salary_hkd_max: null,
  salary_period: null,
  salary_estimated_min: 150_000,
  salary_estimated_max: 200_000,
  salary_estimated_confidence: 'high',
  salary_verified: false,
  years_experience_required: 12,
  posted_at: '2026-09-01T00:00:00Z',
  url: 'https://example.com/role',
  is_internship: false,
  is_new: true,
  description_excerpt: 'Lead the China market private banking team.',
  description_summary: 'Lead the China market private banking team.',
  sources: ['linkedin'],
  closed: false,
  board_signals: {},
  access_token: 'featured-role-grant',
}

const { default: JobBoardPage } = await import('./JobBoardPage')

beforeEach(() => {
  fetchJobs.mockReset().mockImplementation(() => Promise.resolve({
    jobs: [{ ...featuredRole, source_id: 'related-role', title: 'Private Banker' }],
    total: 1,
    total_pages: 1,
    page: 1,
    page_size: 24,
  }))
  // A guessed Role key is not permission to read the detail endpoint. The
  // page must discover the Role through Careers and use the issued grant.
  fetchJobDetail.mockReset().mockRejectedValue(new Error('Role access grant required'))
  fetchWeeklyHighlightRole.mockReset().mockResolvedValue(featuredRole)
})

describe('featured Role deep links', () => {
  it('opens navigation state immediately without another resolver request', async () => {
    render(
      <MemoryRouter initialEntries={[
        {
          pathname: '/jobs',
          search: '?q=Private+Banking&role_source=linkedin&role_id=4443781178',
          state: { featuredRole },
        },
      ]}>
        <Routes><Route path="/jobs" element={<JobBoardPage />} /></Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByRole('complementary', { name: 'Open role' })).toHaveTextContent(
      'International Private Bank, Investor for China Market, Managing Director',
    )
    expect(fetchJobDetail).not.toHaveBeenCalled()
    expect(fetchWeeklyHighlightRole).not.toHaveBeenCalled()
    await waitFor(() => {
      expect(fetchJobs.mock.calls.some(call => call[0].search === 'Private Banking')).toBe(true)
    })
  })

  it('resolves an exact pinned Role on a direct reload and shows progress while waiting', async () => {
    let resolveRole!: (role: JobDetail) => void
    fetchWeeklyHighlightRole.mockReturnValueOnce(new Promise(resolve => { resolveRole = resolve }))

    render(
      <MemoryRouter initialEntries={[
        '/jobs?q=Private+Banking&role_source=linkedin&role_id=4443781178',
      ]}>
        <Routes><Route path="/jobs" element={<JobBoardPage />} /></Routes>
      </MemoryRouter>,
    )

    expect(screen.getByRole('status')).toHaveTextContent(/opening this week.s featured role/i)
    resolveRole(featuredRole)

    expect(await screen.findByRole('complementary', { name: 'Open role' })).toHaveTextContent(
      featuredRole.title,
    )
    expect(fetchWeeklyHighlightRole).toHaveBeenCalledWith('linkedin', '4443781178')
    expect(fetchJobs.mock.calls.some(call => call[0].search === featuredRole.title)).toBe(false)
  })

  it('says when a stale or edited promotional link is unavailable', async () => {
    fetchWeeklyHighlightRole.mockRejectedValueOnce(new Error('not found'))
    render(
      <MemoryRouter initialEntries={[
        '/jobs?q=Private+Banking&role_source=linkedin&role_id=missing',
      ]}>
        <Routes><Route path="/jobs" element={<JobBoardPage />} /></Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByRole('alert')).toHaveTextContent(/featured role is unavailable/i)
  })
})
