import { ArrowLeft, Search, X, SlidersHorizontal, ChevronDown, Flame, Sparkles, Users, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import type { JobFilters, FiltersResponse } from '../api/client'
import MultiSelect from './MultiSelect'
import MobileFilterSheet from './MobileFilterSheet'
import { PillButton, FilterRow, SalaryFields, ExpFields, ApplicantsFields } from './FilterPrimitives'

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
  canFilterHidden?: boolean
}

export default function FilterBar({ filters, filterData, activeCount, onUpdate, onClear, onNewSearch, canFilterHidden }: Props) {
  const [showAllFilters, setShowAllFilters] = useState(false)
  const [mobileSheetOpen, setMobileSheetOpen] = useState(false)

  return (
    <div
      // Nav.tsx renders two different header heights: a single 64px row below
      // `lg`, and a two-tier 90px header (utility strip + primary nav) at
      // `lg` and up. This bar's sticky offset has to match whichever one is
      // actually on screen, or its top edge scrolls under the (higher
      // z-index) header and looks clipped instead of merely covered.
      className="sticky top-16 z-30 w-full lg:top-[90px]"
      style={{
        backgroundColor: 'var(--color-surface)',
        borderBottom: '1px solid var(--color-border)',
        boxShadow: '0 2px 8px -2px rgb(0 0 0 / 0.06)',
      }}
    >
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">

        {/* Row 1: New search + Search + More-filters toggle + clear */}
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

          {/* Mobile trigger: opens the full-screen Filters sheet (below md:).
              Sector pills + the advanced panel live only inside the sheet on
              mobile — keeping them out of this sticky bar is what stops it
              from growing tall enough to swallow a phone-sized viewport. */}
          <button
            type="button"
            onClick={() => setMobileSheetOpen(true)}
            data-active={activeCount > 0}
            className="filter-pill md:hidden flex items-center gap-1.5 rounded-md px-3.5 py-2 text-xs font-semibold cursor-pointer outline-none whitespace-nowrap"
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

          {/* Desktop More-filters toggle (unchanged) */}
          <button
            type="button"
            onClick={() => setShowAllFilters(o => !o)}
            data-active={showAllFilters || activeCount > 0}
            aria-expanded={showAllFilters}
            className="filter-pill hidden md:flex items-center gap-1.5 rounded-md px-3.5 py-2 text-xs font-semibold cursor-pointer outline-none whitespace-nowrap"
            style={{
              border: `1px solid ${showAllFilters || activeCount > 0 ? 'var(--color-ink)' : 'var(--color-border-strong)'}`,
              backgroundColor: showAllFilters || activeCount > 0 ? 'var(--color-ink)' : 'var(--color-surface-2)',
              color: showAllFilters || activeCount > 0 ? 'var(--color-ink-inverse)' : 'var(--color-ink-muted)',
              boxShadow: showAllFilters || activeCount > 0 ? 'var(--shadow-card)' : 'none',
            }}
          >
            <SlidersHorizontal size={14} />
            <span>{showAllFilters ? 'Hide filters' : 'More filters'}</span>
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

          {/* Right-side clear (desktop) */}
          {activeCount > 0 && (
            <button
              type="button"
              onClick={onClear}
              className="hidden md:flex items-center gap-1.5 text-xs font-medium transition-colors duration-150 cursor-pointer"
              style={{ color: 'var(--color-ink-muted)' }}
              onMouseEnter={e => ((e.currentTarget as HTMLButtonElement).style.color = 'var(--color-ink)')}
              onMouseLeave={e => ((e.currentTarget as HTMLButtonElement).style.color = 'var(--color-ink-muted)')}
            >
              <X size={13} />
              Clear filters ({activeCount})
            </button>
          )}
        </div>

        {/* ADR 0032 — Ultimate Admin only. A hidden Role is off the public
            board; this is the only place it can be pulled back into view. */}
        {canFilterHidden && (
          <div className="flex flex-wrap items-center gap-2 pb-3 text-xs">
            <span style={{ color: 'var(--color-ink-muted)' }}>Hidden Roles</span>
            {([
              [undefined, 'Excluded'],
              ['include', 'Shown greyed'],
              ['only', 'Only hidden'],
            ] as const).map(([mode, label]) => {
              const active = (filters.admin_hidden ?? undefined) === mode
              return (
                <button
                  key={label}
                  type="button"
                  onClick={() => onUpdate({ admin_hidden: mode })}
                  data-active={active}
                  className="filter-pill rounded-md px-2.5 py-1 font-medium cursor-pointer whitespace-nowrap"
                  style={{
                    border: `1px solid ${active ? 'var(--color-ink)' : 'var(--color-border-strong)'}`,
                    backgroundColor: active ? 'var(--color-ink)' : 'var(--color-surface-2)',
                    color: active ? 'var(--color-ink-inverse)' : 'var(--color-ink-muted)',
                  }}
                >
                  {label}
                </button>
              )
            })}
          </div>
        )}

        {/* Advanced filters — desktop only, collapsed by default */}
        {showAllFilters && (
          <div className="hidden md:block">
            <AdvancedFilters
              filters={filters}
              filterData={filterData}
              onUpdate={onUpdate}
            />
          </div>
        )}

        {/* Row 3: Active filter chips (both viewports) */}
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

// ── Advanced (collapsed) filter rows — desktop only ───────────────────────────

function AdvancedFilters({
  filters,
  filterData,
  onUpdate,
}: {
  filters: JobFilters
  filterData: FiltersResponse | null
  onUpdate: (p: Partial<JobFilters>) => void
}) {
  const seniority_levels = filterData?.seniority_levels ?? []
  const remote_types = filterData?.remote_types ?? []
  const companyOptions = filterData?.companies ?? []
  const skillOptions = filterData?.skills ?? []

  // Sets give constant-time membership checks inside the render loops below.
  const senSet = new Set(filters.seniority)
  const remoteSet = new Set(filters.remote_type)

  const togglePill = (key: 'seniority' | 'remote_type', val: string) => {
    const cur = filters[key] as string[]
    const next = cur.includes(val) ? cur.filter(x => x !== val) : [...cur, val]
    onUpdate({ [key]: next })
  }

  return (
    <div
      className="flex flex-col gap-4 pt-4 pb-4"
      style={{ borderTop: '1px dashed var(--color-border-strong)' }}
    >
      {/* Level */}
      {seniority_levels.length > 0 && (
        <FilterRow label="Level">
          {seniority_levels.map(s => (
            <PillButton
              key={s}
              active={senSet.has(s)}
              onClick={() => togglePill('seniority', s)}
              palette="blue"
              capitalize
            >
              {s}
            </PillButton>
          ))}
        </FilterRow>
      )}

      {/* Work type */}
      {remote_types.length > 0 && (
        <FilterRow label="Work">
          {remote_types.map(r => (
            <PillButton
              key={r}
              active={remoteSet.has(r)}
              onClick={() => togglePill('remote_type', r)}
              palette="blue"
            >
              {r === 'on-site' ? 'On-site' : r.charAt(0).toUpperCase() + r.slice(1)}
            </PillButton>
          ))}
        </FilterRow>
      )}

      {/* Type */}
      <FilterRow label="Type">
        <PillButton
          active={!!filters.is_internship}
          onClick={() => onUpdate({ is_internship: filters.is_internship ? null : true })}
          palette="amber"
        >
          Internships
        </PillButton>
      </FilterRow>

      {/* Signals — board-derived market signals */}
      <FilterRow label="Signals">
        <PillButton
          active={filters.is_new}
          onClick={() => onUpdate({ is_new: !filters.is_new })}
          palette="green"
        >
          <span className="inline-flex items-center gap-1">
            <Sparkles size={12} strokeWidth={2} aria-hidden="true" />New
          </span>
        </PillButton>
        <PillButton
          active={filters.urgently_hiring}
          onClick={() => onUpdate({ urgently_hiring: !filters.urgently_hiring })}
          palette="red"
        >
          <span className="inline-flex items-center gap-1">
            <Flame size={12} strokeWidth={2} aria-hidden="true" />Urgently hiring
          </span>
        </PillButton>
        <PillButton
          active={filters.verified_only}
          onClick={() => onUpdate({ verified_only: !filters.verified_only })}
          palette="green"
        >
          <span className="inline-flex items-center gap-1">
            <ShieldCheck size={12} strokeWidth={2} aria-hidden="true" />Verified job
          </span>
        </PillButton>
        <ApplicantsFilter filters={filters} onUpdate={onUpdate} />
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
    </div>
  )
}

// ── Active filter chips row ───────────────────────────────────────────────────

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
    ...(filters.max_applicants !== null
      ? [{ label: `Under ${filters.max_applicants} applicants`, remove: () => onUpdate({ max_applicants: null }) }]
      : []),
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

// ── Salary sub-component (desktop popover wrapper around SalaryFields) ───────

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
        type="button"
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
          <SalaryFields filters={filters} onUpdate={onUpdate} />
          <button
            type="button"
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

// ── Experience sub-component (desktop popover wrapper around ExpFields) ─────

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
        type="button"
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
          <ExpFields filters={filters} onUpdate={onUpdate} />
          <button
            type="button"
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

// ── Applicants filter (desktop popover wrapper around ApplicantsFields) ─────

function ApplicantsFilter({
  filters,
  onUpdate,
}: {
  filters: JobFilters
  onUpdate: (p: Partial<JobFilters>) => void
}) {
  const [open, setOpen] = useState(false)
  const isActive = filters.max_applicants !== null

  return (
    <div className="relative">
      <button
        type="button"
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
        <Users size={12} strokeWidth={2} aria-hidden="true" />
        {isActive ? `Under ${filters.max_applicants} applicants` : 'Few applicants'}
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
          <ApplicantsFields filters={filters} onUpdate={onUpdate} />
          <button
            type="button"
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
