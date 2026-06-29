import { Search, X, SlidersHorizontal } from 'lucide-react'
import { useState } from 'react'
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
  const [mobileOpen, setMobileOpen] = useState(false)

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

        {/* Row 1: Search + mobile toggle */}
        <div className="flex items-center gap-3 py-3">
          {/* Search */}
          <div className="relative flex-1 max-w-sm">
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
              className="w-full rounded pl-9 pr-3 py-2 text-sm outline-none transition-all duration-150"
              style={{
                backgroundColor: 'var(--color-surface-2)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-ink)',
              }}
              onFocus={e => (e.currentTarget.style.borderColor = 'var(--color-ring)')}
              onBlur={e => (e.currentTarget.style.borderColor = 'var(--color-border)')}
            />
          </div>

          {/* Mobile: filter toggle button */}
          <button
            className="md:hidden flex items-center gap-1.5 rounded px-3 py-2 text-sm font-medium transition-colors duration-150 cursor-pointer"
            style={{
              border: '1px solid var(--color-border)',
              backgroundColor: activeCount > 0 ? 'var(--color-ink)' : 'var(--color-surface)',
              color: activeCount > 0 ? 'var(--color-ink-inverse)' : 'var(--color-ink-muted)',
            }}
            onClick={() => setMobileOpen(o => !o)}
            aria-expanded={mobileOpen}
          >
            <SlidersHorizontal size={14} />
            Filters
            {activeCount > 0 && (
              <span
                className="flex h-4 w-4 items-center justify-center rounded-full text-xs font-bold"
                style={{ backgroundColor: 'var(--color-gold)', color: '#fff' }}
              >
                {activeCount}
              </span>
            )}
          </button>

          {/* Desktop: right-side clear */}
          {activeCount > 0 && (
            <button
              onClick={onClear}
              className="hidden md:flex items-center gap-1.5 text-xs font-medium transition-colors duration-150 cursor-pointer ml-auto"
              style={{ color: 'var(--color-ink-muted)' }}
              onMouseEnter={e => ((e.currentTarget as HTMLButtonElement).style.color = 'var(--color-ink)')}
              onMouseLeave={e => ((e.currentTarget as HTMLButtonElement).style.color = 'var(--color-ink-muted)')}
            >
              <X size={13} />
              Clear all ({activeCount})
            </button>
          )}
        </div>

        {/* Row 2: Filter controls (hidden on mobile until toggle) */}
        <div className={`${mobileOpen ? 'flex' : 'hidden md:flex'} flex-wrap items-center gap-2 pb-3`}>

          {/* Sector pills */}
          <div className="flex flex-wrap gap-1.5">
            {SECTORS.map(s => {
              const active = filters.sectors.includes(s)
              return (
                <button
                  key={s}
                  onClick={() => toggleSector(s)}
                  className="rounded px-3 py-1 text-xs font-medium transition-all duration-150 cursor-pointer"
                  style={{
                    backgroundColor: active ? 'var(--color-ink)' : 'var(--color-surface-2)',
                    color: active ? 'var(--color-ink-inverse)' : 'var(--color-ink-muted)',
                    border: `1px solid ${active ? 'var(--color-ink)' : 'var(--color-border)'}`,
                  }}
                >
                  {s}
                </button>
              )
            })}
          </div>

          {/* Divider */}
          <div className="hidden md:block h-5 w-px" style={{ backgroundColor: 'var(--color-border)' }} />

          {/* Seniority pills — dynamic from API */}
          {seniority_levels.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {seniority_levels.map(s => {
                const active = filters.seniority.includes(s)
                return (
                  <button
                    key={s}
                    onClick={() => togglePill('seniority', s)}
                    className="rounded px-3 py-1 text-xs font-medium capitalize transition-all duration-150 cursor-pointer"
                    style={{
                      backgroundColor: active ? 'var(--color-blue)' : 'var(--color-surface-2)',
                      color: active ? '#fff' : 'var(--color-ink-muted)',
                      border: `1px solid ${active ? 'var(--color-blue)' : 'var(--color-border)'}`,
                    }}
                  >
                    {s}
                  </button>
                )
              })}
            </div>
          )}

          {/* Divider */}
          <div className="hidden md:block h-5 w-px" style={{ backgroundColor: 'var(--color-border)' }} />

          {/* Work type — only show if options exist */}
          {remote_types.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {remote_types.map(r => {
                const active = filters.remote_type.includes(r)
                const label = r === 'on-site' ? 'On-site' : r.charAt(0).toUpperCase() + r.slice(1)
                return (
                  <button
                    key={r}
                    onClick={() => togglePill('remote_type', r)}
                    className="rounded px-3 py-1 text-xs font-medium transition-all duration-150 cursor-pointer"
                    style={{
                      backgroundColor: active ? 'var(--color-blue)' : 'var(--color-surface-2)',
                      color: active ? '#fff' : 'var(--color-ink-muted)',
                      border: `1px solid ${active ? 'var(--color-blue)' : 'var(--color-border)'}`,
                    }}
                  >
                    {label}
                  </button>
                )
              })}
            </div>
          )}

          {/* Divider */}
          <div className="hidden md:block h-5 w-px" style={{ backgroundColor: 'var(--color-border)' }} />

          {/* Internship toggle */}
          <button
            onClick={() => onUpdate({ is_internship: filters.is_internship ? null : true })}
            className="rounded px-3 py-1 text-xs font-medium transition-all duration-150 cursor-pointer"
            style={{
              backgroundColor: filters.is_internship ? '#FEF9C3' : 'var(--color-surface-2)',
              color: filters.is_internship ? '#854D0E' : 'var(--color-ink-muted)',
              border: `1px solid ${filters.is_internship ? '#FDE68A' : 'var(--color-border)'}`,
            }}
          >
            Internships
          </button>

          {/* Divider */}
          <div className="hidden md:block h-5 w-px" style={{ backgroundColor: 'var(--color-border)' }} />

          {/* Company multi-select */}
          <MultiSelect
            label="Company"
            options={companyOptions}
            selected={filters.companies}
            onChange={v => onUpdate({ companies: v })}
          />

          {/* Skills multi-select */}
          <MultiSelect
            label="Skills"
            options={skillOptions}
            selected={filters.skills}
            onChange={v => onUpdate({ skills: v })}
          />

          {/* Salary */}
          <SalaryToggle filters={filters} onUpdate={onUpdate} />

          {/* Experience */}
          <ExpFilter filters={filters} onUpdate={onUpdate} />

          {/* Mobile clear */}
          {activeCount > 0 && (
            <button
              onClick={() => { onClear(); setMobileOpen(false) }}
              className="md:hidden flex items-center gap-1 text-xs font-medium cursor-pointer"
              style={{ color: 'var(--color-gold)' }}
            >
              <X size={12} /> Clear all
            </button>
          )}
        </div>

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
                  borderOpacity: '0.4',
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
        className="rounded px-3 py-1.5 text-xs font-medium transition-all duration-150 cursor-pointer flex items-center gap-1.5"
        style={{
          backgroundColor: isActive ? 'var(--color-ink)' : 'var(--color-surface-2)',
          color: isActive ? 'var(--color-ink-inverse)' : 'var(--color-ink-muted)',
          border: `1px solid ${isActive ? 'var(--color-ink)' : 'var(--color-border)'}`,
        }}
        aria-expanded={open}
      >
        Salary
        {isActive && <span style={{ color: 'var(--color-gold)' }}>·</span>}
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
        className="rounded px-3 py-1.5 text-xs font-medium transition-all duration-150 cursor-pointer flex items-center gap-1.5"
        style={{
          backgroundColor: isActive ? 'var(--color-ink)' : 'var(--color-surface-2)',
          color: isActive ? 'var(--color-ink-inverse)' : 'var(--color-ink-muted)',
          border: `1px solid ${isActive ? 'var(--color-ink)' : 'var(--color-border)'}`,
        }}
        aria-expanded={open}
      >
        Experience
        {isActive && <span style={{ color: 'var(--color-gold)' }}>·</span>}
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
