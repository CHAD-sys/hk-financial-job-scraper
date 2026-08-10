import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Seeker } from '../api/client'

const fetchResumeMatches = vi.fn()
vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, fetchResumeMatches: (...args: unknown[]) => fetchResumeMatches(...args) }
})

const SEEKER: Seeker = {
  id: 's-1',
  email: 'seeker@example.com',
  display_name: 'Ada',
  email_verified: true,
  is_admin: false,
  is_super_admin: false,
}

let seeker: Seeker | null = null
vi.mock('../auth/useAuth', () => ({ useAuth: () => ({ seeker, loading: false }) }))

const { default: ResumeFeatureSpotlight } = await import('./ResumeFeatureSpotlight')

function renderSubject() {
  return render(<MemoryRouter><ResumeFeatureSpotlight /></MemoryRouter>)
}

beforeEach(() => {
  seeker = null
  fetchResumeMatches.mockReset()
})

describe('ResumeFeatureSpotlight', () => {
  it('explains the feature and sends a visitor to seeker registration', () => {
    renderSubject()
    expect(screen.getByRole('heading', { name: /See where your experience is strongest/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Create a Seeker account/ })).toHaveAttribute('href', '/register')
    expect(screen.getByText(/The careers index stays free and open/)).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'How resume matching works' })).toBeInTheDocument()
    expect(screen.getByText('Explore live Role matches')).toBeInTheDocument()
    expect(screen.queryByText('Credit Risk & Portfolio Roles')).not.toBeInTheDocument()
  })

  it('sends a signed-in Seeker directly to resume management', () => {
    seeker = SEEKER
    fetchResumeMatches.mockResolvedValue({ has_resume: false, resume_uploaded_at: null, model_version: 'resume-signals-v1', items: [] })
    renderSubject()
    expect(screen.getByRole('link', { name: /Add or manage your resume/ })).toHaveAttribute('href', '/account')
    expect(screen.queryByRole('link', { name: /Already have an account/ })).not.toBeInTheDocument()
  })

  it('never invents a strong match for a signed-in Seeker without a resume', async () => {
    seeker = SEEKER
    fetchResumeMatches.mockResolvedValue({ has_resume: false, resume_uploaded_at: null, model_version: 'resume-signals-v1', items: [] })
    renderSubject()

    expect(await screen.findByRole('heading', { name: /Add your resume to start matching/ })).toBeInTheDocument()
    expect(screen.queryByText('Strong match')).not.toBeInTheDocument()
    expect(screen.queryByText('Credit Risk & Portfolio Roles')).not.toBeInTheDocument()
  })

  it('shows the real current Role and evidence when a resume match exists', async () => {
    seeker = SEEKER
    fetchResumeMatches.mockResolvedValue({
      has_resume: true,
      resume_uploaded_at: '2026-08-10T10:00:00Z',
      model_version: 'resume-signals-v1',
      items: [{
        match_score: 84,
        reasons: ['Treasury operations', 'Cash forecasting'],
        job: { title: 'Treasury Operations Manager' },
      }],
    })
    renderSubject()

    expect(await screen.findByRole('heading', { name: 'Treasury Operations Manager' })).toBeInTheDocument()
    expect(screen.getByText('84% evidence match')).toBeInTheDocument()
    expect(screen.getByText('Treasury operations')).toBeInTheDocument()
    expect(screen.queryByText('Credit Risk & Portfolio Roles')).not.toBeInTheDocument()
  })
})
