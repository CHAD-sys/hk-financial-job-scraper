import { Suspense } from 'react'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

vi.mock('./pages/JobBoardPage', () => ({ default: () => <main>Discovery home</main> }))

const { HomeRoute } = await import('./App')

describe('HomeRoute', () => {
  it('opens the discovery home without a device provider', async () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <Suspense fallback={<p>Loading</p>}><HomeRoute /></Suspense>
      </MemoryRouter>,
    )

    expect(await screen.findByText('Discovery home')).toBeInTheDocument()
  })
})
