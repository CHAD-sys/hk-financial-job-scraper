import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { DEFAULT_FILTERS } from '../api/client'

const { default: FilterBar } = await import('./FilterBar')

function renderFilterBar() {
  return render(
    <FilterBar
      filters={DEFAULT_FILTERS}
      filterData={null}
      activeCount={0}
      onUpdate={vi.fn()}
      onClear={vi.fn()}
      onNewSearch={vi.fn()}
    />,
  )
}

describe('FilterBar', () => {
  it('opens the full filter sheet from the shared filter control', async () => {
    const user = userEvent.setup()
    renderFilterBar()

    expect(screen.queryByRole('button', { name: 'More filters' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Filters' }))
    expect(screen.getByRole('dialog', { name: 'Filters' })).toBeInTheDocument()
  })
})
