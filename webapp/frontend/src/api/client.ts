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
 * Called with the request path whenever the API answers 401.
 *
 * AuthProvider and EmployerAuthProvider each register a handler here so a dead
 * session clears the right signed-in state — a Set, not a single slot, because
 * two independent accounts (Seeker, Employer) can be signed in in one browser
 * at once (main.py: "a browser can hold a Seeker session and an Employer
 * session at the same time"), and a 401 from one must never clear the other.
 * The path is what lets each handler tell which account it was: Seeker
 * endpoints live under /api/auth and /api/me, Employer under /api/employer.
 *
 * Deliberately does NOT redirect: the board is public (docs/adr/0002), so
 * losing a session means browsing anonymously again, not being thrown out.
 */
const unauthorizedHandlers = new Set<(path: string) => void>()

export function addUnauthorizedHandler(fn: (path: string) => void): () => void {
  unauthorizedHandlers.add(fn)
  return () => unauthorizedHandlers.delete(fn)
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
  if (res.status === 401) unauthorizedHandlers.forEach(fn => fn(path))
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
  salary_period?: 'month' | 'year' | null
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
  /** Short-lived proof that an allowed discovery path returned this Role. */
  access_token?: string | null
}

export interface JobDetail extends Job {
  // No `description_clean`. The employer's own text is not published — the API
  // does not send it, so nothing here can render it. See the backend's
  // PUBLISHABLE_DESCRIPTION. The admin editor works on AdminJobRecord, which
  // does carry it, because editing the stored text is a different job.
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
  research_total: number
  tier_counts: Record<string, number>
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
  employer_count: number
  by_sector: Record<string, number>
  by_seniority: Record<string, number>
  by_remote_type: Record<string, number>
  by_source_tier: Record<string, number>
  top_skills: NameCount[]
  top_companies: NameCount[]
  internship_count: number
}

export interface LearningEvent {
  id: string
  title: string
  date: string
  start_at: string
  end_at: string | null
  venue: string
  online: boolean
  detail_url: string
  image_url: string | null
}

export interface LearningVideo {
  id: string
  title: string
  topic: string
  published_at: string
  watch_url: string
  thumbnail_url: string
}

export interface LearningContentResponse {
  schema_version: number
  available: boolean
  updated_at: string | null
  storage_bytes: number
  events: LearningEvent[]
  videos: LearningVideo[]
  sources: Record<string, {
    last_success_at: string | null
    last_attempt_at: string | null
    error: string | null
    count?: number
  }>
}

export interface RecommendedRole {
  job: Job
  score: number
  /** Plain-language evidence for this ranking, strongest signal first. */
  reasons: string[]
  /** Explicit choices already attached to this Role. */
  feedback: RecommendationFeedbackAction[]
}

export interface RecommendationsResponse {
  personalized: boolean
  personalization_enabled: boolean
  model_version: string
  signal_count: number
  saved_role_count: number
  activity_count: number
  eligible_count: number
  page: number
  page_size: number
  total_pages: number
  generated_at: string
  batch_id: string | null
  items: RecommendedRole[]
}

export type RecommendationFeedbackAction =
  | 'more_like'
  | 'not_interested'

export interface ResumeAnalysis {
  skills: string[]
  role_families: string[]
  sectors: string[]
  years_experience: number | null
  seniority: string | null
}

export interface ResumeDocument {
  filename: string
  media_type: string
  size_bytes: number
  uploaded_at: string
  analysis: ResumeAnalysis
}

export interface ResumeMatch {
  job: Job
  match_score: number
  reasons: string[]
}

export interface ResumeMatchesResponse {
  has_resume: boolean
  resume_uploaded_at: string | null
  model_version: string
  items: ResumeMatch[]
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

export async function fetchJobDetail(
  source: string,
  sourceId: string,
  accessToken: string | null | undefined,
): Promise<JobDetail> {
  const headers = accessToken ? { 'X-Role-Access': accessToken } : undefined
  const res = await apiFetch(
    `/api/jobs/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}`,
    { headers },
  )
  if (!res.ok) throw new Error(`Job detail fetch failed: ${res.status}`)
  return res.json()
}

export async function fetchFilters(search: string): Promise<FiltersResponse> {
  const params = new URLSearchParams({ search: search.trim() })
  const res = await apiFetch(`/api/filters?${params}`)
  if (!res.ok) throw new Error(`Filters fetch failed: ${res.status}`)
  return res.json()
}

export async function fetchStats(): Promise<StatsResponse> {
  const res = await apiFetch('/api/stats')
  if (!res.ok) throw new Error(`Stats fetch failed: ${res.status}`)
  return res.json()
}

export async function fetchLearningContent(): Promise<LearningContentResponse> {
  const res = await apiFetch('/api/learning')
  if (!res.ok) throw new Error(`Learning content fetch failed: ${res.status}`)
  return res.json()
}

/**
 * A small, explainable feed for a signed-in Seeker. The backend returns no
 * Roles until settled first-party evidence makes them relevant.
 */
export async function fetchRecommendations(
  page = 1,
  pageSize = 6,
): Promise<RecommendationsResponse> {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  const res = await apiFetch(`/api/recommendations?${params}`)
  if (!res.ok) {
    throw new ApiError(res.status, `Could not load recommended Roles (${res.status}).`)
  }
  return res.json()
}

/**
 * Persist one settled search/filter state for recommendation learning.
 * Callers debounce before invoking this; the server also coalesces an exact
 * refresh inside five minutes, so reloads do not masquerade as repeated intent.
 */
/**
 * Fire once per app load. Anonymous board-visit beacon (main.py's /api/visit) —
 * silently no-ops on failure since a missed beacon must never surface as a UI
 * error; it is a best-effort count, not something the Seeker is waiting on.
 * No-op server-side for a request that already carries a Seeker session.
 */
export async function recordVisit(): Promise<void> {
  try {
    await apiFetch('/api/visit', { method: 'POST' })
  } catch {
    // best-effort — see docstring
  }
}

export async function recordDiscovery(filters: JobFilters, resultCount: number): Promise<void> {
  const { search, ...structuredFilters } = filters
  const res = await apiFetch('/api/me/discovery', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      search_query: search.trim(),
      filters: structuredFilters,
      result_count: resultCount,
    }),
  })
  if (!res.ok) {
    throw new ApiError(res.status, `Could not remember this search (${res.status}).`)
  }
}

/** Attribute an opened card to the latest recommendation impression. */
export async function trackRecommendationClick(
  source: string,
  sourceId: string,
  accessToken?: string | null,
): Promise<void> {
  const path = `/api/me/recommendations/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}/click`
  const res = await apiFetch(path, {
    method: 'POST',
    headers: accessToken ? { 'X-Role-Access': accessToken } : undefined,
  })
  if (!res.ok) {
    throw new ApiError(res.status, `Could not record this recommendation (${res.status}).`)
  }
}

export async function submitRecommendationFeedback(
  source: string,
  sourceId: string,
  action: RecommendationFeedbackAction,
  accessToken?: string | null,
  detail?: string,
): Promise<void> {
  const path = `/api/me/recommendations/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}/feedback`
  const res = await apiFetch(path, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(accessToken ? { 'X-Role-Access': accessToken } : {}),
    },
    body: JSON.stringify({ action, ...(detail ? { detail } : {}) }),
  })
  if (!res.ok) {
    throw new ApiError(res.status, `Could not update this recommendation (${res.status}).`)
  }
}

export async function removeRecommendationFeedback(
  source: string,
  sourceId: string,
  action: RecommendationFeedbackAction,
): Promise<void> {
  const path = `/api/me/recommendations/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}/feedback/${encodeURIComponent(action)}`
  const res = await apiFetch(path, { method: 'DELETE' })
  if (!res.ok) {
    throw new ApiError(res.status, `Could not undo this recommendation choice (${res.status}).`)
  }
}

export async function fetchResume(): Promise<ResumeDocument | null> {
  const res = await apiFetch('/api/me/resume')
  if (!res.ok) {
    throw await authError(res, `Could not load your resume (${res.status}).`)
  }
  return res.json()
}

export async function uploadResume(file: File): Promise<ResumeDocument> {
  const body = new FormData()
  body.append('resume', file)
  const res = await apiFetch('/api/me/resume', { method: 'PUT', body })
  if (!res.ok) {
    throw await authError(res, `Could not analyse your resume (${res.status}).`)
  }
  return res.json()
}

export async function deleteResume(): Promise<void> {
  const res = await apiFetch('/api/me/resume', { method: 'DELETE' })
  if (!res.ok) {
    throw await authError(res, `Could not remove your resume (${res.status}).`)
  }
}

export async function fetchResumeMatches(limit = 3): Promise<ResumeMatchesResponse> {
  const params = new URLSearchParams({ limit: String(limit) })
  const res = await apiFetch(`/api/me/resume-matches?${params}`)
  if (!res.ok) {
    throw await authError(res, `Could not load resume matches (${res.status}).`)
  }
  return res.json()
}

// ── Write endpoints ───────────────────────────────────────────────────────────
// Public Role submissions are moderated by the backend and cannot be read back.

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
  /** Admin Mode. Same account, same sign-in — this is the one privilege bit. */
  is_admin: boolean
  /** Ultimate Admin only: direct read/write onto a job's row and enrichment. */
  is_super_admin: boolean
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
/** Seeker-only — no Employer equivalent (docs/adr/0003, PLAN_ACCOUNTS.md §6). */
export const LINKEDIN_SIGN_IN_PATH = `${API}/api/auth/linkedin`

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

export async function saveRole(
  source: string,
  sourceId: string,
  accessToken: string | null | undefined,
): Promise<void> {
  if (!accessToken) throw new ApiError(403, 'This Role must come from an active research result.')
  const res = await apiFetch('/api/me/saved', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source, source_id: sourceId, access_token: accessToken }),
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
  roles: { source: string; source_id: string; access_token: string }[],
): Promise<{
  merged: number
  submitted: number
  accepted: { source: string; source_id: string }[]
}> {
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

// ── Admin Mode ─────────────────────────────────────────────────────────────────
// Every call below only ever succeeds for a Seeker whose `is_admin` bit is set
// (webapp/backend/main.py's `_require_admin`) — an ordinary Seeker gets 403, an
// anonymous caller gets 401. AdminPage is the only thing that calls these.

export interface AdminSubmission {
  id: string
  status: 'pending' | 'approved' | 'rejected'
  contact_name: string
  contact_email: string
  company: string
  title: string
  location: string
  employment_type: string
  salary_range: string
  description: string
  apply_url: string
  received_at: string
  decided_at?: string
  reason?: string
  source_id?: string
}

export async function fetchAdminSubmissions(
  status: 'pending' | 'approved' | 'rejected' | 'all' = 'pending',
): Promise<AdminSubmission[]> {
  const res = await apiFetch(`/api/admin/submissions?status=${status}`)
  if (!res.ok) throw new ApiError(res.status, `Could not load submissions (${res.status}).`)
  return res.json()
}

export async function approveSubmission(id: string): Promise<AdminSubmission> {
  const res = await apiFetch(`/api/admin/submissions/${encodeURIComponent(id)}/approve`, {
    method: 'POST',
  })
  if (!res.ok) throw new ApiError(res.status, await readDetail(res) || `Could not approve (${res.status}).`)
  return res.json()
}

export async function rejectSubmission(id: string, reason: string): Promise<AdminSubmission> {
  const res = await apiFetch(`/api/admin/submissions/${encodeURIComponent(id)}/reject`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  })
  if (!res.ok) throw new ApiError(res.status, await readDetail(res) || `Could not reject (${res.status}).`)
  return res.json()
}

export interface AdminRunToday {
  tracking_available: boolean
  date: string
  ran_today: boolean
  snapshot_received_at: string | null
  companies_scraped_today: number
  companies_zero_today: number
  zero_companies: string[]
  jobs_added_today: number
  jobs_removed_today: number
  listings_collected_today: number
  active_jobs: number
  companies_active: number
  description_coverage_pct: number
  enrichment_coverage_pct: number
  log: {
    available: boolean
    last_run_found?: boolean
    finished?: boolean
    crashed?: boolean
    last_phase?: string | null
    phases_seen?: string[]
  }
}

export interface AdminRunHistoryPoint {
  scraped_date: string
  total_jobs: number
  companies_scraped: number
  companies_down: number
}

export type AdminOperationalStatus = 'success' | 'warning' | 'failed' | 'running' | 'skipped' | 'not_recorded'

export interface AdminOperationsDashboard {
  generated_at: string
  run: {
    run_id?: string
    scraped_date?: string
    source_run_url?: string | null
    status?: AdminOperationalStatus
    started_at?: string | null
    finished_at?: string | null
    restore_source?: string | null
    phases: {
      key: string
      label: string
      status: AdminOperationalStatus
      duration_seconds: number | null
      detail?: string | null
    }[]
  }
  quality_gates: {
    key: string
    label: string
    value: number
    unit: string
    status: 'pass' | 'warning'
    detail: string
  }[]
  // source_health, ai_cost, publication and recommendations are all
  // Ultimate-Admin-only (require_super_admin). null for the other four admins
  // — the backend never serialises these fields for them, so absence here is
  // an authorization outcome, not a "not tracked yet" state (see
  // tracking_available inside each object for that).
  source_health: {
    source: string
    companies: number | null
    successful: number | null
    zero_results: number | null
    failed: number | null
    roles: number
    runtime_seconds: number | null
    /** Share of this source's companies whose run ERRORED. Drives the badge. */
    failure_rate_pct: number | null
    /** Share that found at least one Role. Informational: a quiet employer is
     *  not a fault, so this never decides the badge. */
    hiring_rate_pct: number | null
    status: 'healthy' | 'warning' | 'failed' | 'not_recorded'
    tracking_available: boolean
    roles_found: number | null
    active_roles: number | null
  }[] | null
  ai_cost: {
    calls: number
    roles_processed: number
    estimated_cost_usd: number
    cache_hit_tokens: number
    cache_miss_tokens: number
    completion_tokens: number
    backlog: number
    daily_limit: number
    tracking_available: boolean
  } | null
  publication: {
    source_run_id: string
    snapshot_sha256: string
    source_run_url: string | null
    received_at: string
    active_jobs: number
    restore_source?: string | null
    restore_sha256?: string | null
  } | null
  recommendations: {
    impressions: number
    clicks: number
    click_through_pct: number
    saves: number
    more_like: number
    dismissals: number
    wrong_reason: number
    seekers_reached: number
    eligible_seekers: number
    coverage_pct: number
    tracking_available: boolean
    window_started_at: string | null
    window_ended_at: string | null
  } | null
  alerts: { severity: 'critical' | 'warning'; title: string; detail: string }[]
}

export interface AdminAnalyticsOverview {
  total_board_roles: number
  total_active_rows: number
  cross_posting_rate_pct: number
  duplicate_rows_suppressed: number
  by_source: Record<string, number>
  by_board_source: Record<string, number>
  by_sector: Record<string, number>
  by_seniority: Record<string, number>
  by_remote_type: Record<string, number>
  top_companies: { name: string; count: number }[]
  company_concentration_hhi: number
  company_concentration_label: 'unconcentrated' | 'moderately concentrated' | 'concentrated'
  company_entity_count: number
  top5_company_share_pct: number
  salary_distribution: Record<string, number>
  salary_confidence: Record<string, number>
  salary_median_hkd: number
  salary_p25_hkd: number
  salary_p75_hkd: number
  salary_sample_size: number
  sector_salary: {
    name: string
    median_hkd: number
    p25_hkd: number
    p75_hkd: number
    sample_size: number
  }[]
  top_skills: { name: string; count: number; share_pct: number }[]
  dominant_sector: { name: string; count: number; share_pct: number }
  remote_friendly_pct: number
  data_quality: {
    description_coverage_pct: number
    enrichment_coverage_pct: number
    salary_coverage_pct: number
    high_confidence_salary_pct: number
    skills_coverage_pct: number
    seniority_coverage_pct: number
    workplace_coverage_pct: number
  }
  market_movers: {
    current_date: string | null
    comparison_date: string | null
    gainers: AdminMarketMover[]
    decliners: AdminMarketMover[]
  }
}

export interface AdminMarketMover {
  name: string
  current: number
  previous: number
  change: number
  change_pct: number | null
}

export interface AdminUserActivityPoint {
  date: string
  new_signups: number
  active_seekers: number
  returning_seekers: number
}

export interface AdminAnonymousVisitPoint {
  date: string
  unique_visitors: number
  returning_visitors: number
}

// Two independent, non-overlapping populations — never sum them into one
// "visitors" figure. `anonymous` covers requests with no Seeker session (a
// hashed, non-identifying visitor cookie set by /api/visit); the top-level
// fields cover Seeker accounts via `sessions`, issued on every sign-in path
// (register, login, password-reset re-login, Google/LinkedIn).
export interface AdminUserActivity {
  days: number
  window_started_on: string | null
  window_ended_on: string | null
  total_seekers: number
  new_signups: number
  active_seekers: number
  returning_seekers: number
  repeat_visit_rate_pct: number
  points: AdminUserActivityPoint[]
  tracking_available: boolean
  anonymous: {
    unique_visitors: number
    returning_visitors: number
    repeat_visit_rate_pct: number
    points: AdminAnonymousVisitPoint[]
  }
}

export interface AdminIntelligenceSnapshot {
  schema_version: 1
  generated_at: string
  operating_date: string
  availability: {
    catalogue: boolean
    history: boolean
    daily_run: boolean
    source_health: boolean
    ai_usage: boolean
    publication: boolean
    recommendations: boolean
  }
  today: AdminRunToday
  history: {
    days: number
    tracking_available: boolean
    points: AdminRunHistoryPoint[]
  }
  operations: AdminOperationsDashboard
  analytics: AdminAnalyticsOverview
  user_activity: AdminUserActivity
}

export async function fetchAdminIntelligence(days = 30): Promise<AdminIntelligenceSnapshot> {
  const res = await apiFetch(`/api/admin/intelligence?days=${days}`)
  if (!res.ok) throw new ApiError(res.status, `Could not load admin intelligence (${res.status}).`)
  return res.json()
}

// ── Ultimate Admin: account directory ──────────────────────────────────────────
// Read-only, behind is_super_admin only (require_super_admin) — the whole route
// is gated, not just individual fields. password_hash is never on the wire: the
// backend query never selects it in the first place (seekers_store.list_accounts).

export interface AdminSeekerAccount {
  id: string
  email: string
  display_name: string | null
  username: string | null
  email_verified: boolean
  is_admin: boolean
  is_super_admin: boolean
  created_at: string
  last_login_at: string | null
  /** Whether this Seeker has a resume on file — decides if a row offers a download. */
  has_resume: boolean
}

export interface AdminEmployerAccount {
  id: string
  email: string
  company_name: string
  contact_name: string | null
  email_verified: boolean
  created_at: string
  last_login_at: string | null
}

export interface AdminAccountsResponse {
  seekers: AdminSeekerAccount[]
  employers: AdminEmployerAccount[]
}

/**
 * Fetch a Seeker's resume file and hand it to the browser as a download.
 *
 * A fetch + object URL rather than a plain `<a href download>`: the link would
 * be simpler, but this endpoint can answer 403 (not Ultimate Admin) or 404 (no
 * resume), and a bare anchor navigates the tab to the error JSON instead of
 * surfacing it. Going through apiFetch keeps `credentials: 'include'` and lets
 * the caller show the failure in place.
 *
 * `reason` is optional and free text; it is stored on the audit row the backend
 * writes before it serves a single byte (see admin.py).
 */
export async function downloadSeekerResume(seekerId: string, reason = ''): Promise<void> {
  const query = reason.trim() ? `?reason=${encodeURIComponent(reason.trim())}` : ''
  const res = await apiFetch(`/api/admin/accounts/seekers/${encodeURIComponent(seekerId)}/resume${query}`)
  if (!res.ok) throw new ApiError(res.status, await readDetail(res) || `Could not download the resume (${res.status}).`)

  // Filename comes from the server's Content-Disposition so the saved file
  // matches what the Seeker actually uploaded, not a name invented here.
  const disposition = res.headers.get('content-disposition') ?? ''
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  const plain = /filename="([^"]*)"/i.exec(disposition)
  const filename = utf8 ? decodeURIComponent(utf8[1]) : (plain?.[1] || 'resume.pdf')

  const url = URL.createObjectURL(await res.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  // Revoked on the next tick, not immediately: Safari cancels an in-flight
  // download if the object URL disappears in the same frame as the click.
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

export async function fetchAdminAccounts(): Promise<AdminAccountsResponse> {
  const res = await apiFetch('/api/admin/accounts')
  if (!res.ok) throw new ApiError(res.status, `Could not load the account directory (${res.status}).`)
  return res.json()
}

// Fetched lazily per row, never bundled into fetchAdminAccounts — see
// admin.py's get_seeker_interests_route docstring for why.
export interface AdminSeekerInterests {
  resume_skills: string[]
  resume_role_families: string[]
  resume_sectors: string[]
  resume_seniority: string | null
  searched_sectors: string[]
  searched_skills: string[]
  searched_seniority: string[]
  recent_search_terms: string[]
  saved_roles_count: number
}

export async function fetchSeekerInterests(seekerId: string): Promise<AdminSeekerInterests> {
  const res = await apiFetch(`/api/admin/accounts/seekers/${encodeURIComponent(seekerId)}/interests`)
  if (!res.ok) throw new ApiError(res.status, `Could not load this Seeker's interests (${res.status}).`)
  return res.json()
}

// ── Ultimate Admin: direct job edit ────────────────────────────────────────────
// Behind is_super_admin only — the other four admins never call these. The
// wire shape mirrors webapp/backend/job_edit.py's raw dict(row) exactly: it is
// not the same Job shape /api/jobs returns (e.g. `locations`/`required_skills`
// arrive as a raw JSON string here, not a parsed array — the backend never
// parses them on the read side, only on write).

export interface AdminJobRecord {
  source: string
  source_id: string
  company: string
  title: string
  description_clean: string
  description_raw: string
  locations: string // JSON-encoded array
  employment_type: string
  apply_url: string
  is_active: number
  source_tier: string
  category: string | null
  seniority: string | null
  remote_type: string | null
  salary_min: number | null
  salary_max: number | null
  salary_currency: string | null
  // job_enrichments (aliased e_seniority/e_remote_type to avoid colliding with
  // the jobs.* columns above — see job_edit.py's _ENRICHMENT_ALIASES)
  e_seniority: string | null
  e_remote_type: string | null
  required_skills: string | null // JSON-encoded array
  salary_hkd_min: number | null
  salary_hkd_max: number | null
  job_category: string | null
  salary_estimated_min: number | null
  salary_estimated_max: number | null
  salary_estimated_confidence: string | null
  years_experience_required: number | null
  description_summary: string | null
  title_en: string | null
  manually_edited_at: string | null
}

export async function fetchAdminJob(source: string, sourceId: string): Promise<AdminJobRecord> {
  const res = await apiFetch(
    `/api/admin/jobs/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}`,
  )
  if (res.status === 404) throw new ApiError(404, 'That job could not be found.')
  if (!res.ok) throw new ApiError(res.status, `Could not load that job (${res.status}).`)
  return res.json()
}

export async function patchAdminJob(
  source: string,
  sourceId: string,
  changes: { job?: Record<string, unknown>; enrichment?: Record<string, unknown> },
): Promise<AdminJobRecord> {
  const res = await apiFetch(
    `/api/admin/jobs/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(changes),
    },
  )
  if (!res.ok) {
    throw new ApiError(res.status, await readDetail(res) || `Could not save that job (${res.status}).`)
  }
  return res.json()
}

// ── URL serialisation ─────────────────────────────────────────────────────────

export function filtersToSearchParams(
  filters: JobFilters,
  sort: string,
  page: number,
): URLSearchParams {
  const p = new URLSearchParams()
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
  return {
    filters: {
      // Source tiers are an internal attribution detail, not a public browsing
      // mode. Old shared URLs carrying `?tier=` deliberately collapse into the
      // same all-source research stream.
      tier: 'all',
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
