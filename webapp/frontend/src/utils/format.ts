export function formatSalary(
  min: number | null,
  max: number | null,
  period: 'month' | 'year' | null = 'month',
): string | null {
  const fmt = (n: number): string => {
    if (n >= 1_000_000) return `HK$${(n / 1_000_000).toFixed(1).replace(/\.0$/, '')}m`
    if (n >= 1_000) return `HK$${Math.round(n / 1_000)}k`
    return `HK$${n}`
  }
  const suffix = period === 'year' ? '/yr' : '/mo'
  if (min && max && min > 10_000) return `${fmt(min)} – ${fmt(max)}${suffix}`
  if (min && min > 10_000) return `${fmt(min)}+${suffix}`
  if (max && max > 10_000) return `up to ${fmt(max)}${suffix}`
  return null
}

/**
 * Format an AI-estimated MONTHLY base salary, e.g. "~HK$80k–120k/mo".
 * Visually marked with the leading "~" so it never reads as a disclosed figure.
 */
export function formatEstimatedSalary(min: number | null, max: number | null): string | null {
  const fmt = (n: number): string =>
    n >= 1_000 ? `HK$${Math.round(n / 1_000)}k` : `HK$${n}`
  if (min && max) return `~${fmt(min)}–${fmt(max)}/mo`
  if (min) return `~${fmt(min)}+/mo`
  if (max) return `~up to ${fmt(max)}/mo`
  return null
}

export function timeAgo(iso: string | null): string {
  if (!iso) return 'Unknown date'
  const diff = Date.now() - new Date(iso).getTime()
  const d = Math.floor(diff / 86_400_000)
  if (d === 0) return 'Today'
  if (d === 1) return 'Yesterday'
  if (d < 7) return `${d} days ago`
  if (d < 30) return `${Math.floor(d / 7)}w ago`
  if (d < 365) return `${Math.floor(d / 30)}mo ago`
  return `${Math.floor(d / 365)}y ago`
}

/**
 * The employer name to show for a Role.
 *
 * A Recruiter Post whose extractor found no named employer is stored with
 * `company = "Confidential via {recruiter}"` (hk_jobs/posts/promote.py,
 * decision #7). That puts the recruiter's name on the card through the one
 * route the UI does not control by declining to render a field — it arrives
 * inside a field the UI has every reason to render. Removing the "via
 * {recruiter}" chip, the mailto and the profile link and then printing the name
 * as the company would have been the whole change undone by one string.
 *
 * Only applied to `social`, and only splits on " via ", so an employer that
 * genuinely contains those words elsewhere is untouched.
 *
 * This is a display mask, not redaction: the name is still in `company` in the
 * API response. Taking it out at source means changing promote.py and
 * backfilling, which is a pipeline change, not a frontend one.
 */
export function displayCompany(company: string, sourceTier: string): string {
  if (sourceTier !== 'social') return company
  const via = company.search(/\s+via\s+/i)
  return via === -1 ? company : company.slice(0, via).trim()
}

export function monogram(company: string): string {
  const words = company.replace(/[^a-zA-Z\s]/g, '').trim().split(/\s+/)
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase()
  return company.slice(0, 2).toUpperCase()
}

export const SECTOR_COLOR: Record<string, { bg: string; text: string; border: string; accent: string }> = {
  'Investment Banking': {
    bg: '#EFF6FF',
    text: '#1E3A8A',
    border: '#BFDBFE',
    accent: '#1E3A8A',
  },
  Insurance: {
    bg: '#FBF0D3',
    text: '#9A6F00',
    border: '#F5DFA0',
    accent: '#9A6F00',
  },
  'Asset Management': {
    bg: '#F0FDFA',
    text: '#0F766E',
    border: '#99F6E4',
    accent: '#0F766E',
  },
  Banking: {
    bg: '#F8FAFC',
    text: '#475569',
    border: '#E2E8F0',
    accent: '#475569',
  },
  'Professional Services': {
    bg: '#F5F3FF',
    text: '#6D28D9',
    border: '#DDD6FE',
    accent: '#6D28D9',
  },
  'Digital Assets': {
    bg: '#ECFEFF',
    text: '#0E7490',
    border: '#A5F3FC',
    accent: '#0E7490',
  },
}

export const SENIORITY_COLOR: Record<string, { bg: string; text: string }> = {
  lead:      { bg: '#0B1628', text: '#FFFFFF' },
  senior:    { bg: '#1E3A8A', text: '#FFFFFF' },
  mid:       { bg: '#475569', text: '#FFFFFF' },
  junior:    { bg: '#FBF0D3', text: '#9A6F00' },
  associate: { bg: '#F1F5F9', text: '#475569' },
}

export function getSectorColor(sector: string) {
  return SECTOR_COLOR[sector] ?? SECTOR_COLOR['Banking']
}

export function getSeniorityColor(seniority: string | null) {
  if (!seniority) return null
  return SENIORITY_COLOR[seniority.toLowerCase()] ?? { bg: '#F1F5F9', text: '#475569' }
}

export function formatRemoteType(r: string | null): string {
  if (!r) return ''
  const map: Record<string, string> = {
    'on-site': 'On-site',
    hybrid: 'Hybrid',
    remote: 'Remote',
  }
  return map[r] ?? r
}

export function shortLocation(locations: string[]): string {
  if (!locations.length) return 'Hong Kong'
  const first = locations[0]
  // Trim to city-level: "Central, Hong Kong Island, Hong Kong" → "Central"
  return first.split(',')[0].trim()
}
