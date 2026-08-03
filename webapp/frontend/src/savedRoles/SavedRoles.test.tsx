import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Job, Seeker } from '../api/client'

/**
 * Saved Roles across the signed-in / signed-out line.
 *
 * The bug that started this file: signing out wrote the ACCOUNT's Saved Roles
 * into localStorage, where they stayed — on a shared machine, the next person to
 * open the site inherited them. Nothing about that is visible in either effect
 * on its own; it only appears because the two run in declaration order on the
 * same commit, which is exactly the class of defect that needs a mounted test
 * rather than a careful read.
 */

const KEY = 'finex_saved_roles:v1'

// ── Test doubles ──────────────────────────────────────────────────────────────

const SEEKER: Seeker = {
  id: 's-1', email: 'seeker@example.com', display_name: 'Ada', email_verified: true,
}

function makeJob(over: Partial<Job> = {}): Job {
  return {
    source: 'workday', source_id: 'J1', company: 'HSBC', sector: 'Banking',
    title: 'Credit Risk Analyst', title_en: null, source_tier: 'mainstream',
    locations: ['Hong Kong'], seniority: 'mid', job_category: null, remote_type: null,
    required_skills: [], salary_hkd_min: null, salary_hkd_max: null,
    salary_estimated_min: null, salary_estimated_max: null,
    salary_estimated_confidence: null, years_experience_required: null,
    posted_at: '2026-07-01', url: 'https://example.test/j1', is_internship: false,
    description_excerpt: '', closed: false, board_signals: {},
    ...over,
  }
}

const SERVER_ROLE = makeJob({ source_id: 'FROM_SERVER', title: 'Account Role' })
const LOCAL_ROLE = makeJob({ source_id: 'FROM_BROWSER', title: 'Browser Role' })

/** Mutable auth state the tests drive; the mock below reads it on every render. */
let authState: { seeker: Seeker | null; loading: boolean } = { seeker: null, loading: false }

vi.mock('../auth/useAuth', () => ({
  useAuth: () => ({
    ...authState,
    login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn(),
  }),
}))

const fetchSavedRoles = vi.fn(async () => [SERVER_ROLE])
const saveRole = vi.fn(async () => {})
const unsaveRole = vi.fn(async () => {})
const mergeSavedRoles = vi.fn(async () => ({ merged: 0, submitted: 0 }))

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  fetchSavedRoles: (...a: unknown[]) => fetchSavedRoles(...(a as [])),
  saveRole: (...a: unknown[]) => saveRole(...(a as [])),
  unsaveRole: (...a: unknown[]) => unsaveRole(...(a as [])),
  mergeSavedRoles: (...a: unknown[]) => mergeSavedRoles(...(a as [])),
}))

// Imported after the mocks so the module under test picks them up.
const { default: SavedRolesProvider } = await import('./SavedRolesProvider')
const { useSavedRoles } = await import('./useSavedRoles')

/** Renders the context and prints what it holds, so assertions read off the DOM. */
function Readout() {
  const { savedList, count } = useSavedRoles()
  return (
    <div>
      <span data-testid="count">{count}</span>
      <span data-testid="ids">{savedList.map(j => j.source_id).sort().join(',')}</span>
    </div>
  )
}

function Probe() {
  return (
    <SavedRolesProvider>
      <Readout />
    </SavedRolesProvider>
  )
}

function storedIds(): string[] {
  const raw = localStorage.getItem(KEY)
  if (!raw) return []
  return Object.values(JSON.parse(raw) as Record<string, Job>).map(j => j.source_id).sort()
}

beforeEach(() => {
  authState = { seeker: null, loading: false }
  fetchSavedRoles.mockClear().mockResolvedValue([SERVER_ROLE])
  saveRole.mockClear()
  unsaveRole.mockClear()
  mergeSavedRoles.mockClear()
})

// ── The bug ───────────────────────────────────────────────────────────────────

describe('signing out', () => {
  it('does not leave the account\'s Saved Roles in the browser', async () => {
    authState = { seeker: SEEKER, loading: false }
    const { rerender } = render(<Probe />)
    await waitFor(() => expect(screen.getByTestId('ids')).toHaveTextContent('FROM_SERVER'))

    authState = { seeker: null, loading: false }
    rerender(<Probe />)

    await waitFor(() => expect(screen.getByTestId('count')).toHaveTextContent('0'))
    expect(storedIds()).not.toContain('FROM_SERVER')
    // `?? ''` because the correct outcome is that the key was never written at
    // all — the previous implementation wrote the account's Roles into it here.
    expect(localStorage.getItem(KEY) ?? '').not.toContain('FROM_SERVER')
  })

  it('shows an anonymous visitor nothing from the account', async () => {
    authState = { seeker: SEEKER, loading: false }
    const { rerender } = render(<Probe />)
    await waitFor(() => expect(screen.getByTestId('ids')).toHaveTextContent('FROM_SERVER'))

    authState = { seeker: null, loading: false }
    rerender(<Probe />)

    await waitFor(() => expect(screen.getByTestId('ids')).toHaveTextContent(''))
  })
})

// ── The modes ─────────────────────────────────────────────────────────────────

describe('signed out', () => {
  it('reads Saved Roles from the browser', async () => {
    localStorage.setItem(KEY, JSON.stringify({ 'workday__FROM_BROWSER': LOCAL_ROLE }))
    render(<Probe />)
    await waitFor(() => expect(screen.getByTestId('ids')).toHaveTextContent('FROM_BROWSER'))
    expect(fetchSavedRoles).not.toHaveBeenCalled()
  })
})

describe('signed in', () => {
  it('reads Saved Roles from the account, not the browser', async () => {
    localStorage.setItem(KEY, JSON.stringify({ 'workday__FROM_BROWSER': LOCAL_ROLE }))
    authState = { seeker: SEEKER, loading: false }
    render(<Probe />)
    await waitFor(() => expect(screen.getByTestId('ids')).toHaveTextContent('FROM_SERVER'))
  })

  it('lifts the browser\'s Saved Roles into the account in one call', async () => {
    localStorage.setItem(KEY, JSON.stringify({ 'workday__FROM_BROWSER': LOCAL_ROLE }))
    authState = { seeker: SEEKER, loading: false }
    render(<Probe />)

    await waitFor(() => expect(mergeSavedRoles).toHaveBeenCalledTimes(1))
    expect(mergeSavedRoles).toHaveBeenCalledWith([
      { source: 'workday', source_id: 'FROM_BROWSER' },
    ])
    // The endpoint is atomic and idempotent; N individual POSTs are not.
    expect(saveRole).not.toHaveBeenCalled()
  })

  it('clears the browser copy once it is in the account', async () => {
    localStorage.setItem(KEY, JSON.stringify({ 'workday__FROM_BROWSER': LOCAL_ROLE }))
    authState = { seeker: SEEKER, loading: false }
    render(<Probe />)
    await waitFor(() => expect(localStorage.getItem(KEY)).toBeNull())
  })

  it('keeps the browser copy when the lift fails', async () => {
    // A partial migration that wiped the browser copy would silently delete
    // Saved Roles, so a failure must leave everything where it was.
    mergeSavedRoles.mockRejectedValueOnce(new Error('offline'))
    localStorage.setItem(KEY, JSON.stringify({ 'workday__FROM_BROWSER': LOCAL_ROLE }))
    authState = { seeker: SEEKER, loading: false }
    render(<Probe />)
    await waitFor(() => expect(mergeSavedRoles).toHaveBeenCalled())
    expect(storedIds()).toContain('FROM_BROWSER')
  })
})
