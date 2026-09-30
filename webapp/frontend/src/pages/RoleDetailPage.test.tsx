import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import type { Job } from '../api/client'
import { DeviceModeContext } from '../deviceMode/DeviceModeContext'
import { SavedRolesContext } from '../savedRoles/SavedRolesContext'

vi.mock('../components/Nav', () => ({ default: () => <nav>Navigation</nav> }))
vi.mock('../api/client', async importOriginal => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, fetchJobDetail: vi.fn().mockRejectedValue(new Error('Not needed for seeded route')) }
})

const { default: RoleDetailPage } = await import('./RoleDetailPage')

const role: Job = {
  source: 'jobsdb', source_id: '1', company: 'HSBC', sector: 'Banking',
  title: 'Vice President, Credit Risk', title_en: null, source_tier: 'mainstream',
  locations: ['Central, Hong Kong'], seniority: 'senior', job_category: 'Risk Management',
  remote_type: 'hybrid', required_skills: ['Credit Risk', 'Stakeholder management'],
  salary_hkd_min: 95_000, salary_hkd_max: 120_000, salary_period: 'month',
  salary_estimated_min: null, salary_estimated_max: null, salary_estimated_confidence: null,
  salary_verified: false, years_experience_required: 8, posted_at: '2026-09-29T00:00:00Z',
  url: 'https://example.com/role', is_internship: false, is_new: false, closed: false,
  description_excerpt: 'Own credit-risk analysis and advise senior stakeholders.', board_signals: {}, access_token: 'grant',
}

describe('RoleDetailPage', () => {
  it('renders a phone-first Role detail page from the card navigation state', () => {
    render(
      <DeviceModeContext.Provider value={{ deviceClass: 'phone', uiMode: 'mobile', detectionSource: 'user-agent', touchCapable: true }}>
        <SavedRolesContext.Provider value={{ saved: {}, savedList: [], count: 0, isSaved: () => false, toggle: vi.fn() }}>
          <MemoryRouter initialEntries={[{ pathname: '/roles/jobsdb/1', state: { job: role, returnTo: '/' } }]}>
            <Routes><Route path="/roles/:source/:sourceId" element={<RoleDetailPage />} /></Routes>
          </MemoryRouter>
        </SavedRolesContext.Provider>
      </DeviceModeContext.Provider>,
    )

    expect(screen.getByRole('heading', { name: 'Vice President, Credit Risk' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Back to careers/i })).toHaveAttribute('href', '/')
    expect(screen.getByRole('link', { name: /Apply on company site/i })).toHaveAttribute('href', 'https://example.com/role')
    expect(screen.getByText('Credit Risk')).toBeInTheDocument()
  })
})
