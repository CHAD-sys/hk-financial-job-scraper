// API base. Empty (VITE_API_URL="") → relative "/api" calls, which the Vite dev
// server proxies to the backend (see vite.config.ts). This lets a single tunnel
// on :5173 serve both the UI and the API (same origin, no CORS). Set VITE_API_URL
// to an absolute URL to point at a separately-hosted backend.
export const API = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

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
// attribution for Secret Market jobs (source_tier === 'social').
export interface LinkedInPostSignals {
  recruiter_name: string | null
  recruiter_profile_url: string | null
  // Harvested by hk_jobs/posts/email_harvest.py (LP-5) — null until that
  // module has run for this recruiter, or if no email was found.
  recruiter_email: string | null
  employer_hint: string | null
  engagement: { likes: number; comments: number } | null
  post_created_at: string | null
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

  p.set('sort', sort)
  p.set('page', String(page))
  p.set('page_size', String(pageSize))

  const res = await fetch(`${API}/api/jobs?${p}`)
  if (!res.ok) throw new Error(`Jobs fetch failed: ${res.status}`)
  return res.json()
}

export async function fetchJobDetail(source: string, sourceId: string): Promise<JobDetail> {
  const res = await fetch(`${API}/api/jobs/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}`)
  if (!res.ok) throw new Error(`Job detail fetch failed: ${res.status}`)
  return res.json()
}

export async function fetchFilters(): Promise<FiltersResponse> {
  const res = await fetch(`${API}/api/filters`)
  if (!res.ok) throw new Error(`Filters fetch failed: ${res.status}`)
  return res.json()
}

export async function fetchStats(): Promise<StatsResponse> {
  const res = await fetch(`${API}/api/stats`)
  if (!res.ok) throw new Error(`Stats fetch failed: ${res.status}`)
  return res.json()
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
  return n
}
