import { createContext } from 'react'
import type {
  DeviceClass,
  DeviceDetectionSource,
  DeviceUiMode,
} from './deviceDetection'

export type DeviceModePreference = 'auto' | DeviceUiMode

export interface DeviceModeValue {
  /** Stable physical-device family detected once when the app starts. */
  deviceClass: DeviceClass
  /** The detector's recommendation before a user override is applied. */
  detectedUiMode: DeviceUiMode
  /** The mobile or desktop product shell components should render. */
  uiMode: DeviceUiMode
  preference: DeviceModePreference
  detectionSource: DeviceDetectionSource
  touchCapable: boolean
  setPreference: (preference: DeviceModePreference) => void
}

export const DeviceModeContext = createContext<DeviceModeValue | null>(null)
