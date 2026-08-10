import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Seeker } from '../api/client'

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

beforeEach(() => { seeker = null })

describe('ResumeFeatureSpotlight', () => {
  it('explains the feature and sends a visitor to seeker registration', () => {
    renderSubject()
    expect(screen.getByRole('heading', { name: /See where your experience is strongest/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Create a Seeker account/ })).toHaveAttribute('href', '/register')
    expect(screen.getByText(/The careers index stays free and open/)).toBeInTheDocument()
  })

  it('sends a signed-in Seeker directly to resume management', () => {
    seeker = SEEKER
    renderSubject()
    expect(screen.getByRole('link', { name: /Add or manage your resume/ })).toHaveAttribute('href', '/account')
    expect(screen.queryByRole('link', { name: /Already have an account/ })).not.toBeInTheDocument()
  })
})
