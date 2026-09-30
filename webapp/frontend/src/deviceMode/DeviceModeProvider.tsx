import { useLayoutEffect, useMemo, useState, type ReactNode } from 'react'
import { DeviceModeContext } from './DeviceModeContext'
import { detectDevice } from './deviceDetection'
import type { DetectedDevice, DeviceUiMode } from './deviceDetection'

interface Props {
  children: ReactNode
  /** Test seam; production always lets the browser detector supply this. */
  initialDetection?: DetectedDevice
}

function readDevelopmentPreviewMode(): DeviceUiMode | null {
  if (!import.meta.env.DEV || typeof window === 'undefined') return null
  const value = new URLSearchParams(window.location.search).get('device-preview')
  return value === 'mobile' || value === 'desktop' ? value : null
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
  const [developmentPreviewMode] = useState(readDevelopmentPreviewMode)
  // There is intentionally no stored user override in production. A stale
  // browser value must never silently replace the device's current identity.
  // The query override remains development-only for controlled visual QA.
  const uiMode = developmentPreviewMode ?? detected.uiMode

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
      uiMode,
      detectionSource: detected.source,
      touchCapable: detected.touchCapable,
    }),
    [detected, uiMode],
  )

  return <DeviceModeContext.Provider value={value}>{children}</DeviceModeContext.Provider>
}
