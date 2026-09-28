import { useContext } from 'react'
import { DeviceModeContext } from './DeviceModeContext'
import type { DeviceModeValue } from './DeviceModeContext'

export function useDeviceMode(): DeviceModeValue {
  const value = useContext(DeviceModeContext)
  if (!value) throw new Error('useDeviceMode() must be used inside <DeviceModeProvider>')
  return value
}
