import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import DeviceModeProvider from './DeviceModeProvider'
import { DEVICE_MODE_KEY } from './store'
import { useDeviceMode } from './useDeviceMode'
import type { DetectedDevice } from './deviceDetection'

const PHONE: DetectedDevice = {
  deviceClass: 'phone',
  uiMode: 'mobile',
  source: 'user-agent',
  touchCapable: true,
}

const DESKTOP: DetectedDevice = {
  deviceClass: 'desktop',
  uiMode: 'desktop',
  source: 'default',
  touchCapable: false,
}

function Probe() {
  const { deviceClass, uiMode, preference, setPreference } = useDeviceMode()
  return (
    <div>
      <span data-testid="device">{deviceClass}</span>
      <span data-testid="ui-mode">{uiMode}</span>
      <span data-testid="preference">{preference}</span>
      <button type="button" onClick={() => setPreference('mobile')}>mobile</button>
      <button type="button" onClick={() => setPreference('desktop')}>desktop</button>
      <button type="button" onClick={() => setPreference('auto')}>auto</button>
    </div>
  )
}

function renderProbe(initialDetection: DetectedDevice = PHONE) {
  return render(
    <DeviceModeProvider initialDetection={initialDetection}>
      <Probe />
    </DeviceModeProvider>,
  )
}

describe('Device Mode', () => {
  it('publishes the detected device and UI mode on first render', () => {
    renderProbe()

    expect(screen.getByTestId('device')).toHaveTextContent('phone')
    expect(screen.getByTestId('ui-mode')).toHaveTextContent('mobile')
    expect(screen.getByTestId('preference')).toHaveTextContent('auto')
    expect(document.documentElement).toHaveAttribute('data-device-class', 'phone')
    expect(document.documentElement).toHaveAttribute('data-ui-mode', 'mobile')
  })

  it('locks the detected class instead of changing when the provider rerenders', () => {
    const { rerender } = renderProbe(PHONE)

    rerender(
      <DeviceModeProvider initialDetection={DESKTOP}>
        <Probe />
      </DeviceModeProvider>,
    )

    expect(screen.getByTestId('device')).toHaveTextContent('phone')
    expect(screen.getByTestId('ui-mode')).toHaveTextContent('mobile')
  })

  it('persists a manual desktop override and can return to automatic mode', async () => {
    const user = userEvent.setup()
    const first = renderProbe(PHONE)

    await user.click(screen.getByRole('button', { name: 'desktop' }))
    expect(screen.getByTestId('ui-mode')).toHaveTextContent('desktop')
    expect(localStorage.getItem(DEVICE_MODE_KEY)).toBe('desktop')
    expect(document.documentElement).toHaveAttribute('data-ui-mode', 'desktop')

    first.unmount()
    renderProbe(PHONE)
    expect(screen.getByTestId('ui-mode')).toHaveTextContent('desktop')

    await user.click(screen.getByRole('button', { name: 'auto' }))
    expect(screen.getByTestId('ui-mode')).toHaveTextContent('mobile')
    expect(localStorage.getItem(DEVICE_MODE_KEY)).toBeNull()
  })
})
