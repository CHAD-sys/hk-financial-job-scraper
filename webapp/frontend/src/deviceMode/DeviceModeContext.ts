import { createContext } from 'react'
import type {
  DeviceClass,
  DeviceDetectionSource,
  DeviceUiMode,
} from './deviceDetection'

export interface DeviceModeValue {
  /** Stable physical-device family detected once when the app starts. */
  deviceClass: DeviceClass
  /** The mobile or desktop product shell components should render. */
  uiMode: DeviceUiMode
  detectionSource: DeviceDetectionSource
  touchCapable: boolean
}

export const DeviceModeContext = createContext<DeviceModeValue | null>(null)
