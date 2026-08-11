import { render, screen, waitFor } from '@testing-library/react'
import type { ComponentProps } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ResumeMatchesResponse, Seeker } from '../api/client'

const SEEKER: Seeker = {
  id: 's-1',
  email: 'seeker@example.com',
  display_name: 'Ada',
  email_verified: true,
  is_admin: false,
  is_super_admin: false,
}

const fetchResumeMatches = vi.fn<(limit?: number) => Promise<ResumeMatchesResponse>>()
let seeker: Seeker | null = SEEKER

vi.mock('../auth/useAuth', () => ({ useAuth: () => ({ seeker, loading: false }) }))
vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  fetchResumeMatches: (limit: number) => fetchResumeMatches(limit),
}))
const { default: ResumeMatches } = await import('./ResumeMatches')

function renderSubject(
  props: Partial<ComponentProps<typeof ResumeMatches>> = {},
) {
  return render(
    <MemoryRouter>
      <ResumeMatches
        {...props}
      />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  seeker = SEEKER
  fetchResumeMatches.mockReset()
})

describe('Strong matches for your experience', () => {
  it('offers a concise opt-in path before a resume exists', async () => {
    fetchResumeMatches.mockResolvedValue({
      has_resume: false,
      resume_uploaded_at: null,
      model_version: 'resume-signals-v1',
      items: [],
    })
    renderSubject()

    expect(await screen.findByRole('heading', { name: /Find Roles that fit you/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Upload your resume/ })).toHaveAttribute('href', '/account')
  })

  it('hands resume matches to the combined feed without rendering a second category', async () => {
    const onResolved = vi.fn()
    const response: ResumeMatchesResponse = {
      has_resume: true,
      resume_uploaded_at: '2026-08-10T10:00:00Z',
      model_version: 'resume-signals-v1',
      items: [],
    }
    fetchResumeMatches.mockResolvedValue(response)

    renderSubject({ onResolved })

    await waitFor(() => expect(onResolved).toHaveBeenCalledWith(response))
    expect(screen.queryByRole('heading', { name: 'Where your experience stands out' })).not.toBeInTheDocument()
  })

  it('advertises the private feature without calling the account API for anonymous visitors', () => {
    seeker = null
    renderSubject()
    expect(screen.getByRole('heading', { name: 'Find Roles that fit you.' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Create account/ })).toHaveAttribute('href', '/register')
    expect(fetchResumeMatches).not.toHaveBeenCalled()
  })
})
