import { Search, X, SlidersHorizontal, ChevronDown } from 'lucide-react'
import { useState } from 'react'
import type { ReactNode } from 'react'
import type { JobFilters, FiltersResponse } from '../api/client'
import MultiSelect from './MultiSelect'

interface Props {
  filters: JobFilters
  filterData: FiltersResponse | null
  activeCount: number
  onUpdate: (patch: Partial<JobFilters>) => void
  onClear: () => void
}

const SECTORS = ['Banking', 'Insurance', 'Asset Management', 'Investment Banking', 'Professional Services', 'Digital Assets']

export default function FilterBar({ filters, filterData, activeCount, onUpdate, onClear }: Props) {
  const [showAllFilters, setShowAllFilters] = useState(false)

  const toggleSector = (s: string) => {
    const next = filters.sectors.includes(s)
      ? filters.sectors.filter(x => x !== s)
      : [...filters.sectors, s]
    onUpdate({ sectors: next })
  }

  const togglePill = (key: 'seniority' | 'remote_type', val: string) => {
    const cur = filters[key] as string[]
    const next = cur.includes(val) ? cur.filter(x => x !== val) : [...cur, val]
    onUpdate({ [key]: next })
  }

  const seniority_levels = filterData?.seniority_levels ?? []
  const remote_types = filterData?.remote_types ?? []

  // Build NameCount arrays for MultiSelect
  const companyOptions = filterData?.companies ?? []
  const skillOptions = filterData?.skills ?? []

  const activeChips: { label: string; remove: () => void }[] = [
    ...filters.sectors.map(s => ({
      label: s,
      remove: () => onUpdate({ sectors: filters.sectors.filter(x => x !== s) }),
    })),
    ...filters.companies.map(c => ({
      label: c,
      remove: () => onUpdate({ companies: filters.companies.filter(x => x !== c) }),
    })),
    ...filters.seniority.map(s => ({
      label: s,
      remove: () => onUpdate({ seniority: filters.seniority.filter(x => x !== s) }),
    })),
    ...filters.remote_type.map(r => ({
      label: r === 'on-site' ? 'On-site' : r.charAt(0).toUpperCase() + r.slice(1),
      remove: () => onUpdate({ remote_type: filters.remote_type.filter(x => x !== r) }),
    })),
    ...filters.skills.map(s => ({
      label: s,
      remove: () => onUpdate({ skills: filters.skills.filter(x => x !== s) }),
    })),
    ...(filters.is_internship ? [{ label: 'Internships', remove: () => onUpdate({ is_internship: null }) }] : []),
    ...(filters.salary_disclosed_only ? [{ label: 'Salary disclosed', remove: () => onUpdate({ salary_disclosed_only: false, salary_min: null, salary_max: null }) }] : []),
    ...(filters.exp_min !== null || filters.exp_max !== null
      ? [{
          label: `Exp: ${filters.exp_min ?? 0}–${filters.exp_max ?? '∞'} yrs`,
          remove: () => onUpdate({ exp_min: null, exp_max: null }),
        }]
      : []),
  ]

  return (
    <div
      className="sticky z-30 w-full"
      style={{
        top: '64px',
        backgroundColor: 'var(--color-surface)',
        borderBottom: '1px solid var(--color-border)',
        boxShadow: '0 2px 8px -2px rgb(0 0 0 / 0.06)',
      }}
    >
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">

        {/* Row 1: Search + More-filters toggle + clear */}
        <div className="flex items-center gap-3 py-3.5">
          {/* Search */}
          <div className="relative flex-1 max-w-md">
            <Search
              size={15}
              className="absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none"
              style={{ color: 'var(--color-ink-faint)' }}
            />
            <input
              type="search"
              value={filters.search}
              onChange={e => onUpdate({ search: e.target.value })}
              placeholder="Search roles, companies…"
              className="w-full rounded-md pl-9 pr-3 py-2 text-sm outline-none transition-all duration-150"
              style={{
                backgroundColor: 'var(--color-surface-2)',
                border: '1px solid var(--color-border-strong)',
                color: 'var(--color-ink)',
              }}
              onFocus={e => {
                e.currentTarget.style.borderColor = 'var(--color-ring)'
                e.currentTarget.style.boxShadow = '0 0 0 3px rgba(30,58,138,0.12)'
                e.currentTarget.style.backgroundColor = 'var(--color-surface)'
              }}
              onBlur={e => {
                e.currentTarget.style.borderColor = 'var(--color-border-strong)'
                e.currentTarget.style.boxShadow = 'none'
                e.currentTarget.style.backgroundColor = 'var(--color-surface-2)'
              }}
            />
          </div>

          {/* More-filters toggle (all viewports) */}
          <button
            onClick={() => setShowAllFilters(o => !o)}
            data-active={showAllFilters || activeCount > 0}
            aria-expanded={showAllFilters}
            className="filter-pill flex items-center gap-1.5 rounded-md px-3.5 py-2 text-xs font-semibold cursor-pointer outline-none whitespace-nowrap"
            style={{
              border: `1px solid ${showAllFilters || activeCount > 0 ? 'var(--color-ink)' : 'var(--color-border-strong)'}`,
              backgroundColor: showAllFilters || activeCount > 0 ? 'var(--color-ink)' : 'var(--color-surface-2)',
              color: showAllFilters || activeCount > 0 ? 'var(--color-ink-inverse)' : 'var(--color-ink-muted)',
              boxShadow: showAllFilters || activeCount > 0 ? 'var(--shadow-card)' : 'none',
            }}
          >
            <SlidersHorizontal size={14} />
            <span className="hidden sm:inline">{showAllFilters ? 'Hide filters' : 'More filters'}</span>
            <span className="sm:hidden">Filters</span>
            {activeCount > 0 && (
              <span
                className="flex h-4 min-w-4 px-1 items-center justify-center rounded-full text-[10px] font-bold"
                style={{ backgroundColor: 'var(--color-gold-star)', color: 'var(--color-nav)' }}
              >
                {activeCount}
              </span>
            )}
            <ChevronDown
              size={14}
              style={{ transform: showAllFilters ? 'rotate(180deg)' : 'none', transition: 'transform 150ms' }}
            />
          </button>

          {/* Right-side clear */}
          {activeCount > 0 && (
            <button
              onClick={onClear}
              className="hidden md:flex items-center gap-1.5 text-xs font-medium transition-colors duration-150 cursor-pointer"
              style={{ color: 'var(--color-ink-muted)' }}
              onMouseEnter={e => ((e.currentTarget as HTMLButtonElement).style.color = 'var(--color-ink)')}
              onMouseLeave={e => ((e.currentTarget as HTMLButtonElement).style.color = 'var(--color-ink-muted)')}
            >
              <X size={13} />
              Clear all ({activeCount})
            </button>
          )}
        </div>

        {/* Row 2: Primary sector filter — always visible */}
        <div className="pb-3.5">
          <FilterRow label="Sector">
            {SECTORS.map(s => {
              const active = filters.sectors.includes(s)
              return (
                <button
                  key={s}
                  onClick={() => toggleSector(s)}
                  data-active={active}
                  aria-pressed={active}
                  className="filter-pill rounded-md px-3 py-1.5 text-xs font-semibold cursor-pointer outline-none"
                  style={{
                    backgroundColor: active ? 'var(--color-ink)' : 'var(--color-surface-2)',
                    color: active ? 'var(--color-ink-inverse)' : 'var(--color-ink-muted)',
                    border: `1px solid ${active ? 'var(--color-ink)' : 'var(--color-border-strong)'}`,
                    boxShadow: active ? 'var(--shadow-card)' : 'none',
                  }}
                >
                  {s}
                </button>
              )
            })}
          </FilterRow>
        </div>

        {/* Advanced filters — collapsed by default so the bar stays calm */}
        {showAllFilters && (
          <div
            className="flex flex-col gap-4 pt-4 pb-4"
            style={{ borderTop: '1px dashed var(--color-border-strong)' }}
          >
            {/* Level */}
            {seniority_levels.length > 0 && (
              <FilterRow label="Level">
                {seniority_levels.map(s => {
                  const active = filters.seniority.includes(s)
                  return (
                    <button
                      key={s}
                      onClick={() => togglePill('seniority', s)}
                      data-active={active}
                      aria-pressed={active}
                      className="filter-pill rounded-md px-3 py-1.5 text-xs font-semibold capitalize cursor-pointer outline-none"
                      style={{
                        backgroundColor: active ? 'var(--color-blue)' : 'var(--color-surface-2)',
                        color: active ? '#fff' : 'var(--color-ink-muted)',
                        border: `1px solid ${active ? 'var(--color-blue)' : 'var(--color-border-strong)'}`,
                        boxShadow: active ? 'var(--shadow-card)' : 'none',
                      }}
                    >
                      {s}
                    </button>
                  )
                })}
              </FilterRow>
            )}

            {/* Work type */}
            {remote_types.length > 0 && (
              <FilterRow label="Work">
                {remote_types.map(r => {
                  const active = filters.remote_type.includes(r)
                  const label = r === 'on-site' ? 'On-site' : r.charAt(0).toUpperCase() + r.slice(1)
                  return (
                    <button
                      key={r}
                      onClick={() => togglePill('remote_type', r)}
                      data-active={active}
                      aria-pressed={active}
                      className="filter-pill rounded-md px-3 py-1.5 text-xs font-semibold cursor-pointer outline-none"
                      style={{
                        backgroundColor: active ? 'var(--color-blue)' : 'var(--color-surface-2)',
                        color: active ? '#fff' : 'var(--color-ink-muted)',
                        border: `1px solid ${active ? 'var(--color-blue)' : 'var(--color-border-strong)'}`,
                        boxShadow: active ? 'var(--shadow-card)' : 'none',
                      }}
                    >
                      {label}
                    </button>
                  )
                })}
              </FilterRow>
            )}

            {/* Type */}
            <FilterRow label="Type">
              <button
                onClick={() => onUpdate({ is_internship: filters.is_internship ? null : true })}
                data-active={!!filters.is_internship}
                aria-pressed={!!filters.is_internship}
                className="filter-pill rounded-md px-3 py-1.5 text-xs font-semibold cursor-pointer outline-none"
                style={{
                  backgroundColor: filters.is_internship ? '#FEF3C7' : 'var(--color-surface-2)',
                  color: filters.is_internship ? '#854D0E' : 'var(--color-ink-muted)',
                  border: `1px solid ${filters.is_internship ? '#F5C451' : 'var(--color-border-strong)'}`,
                  boxShadow: filters.is_internship ? 'var(--shadow-card)' : 'none',
                }}
              >
                Internships
              </button>
            </FilterRow>

            {/* Refine — company / skills / salary / experience */}
            <FilterRow label="Refine">
              <MultiSelect
                label="Company"
                options={companyOptions}
                selected={filters.companies}
                onChange={v => onUpdate({ companies: v })}
              />
              <MultiSelect
                label="Skills"
                options={skillOptions}
                selected={filters.skills}
                onChange={v => onUpdate({ skills: v })}
              />
              <SalaryToggle filters={filters} onUpdate={onUpdate} />
              <ExpFilter filters={filters} onUpdate={onUpdate} />
            </FilterRow>

            {/* Mobile clear */}
            {activeCount > 0 && (
              <button
                onClick={() => { onClear(); setShowAllFilters(false) }}
                className="md:hidden flex items-center gap-1 text-xs font-semibold cursor-pointer self-start"
                style={{ color: 'var(--color-gold)' }}
              >
                <X size={12} /> Clear all filters
              </button>
            )}
          </div>
        )}

        {/* Row 3: Active filter chips */}
        {activeChips.length > 0 && (
          <div className="flex flex-wrap gap-2 pb-3">
            {activeChips.map(chip => (
              <span
                key={chip.label}
                className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium"
                style={{
                  backgroundColor: 'var(--color-gold-light)',
                  color: 'var(--color-gold)',
                  border: '1px solid var(--color-gold)',
                }}
              >
                {chip.label}
                <button
                  onClick={chip.remove}
                  className="cursor-pointer flex-shrink-0"
                  aria-label={`Remove ${chip.label} filter`}
                >
                  <X size={11} strokeWidth={2.5} />
                </button>
              </span>
            ))}
            <button
              onClick={onClear}
              className="text-xs font-medium cursor-pointer transition-colors duration-150"
              style={{ color: 'var(--color-ink-faint)' }}
              onMouseEnter={e => ((e.currentTarget as HTMLButtonElement).style.color = 'var(--color-ink-muted)')}
              onMouseLeave={e => ((e.currentTarget as HTMLButtonElement).style.color = 'var(--color-ink-faint)')}
            >
              Clear all
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Labeled filter row ────────────────────────────────────────────────────────

function FilterRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-start gap-1.5 sm:gap-3">
      <span
        className="flex-shrink-0 sm:w-16 sm:pt-1.5 text-[10px] font-bold uppercase tracking-wider select-none"
        style={{ color: 'var(--color-ink-faint)', letterSpacing: '0.08em' }}
      >
        {label}
      </span>
      <div className="flex flex-wrap items-center gap-2">{children}</div>
    </div>
  )
}

// ── Salary sub-component ──────────────────────────────────────────────────────

function SalaryToggle({
  filters,
  onUpdate,
}: {
  filters: JobFilters
  onUpdate: (p: Partial<JobFilters>) => void
}) {
  const [open, setOpen] = useState(false)
  const isActive = filters.salary_disclosed_only || filters.salary_min !== null || filters.salary_max !== null

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        data-active={isActive}
        className="filter-pill rounded-md px-3 py-1.5 text-xs font-semibold cursor-pointer flex items-center gap-1.5 outline-none"
        style={{
          backgroundColor: isActive ? 'var(--color-ink)' : 'var(--color-surface-2)',
          color: isActive ? 'var(--color-ink-inverse)' : 'var(--color-ink-muted)',
          border: `1px solid ${isActive ? 'var(--color-ink)' : 'var(--color-border-strong)'}`,
          boxShadow: isActive ? 'var(--shadow-card)' : 'none',
        }}
        aria-expanded={open}
      >
        Salary
        {isActive && <span style={{ color: 'var(--color-gold-star)' }}>·</span>}
      </button>

      {open && (
        <div
          className="absolute left-0 top-full mt-1 z-40 rounded-lg p-4 flex flex-col gap-3"
          style={{
            minWidth: '240px',
            backgroundColor: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
            boxShadow: 'var(--shadow-float)',
          }}
        >
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={filters.salary_disclosed_only}
              onChange={e =>
                onUpdate({
                  salary_disclosed_only: e.target.checked,
                  salary_min: e.target.checked ? null : null,
                  salary_max: null,
                })
              }
              className="cursor-pointer"
              style={{ accentColor: 'var(--color-blue)' }}
            />
            <span className="text-sm" style={{ color: 'var(--color-ink)' }}>
              Salary disclosed only
            </span>
          </label>

          {filters.salary_disclosed_only && (
            <div className="flex flex-col gap-2">
              <p className="text-xs" style={{ color: 'var(--color-ink-faint)' }}>
                Annual HKD range (optional)
              </p>
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  placeholder="Min"
                  value={filters.salary_min ?? ''}
                  onChange={e =>
                    onUpdate({ salary_min: e.target.value ? Number(e.target.value) : null })
                  }
                  className="w-full rounded px-2 py-1.5 text-sm outline-none"
                  style={{
                    border: '1px solid var(--color-border)',
                    color: 'var(--color-ink)',
                    backgroundColor: 'var(--color-surface-2)',
                  }}
                  onFocus={e => (e.currentTarget.style.borderColor = 'var(--color-ring)')}
                  onBlur={e => (e.currentTarget.style.borderColor = 'var(--color-border)')}
                />
                <span style={{ color: 'var(--color-ink-faint)' }}>–</span>
                <input
                  type="number"
                  placeholder="Max"
                  value={filters.salary_max ?? ''}
                  onChange={e =>
                    onUpdate({ salary_max: e.target.value ? Number(e.target.value) : null })
                  }
                  className="w-full rounded px-2 py-1.5 text-sm outline-none"
                  style={{
                    border: '1px solid var(--color-border)',
                    color: 'var(--color-ink)',
                    backgroundColor: 'var(--color-surface-2)',
                  }}
                  onFocus={e => (e.currentTarget.style.borderColor = 'var(--color-ring)')}
                  onBlur={e => (e.currentTarget.style.borderColor = 'var(--color-border)')}
                />
              </div>
            </div>
          )}

          <button
            onClick={() => setOpen(false)}
            className="text-xs font-medium text-right cursor-pointer"
            style={{ color: 'var(--color-gold)' }}
          >
            Done
          </button>
        </div>
      )}
    </div>
  )
}

// ── Experience sub-component ──────────────────────────────────────────────────

function ExpFilter({
  filters,
  onUpdate,
}: {
  filters: JobFilters
  onUpdate: (p: Partial<JobFilters>) => void
}) {
  const [open, setOpen] = useState(false)
  const isActive = filters.exp_min !== null || filters.exp_max !== null

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        data-active={isActive}
        className="filter-pill rounded-md px-3 py-1.5 text-xs font-semibold cursor-pointer flex items-center gap-1.5 outline-none"
        style={{
          backgroundColor: isActive ? 'var(--color-ink)' : 'var(--color-surface-2)',
          color: isActive ? 'var(--color-ink-inverse)' : 'var(--color-ink-muted)',
          border: `1px solid ${isActive ? 'var(--color-ink)' : 'var(--color-border-strong)'}`,
          boxShadow: isActive ? 'var(--shadow-card)' : 'none',
        }}
        aria-expanded={open}
      >
        Experience
        {isActive && <span style={{ color: 'var(--color-gold-star)' }}>·</span>}
      </button>

      {open && (
        <div
          className="absolute left-0 top-full mt-1 z-40 rounded-lg p-4 flex flex-col gap-3"
          style={{
            minWidth: '220px',
            backgroundColor: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
            boxShadow: 'var(--shadow-float)',
          }}
        >
          <p className="text-xs" style={{ color: 'var(--color-ink-faint)' }}>
            Years of experience
          </p>
          <div className="flex items-center gap-2">
            <input
              type="number"
              min={0}
              max={20}
              placeholder="Min"
              value={filters.exp_min ?? ''}
              onChange={e => onUpdate({ exp_min: e.target.value ? Number(e.target.value) : null })}
              className="w-full rounded px-2 py-1.5 text-sm outline-none"
              style={{
                border: '1px solid var(--color-border)',
                color: 'var(--color-ink)',
                backgroundColor: 'var(--color-surface-2)',
              }}
              onFocus={e => (e.currentTarget.style.borderColor = 'var(--color-ring)')}
              onBlur={e => (e.currentTarget.style.borderColor = 'var(--color-border)')}
            />
            <span style={{ color: 'var(--color-ink-faint)' }}>–</span>
            <input
              type="number"
              min={0}
              max={20}
              placeholder="Max"
              value={filters.exp_max ?? ''}
              onChange={e => onUpdate({ exp_max: e.target.value ? Number(e.target.value) : null })}
              className="w-full rounded px-2 py-1.5 text-sm outline-none"
              style={{
                border: '1px solid var(--color-border)',
                color: 'var(--color-ink)',
                backgroundColor: 'var(--color-surface-2)',
              }}
              onFocus={e => (e.currentTarget.style.borderColor = 'var(--color-ring)')}
              onBlur={e => (e.currentTarget.style.borderColor = 'var(--color-border)')}
            />
          </div>
          <button
            onClick={() => setOpen(false)}
            className="text-xs font-medium text-right cursor-pointer"
            style={{ color: 'var(--color-gold)' }}
          >
            Done
          </button>
        </div>
      )}
    </div>
  )
}
