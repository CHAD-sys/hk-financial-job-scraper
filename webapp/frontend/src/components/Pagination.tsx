import { ChevronLeft, ChevronRight } from 'lucide-react'

interface Props {
  page: number
  totalPages: number
  onChange: (page: number) => void
}

export default function Pagination({ page, totalPages, onChange }: Props) {
  if (totalPages <= 1) return null

  const pages: (number | '…')[] = []
  if (totalPages <= 7) {
    for (let i = 1; i <= totalPages; i++) pages.push(i)
  } else {
    pages.push(1)
    if (page > 3) pages.push('…')
    for (let i = Math.max(2, page - 1); i <= Math.min(totalPages - 1, page + 1); i++) {
      pages.push(i)
    }
    if (page < totalPages - 2) pages.push('…')
    pages.push(totalPages)
  }

  const btn = (
    content: React.ReactNode,
    target: number,
    disabled: boolean,
    isActive = false,
  ) => (
    <button type="button"
      key={String(target) + String(isActive)}
      onClick={() => !disabled && onChange(target)}
      disabled={disabled}
      className="flex h-9 min-w-9 items-center justify-center rounded px-3 text-sm font-medium transition-colors duration-150 cursor-pointer disabled:cursor-default disabled:opacity-40"
      style={{
        backgroundColor: isActive ? 'var(--color-ink)' : 'transparent',
        color: isActive ? 'var(--color-ink-inverse)' : 'var(--color-ink-muted)',
        border: isActive ? '1px solid var(--color-ink)' : '1px solid var(--color-border)',
      }}
      onMouseEnter={e => {
        if (!disabled && !isActive)
          (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'var(--color-surface-2)'
      }}
      onMouseLeave={e => {
        if (!disabled && !isActive)
          (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'transparent'
      }}
      aria-label={isActive ? `Page ${target}, current` : `Page ${target}`}
      aria-current={isActive ? 'page' : undefined}
    >
      {content}
    </button>
  )

  return (
    <nav
      className="flex items-center justify-center py-8"
      aria-label="Pagination"
    >
      {/* Compact mode below sm: — a full numbered pager (up to 9 buttons)
          can overflow or wrap awkwardly on a 360px screen; Prev/Next + a
          page label degrades cleanly and stays a single row. */}
      <div className="flex sm:hidden items-center gap-3">
        <button type="button"
          onClick={() => page > 1 && onChange(page - 1)}
          disabled={page === 1}
          className="flex min-h-11 min-w-11 items-center justify-center rounded cursor-pointer disabled:cursor-default disabled:opacity-40"
          style={{ border: '1px solid var(--color-border)', color: 'var(--color-ink-muted)' }}
          aria-label="Previous page"
        >
          <ChevronLeft size={18} />
        </button>
        <span
          className="text-sm font-medium tabular-nums"
          style={{ color: 'var(--color-ink-muted)', fontFamily: 'var(--font-mono)' }}
        >
          Page {page} of {totalPages}
        </span>
        <button type="button"
          onClick={() => page < totalPages && onChange(page + 1)}
          disabled={page === totalPages}
          className="flex min-h-11 min-w-11 items-center justify-center rounded cursor-pointer disabled:cursor-default disabled:opacity-40"
          style={{ border: '1px solid var(--color-border)', color: 'var(--color-ink-muted)' }}
          aria-label="Next page"
        >
          <ChevronRight size={18} />
        </button>
      </div>

      {/* Full numbered pager — sm: and up */}
      <div className="hidden sm:flex items-center gap-1">
        {btn(<ChevronLeft size={16} />, page - 1, page === 1)}
        {pages.map((p, i) =>
          p === '…' ? (
            <span
              key={`ellipsis-${i}`}
              className="flex h-9 w-9 items-center justify-center text-sm"
              style={{ color: 'var(--color-ink-faint)' }}
              aria-hidden="true"
            >
              …
            </span>
          ) : (
            btn(p, p, false, p === page)
          ),
        )}
        {btn(<ChevronRight size={16} />, page + 1, page === totalPages)}
      </div>
    </nav>
  )
}
