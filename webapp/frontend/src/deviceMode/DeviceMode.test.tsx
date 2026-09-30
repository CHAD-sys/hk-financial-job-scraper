import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import DeviceModeProvider from './DeviceModeProvider'
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
  const { deviceClass, uiMode, detectionSource } = useDeviceMode()
  return (
    <div>
      <span data-testid="device">{deviceClass}</span>
      <span data-testid="ui-mode">{uiMode}</span>
      <span data-testid="source">{detectionSource}</span>
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

afterEach(() => localStorage.clear())

describe('Device Mode', () => {
  it('publishes the detected device and UI mode on first render', () => {
    renderProbe()

    expect(screen.getByTestId('device')).toHaveTextContent('phone')
    expect(screen.getByTestId('ui-mode')).toHaveTextContent('mobile')
    expect(screen.getByTestId('source')).toHaveTextContent('user-agent')
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

  it('ignores a stale legacy local-storage override', () => {
    localStorage.setItem('finex_device_mode:v1', 'mobile')

    renderProbe(DESKTOP)

    expect(screen.getByTestId('device')).toHaveTextContent('desktop')
    expect(screen.getByTestId('ui-mode')).toHaveTextContent('desktop')
  })
})
