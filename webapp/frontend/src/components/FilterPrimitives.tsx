import type { ReactNode } from 'react'
import type { JobFilters } from '../api/client'

// Shared building blocks used by both the desktop FilterBar (popover-style
// Salary/Experience/Applicants controls, toggle pills) and MobileFilterSheet
// (same fields rendered always-expanded, full width). Keeping them here means
// the two surfaces can never drift out of sync with each other.

// Not exported: nothing outside this file references the map itself, only
// PillButton's `palette` prop (a `keyof typeof PILL_PALETTES` string, which
// carries its own type without needing this constant re-imported). Keeping
// it private is also what lets this file export only components, which Fast
// Refresh needs to preserve component state across edits.
const PILL_PALETTES = {
  ink: { bg: 'var(--color-ink)', fg: 'var(--color-ink-inverse)', border: 'var(--color-ink)' },
  blue: { bg: 'var(--color-blue)', fg: '#fff', border: 'var(--color-blue)' },
  amber: { bg: '#FEF3C7', fg: '#854D0E', border: '#F5C451' },
  green: { bg: '#DCFCE7', fg: '#15803D', border: '#BBF7D0' },
  red: { bg: '#FEE2E2', fg: '#B91C1C', border: '#FECACA' },
} as const

export function PillButton({
  active,
  onClick,
  palette,
  capitalize = false,
  children,
}: {
  active: boolean
  onClick: () => void
  palette: keyof typeof PILL_PALETTES
  capitalize?: boolean
  children: ReactNode
}) {
  const colors = PILL_PALETTES[palette]
  return (
    <button
      type="button"
      onClick={onClick}
      data-active={active}
      aria-pressed={active}
      className={`filter-pill rounded-md px-3 py-1.5 text-xs font-semibold cursor-pointer outline-none${capitalize ? ' capitalize' : ''}`}
      style={{
        backgroundColor: active ? colors.bg : 'var(--color-surface-2)',
        color: active ? colors.fg : 'var(--color-ink-muted)',
        border: `1px solid ${active ? colors.border : 'var(--color-border-strong)'}`,
        boxShadow: active ? 'var(--shadow-card)' : 'none',
      }}
    >
      {children}
    </button>
  )
}

export function FilterRow({ label, children }: { label: string; children: ReactNode }) {
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

// Not exported: only SalaryFields/ExpFields/ApplicantsFields below use it,
// all in this same file — nothing imports it from elsewhere.
function RangeInput({
  placeholder,
  value,
  onChange,
  min,
  max,
}: {
  placeholder: string
  value: number | null
  onChange: (v: number | null) => void
  min?: number
  max?: number
}) {
  return (
    <input
      type="number"
      inputMode="numeric"
      min={min}
      max={max}
      placeholder={placeholder}
      value={value ?? ''}
      onChange={e => onChange(e.target.value ? Number(e.target.value) : null)}
      className="w-full rounded px-2 py-1.5 text-sm outline-none"
      style={{
        border: '1px solid var(--color-border)',
        color: 'var(--color-ink)',
        backgroundColor: 'var(--color-surface-2)',
      }}
      onFocus={e => (e.currentTarget.style.borderColor = 'var(--color-ring)')}
      onBlur={e => (e.currentTarget.style.borderColor = 'var(--color-border)')}
    />
  )
}

// ── Field content shared between the desktop popover wrapper and the
// always-expanded mobile sheet section ────────────────────────────────────

export function SalaryFields({
  filters,
  onUpdate,
}: {
  filters: JobFilters
  onUpdate: (p: Partial<JobFilters>) => void
}) {
  return (
    <div className="flex flex-col gap-3">
      <label className="flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          checked={filters.salary_disclosed_only}
          onChange={e =>
            onUpdate({
              salary_disclosed_only: e.target.checked,
              salary_min: null,
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
            <RangeInput
              placeholder="Min"
              value={filters.salary_min}
              onChange={v => onUpdate({ salary_min: v })}
            />
            <span style={{ color: 'var(--color-ink-faint)' }}>–</span>
            <RangeInput
              placeholder="Max"
              value={filters.salary_max}
              onChange={v => onUpdate({ salary_max: v })}
            />
          </div>
        </div>
      )}
    </div>
  )
}

export function ExpFields({
  filters,
  onUpdate,
}: {
  filters: JobFilters
  onUpdate: (p: Partial<JobFilters>) => void
}) {
  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs" style={{ color: 'var(--color-ink-faint)' }}>
        Years of experience
      </p>
      <div className="flex items-center gap-2">
        <RangeInput
          placeholder="Min"
          min={0}
          max={20}
          value={filters.exp_min}
          onChange={v => onUpdate({ exp_min: v })}
        />
        <span style={{ color: 'var(--color-ink-faint)' }}>–</span>
        <RangeInput
          placeholder="Max"
          min={0}
          max={20}
          value={filters.exp_max}
          onChange={v => onUpdate({ exp_max: v })}
        />
      </div>
    </div>
  )
}

export function ApplicantsFields({
  filters,
  onUpdate,
}: {
  filters: JobFilters
  onUpdate: (p: Partial<JobFilters>) => void
}) {
  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs" style={{ color: 'var(--color-ink-faint)' }}>
        Show jobs with fewer than…
      </p>
      <div className="flex items-center gap-2">
        <RangeInput
          placeholder="e.g. 25"
          min={1}
          max={500}
          value={filters.max_applicants}
          onChange={v => onUpdate({ max_applicants: v })}
        />
        <span className="text-xs" style={{ color: 'var(--color-ink-muted)' }}>applicants</span>
      </div>
      <div className="flex items-center gap-1.5">
        {[10, 25, 50].map(n => (
          <button
            key={n}
            type="button"
            onClick={() => onUpdate({ max_applicants: n })}
            className="filter-pill rounded px-2 py-1 text-xs font-semibold cursor-pointer outline-none"
            style={{
              backgroundColor: filters.max_applicants === n ? 'var(--color-ink)' : 'var(--color-surface-2)',
              color: filters.max_applicants === n ? 'var(--color-ink-inverse)' : 'var(--color-ink-muted)',
              border: '1px solid var(--color-border-strong)',
            }}
          >
            &lt;{n}
          </button>
        ))}
      </div>
    </div>
  )
}
