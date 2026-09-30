import { Suspense } from 'react'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { DeviceModeContext } from './deviceMode/DeviceModeContext'
import type { DeviceModeValue } from './deviceMode/DeviceModeContext'

vi.mock('./pages/LandingPage', () => ({ default: () => <main>Desktop landing</main> }))
vi.mock('./pages/JobBoardPage', () => ({ default: () => <main>Mobile discovery</main> }))

const { HomeRoute } = await import('./App')

function mode(uiMode: DeviceModeValue['uiMode']): DeviceModeValue {
  return {
    deviceClass: uiMode === 'mobile' ? 'phone' : 'desktop',
    uiMode,
    detectionSource: uiMode === 'mobile' ? 'user-agent' : 'default',
    touchCapable: uiMode === 'mobile',
  }
}

function renderHome(uiMode: DeviceModeValue['uiMode']) {
  return render(
    <DeviceModeContext.Provider value={mode(uiMode)}>
      <MemoryRouter initialEntries={['/']}>
        <Suspense fallback={<p>Loading</p>}><HomeRoute /></Suspense>
      </MemoryRouter>
    </DeviceModeContext.Provider>,
  )
}

describe('HomeRoute device mode', () => {
  it('renders the dedicated mobile discovery home only for mobile mode', async () => {
    renderHome('mobile')

    expect(await screen.findByText('Mobile discovery')).toBeInTheDocument()
    expect(screen.queryByText('Desktop landing')).not.toBeInTheDocument()
  })

  it('renders the desktop landing for desktop mode', async () => {
    renderHome('desktop')

    expect(await screen.findByText('Desktop landing')).toBeInTheDocument()
    expect(screen.queryByText('Mobile discovery')).not.toBeInTheDocument()
  })
})
