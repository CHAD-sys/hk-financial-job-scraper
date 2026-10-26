import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import MarqueeControls from './MarqueeControls'

describe('MarqueeControls', () => {
  it('provides named, working controls in both directions', () => {
    const previous = vi.fn()
    const next = vi.fn()
    render(<MarqueeControls label="roles" onPrevious={previous} onNext={next} />)

    fireEvent.click(screen.getByRole('button', { name: 'Show previous roles' }))
    fireEvent.click(screen.getByRole('button', { name: 'Show next roles' }))

    expect(previous).toHaveBeenCalledOnce()
    expect(next).toHaveBeenCalledOnce()
    expect(screen.getByText('Drag or use arrows')).toBeVisible()
  })
})
