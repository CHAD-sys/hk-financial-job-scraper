import { SearchX } from 'lucide-react'

interface Props {
  onClear: () => void
}

export default function EmptyState({ onClear }: Props) {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <div
        className="flex h-16 w-16 items-center justify-center rounded-full mb-5"
        style={{ backgroundColor: 'var(--color-surface-2)', border: '1px solid var(--color-border)' }}
      >
        <SearchX size={28} style={{ color: 'var(--color-ink-faint)' }} strokeWidth={1.5} />
      </div>
      <h2
        className="text-xl font-semibold mb-2"
        style={{ fontFamily: 'var(--font-display)', color: 'var(--color-ink)' }}
      >
        No roles match these filters
      </h2>
      <p className="text-sm mb-6 max-w-sm" style={{ color: 'var(--color-ink-muted)' }}>
        Try broadening your search — remove a filter or two to see more results.
      </p>
      <button type="button"
        onClick={onClear}
        className="inline-flex items-center gap-2 rounded px-5 py-2.5 text-sm font-medium transition-colors duration-150 cursor-pointer"
        style={{ backgroundColor: 'var(--color-ink)', color: 'var(--color-ink-inverse)' }}
        onMouseEnter={e => ((e.currentTarget as HTMLButtonElement).style.backgroundColor = 'var(--color-blue)')}
        onMouseLeave={e => ((e.currentTarget as HTMLButtonElement).style.backgroundColor = 'var(--color-ink)')}
      >
        Clear all filters
      </button>
    </div>
  )
}
