import { useEffect, useRef } from 'react'
import { X, Sparkles, Flame, ShieldCheck } from 'lucide-react'
import type { JobFilters, FiltersResponse } from '../api/client'
import { PillButton, FilterRow, SalaryFields, ExpFields, ApplicantsFields } from './FilterPrimitives'
import MultiSelect from './MultiSelect'

interface Props {
  filters: JobFilters
  filterData: FiltersResponse | null
  activeCount: number
  onUpdate: (patch: Partial<JobFilters>) => void
  onClear: () => void
  onClose: () => void
}

// Full-screen mobile equivalent of FilterBar's inline sector row + advanced
// panel. Everything here is always-expanded (no nested toggles) since the
// sheet itself is already the opt-in step — matches the mobile-optimization
// plan's "Filters" overlay pattern used by Indeed/LinkedIn/Glassdoor mobile web.
export default function MobileFilterSheet({
  filters,
  filterData,
  activeCount,
  onUpdate,
  onClear,
  onClose,
}: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)

  // Native <dialog> + showModal() gives focus trapping for free — the div it
  // replaced (role="dialog" + a manual keydown listener) let Tab reach page
  // content behind the sheet, because nothing actually contained focus.
  // showModal() also handles Escape (fired as a 'cancel' event, intercepted
  // below so it goes through the same onClose the Close button uses) and
  // opens the top-layer ::backdrop declared in index.css.
  useEffect(() => {
    const dlg = dialogRef.current
    if (!dlg) return
    dlg.showModal()
    document.body.style.overflow = 'hidden'
    closeRef.current?.focus()
    const onCancel = (e: Event) => { e.preventDefault(); onClose() }
    dlg.addEventListener('cancel', onCancel)
    return () => {
      dlg.removeEventListener('cancel', onCancel)
      document.body.style.overflow = ''
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const senSet = new Set(filters.seniority)
  const remoteSet = new Set(filters.remote_type)
  const seniority_levels = filterData?.seniority_levels ?? []
  const remote_types = filterData?.remote_types ?? []
  const companyOptions = filterData?.companies ?? []
  const skillOptions = filterData?.skills ?? []

  const togglePill = (key: 'seniority' | 'remote_type', val: string) => {
    const cur = filters[key] as string[]
    const next = cur.includes(val) ? cur.filter(x => x !== val) : [...cur, val]
    onUpdate({ [key]: next })
  }

  return (
    <dialog
      ref={dialogRef}
      className="mobile-filter-sheet fixed inset-0 flex flex-col md:hidden"
      style={{ zIndex: 300, backgroundColor: 'var(--color-bg)' }}
      aria-label="Filters"
    >
      {/* Header */}
      <div
        className="flex-shrink-0 flex items-center justify-between px-4 py-3"
        style={{ borderBottom: '1px solid var(--color-border)', backgroundColor: 'var(--color-surface)' }}
      >
        <h2
          className="text-base font-semibold"
          style={{ fontFamily: 'var(--font-display)', color: 'var(--color-ink)' }}
        >
          Filters
        </h2>
        <button
          ref={closeRef}
          type="button"
          onClick={onClose}
          className="flex min-h-11 min-w-11 items-center justify-center rounded cursor-pointer"
          style={{ color: 'var(--color-ink-faint)' }}
          aria-label="Close filters"
        >
          <X size={20} strokeWidth={1.8} />
        </button>
      </div>

      {/* Scrollable body */}
      <div className="flex-1 overflow-y-auto px-4 py-5 flex flex-col gap-6">
        {seniority_levels.length > 0 && (
          <FilterRow label="Level">
            {seniority_levels.map(s => (
              <PillButton key={s} active={senSet.has(s)} onClick={() => togglePill('seniority', s)} palette="blue" capitalize>
                {s}
              </PillButton>
            ))}
          </FilterRow>
        )}

        {remote_types.length > 0 && (
          <FilterRow label="Work">
            {remote_types.map(r => (
              <PillButton key={r} active={remoteSet.has(r)} onClick={() => togglePill('remote_type', r)} palette="blue">
                {r === 'on-site' ? 'On-site' : r.charAt(0).toUpperCase() + r.slice(1)}
              </PillButton>
            ))}
          </FilterRow>
        )}

        <FilterRow label="Type">
          <PillButton
            active={!!filters.is_internship}
            onClick={() => onUpdate({ is_internship: filters.is_internship ? null : true })}
            palette="amber"
          >
            Internships
          </PillButton>
        </FilterRow>

        <FilterRow label="Signals">
          <PillButton active={filters.is_new} onClick={() => onUpdate({ is_new: !filters.is_new })} palette="green">
            <span className="inline-flex items-center gap-1">
              <Sparkles size={12} strokeWidth={2} aria-hidden="true" />New
            </span>
          </PillButton>
          <PillButton active={filters.urgently_hiring} onClick={() => onUpdate({ urgently_hiring: !filters.urgently_hiring })} palette="red">
            <span className="inline-flex items-center gap-1">
              <Flame size={12} strokeWidth={2} aria-hidden="true" />Urgently hiring
            </span>
          </PillButton>
          <PillButton active={filters.verified_only} onClick={() => onUpdate({ verified_only: !filters.verified_only })} palette="green">
            <span className="inline-flex items-center gap-1">
              <ShieldCheck size={12} strokeWidth={2} aria-hidden="true" />Verified job
            </span>
          </PillButton>
        </FilterRow>

        <SectionHeader label="Applicants">
          <ApplicantsFields filters={filters} onUpdate={onUpdate} />
        </SectionHeader>

        <MultiSelect
          inline
          label="Company"
          options={companyOptions}
          selected={filters.companies}
          onChange={v => onUpdate({ companies: v })}
        />
        <MultiSelect
          inline
          label="Skills"
          options={skillOptions}
          selected={filters.skills}
          onChange={v => onUpdate({ skills: v })}
        />

        <SectionHeader label="Salary">
          <SalaryFields filters={filters} onUpdate={onUpdate} />
        </SectionHeader>

        <SectionHeader label="Experience">
          <ExpFields filters={filters} onUpdate={onUpdate} />
        </SectionHeader>
      </div>

      {/* Footer */}
      <div
        className="flex-shrink-0 flex items-center gap-3 px-4 py-4"
        style={{ borderTop: '1px solid var(--color-border)', backgroundColor: 'var(--color-surface)' }}
      >
        {activeCount > 0 && (
          <button
            type="button"
            onClick={onClear}
            className="flex min-h-11 items-center gap-1.5 text-sm font-semibold cursor-pointer whitespace-nowrap"
            style={{ color: 'var(--color-gold)' }}
          >
            <X size={14} /> Clear filters ({activeCount})
          </button>
        )}
        <button
          type="button"
          onClick={onClose}
          className="flex-1 min-h-11 rounded px-5 py-3 text-sm font-semibold cursor-pointer"
          style={{ backgroundColor: 'var(--color-ink)', color: 'var(--color-ink-inverse)' }}
        >
          Show results
        </button>
      </div>
    </dialog>
  )
}

function SectionHeader({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <span
        className="text-xs font-bold uppercase tracking-wider"
        style={{ color: 'var(--color-ink-faint)', letterSpacing: '0.08em' }}
      >
        {label}
      </span>
      {children}
    </div>
  )
}
