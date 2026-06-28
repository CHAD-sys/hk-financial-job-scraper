export default function SkeletonCard() {
  return (
    <div
      className="rounded-lg p-5 flex flex-col gap-3 animate-pulse"
      style={{
        backgroundColor: 'var(--color-surface)',
        border: '1px solid var(--color-border)',
      }}
      aria-hidden="true"
    >
      <div className="flex items-start gap-3">
        <div className="h-10 w-10 rounded-md flex-shrink-0" style={{ backgroundColor: 'var(--color-border)' }} />
        <div className="flex-1 flex flex-col gap-2">
          <div className="h-3.5 rounded" style={{ backgroundColor: 'var(--color-border)', width: '55%' }} />
          <div className="h-3 rounded" style={{ backgroundColor: 'var(--color-border)', width: '35%' }} />
        </div>
        <div className="h-6 w-16 rounded-full" style={{ backgroundColor: 'var(--color-border)' }} />
      </div>
      <div className="h-5 rounded" style={{ backgroundColor: 'var(--color-border)', width: '80%' }} />
      <div className="h-4 rounded" style={{ backgroundColor: 'var(--color-border)', width: '65%' }} />
      <div className="flex gap-2 mt-1">
        {[1, 2, 3].map(i => (
          <div key={i} className="h-5 w-20 rounded-full" style={{ backgroundColor: 'var(--color-border)' }} />
        ))}
      </div>
      <div className="h-3 rounded mt-1" style={{ backgroundColor: 'var(--color-border)', width: '40%' }} />
    </div>
  )
}
