import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  DEFAULT_FILTERS,
  addUnauthorizedHandler,
  fetchEmployerMe,
  fetchMe,
  filtersToSearchParams,
  hasResearchScope,
  searchParamsToFilters,
} from './client'
import type { JobFilters } from './client'

/**
 * The 401 fan-out client.ts added when Employer accounts got their own
 * AuthProvider: a Set of handlers instead of one slot, each receiving the
 * request path, because a Seeker session and an Employer session can be
 * signed in in the same browser at once (main.py) and a 401 from one must
 * never clear the other. The path is the only thing that lets AuthProvider
 * and EmployerAuthProvider tell which account a given 401 was about.
 */

function mockFetch(status: number) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    status,
    ok: status < 400,
    json: async () => ({}),
  }))
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('hasResearchScope', () => {
  // Mirrors job_read.MIN_RESEARCH_QUERY_LENGTH (ADR 0018) — see
  // tests/test_research_scope_contract.py for the cross-language parity check.
  it('rejects a one-character query', () => {
    expect(hasResearchScope('a')).toBe(false)
  })

  it('accepts a two-character query', () => {
    expect(hasResearchScope('ab')).toBe(true)
  })

  it('trims whitespace before counting', () => {
    expect(hasResearchScope(' a ')).toBe(false)
    expect(hasResearchScope(' ab ')).toBe(true)
  })

  it('rejects an empty query', () => {
    expect(hasResearchScope('')).toBe(false)
  })
})

describe('addUnauthorizedHandler', () => {
  // unauthorizedHandlers lives at module scope, so a handler this file forgot
  // to unsubscribe would leak into every later test in the run. Each test
  // tracks its own subscriptions here and unwinds them in afterEach, rather
  // than trusting a manual unsubscribe() call at the end of every test body.
  const unsubs: (() => void)[] = []
  function subscribe(fn: (path: string) => void) {
    const unsubscribe = addUnauthorizedHandler(fn)
    unsubs.push(unsubscribe)
    return unsubscribe
  }
  afterEach(() => {
    while (unsubs.length) unsubs.pop()!()
  })

  it('fires every registered handler with the request path', async () => {
    mockFetch(401)
    const calls: string[] = []
    subscribe(path => calls.push(`seeker:${path}`))
    subscribe(path => calls.push(`employer:${path}`))

    await fetchMe()

    expect(calls).toEqual(['seeker:/api/auth/me', 'employer:/api/auth/me'])
  })

  it('does not fire on a non-401 response', async () => {
    mockFetch(200)
    const calls: string[] = []
    subscribe(path => calls.push(path))

    await fetchMe()

    expect(calls).toEqual([])
  })

  it('lets a handler stop listening via the returned unsubscribe function', async () => {
    mockFetch(401)
    const calls: string[] = []
    const unsubscribe = subscribe(path => calls.push(path))
    unsubscribe()

    await fetchMe()

    expect(calls).toEqual([])
  })

  it('a Seeker-scoped handler ignores an Employer-endpoint 401, and vice versa', async () => {
    // This is the actual bug the Set-plus-path design exists to prevent: with
    // the old single-slot setUnauthorizedHandler(), whichever provider
    // registered last would have its handler fire for EVERY 401 — an
    // Employer session expiring would have silently signed the Seeker out
    // too, and there would have been no way to tell which endpoint any given
    // 401 even came from.
    mockFetch(401)
    let seekerCleared = false
    let employerCleared = false
    subscribe(path => {
      if (path.startsWith('/api/auth/') || path.startsWith('/api/me')) seekerCleared = true
    })
    subscribe(path => {
      if (path.startsWith('/api/employer')) employerCleared = true
    })

    await fetchEmployerMe()

    expect(employerCleared).toBe(true)
    expect(seekerCleared).toBe(false)
  })
})

describe('public Role research URLs', () => {
  it('does not expose source tiers in generated URLs', () => {
    const params = filtersToSearchParams(
      { ...DEFAULT_FILTERS, search: 'risk', tier: 'social' },
      'relevance',
      1,
    )

    expect(params.get('q')).toBe('risk')
    expect(params.has('tier')).toBe(false)
  })

  it('folds legacy tier links back into the all-source result stream', () => {
    const parsed = searchParamsToFilters(
      new URLSearchParams('q=risk&tier=boutique&sort=relevance'),
    )

    expect(parsed.filters.search).toBe('risk')
    expect(parsed.filters.tier).toBe('all')
  })

  it('round-trips every filter field through the URL and back unchanged', () => {
    // filtersToSearchParams (write) and searchParamsToFilters (read) used to
    // each hand-spell every param name independently — this is the test that
    // would have caught 'q' vs 'search' or 'sector' vs 'sectors' drifting
    // apart, by exercising every field in JobFilters at once rather than one
    // at a time.
    const filters: JobFilters = {
      tier: 'all',
      search: 'risk analyst',
      sectors: ['Banking', 'Insurance'],
      companies: ['HSBC'],
      seniority: ['senior'],
      remote_type: ['hybrid'],
      skills: ['Python'],
      salary_min: 30000,
      salary_max: 80000,
      salary_disclosed_only: true,
      exp_min: 2,
      exp_max: 8,
      is_internship: true,
      is_new: true,
      urgently_hiring: true,
      max_applicants: 10,
      hidden_only: true,
      verified_only: true,
    }

    const params = filtersToSearchParams(filters, 'relevance', 3)
    const parsed = searchParamsToFilters(params)

    expect(parsed.filters).toEqual(filters)
    expect(parsed.sort).toBe('relevance')
    expect(parsed.page).toBe(3)
  })
})
