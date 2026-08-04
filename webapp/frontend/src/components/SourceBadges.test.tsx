import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import SourceBadges from './SourceBadges'

/**
 * The "Listed on" tags, at the render.
 *
 * The bug that started this file: `successfactors` was in neither OWN_SITE nor
 * ORDER, so normalise() dropped it — a source that survives neither branch just
 * disappears. No tag, no error, no clue. HKJC's nine active roles showed no
 * "Listed on" section at all, and a role on both SuccessFactors and JobsDB
 * showed only JobsDB, hiding the employer's own careers page — the very copy
 * the pipeline ranks highest for applying.
 *
 * The registry that must agree with this file is checked from Python, in
 * tests/test_sources.py — it is the side that can see both languages. These
 * tests cover what that one cannot: what a Seeker actually sees.
 */

describe('SourceBadges', () => {
  it('shows the employer’s own careers page for every own-site source', () => {
    for (const source of ['workday', 'eightfold', 'successfactors', 'longtail']) {
      const { unmount } = render(<SourceBadges sources={[source]} />)
      expect(screen.getByText('Company site'), source).toBeTruthy()
      unmount()
    }
  })

  it('never names the ATS vendor at a Seeker', () => {
    render(<SourceBadges sources={['successfactors']} />)
    expect(screen.queryByText(/SuccessFactors/i)).toBeNull()
  })

  it('shows the company site alongside the board when a role is on both', () => {
    render(<SourceBadges sources={['successfactors', 'jobsdb']} />)
    expect(screen.getByText('Company site')).toBeTruthy()
    expect(screen.getByText('JobsDB')).toBeTruthy()
  })

  it('names each job board', () => {
    render(<SourceBadges sources={['jobsdb', 'indeed', 'linkedin', 'efinancialcareers']} />)
    for (const label of ['JobsDB', 'Indeed', 'LinkedIn', 'eFinancialCareers']) {
      expect(screen.getByText(label)).toBeTruthy()
    }
  })

  it('collapses several own-site sources into a single tag', () => {
    render(<SourceBadges sources={['workday', 'successfactors', 'longtail']} />)
    expect(screen.getAllByText('Company site')).toHaveLength(1)
  })

  it('calls a recruiter post what it is, not a LinkedIn listing', () => {
    render(<SourceBadges sources={['linkedin_posts']} />)
    expect(screen.getByText('Recruiter post')).toBeTruthy()
    expect(screen.queryByText('LinkedIn')).toBeNull()
  })

  it('renders nothing when there are no sources', () => {
    const { container } = render(<SourceBadges sources={[]} />)
    expect(container.firstChild).toBeNull()
  })

  it('drops a source it does not know rather than throwing', () => {
    // The registry test is what stops this happening; this is the backstop, so
    // an unknown value in the data degrades to a missing tag, not a blank page.
    expect(() => render(<SourceBadges sources={['a-board-from-2027']} />)).not.toThrow()
  })
})
