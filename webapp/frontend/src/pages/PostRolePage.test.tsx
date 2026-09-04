import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * The one guarantee the Employer preview owes: an Ultimate Admin looking around
 * the employer surface cannot write anything.
 *
 * /post-a-role is the only action the Employer product has, and it appends to
 * the moderation queue under whatever company name is in the form. A preview
 * that could submit would let an admin drop a row into that queue wearing some
 * company's name — the exact impersonation the mode is written not to be
 * (employerView/EmployerViewProvider.tsx).
 *
 * Both halves are pinned here because the button being disabled is a UI state,
 * not a guarantee: a form can still be submitted by keyboard or by a later edit
 * that forgets the flag, so `handleSubmit` refuses independently.
 */

const submitRole = vi.hoisted(() => vi.fn())
vi.mock('../api/client', async importOriginal => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  submitRole,
}))
vi.mock('../components/Nav', () => ({ default: () => <nav>Navigation</nav> }))

const employerAuthValue = vi.hoisted(() => ({
  employer: null as Record<string, unknown> | null, loading: false,
}))
const employerViewValue = vi.hoisted(() => ({
  employerView: false, canUseEmployerView: false, setEmployerView: vi.fn(),
}))
vi.mock('../auth/useEmployerAuth', () => ({ useEmployerAuth: () => employerAuthValue }))
vi.mock('../employerView/useEmployerView', () => ({ useEmployerView: () => employerViewValue }))

const { default: PostRolePage } = await import('./PostRolePage')

function renderPage() {
  return render(<MemoryRouter><PostRolePage /></MemoryRouter>)
}

const REAL_EMPLOYER = {
  id: 'emp-1', email: 'hr@acmecapital.com',
  company_name: 'Acme Capital', contact_name: 'Jamie Lee', email_verified: true,
}

beforeEach(() => {
  submitRole.mockReset()
  submitRole.mockResolvedValue(undefined)
  employerAuthValue.employer = null
  employerAuthValue.loading = false
  employerViewValue.employerView = false
})

describe('Post a role', () => {
  it('still turns away someone who is neither an Employer nor previewing', () => {
    // The gate that already existed. It must not have been widened into "anyone
    // signed in" by the preview being bolted on beside it.
    renderPage()
    expect(screen.queryByRole('button', { name: /Submit for review/ })).not.toBeInTheDocument()
  })

  it('lets a real Employer submit, prefilled from their account', async () => {
    employerAuthValue.employer = REAL_EMPLOYER
    renderPage()

    expect(screen.getByDisplayValue('Acme Capital')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Submit for review/ })).toBeEnabled()
  })

  it('shows the preview the real form, so there is something to look at', () => {
    employerViewValue.employerView = true
    renderPage()

    expect(screen.getByRole('heading', { name: 'Post a role' })).toBeInTheDocument()
    // No company to prefill from — the preview holds no Employer identity, and
    // inventing one is the thing this mode must never do.
    expect(screen.queryByDisplayValue('Acme Capital')).not.toBeInTheDocument()
  })

  it('disables submission in the preview, and says why on the button itself', () => {
    employerViewValue.employerView = true
    renderPage()

    const button = screen.getByRole('button', { name: /Submitting is disabled in Employer view/ })
    expect(button).toBeDisabled()
  })

  it('refuses the write even if the form is submitted around the button', async () => {
    // The half that holds when the button is bypassed. Went RED with the
    // `if (preview) return` guard removed and only the disabled attribute left.
    employerViewValue.employerView = true
    const { container } = renderPage()

    const form = container.querySelector('form')
    expect(form).not.toBeNull()
    form!.requestSubmit()

    expect(submitRole).not.toHaveBeenCalled()
  })

  it('a real Employer session wins over a stale preview flag', async () => {
    // Both true at once should not be reachable (the provider makes the preview
    // unavailable while a session exists), but if it ever were, the real
    // Employer must keep their working form rather than lose it to a preview.
    employerAuthValue.employer = REAL_EMPLOYER
    employerViewValue.employerView = true
    renderPage()

    expect(screen.getByRole('button', { name: /Submit for review/ })).toBeEnabled()
    await userEvent.click(screen.getByRole('button', { name: /Submit for review/ }))
    expect(submitRole).toHaveBeenCalled()
  })
})
