import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Job, WeeklyHighlightsResponse } from '../../api/client'

const fetchWeeklyHighlights = vi.fn<() => Promise<WeeklyHighlightsResponse>>()

vi.mock('../../api/client', async importOriginal => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  fetchWeeklyHighlights: () => fetchWeeklyHighlights(),
}))

vi.mock('./useSwipeableMarquee', () => ({ useSwipeableMarquee: vi.fn() }))

const featuredRole: Job = {
  source: 'workday',
  source_id: 'FEATURED',
  company: 'HSBC',
  sector: 'Banking',
  title: 'Featured Risk Director',
  title_en: null,
  source_tier: 'mainstream',
  locations: ['Hong Kong'],
  seniority: 'Director',
  job_category: 'Risk',
  remote_type: 'hybrid',
  required_skills: ['risk'],
  salary_hkd_min: null,
  salary_hkd_max: null,
  salary_estimated_min: 90_000,
  salary_estimated_max: 120_000,
  salary_estimated_confidence: 'high',
  salary_verified: false,
  years_experience_required: 10,
  posted_at: '2026-09-01',
  url: 'https://example.test/featured',
  is_internship: false,
  is_new: true,
  description_excerpt: 'Lead a regional risk function.',
  closed: false,
  board_signals: {},
  access_token: 'weekly-grant',
}

const weeklyResponse: WeeklyHighlightsResponse = {
  week_start: '2026-09-07',
  week_end: '2026-09-13',
  roles: [{ position: 0, related_search: 'Risk', role: featuredRole }],
}

function LocationProbe() {
  const location = useLocation()
  const state = location.state as { featuredRole?: Job } | null
  return (
    <div data-testid="location">
      {location.pathname}{location.search}|{state?.featuredRole?.source_id ?? 'no-state'}
    </div>
  )
}

const { default: WeeklyHighlights } = await import('./WeeklyHighlights')

beforeEach(() => {
  fetchWeeklyHighlights.mockReset().mockResolvedValue(weeklyResponse)
  vi.stubGlobal('ResizeObserver', class {
    observe() {}
    disconnect() {}
  })
  vi.stubGlobal('IntersectionObserver', class {
    observe() {}
    disconnect() {}
  })
})

describe('weekly Role navigation', () => {
  it('loads the server-locked week and navigates inside the SPA with the exact Role', async () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<WeeklyHighlights />} />
          <Route path="/jobs" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>,
    )

    const role = await screen.findByRole('link', { name: /Featured Risk Director/i })
    const duplicateRole = document.querySelector('.hl__group[aria-hidden="true"] a')
    expect(duplicateRole).not.toBeNull()
    expect(duplicateRole).toHaveAttribute('tabindex', '-1')
    fireEvent.click(role)

    expect(await screen.findByTestId('location')).toHaveTextContent(
      '/jobs?q=Risk&role_source=workday&role_id=FEATURED|FEATURED',
    )
    expect(fetchWeeklyHighlights).toHaveBeenCalledOnce()
  }, 10_000)

  it('shows a recoverable failure instead of silently keeping stale hard-coded Roles', async () => {
    fetchWeeklyHighlights.mockRejectedValueOnce(new Error('offline'))
    render(<MemoryRouter><WeeklyHighlights /></MemoryRouter>)

    expect(await screen.findByRole('alert')).toHaveTextContent(/couldn.t load this week.s roles/i)
    fetchWeeklyHighlights.mockResolvedValueOnce(weeklyResponse)
    fireEvent.click(screen.getByRole('button', { name: /try again/i }))

    await waitFor(() => expect(fetchWeeklyHighlights).toHaveBeenCalledTimes(2))
    expect(await screen.findByRole('link', { name: /Featured Risk Director/i })).toBeVisible()
  })
})
