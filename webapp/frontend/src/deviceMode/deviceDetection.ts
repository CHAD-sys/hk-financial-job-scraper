export type DeviceClass = 'phone' | 'tablet' | 'desktop'
export type DeviceUiMode = 'mobile' | 'desktop'
export type DeviceDetectionSource = 'ua-client-hints' | 'user-agent' | 'capabilities' | 'default'

export interface DeviceSignals {
  userAgent: string
  platform: string
  userAgentDataMobile: boolean | undefined
  maxTouchPoints: number
  coarsePointer: boolean
  noHover: boolean
  screenWidth: number
  screenHeight: number
}

export interface DetectedDevice {
  deviceClass: DeviceClass
  uiMode: DeviceUiMode
  source: DeviceDetectionSource
  touchCapable: boolean
}

interface NavigatorWithUserAgentData extends Navigator {
  userAgentData?: {
    mobile?: boolean
    platform?: string
  }
}

const TABLET_MIN_SHORT_EDGE = 600

function shortScreenEdge(signals: DeviceSignals): number {
  const positiveEdges = [signals.screenWidth, signals.screenHeight].filter(edge => edge > 0)
  return positiveEdges.length > 0 ? Math.min(...positiveEdges) : 0
}

function result(
  deviceClass: DeviceClass,
  source: DeviceDetectionSource,
  touchCapable: boolean,
): DetectedDevice {
  return {
    deviceClass,
    uiMode: deviceClass === 'desktop' ? 'desktop' : 'mobile',
    source,
    touchCapable,
  }
}

/**
 * Classify a browser into a stable device family without reading its viewport.
 *
 * Viewport width is intentionally absent. Resizing a desktop window must not
 * turn it into the phone product, and rotating a phone must not turn it into
 * the desktop product. Identity signals come first; touch/input capabilities
 * are a conservative fallback for browsers that expose little identity data.
 */
export function classifyDevice(signals: DeviceSignals): DetectedDevice {
  const userAgent = signals.userAgent.toLowerCase()
  const platform = signals.platform.toLowerCase()
  const touchCapable = signals.maxTouchPoints > 0

  // iPadOS may identify itself as macOS, including while a Magic Keyboard or
  // trackpad makes its primary pointer fine and hover-capable. Macs report no
  // multi-touch display, whereas iPads expose multiple touch points, so that
  // is the durable discriminator — pointer media queries are not.
  const ipadAsMac = platform.includes('mac')
    && signals.maxTouchPoints > 1
  const ipad = userAgent.includes('ipad') || ipadAsMac
  if (ipad) {
    return result('tablet', userAgent.includes('ipad') ? 'user-agent' : 'capabilities', touchCapable)
  }

  const android = userAgent.includes('android')
  const mobileToken = /\b(mobile|mobi|iphone|ipod|windows phone)\b/.test(userAgent)

  // Android tablets omit the Mobile token, but privacy-oriented browsers and
  // embedded WebViews can strip it from phones too. A known phone-sized touch
  // screen is stronger evidence than the absent token; unknown dimensions
  // retain the conservative tablet classification.
  if (android && !mobileToken) {
    const shortEdge = shortScreenEdge(signals)
    return result(shortEdge > 0 && shortEdge < TABLET_MIN_SHORT_EDGE ? 'phone' : 'tablet', 'user-agent', touchCapable)
  }
  if (mobileToken) return result('phone', 'user-agent', touchCapable)
  if (signals.userAgentDataMobile === true) {
    return result('phone', 'ua-client-hints', touchCapable)
  }

  // Last-resort capability classification. This deliberately requires all
  // three touch signals so a touch-enabled laptop with a mouse remains a
  // desktop. `screen`, unlike the browser viewport, does not change when the
  // user narrows a desktop window; it only separates an unknown phone-sized
  // touch device from an unknown tablet-sized one.
  if (touchCapable && signals.coarsePointer && signals.noHover) {
    const shortEdge = shortScreenEdge(signals)
    return result(shortEdge >= TABLET_MIN_SHORT_EDGE ? 'tablet' : 'phone', 'capabilities', true)
  }

  return result('desktop', 'default', touchCapable)
}

function mediaMatches(query: string): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia(query).matches
}

export function readDeviceSignals(): DeviceSignals {
  if (typeof navigator === 'undefined') {
    return {
      userAgent: '',
      platform: '',
      userAgentDataMobile: undefined,
      maxTouchPoints: 0,
      coarsePointer: false,
      noHover: false,
      screenWidth: 0,
      screenHeight: 0,
    }
  }

  const browserNavigator = navigator as NavigatorWithUserAgentData
  const browserScreen = typeof window === 'undefined' ? undefined : window.screen

  return {
    userAgent: browserNavigator.userAgent || '',
    platform: browserNavigator.userAgentData?.platform || browserNavigator.platform || '',
    userAgentDataMobile: browserNavigator.userAgentData?.mobile,
    maxTouchPoints: browserNavigator.maxTouchPoints || 0,
    coarsePointer: mediaMatches('(pointer: coarse)'),
    noHover: mediaMatches('(hover: none)'),
    screenWidth: browserScreen?.width || 0,
    screenHeight: browserScreen?.height || 0,
  }
}

export function detectDevice(): DetectedDevice {
  return classifyDevice(readDeviceSignals())
}
