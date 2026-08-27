import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import JobCard from './JobCard'
import type { Job } from '../api/client'

/**
 * What a card is allowed to say.
 *
 * Two of these are policy rather than appearance, which is why they are tests
 * and not comments: a Recruiter Post must not name the person who posted it,
 * and must not present LLM-guessed skills as the employer's requirements
 * (owner decision, 2026-08-04 — it reverses part of LP-5 / decision #9 in
 * docs/PLAN_LINKEDIN_POSTS.md). Both are enforced by *absence*, and absence is
 * exactly what nobody notices coming back.
 */

const base: Job = {
  source: 'jobsdb',
  source_id: '1',
  company: 'HSBC',
  sector: 'Banking',
  title: 'Vice President, Credit Risk',
  title_en: null,
  source_tier: 'mainstream',
  locations: ['Central, Hong Kong'],
  seniority: 'senior',
  job_category: null,
  remote_type: 'hybrid',
  required_skills: ['Python', 'Credit Risk'],
  salary_hkd_min: null,
  salary_hkd_max: null,
  salary_estimated_min: null,
  salary_estimated_max: null,
  salary_estimated_confidence: null,
  salary_verified: false,
  years_experience_required: null,
  posted_at: '2026-07-28T00:00:00Z',
  url: 'https://example.com/job',
  is_internship: false,
  description_excerpt: '',
  closed: false,
  board_signals: {},
}

const recruiterPost: Job = {
  ...base,
  source: 'linkedin_posts',
  source_tier: 'social',
  company: 'Confidential via Sarah Chen',
  required_skills: ['Python', 'Portfolio Management'],
  board_signals: {
    linkedin_posts: {
      recruiter_name: 'Sarah Chen',
      recruiter_email: 's.chen@example.com',
      recruiter_profile_url: 'https://linkedin.com/in/sarahchen',
    },
  },
}

const noop = () => {}

describe('JobCard', () => {
  it('shows where the Role was retrieved from', () => {
    render(<JobCard job={base} saved={false} onToggleSave={noop} onClick={noop} />)
    expect(screen.getByText('JobsDB')).toBeTruthy()
  })

  it('explains why a searched Role matched', () => {
    render(
      <JobCard
        job={{ ...base, match_reason: 'title' }}
        saved={false}
        onToggleSave={noop}
        onClick={noop}
      />,
    )
    expect(screen.getByText('Title match')).toBeTruthy()
  })

  it('calls an own-site source the company site, never the ATS vendor', () => {
    render(<JobCard job={{ ...base, source: 'workday' }} saved={false} onToggleSave={noop} onClick={noop} />)
    expect(screen.getByText('Company site')).toBeTruthy()
    expect(screen.queryByText(/workday/i)).toBeNull()
  })

  it('never names the recruiter behind a Recruiter Post', () => {
    const { container } = render(
      <JobCard job={recruiterPost} saved={false} onToggleSave={noop} onClick={noop} />,
    )
    // Not in the badges, not in the company line, not in an aria-label. The
    // company field is the one that catches people out: promote.py stores the
    // name inside it as "Confidential via {recruiter}".
    expect(container.textContent).not.toContain('Sarah Chen')
    expect(container.innerHTML).not.toContain('Sarah Chen')
    expect(screen.getByText('Confidential')).toBeTruthy()
  })

  it('offers no route to the recruiter’s inbox or profile', () => {
    const { container } = render(
      <JobCard job={recruiterPost} saved={false} onToggleSave={noop} onClick={noop} />,
    )
    expect(container.querySelector('a[href^="mailto:"]')).toBeNull()
    expect(container.querySelector('a[href*="linkedin.com/in/"]')).toBeNull()
  })

  it('never lists skills on a card, on any tier', () => {
    // The card is scanned, not read. Skills live in the detail view now — and
    // on a Recruiter Post not even there, since there is no job description
    // behind one to extract them from.
    for (const job of [base, recruiterPost]) {
      const { unmount } = render(<JobCard job={job} saved={false} onToggleSave={noop} onClick={noop} />)
      expect(screen.queryByText('Python'), job.source_tier).toBeNull()
      unmount()
    }
  })

  it('leaves a named employer on a Recruiter Post alone', () => {
    // The mask only strips "… via {name}". An employer the extractor did name
    // must survive it untouched.
    render(
      <JobCard
        job={{ ...recruiterPost, company: 'Citi' }}
        saved={false}
        onToggleSave={noop}
        onClick={noop}
      />,
    )
    expect(screen.getByText('Citi')).toBeTruthy()
  })

  it('says CLOSED once, loudly, rather than twice in small print', () => {
    render(<JobCard job={{ ...base, closed: true }} saved onToggleSave={noop} onClick={noop} />)
    expect(screen.getAllByText('Closed')).toHaveLength(1)
  })

  it('drops market signals on a closed Role — they claim it is still open', () => {
    const live = { ...base, board_signals: { jobsdb: { urgently_hiring: true } } }
    const { unmount } = render(<JobCard job={live} saved={false} onToggleSave={noop} onClick={noop} />)
    expect(screen.getByText('Urgently hiring')).toBeTruthy()
    unmount()

    render(<JobCard job={{ ...live, closed: true }} saved={false} onToggleSave={noop} onClick={noop} />)
    expect(screen.queryByText('Urgently hiring')).toBeNull()
  })

  // ── Admin edit affordance ──────────────────────────────────────────────
  // Absence again, and the same reason as the two above: an ordinary Seeker
  // must never see the pencil, and a control that leaks onto every card is
  // exactly the kind of regression nobody notices arriving.

  it('shows no edit control when the board did not pass onEdit', () => {
    render(<JobCard job={base} saved={false} onToggleSave={noop} onClick={noop} />)
    expect(screen.queryByLabelText(/^Edit /)).toBeNull()
  })

  it('shows an edit control for an admin', () => {
    render(<JobCard job={base} saved={false} onToggleSave={noop} onClick={noop} onEdit={noop} />)
    expect(screen.getByLabelText('Edit Vice President, Credit Risk')).toBeTruthy()
  })

  // ── Whose number is it ────────────────────────────────────────────────
  // Same figure, two very different claims. Badging a human-corrected salary
  // "AI est." tells the Seeker a machine guessed it, which is exactly the
  // provenance error the badge exists to prevent, pointed the other way.

  it('badges an untouched estimate as the AI estimate it is', () => {
    const estimated = { ...base, salary_estimated_min: 40_000, salary_estimated_max: 60_000 }
    render(<JobCard job={estimated} saved={false} onToggleSave={noop} onClick={noop} />)
    expect(screen.getByText('AI est.')).toBeTruthy()
    expect(screen.queryByText('Checked')).toBeNull()
  })

  it('stops calling a corrected salary an AI estimate', () => {
    const corrected = {
      ...base,
      salary_estimated_min: 40_000,
      salary_estimated_max: 60_000,
      salary_verified: true,
    }
    render(<JobCard job={corrected} saved={false} onToggleSave={noop} onClick={noop} />)
    expect(screen.getByText('Checked')).toBeTruthy()
    expect(screen.queryByText('AI est.')).toBeNull()
  })

  it('leaves a disclosed salary alone either way', () => {
    // salary_verified rides on the enrichment, and an employer-stated figure is
    // not an enrichment. It must not pick up a badge it never had.
    const disclosed = {
      ...base, salary_hkd_min: 50_000, salary_hkd_max: 80_000, salary_verified: true,
    }
    render(<JobCard job={disclosed} saved={false} onToggleSave={noop} onClick={noop} />)
    expect(screen.queryByText('Checked')).toBeNull()
    expect(screen.queryByText('AI est.')).toBeNull()
  })

  it('edits the posting without also opening it', () => {
    // The card's title button is stretched over the whole card, so a pencil
    // that did not stop propagation would fire both — the drawer and the
    // detail panel would open on top of each other.
    const edited: Job[] = []
    const opened: Job[] = []
    render(
      <JobCard
        job={base}
        saved={false}
        onToggleSave={noop}
        onClick={j => opened.push(j)}
        onEdit={j => edited.push(j)}
      />,
    )
    fireEvent.click(screen.getByLabelText('Edit Vice President, Credit Risk'))
    expect(edited).toHaveLength(1)
    expect(opened).toHaveLength(0)
  })
})
