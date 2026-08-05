// API base. Empty → relative "/api" calls, which is the normal case now: one
// FastAPI service serves this bundle AND the API from a single origin (docs/adr/
// 0005), and in dev the Vite proxy forwards the same relative calls to :8000
// (see vite.config.ts). So empty is correct in dev, in preview and in production.
//
// The default is deliberately '' and not 'http://localhost:8000'. A production
// build runs where no .env.local exists, so a localhost default would silently
// bake a dead address into the deployed bundle whenever the env var is forgotten.
// Failing to relative /api instead just works. Set VITE_API_URL to an absolute
// URL only to aim at a genuinely separate backend — and note that doing so puts
// the UI and API on two origins again, which is what breaks session cookies.
export const API = import.meta.env.VITE_API_URL ?? ''

// ── Transport ─────────────────────────────────────────────────────────────────

/**
 * Called whenever the API answers 401.
 *
 * AuthProvider registers itself here so one dead session clears the signed-in
 * state everywhere at once. It deliberately does NOT redirect: the board is
 * public (docs/adr/0002), so losing a session means you are browsing anonymously
 * again, not that you have been thrown out of the site.
 */
let onUnauthorized: (() => void) | null = null

export function setUnauthorizedHandler(fn: (() => void) | null): void {
  onUnauthorized = fn
}

/**
 * Every request in this file goes through here, for one reason:
 * `credentials: 'include'`.
 *
 * The session cookie is httpOnly, so JavaScript can never read it or attach it
 * by hand — the browser only sends it when the fetch asks for it. Omitting the
 * flag is the classic way auth "works locally but not in production": in dev the
 * API is same-origin through the Vite proxy, where the cookie rides along
 * regardless, so the bug stays invisible until deploy.
 */
async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const res = await fetch(`${API}${path}`, { credentials: 'include', ...init })
  if (res.status === 401) onUnauthorized?.()
  return res
}

/** Pull the backend's `detail` string out of an error body, if there is one. */
async function readDetail(res: Response): Promise<string> {
  try {
    const j = await res.json()
    return typeof j?.detail === 'string' ? j.detail : ''
  } catch {
    return '' // non-JSON error body — the caller falls back to a generic message
  }
}

/** An API failure that still knows its status code, so callers can branch on it. */
export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

// ── Types ─────────────────────────────────────────────────────────────────────

export interface Job {
  source: string
  source_id: string
  company: string
  sector: string
  title: string
  title_en: string | null
  source_tier: string
  locations: string[]
  seniority: string | null
  job_category: string | null
  remote_type: string | null
  required_skills: string[]
  salary_hkd_min: number | null
  salary_hkd_max: number | null
  salary_estimated_min: number | null
  salary_estimated_max: number | null
  salary_estimated_confidence: string | null
  years_experience_required: number | null
  posted_at: string | null
  url: string
  is_internship: boolean
  description_excerpt: string
  /**
   * The vacancy is no longer open.
   *
   * Only ever true for a Role reached by reference — a Saved Role, or a detail
   * URL. The board never returns one, because browsing is filtered and
   * addressing is not (see webapp/backend/job_read.py).
   *
   * This is the field that makes a Saved Role worth having: the server resolves
   * the reference against jobs.db on every read, so a Role that closed since it
   * was saved says so, instead of showing an apply button into a void.
   */
  closed: boolean
  // Market signals by board, e.g. { indeed: { urgently_hiring, applicant_count, new_job }, linkedin: { reposted } }
  board_signals: Record<string, Record<string, unknown>>
}

export interface JobDetail extends Job {
  description_clean: string
  description_summary: string
  sources: string[]
}

export interface JobListResponse {
  total: number
  page: number
  page_size: number
  total_pages: number
  jobs: Job[]
}

export interface NameCount {
  name: string
  count: number
}

export interface FiltersResponse {
  companies: NameCount[]
  sectors: NameCount[]
  skills: NameCount[]
  seniority_levels: string[]
  remote_types: string[]
  salary_range: { min: number | null; max: number | null }
  experience_range: { min: number | null; max: number | null }
}

export interface StatsResponse {
  total_active_jobs: number
  by_sector: Record<string, number>
  by_seniority: Record<string, number>
  by_remote_type: Record<string, number>
  by_source_tier: Record<string, number>
  top_skills: NameCount[]
  top_companies: NameCount[]
  internship_count: number
}

export type TierTab = 'all' | 'boutique' | 'mainstream' | 'social'

// board_signals.linkedin_posts shape, set by hk_jobs/posts/promote.py — recruiter
// attribution for Recruiter Posts jobs (source_tier === 'social').
export interface LinkedInPostSignals {
  recruiter_name: string | null
  recruiter_profile_url: string | null
  // Harvested by hk_jobs/posts/email_harvest.py (LP-5) — null until that
  // module has run for this recruiter, or if no email was found.
  recruiter_email: string | null
  employer_hint: string | null
  engagement: { likes: number; comments: number } | null
  post_created_at: string | null
  // Set by hk_jobs/posts/ghost_check.py when a cheap DeepSeek pass confirms
  // this post is the SAME real vacancy as a listing already on the mainstream/
  // boutique board — undefined/false until that pass has run and matched.
  not_a_ghost_job?: boolean
}

export interface JobFilters {
  tier: TierTab
  search: string
  sectors: string[]
  companies: string[]
  seniority: string[]
  remote_type: string[]
  skills: string[]
  salary_min: number | null
  salary_max: number | null
  salary_disclosed_only: boolean
  exp_min: number | null
  exp_max: number | null
  is_internship: boolean | null
  is_new: boolean
  urgently_hiring: boolean
  max_applicants: number | null
  hidden_only: boolean
  verified_only: boolean
}

export const DEFAULT_FILTERS: JobFilters = {
  tier: 'all',
  search: '',
  sectors: [],
  companies: [],
  seniority: [],
  remote_type: [],
  skills: [],
  salary_min: null,
  salary_max: null,
  salary_disclosed_only: false,
  exp_min: null,
  exp_max: null,
  is_internship: null,
  is_new: false,
  urgently_hiring: false,
  max_applicants: null,
  hidden_only: false,
  verified_only: false,
}

// ── Fetch helpers ─────────────────────────────────────────────────────────────

export async function fetchJobs(
  filters: JobFilters,
  sort: string,
  page: number,
  pageSize = 24,
): Promise<JobListResponse> {
  const p = new URLSearchParams()

  if (filters.tier !== 'all') p.set('tier', filters.tier)
  if (filters.search) p.set('search', filters.search)
  filters.sectors.forEach(s => p.append('sectors', s))
  filters.companies.forEach(c => p.append('companies', c))
  filters.seniority.forEach(s => p.append('seniority', s))
  filters.remote_type.forEach(r => p.append('remote_type', r))
  filters.skills.forEach(s => p.append('skills', s))

  if (filters.salary_disclosed_only) {
    p.set('salary_min', String(filters.salary_min ?? 1))
  } else if (filters.salary_min !== null) {
    p.set('salary_min', String(filters.salary_min))
  }
  if (filters.salary_max !== null) {
    p.set('salary_max', String(filters.salary_max))
  }

  if (filters.exp_min !== null) p.set('exp_min', String(filters.exp_min))
  if (filters.exp_max !== null) p.set('exp_max', String(filters.exp_max))
  if (filters.is_internship !== null) p.set('is_internship', String(filters.is_internship))
  if (filters.is_new) p.set('is_new', 'true')
  if (filters.urgently_hiring) p.set('urgently_hiring', 'true')
  if (filters.max_applicants !== null) p.set('max_applicants', String(filters.max_applicants))
  if (filters.hidden_only) p.set('hidden_only', 'true')
  if (filters.verified_only) p.set('verified_only', 'true')

  p.set('sort', sort)
  p.set('page', String(page))
  p.set('page_size', String(pageSize))

  const res = await apiFetch(`/api/jobs?${p}`)
  if (!res.ok) throw new Error(`Jobs fetch failed: ${res.status}`)
  return res.json()
}

export async function fetchJobDetail(source: string, sourceId: string): Promise<JobDetail> {
  const res = await apiFetch(`/api/jobs/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}`)
  if (!res.ok) throw new Error(`Job detail fetch failed: ${res.status}`)
  return res.json()
}

export async function fetchFilters(): Promise<FiltersResponse> {
  const res = await apiFetch('/api/filters')
  if (!res.ok) throw new Error(`Filters fetch failed: ${res.status}`)
  return res.json()
}

export async function fetchStats(): Promise<StatsResponse> {
  const res = await apiFetch('/api/stats')
  if (!res.ok) throw new Error(`Stats fetch failed: ${res.status}`)
  return res.json()
}

// ── Write endpoints ───────────────────────────────────────────────────────────
// The only two POSTs in the app. Both are moderated//relayed by the backend and
// neither writes anything a visitor can read back, so there is no auth here.

/** Career stages offered on the consultation form. Must match the backend enum. */
export const CAREER_STAGES = [
  '3–8 years',
  '8–15 years',
  '15+ years',
  'C-suite / board',
] as const

export interface EnquiryPayload {
  name: string
  email: string
  career_stage: string
  message: string
  /** Honeypot. Always sent, always empty for a human. */
  website: string
}

export interface RolePayload {
  contact_name: string
  contact_email: string
  company: string
  title: string
  location: string
  employment_type: string
  salary_range: string
  description: string
  apply_url: string
  /** Honeypot. */
  website: string
}

/**
 * Shared POST helper. Surfaces the backend's `detail` string as the thrown
 * message so forms can show a real reason (rate limit, validation) rather than
 * a generic failure.
 */
async function postJson(path: string, body: unknown): Promise<{ ok: boolean }> {
  const res = await apiFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

  if (!res.ok) {
    const detail = await readDetail(res)
    if (res.status === 429) {
      throw new Error(detail || 'Too many submissions. Please try again later.')
    }
    throw new Error(detail || `Submission failed (${res.status}).`)
  }

  return res.json()
}

export function submitEnquiry(payload: EnquiryPayload): Promise<{ ok: boolean }> {
  return postJson('/api/contact', payload)
}

export function submitRole(payload: RolePayload): Promise<{ ok: boolean }> {
  return postJson('/api/post-role', payload)
}

// ── Seeker accounts ───────────────────────────────────────────────────────────
// A Seeker is the only kind of account holder (CONTEXT.md, docs/adr/0001). None
// of this gates anything: an account exists so Saved Roles outlive the browser.
// Every call below relies on the session cookie set by the backend, which is why
// they all go through apiFetch.

export interface Seeker {
  id: string
  email: string
  display_name: string | null
  email_verified: boolean
}

export interface RegisterPayload {
  email: string
  password: string
  display_name: string
  /** Honeypot. Always sent, always empty for a human. */
  website: string
}

/** Where "Continue with Google" points. A plain link — the backend redirects. */
export const GOOGLE_SIGN_IN_PATH = `${API}/api/auth/google`

/** Turn a non-OK auth response into an ApiError carrying the backend's reason. */
async function authError(res: Response, fallback: string): Promise<ApiError> {
  const detail = await readDetail(res)
  if (res.status === 429) {
    return new ApiError(429, detail || 'Too many attempts. Please try again later.')
  }
  return new ApiError(res.status, detail || fallback)
}

/**
 * Who is signed in, or `null`.
 *
 * A 401 here is the ordinary answer for an anonymous visitor, not a failure —
 * so it resolves to null rather than throwing. Only a genuine transport or
 * server error throws.
 */
export async function fetchMe(): Promise<Seeker | null> {
  const res = await apiFetch('/api/auth/me')
  if (res.status === 401) return null
  if (!res.ok) throw new ApiError(res.status, `Could not load your account (${res.status}).`)
  return res.json()
}

export async function registerSeeker(payload: RegisterPayload): Promise<void> {
  const res = await apiFetch('/api/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  // Registering an address that already exists answers like success on purpose,
  // so the endpoint is not an account-existence oracle (PLAN_ACCOUNTS §5). The
  // caller therefore asks /me afterwards rather than assuming it is signed in.
  if (!res.ok) throw await authError(res, `Could not create your account (${res.status}).`)
}

export async function loginSeeker(email: string, password: string): Promise<void> {
  const res = await apiFetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (res.status === 401) {
    // Deliberately one message for "no such address" and "wrong password" —
    // saying which one is true tells a stranger whether the address has an
    // account here.
    throw new ApiError(401, 'That email and password combination is not right.')
  }
  if (!res.ok) throw await authError(res, `Could not sign you in (${res.status}).`)
}

export async function logoutSeeker(): Promise<void> {
  const res = await apiFetch('/api/auth/logout', { method: 'POST' })
  // 401 means the session was already gone, which is the outcome we wanted.
  if (!res.ok && res.status !== 401) {
    throw new ApiError(res.status, `Could not sign you out (${res.status}).`)
  }
}

/** Permanent. Rows removed, sessions revoked — see docs/adr/0007. */
export async function deleteAccount(): Promise<void> {
  const res = await apiFetch('/api/me', { method: 'DELETE' })
  if (!res.ok) throw await authError(res, `Could not delete your account (${res.status}).`)
}

/**
 * Spend the token from a "confirm your email" link.
 *
 * A POST the page fires from script, not the GET the link itself would be —
 * see main.py's verify_email() docstring: some mail clients pre-fetch links to
 * scan them, which would burn a single-use GET token before a human ever
 * clicked it.
 */
export async function verifyEmail(token: string): Promise<Seeker> {
  const res = await apiFetch('/api/auth/verify-email', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }),
  })
  if (!res.ok) throw await authError(res, `Could not verify your email (${res.status}).`)
  return res.json()
}

/**
 * Ask for a password-reset email. Always resolves the same way whether or not
 * the address has an account — same non-enumeration posture as register
 * (PLAN_ACCOUNTS §5) — so the caller has nothing to branch on beyond a genuine
 * transport/server error.
 */
export async function requestPasswordReset(email: string): Promise<void> {
  const res = await apiFetch('/api/auth/forgot-password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  })
  if (!res.ok) throw await authError(res, `Could not send a reset link (${res.status}).`)
}

/** Spend a reset token and set a new password. Signs the caller back in. */
export async function resetPassword(token: string, password: string): Promise<Seeker> {
  const res = await apiFetch('/api/auth/reset-password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token, password }),
  })
  if (!res.ok) throw await authError(res, `Could not reset your password (${res.status}).`)
  return res.json()
}

// ── Saved Roles (server-side) ─────────────────────────────────────────────────
// The server stores only (source, source_id) and joins the Role's fields from
// jobs.db at read time, so a Saved Role is a reference and never a frozen copy
// — which is the whole reason it beats the localStorage version.

export type SavedRole = Job

export async function fetchSavedRoles(): Promise<SavedRole[]> {
  const res = await apiFetch('/api/me/saved')
  if (!res.ok) throw new ApiError(res.status, `Could not load your Saved Roles (${res.status}).`)
  return res.json()
}

export async function saveRole(source: string, sourceId: string): Promise<void> {
  const res = await apiFetch('/api/me/saved', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source, source_id: sourceId }),
  })
  if (!res.ok) throw new ApiError(res.status, `Could not save that Role (${res.status}).`)
}

/**
 * Lift a browser's Saved Roles into the account in one call.
 *
 * A union, never a replace, and idempotent — so a Seeker signing in on a second
 * device keeps both sets, and a retry after a flaky network cannot duplicate or
 * drop anything. That is why this exists instead of N calls to `saveRole`:
 * "all or nothing" is a property the server can actually provide, and a client
 * loop cannot.
 */
export async function mergeSavedRoles(
  roles: { source: string; source_id: string }[],
): Promise<{ merged: number; submitted: number }> {
  const res = await apiFetch('/api/me/saved/merge', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ roles }),
  })
  if (!res.ok) {
    throw new ApiError(res.status, `Could not move your Saved Roles into the account (${res.status}).`)
  }
  return res.json()
}

export async function unsaveRole(source: string, sourceId: string): Promise<void> {
  const path = `/api/me/saved/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}`
  const res = await apiFetch(path, { method: 'DELETE' })
  // 404 means it was not saved in the first place — the end state is the one
  // the Seeker asked for, so treat it as done rather than an error.
  if (!res.ok && res.status !== 404) {
    throw new ApiError(res.status, `Could not remove that Saved Role (${res.status}).`)
  }
}

// ── URL serialisation ─────────────────────────────────────────────────────────

export function filtersToSearchParams(
  filters: JobFilters,
  sort: string,
  page: number,
): URLSearchParams {
  const p = new URLSearchParams()
  if (filters.tier !== 'all') p.set('tier', filters.tier)
  if (filters.search) p.set('q', filters.search)
  filters.sectors.forEach(s => p.append('sector', s))
  filters.companies.forEach(c => p.append('company', c))
  filters.seniority.forEach(s => p.append('seniority', s))
  filters.remote_type.forEach(r => p.append('remote', r))
  filters.skills.forEach(s => p.append('skill', s))
  if (filters.salary_disclosed_only) p.set('sal_disclosed', '1')
  if (filters.salary_min !== null) p.set('sal_min', String(filters.salary_min))
  if (filters.salary_max !== null) p.set('sal_max', String(filters.salary_max))
  if (filters.exp_min !== null) p.set('exp_min', String(filters.exp_min))
  if (filters.exp_max !== null) p.set('exp_max', String(filters.exp_max))
  if (filters.is_internship) p.set('intern', '1')
  if (filters.is_new) p.set('new', '1')
  if (filters.urgently_hiring) p.set('urgent', '1')
  if (filters.max_applicants !== null) p.set('max_appl', String(filters.max_applicants))
  if (filters.hidden_only) p.set('hidden', '1')
  if (filters.verified_only) p.set('verified', '1')
  if (sort !== 'newest') p.set('sort', sort)
  if (page > 1) p.set('page', String(page))
  return p
}

export function searchParamsToFilters(
  p: URLSearchParams,
): { filters: JobFilters; sort: string; page: number } {
  const tierParam = p.get('tier')
  return {
    filters: {
      tier: (tierParam === 'boutique' || tierParam === 'mainstream' || tierParam === 'social') ? tierParam : 'all',
      search: p.get('q') ?? '',
      sectors: p.getAll('sector'),
      companies: p.getAll('company'),
      seniority: p.getAll('seniority'),
      remote_type: p.getAll('remote'),
      skills: p.getAll('skill'),
      salary_disclosed_only: p.get('sal_disclosed') === '1',
      salary_min: p.has('sal_min') ? Number(p.get('sal_min')) : null,
      salary_max: p.has('sal_max') ? Number(p.get('sal_max')) : null,
      exp_min: p.has('exp_min') ? Number(p.get('exp_min')) : null,
      exp_max: p.has('exp_max') ? Number(p.get('exp_max')) : null,
      is_internship: p.get('intern') === '1' ? true : null,
      is_new: p.get('new') === '1',
      urgently_hiring: p.get('urgent') === '1',
      max_applicants: p.has('max_appl') ? Number(p.get('max_appl')) : null,
      hidden_only: p.get('hidden') === '1',
      verified_only: p.get('verified') === '1',
    },
    sort: p.get('sort') ?? 'newest',
    page: Number(p.get('page') ?? '1'),
  }
}

export function countActiveFilters(filters: JobFilters): number {
  let n = 0
  if (filters.search) n++
  n += filters.sectors.length
  n += filters.companies.length
  n += filters.seniority.length
  n += filters.remote_type.length
  n += filters.skills.length
  if (filters.salary_disclosed_only || filters.salary_min !== null || filters.salary_max !== null) n++
  if (filters.exp_min !== null || filters.exp_max !== null) n++
  if (filters.is_internship) n++
  if (filters.is_new) n++
  if (filters.urgently_hiring) n++
  if (filters.max_applicants !== null) n++
  if (filters.hidden_only) n++
  if (filters.verified_only) n++
  return n
}

// ── Employer / recruiter accounts ───────────────────────────────────────────
//
// A separate identity from Seeker (docs/adr/0001) — its own cookie
// (finex_employer_session), its own endpoints, no shared session. Email
// verification, password reset and Google sign-in shipped in phase 2 — see
// main.py's "Employer / recruiter accounts" section for the full scope note.
// Still no submissions dashboard.

export interface Employer {
  id: string
  email: string
  company_name: string
  contact_name: string
  email_verified: boolean
}

export interface EmployerRegisterPayload {
  email: string
  password: string
  company_name: string
  contact_name: string
  /** Honeypot. Always sent, always empty for a human. */
  website: string
}

/** Turn a non-OK employer-auth response into an ApiError carrying the reason. */
async function employerAuthError(res: Response, fallback: string): Promise<ApiError> {
  const detail = await readDetail(res)
  if (res.status === 429) {
    return new ApiError(429, detail || 'Too many attempts. Please try again later.')
  }
  if (res.status === 409) {
    return new ApiError(409, detail || 'That email already has an employer account.')
  }
  return new ApiError(res.status, detail || fallback)
}

/** Who is signed in as an Employer, or `null`. A 401 is the ordinary anonymous
 * answer, not a failure. */
export async function fetchEmployerMe(): Promise<Employer | null> {
  const res = await apiFetch('/api/employer/me')
  if (res.status === 401) return null
  if (!res.ok) throw new ApiError(res.status, `Could not load your account (${res.status}).`)
  return res.json()
}

export async function registerEmployer(payload: EmployerRegisterPayload): Promise<Employer> {
  const res = await apiFetch('/api/employer/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  // Unlike registerSeeker(), a duplicate address is an honest 409 here — see
  // main.py's employer_register() docstring for why that trade differs.
  if (!res.ok) throw await employerAuthError(res, `Could not create your account (${res.status}).`)
  return res.json()
}

export async function loginEmployer(email: string, password: string): Promise<Employer> {
  const res = await apiFetch('/api/employer/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (res.status === 401) {
    throw new ApiError(401, 'That email and password combination is not right.')
  }
  if (!res.ok) throw await employerAuthError(res, `Could not sign you in (${res.status}).`)
  return res.json()
}

export async function logoutEmployer(): Promise<void> {
  const res = await apiFetch('/api/employer/logout', { method: 'POST' })
  if (!res.ok && res.status !== 401) {
    throw new ApiError(res.status, `Could not sign you out (${res.status}).`)
  }
}

/** Where "Continue with Google" points for an Employer — a separate redirect
 * URI from the Seeker one (see main.py's Employer Google section), but the
 * same reasoning: a plain link, not a fetch, so Google's own consent-screen
 * navigation completes. */
export const EMPLOYER_GOOGLE_SIGN_IN_PATH = `${API}/api/employer/auth/google`

/** Spend the token from an Employer "confirm your email" link. Same POST-
 * from-script reasoning as verifyEmail() — see that docstring. */
export async function verifyEmployerEmail(token: string): Promise<Employer> {
  const res = await apiFetch('/api/employer/auth/verify-email', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }),
  })
  if (!res.ok) throw await employerAuthError(res, `Could not verify your email (${res.status}).`)
  return res.json()
}

/** Ask for an Employer password-reset email. Always resolves the same way
 * whether or not the address has an account — see main.py's employer_
 * forgot_password() docstring for why this one differs from register's
 * honest 409. */
export async function requestEmployerPasswordReset(email: string): Promise<void> {
  const res = await apiFetch('/api/employer/auth/forgot-password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  })
  if (!res.ok) throw await employerAuthError(res, `Could not send a reset link (${res.status}).`)
}

/** Spend an Employer reset token and set a new password. Signs the caller
 * back in. */
export async function resetEmployerPassword(token: string, password: string): Promise<Employer> {
  const res = await apiFetch('/api/employer/auth/reset-password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token, password }),
  })
  if (!res.ok) throw await employerAuthError(res, `Could not reset your password (${res.status}).`)
  return res.json()
}

/**
 * Domains common enough that a registration against one is almost certainly a
 * personal inbox, not a company one. A hint, never a rule — nothing here
 * blocks submission, and "Continue with Google" a few lines below is fully
 * Gmail-capable regardless of what this returns.
 */
const PERSONAL_EMAIL_DOMAINS = new Set([
  'gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com', 'icloud.com',
  'aol.com', 'live.com', 'msn.com', 'qq.com', '163.com',
])

export function isPersonalEmailDomain(email: string): boolean {
  const domain = email.split('@')[1]?.toLowerCase().trim()
  return !!domain && PERSONAL_EMAIL_DOMAINS.has(domain)
}
