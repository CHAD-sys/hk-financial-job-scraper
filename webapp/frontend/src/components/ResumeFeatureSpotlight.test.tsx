import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
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
    expect(screen.getByRole('heading', { name: /Turn one resume into better job discovery/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Create a Seeker account/ })).toHaveAttribute('href', '/register')
    expect(screen.getByRole('list', { name: 'How resume matching works' })).toBeInTheDocument()
    expect(screen.getByText('Explore matches')).toBeInTheDocument()
    expect(screen.queryByText('Credit Risk & Portfolio Roles')).not.toBeInTheDocument()
  })

  it('asks a signed-out visitor to sign in when they click the how-it-works panel', async () => {
    const user = userEvent.setup()
    renderSubject()

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Sign in or create an account/ }))

    // Scoped to the dialog: the panel's own column already carries links with
    // these same labels, so an unscoped query would pass without the dialog.
    const dialog = screen.getByRole('dialog')
    const prompt = within(dialog)
    expect(prompt.getByRole('heading', { name: /Create an account to upload your resume/ })).toBeInTheDocument()
    // Both ways in, not just registration — a returning Seeker who is simply
    // signed out must not be told to make a second account.
    expect(prompt.getByRole('link', { name: /Create a Seeker account/ })).toHaveAttribute('href', '/register')
    expect(prompt.getByRole('link', { name: /Already have an account\? Sign in/ })).toHaveAttribute('href', '/signin')

    await user.click(prompt.getByRole('button', { name: 'Close' }))
    expect(dialog).not.toBeInTheDocument()
  })

  /**
   * Regression: the prompt was first wired to useModalHistoryGuard, which pushes
   * a history entry on open and pops it with history.back() on unmount. Every
   * useful exit from this dialog is a router navigation, so clicking through to
   * /register unmounted it and the cleanup fired history.back() against the
   * navigation that had just happened — which wedged the tab in a real browser.
   *
   * Asserted on window.history directly rather than by following the link:
   * MemoryRouter keeps its own in-memory stack and never touches window.history,
   * so a "did we land on /register" assertion passes whether or not the guard is
   * installed. This spy is the part that actually goes red.
   */
  it('does not rewind browser history when the prompt is clicked through', async () => {
    const user = userEvent.setup()
    const back = vi.spyOn(window.history, 'back').mockImplementation(() => {})
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<ResumeFeatureSpotlight />} />
          <Route path="/register" element={<h1>Registration</h1>} />
        </Routes>
      </MemoryRouter>,
    )

    await user.click(screen.getByRole('button', { name: /Sign in or create an account/ }))
    await user.click(within(screen.getByRole('dialog')).getByRole('link', { name: /Create a Seeker account/ }))

    expect(await screen.findByRole('heading', { name: 'Registration' })).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(back).not.toHaveBeenCalled()
  })

  /**
   * Regression: showModal() puts the dialog in the top layer and makes the rest
   * of the document inert. Unmounting the element does not reliably undo that in
   * Chrome, so the first version — which never called close() — left the whole
   * page unclickable after the visitor followed a link out of the prompt. The
   * freeze itself only reproduces in a real browser (jsdom has no top layer at
   * all), so what is pinned here is the mechanism: close() must run on the way
   * out, whichever way the prompt is dismissed.
   */
  it('closes the dialog rather than just unmounting it', async () => {
    const user = userEvent.setup()
    const close = vi.spyOn(HTMLDialogElement.prototype, 'close')
    renderSubject()

    await user.click(screen.getByRole('button', { name: /Sign in or create an account/ }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Close' }))

    expect(close).toHaveBeenCalled()
  })

  it('never shows the sign-in prompt to a signed-in Seeker', async () => {
    seeker = SEEKER
    fetchResumeMatches.mockResolvedValue({ has_resume: false, resume_uploaded_at: null, model_version: 'resume-signals-v1', items: [] })
    renderSubject()

    expect(await screen.findByRole('heading', { name: /Add your resume to start matching/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Sign in or create an account/ })).not.toBeInTheDocument()
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
