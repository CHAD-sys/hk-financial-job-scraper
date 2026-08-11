import { render, screen } from '@testing-library/react'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import type { Job, JobDetail } from '../api/client'
import { fetchJobDetail } from '../api/client'
import JobDetailModal from './JobDetailModal'

vi.mock('../api/client', async importOriginal => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, fetchJobDetail: vi.fn() }
})

const recruiterAccountingOfficer: Job = {
  source: 'linkedin_posts',
  source_id: '7472314676593471489',
  company: 'Confidential via Kelvin W.',
  sector: 'Banking',
  title: 'Accounting Officer',
  title_en: null,
  source_tier: 'social',
  locations: ['Hong Kong'],
  seniority: 'junior',
  job_category: 'Finance',
  remote_type: 'on-site',
  required_skills: [],
  salary_hkd_min: null,
  salary_hkd_max: 30_000,
  salary_period: 'month',
  salary_estimated_min: null,
  salary_estimated_max: 23_500,
  salary_estimated_confidence: 'high',
  years_experience_required: 2,
  posted_at: '2026-07-01T00:00:00Z',
  url: 'https://linkedin.example/post',
  is_internship: false,
  description_excerpt: 'Salary up to HK$30K.',
  closed: false,
  board_signals: {},
  access_token: 'grant',
}

const detail: JobDetail = {
  ...recruiterAccountingOfficer,
  description_clean: 'Salary up to HK$30K.',
  description_summary: 'Accounting Officer with salary up to HK$30K.',
  sources: ['linkedin_posts'],
}

beforeAll(() => {
  HTMLDialogElement.prototype.showModal = vi.fn()
})

describe('JobDetailModal compensation', () => {
  it('labels disclosed Hong Kong salary fields as monthly, including recruiter posts', async () => {
    vi.mocked(fetchJobDetail).mockResolvedValue(detail)
    render(
      <JobDetailModal
        job={recruiterAccountingOfficer}
        saved={false}
        onToggleSave={() => {}}
        onClose={() => {}}
      />,
    )

    expect(await screen.findByText(/up to HK\$30k\/mo/i)).toBeInTheDocument()
    expect(screen.queryByText(/up to HK\$30k \/ year/i)).not.toBeInTheDocument()
  })

  it('keeps an explicitly annual disclosed salary annual', async () => {
    const annualJob: Job = {
      ...recruiterAccountingOfficer,
      source_id: 'annual-role',
      salary_hkd_max: 720_000,
      salary_period: 'year',
      description_excerpt: 'Salary HKD720000 per annum.',
    }
    vi.mocked(fetchJobDetail).mockResolvedValue({
      ...detail,
      ...annualJob,
      description_clean: 'Salary HKD720000 per annum.',
      description_summary: 'Annual salary HKD720000.',
      sources: ['linkedin_posts'],
    })
    render(
      <JobDetailModal
        job={annualJob}
        saved={false}
        onToggleSave={() => {}}
        onClose={() => {}}
      />,
    )

    expect(await screen.findByText(/up to HK\$720k\/yr/i)).toBeInTheDocument()
  })
})
