import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { MTProgramme } from '../content/managementTraineePrograms'
import MTProgrammeCard from './MTProgrammeCard'

const programme: MTProgramme = {
  id: 'hong-kong-monetary-authority-hkma',
  company: 'Hong Kong Monetary Authority (HKMA)',
  companyChinese: '香港金融管理局',
  industry: 'Asset Management, Financial Services & FinTech',
  programmeName: 'Manager Trainee Programme',
  applicationUrls: ['https://www.hkma.gov.hk/example'],
  linksVerified: true,
}

describe('MTProgrammeCard', () => {
  it('opens a supplied official programme link and keeps a non-open status explicit', () => {
    render(<MTProgrammeCard programme={programme} />)

    expect(screen.getByText('Manager Trainee Programme')).toBeInTheDocument()
    expect(document.querySelector('.mt-programme-card__deadline')).toHaveTextContent('Not currently open · No verified active intake')
    expect(screen.getByRole('link', { name: /view official programme/i })).toHaveAttribute(
      'href',
      programme.applicationUrls[0],
    )
  })

  it('uses update-needed language when an intake has no current confirmation', () => {
    render(<MTProgrammeCard programme={{ ...programme, application: {
      status: 'closed', checkedAt: '2026-09-14', sourceUrl: programme.applicationUrls[0], evidence: 'The prior window ended.',
    } }} />)
    expect(document.querySelector('.mt-programme-card__deadline')).toHaveTextContent('To be updated')
    expect(screen.queryByText('Closed')).toBeNull()
  })

  it('uses one best programme link when an employer has multiple supplied links', () => {
    const multiLinkProgramme: MTProgramme = {
      ...programme,
      company: 'HSBC',
      linksVerified: undefined,
      applicationUrls: [
        'https://www.hsbc.com/careers/students-and-graduates/internships',
        'https://www.hsbc.com/careers/students-and-graduates/graduate-programmes',
      ],
    }

    render(<MTProgrammeCard programme={multiLinkProgramme} />)
    expect(screen.getByRole('link', { name: /view programme/i })).toHaveAttribute('href', multiLinkProgramme.applicationUrls[0])
    expect(screen.queryByText('View 2 programme links')).not.toBeInTheDocument()
  })

  it('makes an explicitly verified open deadline scannable', () => {
    render(<MTProgrammeCard programme={{
      ...programme,
      application: {
        status: 'open',
        deadline: '2026-10-25',
        checkedAt: '2026-09-14',
        sourceUrl: programme.applicationUrls[0],
        evidence: 'Applications are now open until 25 October 2026.',
      },
    }} />)

    expect(document.querySelector('.mt-programme-card__deadline')).toHaveTextContent('Open now · Closes 25 Oct 2026')
    expect(screen.getByText(/checked 14 sept 2026/i)).toBeInTheDocument()
  })

  it('shows a current live opening even when the directory snapshot has no open status', () => {
    render(<MTProgrammeCard programme={programme} liveActive />)

    expect(document.querySelector('.mt-programme-card__deadline')).toHaveTextContent(
      'Open now · Active role listed above · deadline not stated',
    )
  })
})
