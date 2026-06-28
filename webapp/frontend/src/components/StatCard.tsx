interface StatCardProps {
  value: string
  label: string
  sub?: string
}

export default function StatCard({ value, label, sub }: StatCardProps) {
  return (
    <div
      className="flex flex-col gap-1 rounded-lg p-6 transition-shadow duration-200"
      style={{
        backgroundColor: 'var(--color-surface)',
        border: '1px solid var(--color-border)',
        boxShadow: 'var(--shadow-card)',
      }}
      onMouseEnter={e => {
        (e.currentTarget as HTMLDivElement).style.boxShadow = 'var(--shadow-raised)'
      }}
      onMouseLeave={e => {
        (e.currentTarget as HTMLDivElement).style.boxShadow = 'var(--shadow-card)'
      }}
    >
      <span
        className="text-3xl font-bold tabular-nums leading-none tracking-tight"
        style={{
          fontFamily: 'var(--font-mono)',
          color: 'var(--color-ink)',
        }}
      >
        {value}
      </span>
      <span
        className="text-sm font-semibold uppercase tracking-widest mt-1"
        style={{ color: 'var(--color-gold)', letterSpacing: '0.1em' }}
      >
        {label}
      </span>
      {sub && (
        <span
          className="text-xs mt-0.5"
          style={{ color: 'var(--color-ink-faint)' }}
        >
          {sub}
        </span>
      )}
    </div>
  )
}
