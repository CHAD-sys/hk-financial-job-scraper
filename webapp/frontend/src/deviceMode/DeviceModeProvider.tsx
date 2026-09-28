import {
  useCallback,
  useLayoutEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { DeviceModeContext } from './DeviceModeContext'
import type { DeviceModePreference } from './DeviceModeContext'
import { detectDevice } from './deviceDetection'
import type { DetectedDevice } from './deviceDetection'
import { readDeviceModePreference, writeDeviceModePreference } from './store'

interface Props {
  children: ReactNode
  /** Test seam; production always lets the browser detector supply this. */
  initialDetection?: DetectedDevice
}

/**
 * One device decision for one app lifetime.
 *
 * There is deliberately no resize listener. Structural mobile/desktop choices
 * are tied to the device family, while ordinary CSS can still reflow spacing
 * and columns safely inside that chosen product shell.
 */
export default function DeviceModeProvider({ children, initialDetection }: Props) {
  const [detected] = useState(() => initialDetection ?? detectDevice())
  const [preference, setStoredPreference] = useState(readDeviceModePreference)
  const uiMode = preference === 'auto' ? detected.uiMode : preference

  const setPreference = useCallback((next: DeviceModePreference) => {
    setStoredPreference(next)
    writeDeviceModePreference(next)
  }, [])

  // These attributes give CSS and browser diagnostics the same single source
  // of truth as React components. useLayoutEffect applies them before paint,
  // avoiding a mobile-first flash on a detected desktop.
  useLayoutEffect(() => {
    const root = document.documentElement
    const previousClass = root.dataset.deviceClass
    const previousMode = root.dataset.uiMode
    const previousSource = root.dataset.deviceDetection

    root.dataset.deviceClass = detected.deviceClass
    root.dataset.uiMode = uiMode
    root.dataset.deviceDetection = detected.source

    return () => {
      if (previousClass === undefined) delete root.dataset.deviceClass
      else root.dataset.deviceClass = previousClass
      if (previousMode === undefined) delete root.dataset.uiMode
      else root.dataset.uiMode = previousMode
      if (previousSource === undefined) delete root.dataset.deviceDetection
      else root.dataset.deviceDetection = previousSource
    }
  }, [detected.deviceClass, detected.source, uiMode])

  const value = useMemo(
    () => ({
      deviceClass: detected.deviceClass,
      detectedUiMode: detected.uiMode,
      uiMode,
      preference,
      detectionSource: detected.source,
      touchCapable: detected.touchCapable,
      setPreference,
    }),
    [detected, preference, setPreference, uiMode],
  )

  return <DeviceModeContext.Provider value={value}>{children}</DeviceModeContext.Provider>
}
