import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DEFAULT_FILTERS } from '../api/client'

const deviceModeValue = vi.hoisted(() => ({ uiMode: 'desktop' as 'mobile' | 'desktop' }))

vi.mock('../deviceMode/useDeviceMode', () => ({ useDeviceMode: () => deviceModeValue }))

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

beforeEach(() => {
  deviceModeValue.uiMode = 'desktop'
})

describe('FilterBar — device-specific structure', () => {
  it('uses inline advanced filters for the desktop UI', () => {
    renderFilterBar()

    expect(screen.getByRole('button', { name: 'More filters' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Filters' })).not.toBeInTheDocument()
  })

  it('uses the full-screen filter sheet for the mobile UI', async () => {
    const user = userEvent.setup()
    deviceModeValue.uiMode = 'mobile'
    renderFilterBar()

    expect(screen.queryByRole('button', { name: 'More filters' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Filters' }))
    expect(screen.getByRole('dialog', { name: 'Filters' })).toBeInTheDocument()
  })
})
