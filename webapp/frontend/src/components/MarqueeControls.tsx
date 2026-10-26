import { ChevronLeft, ChevronRight } from 'lucide-react'

interface MarqueeControlsProps {
  label: string
  onPrevious: () => void
  onNext: () => void
  compact?: boolean
}

/** Visible alternatives to dragging an automatically moving content rail. */
export default function MarqueeControls({
  label,
  onPrevious,
  onNext,
  compact = false,
}: MarqueeControlsProps) {
  return (
    <div className="marquee-controls" data-compact={compact || undefined} aria-label={`${label} controls`}>
      <span className="marquee-controls__hint">Drag or use arrows</span>
      <span className="marquee-controls__buttons">
        <button type="button" onClick={onPrevious} aria-label={`Show previous ${label}`}>
          <ChevronLeft size={19} strokeWidth={2.2} aria-hidden="true" />
        </button>
        <button type="button" onClick={onNext} aria-label={`Show next ${label}`}>
          <ChevronRight size={19} strokeWidth={2.2} aria-hidden="true" />
        </button>
      </span>
    </div>
  )
}
