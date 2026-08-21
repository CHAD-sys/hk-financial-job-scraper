import { useCallback, useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { Loader2, RefreshCw } from 'lucide-react'
import Nav from '../components/Nav'
import { useAuth } from '../auth/useAuth'
import {
  DEFAULT_SALARY_AUDIT_FILTERS,
  fetchSalaryAuditEditors,
  fetchSalaryAuditJobs,
  type SalaryAuditFilters,
  type SalaryAuditResponse,
  type SalaryAuditRow,
  type SalaryEditor,
} from '../api/client'

const PAGE_SIZE = 50

const CONFIDENCE_OPTIONS = ['high', 'medium', 'low']

//: The 7 pricing function tiers hk_salary_anchors.json prices against — not
//: to be confused with source_tier (boutique/mainstream/social), which the
//: board's own tier tabs already filter by.
const SALARY_TIER_OPTIONS = [
  'front_office',
  'commercial_corporate_banking',
  'retail_banking',
  'middle_office',
  'back_office_operations',
  'corporate_finance_accounting',
  'insurance',
]

function fmtSalary(min: number | null, max: number | null): string {
  if (min == null && max == null) return '—'
  const f = (n: number) => `HK$${n.toLocaleString('en-US')}`
  if (min != null && max != null) return `${f(min)}–${f(max)}`
  return f((min ?? max) as number)
}

/**
 * ASF — Audit Salary Fixing.
 *
 * Ultimate-Admin-only (is_super_admin, not merely is_admin — see Nav.tsx's
 * primaryLinksFor). Opens on the whole catalogue, no search required, the
 * same "empty-search admin browse" the board already supports — plus a bank
 * of salary-specific filters /api/jobs has no reason to carry, layered on top
 * of the board's own global filters.
 */
export default function AsfPage() {
  const { seeker, loading } = useAuth()

  const [filters, setFilters] = useState<SalaryAuditFilters>(DEFAULT_SALARY_AUDIT_FILTERS)
  const [page, setPage] = useState(1)
  const [data, setData] = useState<SalaryAuditResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [editors, setEditors] = useState<SalaryEditor[]>([])

  const update = useCallback(<K extends keyof SalaryAuditFilters>(key: K, value: SalaryAuditFilters[K]) => {
    setPage(1)
    setFilters(prev => ({ ...prev, [key]: value }))
  }, [])

  const toggleInList = useCallback((key: 'confidence' | 'salary_tier_key', value: string) => {
    setPage(1)
    setFilters(prev => {
      const list = prev[key]
      const next = list.includes(value) ? list.filter(v => v !== value) : [...list, value]
      return { ...prev, [key]: next }
    })
  }, [])

  const load = useCallback(async () => {
    setBusy(true)
    setError(null)
    try {
      setData(await fetchSalaryAuditJobs(filters, 'newest', page, PAGE_SIZE))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load the salary audit.')
    } finally {
      setBusy(false)
    }
  }, [filters, page])

  useEffect(() => {
    if (loading || !seeker?.is_super_admin) return
    void load()
  }, [loading, seeker?.is_super_admin, load])

  useEffect(() => {
    if (loading || !seeker?.is_super_admin) return
    fetchSalaryAuditEditors().then(setEditors).catch(() => setEditors([]))
  }, [loading, seeker?.is_super_admin])

  if (!loading && !seeker?.is_super_admin) {
    return <Navigate to="/signin" state={{ from: '/asf' }} replace />
  }

  return (
    <div style={{ backgroundColor: 'var(--color-bg)', minHeight: '100dvh' }}>
      <Nav />
      <main className="mx-auto max-w-7xl px-4 pb-20 sm:px-6 lg:px-8" style={{ paddingTop: '2.5rem' }}>
        <header className="mb-6 flex flex-col gap-5 border-b pb-6 sm:flex-row sm:items-end sm:justify-between" style={{ borderColor: 'var(--color-border)' }}>
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em]" style={{ color: 'var(--color-gold)' }}>ASF</p>
            <h1 className="mt-1 text-3xl font-bold tracking-tight sm:text-4xl" style={{ fontFamily: 'var(--font-display)', color: 'var(--color-ink)' }}>
              Audit Salary Fixing
            </h1>
            <p className="mt-2 text-sm" style={{ color: 'var(--color-ink-muted)' }}>
              The whole catalogue, priced as an admin sees it — every posting, filterable by
              coordinate, confidence, and who last corrected it.
              {data && !busy && ` ${data.total.toLocaleString('en-US')} roles match the current filters.`}
            </p>
          </div>
          <button
            type="button"
            onClick={() => void load()}
            disabled={busy}
            className="inline-flex min-h-11 items-center justify-center gap-2 self-start rounded-md px-4 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-60 sm:self-auto"
            style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border-strong)', color: 'var(--color-ink)' }}
          >
            <RefreshCw size={15} className={busy ? 'animate-spin' : ''} aria-hidden="true" />
            {busy ? 'Loading…' : 'Refresh'}
          </button>
        </header>

        {/* ── Filters ─────────────────────────────────────────────────── */}
        <section
          className="mb-8 rounded-lg p-5"
          style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
        >
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <label className="flex flex-col gap-1 text-xs font-semibold" style={{ color: 'var(--color-ink-muted)' }}>
              Search
              <input
                type="text"
                value={filters.search}
                onChange={e => update('search', e.target.value)}
                placeholder="Title, company, skills…"
                className="min-h-9 rounded px-2 text-sm font-normal"
                style={{ border: '1px solid var(--color-border)', backgroundColor: 'var(--color-surface-2)', color: 'var(--color-ink)' }}
              />
            </label>

            <label className="flex flex-col gap-1 text-xs font-semibold" style={{ color: 'var(--color-ink-muted)' }}>
              Companies (comma-separated)
              <input
                type="text"
                value={filters.companies.join(', ')}
                onChange={e => update('companies', e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
                className="min-h-9 rounded px-2 text-sm font-normal"
                style={{ border: '1px solid var(--color-border)', backgroundColor: 'var(--color-surface-2)', color: 'var(--color-ink)' }}
              />
            </label>

            <label className="flex flex-col gap-1 text-xs font-semibold" style={{ color: 'var(--color-ink-muted)' }}>
              Seniority (comma-separated: junior, mid, senior, lead)
              <input
                type="text"
                value={filters.seniority.join(', ')}
                onChange={e => update('seniority', e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
                className="min-h-9 rounded px-2 text-sm font-normal"
                style={{ border: '1px solid var(--color-border)', backgroundColor: 'var(--color-surface-2)', color: 'var(--color-ink)' }}
              />
            </label>

            <label className="flex flex-col gap-1 text-xs font-semibold" style={{ color: 'var(--color-ink-muted)' }}>
              Salary min / max (HKD, monthly)
              <div className="flex gap-2">
                <input
                  type="number"
                  value={filters.salary_min ?? ''}
                  onChange={e => update('salary_min', e.target.value ? Number(e.target.value) : null)}
                  className="min-h-9 w-full rounded px-2 text-sm font-normal"
                  style={{ border: '1px solid var(--color-border)', backgroundColor: 'var(--color-surface-2)', color: 'var(--color-ink)' }}
                />
                <input
                  type="number"
                  value={filters.salary_max ?? ''}
                  onChange={e => update('salary_max', e.target.value ? Number(e.target.value) : null)}
                  className="min-h-9 w-full rounded px-2 text-sm font-normal"
                  style={{ border: '1px solid var(--color-border)', backgroundColor: 'var(--color-surface-2)', color: 'var(--color-ink)' }}
                />
              </div>
            </label>

            <label className="flex flex-col gap-1 text-xs font-semibold" style={{ color: 'var(--color-ink-muted)' }}>
              Edited by
              <select
                value={filters.edited_by ?? ''}
                onChange={e => update('edited_by', e.target.value || null)}
                className="min-h-9 rounded px-2 text-sm font-normal"
                style={{ border: '1px solid var(--color-border)', backgroundColor: 'var(--color-surface-2)', color: 'var(--color-ink)' }}
              >
                <option value="">Any admin</option>
                {editors.map(ed => (
                  <option key={ed.id} value={ed.id}>{ed.display_name || ed.email}</option>
                ))}
              </select>
            </label>

            <label className="flex flex-col gap-1 text-xs font-semibold" style={{ color: 'var(--color-ink-muted)' }}>
              Edited within N days
              <input
                type="number"
                min={1}
                value={filters.edited_within_days ?? ''}
                onChange={e => update('edited_within_days', e.target.value ? Number(e.target.value) : null)}
                className="min-h-9 rounded px-2 text-sm font-normal"
                style={{ border: '1px solid var(--color-border)', backgroundColor: 'var(--color-surface-2)', color: 'var(--color-ink)' }}
              />
            </label>
          </div>

          {/* Tri-state toggles: Any / Yes / No */}
          <div className="mt-4 flex flex-wrap gap-4">
            {([
              ['has_ai_estimate', 'Has AI estimate'],
              ['has_disclosed_salary', 'Has disclosed salary'],
              ['manually_edited', 'Manually pinned'],
              ['coordinate_resolved', 'Coordinate resolved'],
            ] as const).map(([key, label]) => (
              <div key={key} className="flex flex-col gap-1">
                <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--color-ink-faint)' }}>{label}</span>
                <div className="flex gap-1">
                  {([['Any', null], ['Yes', true], ['No', false]] as const).map(([lbl, val]) => (
                    <button
                      key={lbl}
                      type="button"
                      onClick={() => update(key, val)}
                      data-active={filters[key] === val}
                      className="rounded px-2 py-1 text-xs font-semibold"
                      style={{
                        backgroundColor: filters[key] === val ? 'var(--color-ink)' : 'var(--color-surface-2)',
                        color: filters[key] === val ? 'var(--color-ink-inverse)' : 'var(--color-ink-muted)',
                        border: '1px solid var(--color-border-strong)',
                      }}
                    >
                      {lbl}
                    </button>
                  ))}
                </div>
              </div>
            ))}

            <div className="flex flex-col gap-1">
              <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--color-ink-faint)' }}>Wide range (≥4× min)</span>
              <button
                type="button"
                onClick={() => update('wide_range_only', !filters.wide_range_only)}
                data-active={filters.wide_range_only}
                className="rounded px-2 py-1 text-xs font-semibold"
                style={{
                  backgroundColor: filters.wide_range_only ? 'var(--color-ink)' : 'var(--color-surface-2)',
                  color: filters.wide_range_only ? 'var(--color-ink-inverse)' : 'var(--color-ink-muted)',
                  border: '1px solid var(--color-border-strong)',
                }}
              >
                {filters.wide_range_only ? 'On' : 'Off'}
              </button>
            </div>
          </div>

          <div className="mt-4">
            <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--color-ink-faint)' }}>Confidence</span>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {CONFIDENCE_OPTIONS.map(c => (
                <button
                  key={c}
                  type="button"
                  onClick={() => toggleInList('confidence', c)}
                  data-active={filters.confidence.includes(c)}
                  className="rounded-full px-2.5 py-1 text-xs font-semibold capitalize"
                  style={{
                    backgroundColor: filters.confidence.includes(c) ? 'var(--color-ink)' : 'var(--color-surface-2)',
                    color: filters.confidence.includes(c) ? 'var(--color-ink-inverse)' : 'var(--color-ink-muted)',
                    border: '1px solid var(--color-border-strong)',
                  }}
                >
                  {c}
                </button>
              ))}
            </div>
          </div>

          <div className="mt-4">
            <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--color-ink-faint)' }}>Pricing tier</span>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {SALARY_TIER_OPTIONS.map(t => (
                <button
                  key={t}
                  type="button"
                  onClick={() => toggleInList('salary_tier_key', t)}
                  data-active={filters.salary_tier_key.includes(t)}
                  className="rounded-full px-2.5 py-1 text-xs font-semibold"
                  style={{
                    backgroundColor: filters.salary_tier_key.includes(t) ? 'var(--color-ink)' : 'var(--color-surface-2)',
                    color: filters.salary_tier_key.includes(t) ? 'var(--color-ink-inverse)' : 'var(--color-ink-muted)',
                    border: '1px solid var(--color-border-strong)',
                  }}
                >
                  {t.replace(/_/g, ' ')}
                </button>
              ))}
            </div>
          </div>

          <div className="mt-4 flex justify-end">
            <button
              type="button"
              onClick={() => { setPage(1); setFilters(DEFAULT_SALARY_AUDIT_FILTERS) }}
              className="text-xs font-semibold underline"
              style={{ color: 'var(--color-ink-muted)' }}
            >
              Clear all filters
            </button>
          </div>
        </section>

        {/* ── Results ─────────────────────────────────────────────────── */}
        {error && (
          <div className="mb-6 rounded-lg p-4 text-sm" style={{ backgroundColor: '#FEF2F2', border: '1px solid #FECACA', color: '#991B1B' }}>
            {error}
          </div>
        )}

        {busy && !data && (
          <div className="flex items-center gap-2 py-16 text-sm" style={{ color: 'var(--color-ink-muted)' }}>
            <Loader2 size={16} className="animate-spin" aria-hidden="true" /> Loading the catalogue…
          </div>
        )}

        {data && (
          <>
            <div className="overflow-x-auto rounded-lg" style={{ border: '1px solid var(--color-border)' }}>
              <table className="w-full min-w-[880px] text-left text-sm">
                <thead>
                  <tr style={{ backgroundColor: 'var(--color-surface-2)' }}>
                    {['Role', 'Coordinate', 'Salary', 'Confidence', 'Last correction'].map(h => (
                      <th key={h} className="px-3 py-2 text-xs font-bold uppercase tracking-wider" style={{ color: 'var(--color-ink-faint)' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.jobs.map((row: SalaryAuditRow) => (
                    <tr key={`${row.source}/${row.source_id}`} style={{ borderTop: '1px solid var(--color-border)' }}>
                      <td className="px-3 py-2 align-top">
                        <div className="font-semibold" style={{ color: 'var(--color-ink)' }}>{row.title}</div>
                        <div className="text-xs" style={{ color: 'var(--color-ink-muted)' }}>{row.company}</div>
                      </td>
                      <td className="px-3 py-2 align-top font-mono text-xs" style={{ color: 'var(--color-ink-muted)' }}>
                        {row.salary_grade
                          ? <>{row.salary_tier}<br />[{row.salary_role}]<br /><span style={{ color: 'var(--color-ink)' }}>{row.salary_grade}</span></>
                          : <span style={{ color: 'var(--color-ink-faint)' }}>no confident match</span>}
                      </td>
                      <td className="px-3 py-2 align-top font-mono text-sm" style={{ color: 'var(--color-ink)' }}>
                        {row.salary_hkd_min != null || row.salary_hkd_max != null
                          ? fmtSalary(row.salary_hkd_min, row.salary_hkd_max)
                          : fmtSalary(row.salary_estimated_min, row.salary_estimated_max)}
                      </td>
                      <td className="px-3 py-2 align-top text-xs capitalize" style={{ color: 'var(--color-ink-muted)' }}>
                        {row.salary_estimated_confidence ?? '—'}
                      </td>
                      <td className="px-3 py-2 align-top text-xs" style={{ color: 'var(--color-ink-muted)' }}>
                        {row.last_correction ? (
                          <>
                            <div style={{ color: 'var(--color-ink)' }}>{row.last_correction.admin_name}</div>
                            <div>{new Date(row.last_correction.corrected_at).toLocaleDateString()}</div>
                            <div className="font-mono">
                              {fmtSalary(row.last_correction.old_min, row.last_correction.old_max)}
                              {' → '}
                              {fmtSalary(row.last_correction.new_min, row.last_correction.new_max)}
                            </div>
                          </>
                        ) : '—'}
                      </td>
                    </tr>
                  ))}
                  {data.jobs.length === 0 && (
                    <tr>
                      <td colSpan={5} className="px-3 py-10 text-center text-sm" style={{ color: 'var(--color-ink-faint)' }}>
                        No roles match these filters.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            <div className="mt-4 flex items-center justify-between text-sm" style={{ color: 'var(--color-ink-muted)' }}>
              <span>
                Page {data.page} of {Math.max(data.total_pages, 1)} · {data.total.toLocaleString('en-US')} total
              </span>
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={page <= 1 || busy}
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  className="min-h-9 rounded px-3 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                  style={{ border: '1px solid var(--color-border-strong)' }}
                >
                  Previous
                </button>
                <button
                  type="button"
                  disabled={page >= data.total_pages || busy}
                  onClick={() => setPage(p => p + 1)}
                  className="min-h-9 rounded px-3 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                  style={{ border: '1px solid var(--color-border-strong)' }}
                >
                  Next
                </button>
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  )
}
