import type { DeviceModePreference } from './DeviceModeContext'

// Versioned so a future preference shape can migrate explicitly instead of
// silently teaching today's reader to accept several historical formats.
export const DEVICE_MODE_KEY = 'finex_device_mode:v1'

function isPreference(value: string | null): value is Exclude<DeviceModePreference, 'auto'> {
  return value === 'mobile' || value === 'desktop'
}

export function readDeviceModePreference(): DeviceModePreference {
  try {
    if (typeof window === 'undefined') return 'auto'
    const stored = window.localStorage.getItem(DEVICE_MODE_KEY)
    return isPreference(stored) ? stored : 'auto'
  } catch {
    // Storage can be disabled (notably in some private-browsing modes). The
    // detector still works; only the optional override stops surviving reloads.
    return 'auto'
  }
}

export function writeDeviceModePreference(preference: DeviceModePreference): void {
  try {
    if (typeof window === 'undefined') return
    if (preference === 'auto') window.localStorage.removeItem(DEVICE_MODE_KEY)
    else window.localStorage.setItem(DEVICE_MODE_KEY, preference)
  } catch {
    // Non-fatal. Keep the in-memory choice for this page lifetime.
  }
}
