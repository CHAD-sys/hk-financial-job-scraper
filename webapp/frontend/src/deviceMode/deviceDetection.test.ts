import { describe, expect, it } from 'vitest'
import { classifyDevice } from './deviceDetection'
import type { DeviceSignals } from './deviceDetection'

const BASE_SIGNALS: DeviceSignals = {
  userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
  platform: 'Win32',
  userAgentDataMobile: undefined,
  maxTouchPoints: 0,
  coarsePointer: false,
  noHover: false,
  screenWidth: 1920,
  screenHeight: 1080,
}

function signals(overrides: Partial<DeviceSignals>): DeviceSignals {
  return { ...BASE_SIGNALS, ...overrides }
}

describe('device classification', () => {
  it('uses the mobile Client Hint when the browser supplies it', () => {
    expect(classifyDevice(signals({ userAgentDataMobile: true }))).toMatchObject({
      deviceClass: 'phone',
      uiMode: 'mobile',
      source: 'ua-client-hints',
    })
  })

  it('recognises an iPhone without consulting the viewport', () => {
    expect(classifyDevice(signals({
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Mobile/15E148',
      platform: 'iPhone',
      maxTouchPoints: 5,
      coarsePointer: true,
      noHover: true,
      screenWidth: 430,
      screenHeight: 932,
    }))).toMatchObject({ deviceClass: 'phone', uiMode: 'mobile', source: 'user-agent' })
  })

  it('keeps an Android tablet distinct from an Android phone', () => {
    expect(classifyDevice(signals({
      userAgent: 'Mozilla/5.0 (Linux; Android 15; Pixel Tablet) AppleWebKit/537.36',
      platform: 'Linux armv8l',
      maxTouchPoints: 10,
      coarsePointer: true,
      noHover: true,
      screenWidth: 1280,
      screenHeight: 800,
    }))).toMatchObject({ deviceClass: 'tablet', uiMode: 'mobile', source: 'user-agent' })
  })

  it('recognises an iPad that identifies itself as a Mac', () => {
    expect(classifyDevice(signals({
      userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) AppleWebKit/605.1.15',
      platform: 'MacIntel',
      maxTouchPoints: 5,
      coarsePointer: true,
      noHover: true,
      screenWidth: 1024,
      screenHeight: 1366,
    }))).toMatchObject({ deviceClass: 'tablet', uiMode: 'mobile', source: 'capabilities' })
  })

  it('uses touch capabilities only when identity signals are inconclusive', () => {
    expect(classifyDevice(signals({
      userAgent: 'Unknown browser',
      platform: 'Unknown',
      maxTouchPoints: 5,
      coarsePointer: true,
      noHover: true,
      screenWidth: 390,
      screenHeight: 844,
    }))).toMatchObject({ deviceClass: 'phone', uiMode: 'mobile', source: 'capabilities' })
  })

  it('does not turn a touch-capable laptop into a mobile UI', () => {
    expect(classifyDevice(signals({
      maxTouchPoints: 10,
      coarsePointer: false,
      noHover: false,
    }))).toMatchObject({ deviceClass: 'desktop', uiMode: 'desktop', source: 'default' })
  })

  it('does not classify a narrow non-touch desktop screen as a phone', () => {
    expect(classifyDevice(signals({ screenWidth: 390, screenHeight: 844 }))).toMatchObject({
      deviceClass: 'desktop',
      uiMode: 'desktop',
    })
  })
})
