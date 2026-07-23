import { useState, useRef, useEffect } from 'react'
import { ChevronDown, Check, Search, X } from 'lucide-react'
import type { NameCount } from '../api/client'

interface Props {
  label: string
  options: NameCount[]
  selected: string[]
  onChange: (vals: string[]) => void
  showCount?: boolean
  maxHeight?: number
  // Renders as an always-expanded, full-width block instead of a floating
  // popover — used inside MobileFilterSheet, where a fixed-minWidth absolute
  // popover could clip off the edge of a narrow screen.
  inline?: boolean
}

export default function MultiSelect({
  label,
  options,
  selected,
  onChange,
  showCount = true,
  maxHeight = 260,
  inline = false,
}: Props) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (inline) return // no floating panel to dismiss
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
        setQuery('')
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [inline])

  const filtered = query
    ? options.filter(o => o.name.toLowerCase().includes(query.toLowerCase()))
    : options

  const toggle = (name: string) => {
    onChange(
      selected.includes(name) ? selected.filter(s => s !== name) : [...selected, name],
    )
  }

  const isActive = selected.length > 0
  // Set lookup: checked-state is tested once per option while rendering the list.
  const selectedSet = new Set(selected)

  const panelBody = (
    <>
      {/* Search */}
      {options.length > 8 && (
        <div
          className="flex items-center gap-2 px-3 py-2"
          style={{ borderBottom: '1px solid var(--color-border)' }}
        >
          <Search size={13} style={{ color: 'var(--color-ink-faint)' }} />
          <input
            autoFocus={!inline}
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder={`Search ${label.toLowerCase()}…`}
            className="flex-1 bg-transparent text-sm outline-none"
            style={{ color: 'var(--color-ink)' }}
          />
          {query && (
            <button type="button" onClick={() => setQuery('')} className="cursor-pointer" aria-label="Clear search">
              <X size={13} style={{ color: 'var(--color-ink-faint)' }} />
            </button>
          )}
        </div>
      )}

      {/* Options */}
      <div
        className="overflow-y-auto py-1"
        style={{ maxHeight }}
        role="listbox"
        aria-multiselectable="true"
      >
        {filtered.length === 0 ? (
          <p className="px-3 py-2 text-xs" style={{ color: 'var(--color-ink-faint)' }}>
            No results
          </p>
        ) : (
          filtered.map(opt => {
            const isChecked = selectedSet.has(opt.name)
            return (
              <button type="button"
                key={opt.name}
                role="option"
                aria-selected={isChecked}
                onClick={() => toggle(opt.name)}
                className="w-full flex items-center gap-2.5 px-3 py-1.5 text-sm text-left transition-colors duration-100 cursor-pointer"
                style={{
                  backgroundColor: isChecked ? 'var(--color-blue-light)' : 'transparent',
                  color: 'var(--color-ink)',
                }}
                onMouseEnter={e => {
                  if (!isChecked)
                    (e.currentTarget as HTMLButtonElement).style.backgroundColor =
                      'var(--color-surface-2)'
                }}
                onMouseLeave={e => {
                  if (!isChecked)
                    (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'transparent'
                }}
              >
                <span
                  className="flex h-4 w-4 flex-shrink-0 items-center justify-center rounded"
                  style={{
                    backgroundColor: isChecked ? 'var(--color-blue)' : 'transparent',
                    border: `1.5px solid ${isChecked ? 'var(--color-blue)' : 'var(--color-border-strong)'}`,
                  }}
                >
                  {isChecked && <Check size={10} color="var(--color-ink-inverse)" strokeWidth={3} />}
                </span>
                <span className="flex-1 truncate">{opt.name}</span>
                {showCount && (
                  <span
                    className="text-xs tabular-nums"
                    style={{ color: 'var(--color-ink-faint)', fontFamily: 'var(--font-mono)' }}
                  >
                    {opt.count}
                  </span>
                )}
              </button>
            )
          })
        )}
      </div>

      {/* Clear */}
      {selected.length > 0 && (
        <div style={{ borderTop: '1px solid var(--color-border)' }}>
          <button type="button"
            onClick={() => { onChange([]); if (!inline) setOpen(false) }}
            className="w-full px-3 py-2 text-xs font-medium text-left transition-colors duration-100 cursor-pointer"
            style={{ color: 'var(--color-gold)' }}
            onMouseEnter={e => ((e.currentTarget as HTMLButtonElement).style.color = 'var(--color-blue)')}
            onMouseLeave={e => ((e.currentTarget as HTMLButtonElement).style.color = 'var(--color-gold)')}
          >
            Clear selection
          </button>
        </div>
      )}
    </>
  )

  if (inline) {
    return (
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <span
            className="text-xs font-bold uppercase tracking-wider"
            style={{ color: 'var(--color-ink-faint)', letterSpacing: '0.08em' }}
          >
            {label}
          </span>
          {isActive && (
            <span className="text-xs font-medium" style={{ color: 'var(--color-gold)' }}>
              {selected.length} selected
            </span>
          )}
        </div>
        <div
          className="rounded-lg overflow-hidden"
          style={{ border: '1px solid var(--color-border)', backgroundColor: 'var(--color-surface)' }}
        >
          {panelBody}
        </div>
      </div>
    )
  }

  return (
    <div ref={ref} className="relative">
      <button type="button"
        onClick={() => setOpen(o => !o)}
        data-active={isActive}
        className="filter-pill flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold cursor-pointer whitespace-nowrap outline-none"
        style={{
          backgroundColor: isActive ? 'var(--color-ink)' : 'var(--color-surface-2)',
          color: isActive ? 'var(--color-ink-inverse)' : 'var(--color-ink-muted)',
          border: `1px solid ${isActive ? 'var(--color-ink)' : 'var(--color-border-strong)'}`,
          boxShadow: isActive ? 'var(--shadow-card)' : 'none',
        }}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        {label}
        {isActive && (
          <span
            className="flex h-4 w-4 items-center justify-center rounded-full text-xs font-bold"
            style={{ backgroundColor: 'var(--color-gold)', color: 'var(--color-ink-inverse)' }}
          >
            {selected.length}
          </span>
        )}
        <ChevronDown
          size={14}
          strokeWidth={2}
          className="transition-transform duration-150"
          style={{ transform: open ? 'rotate(180deg)' : 'none' }}
        />
      </button>

      {open && (
        <div
          className="absolute left-0 top-full mt-1 z-40 rounded-lg overflow-hidden"
          style={{
            minWidth: '220px',
            backgroundColor: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
            boxShadow: 'var(--shadow-float)',
          }}
        >
          {panelBody}
        </div>
      )}
    </div>
  )
}
