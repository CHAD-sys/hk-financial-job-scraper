import { ArrowLeft, Search, X, SlidersHorizontal } from 'lucide-react'
import { useState } from 'react'
import type { JobFilters, FiltersResponse } from '../api/client'
import MobileFilterSheet from './MobileFilterSheet'

interface Props {
  filters: JobFilters
  filterData: FiltersResponse | null
  activeCount: number
  onUpdate: (patch: Partial<JobFilters>) => void
  onClear: () => void
  /** Back to the SearchHero "discover" screen — kept in this always-visible
   * bar rather than the scrolling hero above it, so the way back to search
   * never leaves the viewport. */
  onNewSearch: () => void
  /** ADR 0032: show the admin-hidden Roles control. Ultimate Admin in Admin
   * Mode only — the parent decides, this component just renders it. */
}

export default function FilterBar({ filters, filterData, activeCount, onUpdate, onClear, onNewSearch }: Props) {
  const [mobileSheetOpen, setMobileSheetOpen] = useState(false)

  return (
    <div
      // The single-row navigation height is shared at every viewport.
      className="sticky top-[var(--nav-height)] z-30 w-full"
      style={{
        backgroundColor: 'var(--color-surface)',
        borderBottom: '1px solid var(--color-border)',
        boxShadow: '0 2px 8px -2px rgb(0 0 0 / 0.06)',
      }}
    >
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">

        {/* New search, query, and filter sheet. */}
        <div className="flex items-center gap-3 py-3.5">
          {/* The way back to the search home. A results page that cannot
              return to its own search box is a dead end — this bar is sticky,
              so unlike the slim hero above it, this button never scrolls
              out of reach. */}
          <button
            type="button"
            onClick={onNewSearch}
            aria-label="New search"
            className="flex flex-shrink-0 items-center gap-1.5 rounded-md px-2.5 sm:px-3.5 py-2 text-xs font-semibold cursor-pointer outline-none whitespace-nowrap"
            style={{
              minHeight: '2.25rem',
              border: '1px solid var(--color-border-strong)',
              backgroundColor: 'var(--color-surface-2)',
              color: 'var(--color-ink-muted)',
            }}
          >
            <ArrowLeft size={14} strokeWidth={2.25} aria-hidden="true" />
            <span className="hidden sm:inline">New search</span>
          </button>

          <SearchInput value={filters.search} onChange={v => onUpdate({ search: v })} />

          {/* The filter sheet keeps the sticky bar compact at every width. */}
          <button
              type="button"
              onClick={() => setMobileSheetOpen(true)}
              data-active={activeCount > 0}
              className="filter-pill flex items-center gap-1.5 rounded-md px-3.5 py-2 text-xs font-semibold cursor-pointer outline-none whitespace-nowrap"
              style={{
                border: `1px solid ${activeCount > 0 ? 'var(--color-ink)' : 'var(--color-border-strong)'}`,
                backgroundColor: activeCount > 0 ? 'var(--color-ink)' : 'var(--color-surface-2)',
                color: activeCount > 0 ? 'var(--color-ink-inverse)' : 'var(--color-ink-muted)',
                boxShadow: activeCount > 0 ? 'var(--shadow-card)' : 'none',
              }}
            >
              <SlidersHorizontal size={14} />
              Filters
              {activeCount > 0 && (
                <span
                  className="flex h-4 min-w-4 px-1 items-center justify-center rounded-full text-[10px] font-bold"
                  style={{ backgroundColor: 'var(--color-gold-star)', color: 'var(--color-nav)' }}
                >
                  {activeCount}
                </span>
              )}
            </button>

        </div>


        {/* Active filter chips. */}
        <ActiveChips filters={filters} onUpdate={onUpdate} onClear={onClear} />
      </div>

      {mobileSheetOpen && (
        <MobileFilterSheet
          filters={filters}
          filterData={filterData}
          activeCount={activeCount}
          onUpdate={onUpdate}
          onClear={onClear}
          onClose={() => setMobileSheetOpen(false)}
        />
      )}
    </div>
  )
}

// ── Search input ──────────────────────────────────────────────────────────────

function SearchInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div className="relative flex-1 max-w-md">
      <label htmlFor="filter-bar-search" className="sr-only">
        Search job titles, employers, and skills
      </label>
      <Search
        size={15}
        className="absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none"
        style={{ color: 'var(--color-ink-faint)' }}
      />
      <input
        id="filter-bar-search"
        type="search"
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder="Job title, employer, or skill…"
        className="w-full rounded-md pl-9 pr-3 py-2 text-sm outline-none transition-[background-color,border-color,box-shadow] duration-150"
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
  )
}

function ActiveChips({
  filters,
  onUpdate,
  onClear,
}: {
  filters: JobFilters
  onUpdate: (p: Partial<JobFilters>) => void
  onClear: () => void
}) {
  const chips: { label: string; remove: () => void }[] = [
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
    ...(filters.is_new ? [{ label: 'New', remove: () => onUpdate({ is_new: false }) }] : []),
    ...(filters.urgently_hiring ? [{ label: 'Urgently hiring', remove: () => onUpdate({ urgently_hiring: false }) }] : []),
    ...(filters.verified_only ? [{ label: 'Verified job', remove: () => onUpdate({ verified_only: false }) }] : []),
  ]

  if (chips.length === 0) return null

  return (
    <div className="flex flex-wrap gap-2 pb-3">
      {chips.map(chip => (
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
            type="button"
            onClick={chip.remove}
            className="cursor-pointer flex-shrink-0"
            aria-label={`Remove ${chip.label} filter`}
          >
            <X size={11} strokeWidth={2.5} />
          </button>
        </span>
      ))}
      <button
        type="button"
        onClick={onClear}
        className="text-xs font-medium cursor-pointer transition-colors duration-150"
        style={{ color: 'var(--color-ink-faint)' }}
        onMouseEnter={e => ((e.currentTarget as HTMLButtonElement).style.color = 'var(--color-ink-muted)')}
        onMouseLeave={e => ((e.currentTarget as HTMLButtonElement).style.color = 'var(--color-ink-faint)')}
      >
        Clear filters
      </button>
    </div>
  )
}
