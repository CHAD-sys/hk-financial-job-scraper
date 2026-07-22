import { useEffect, useRef } from 'react'

/**
 * Makes a modal closeable via the phone/browser back gesture. Without this,
 * opening the job detail modal never touches the URL, so a phone's back
 * gesture navigates away from /jobs entirely instead of just closing it.
 *
 * Pushes one history entry on mount, closes on 'popstate' (back), and pops
 * that entry on unmount if the modal was instead closed via the X button,
 * Escape, or the backdrop — so the history stack never grows unbounded.
 */
export function useModalHistoryGuard(onClose: () => void) {
  // Ref so the effect below can stay mount-once (empty deps) while still
  // calling the latest onClose — the parent passes a fresh arrow every
  // render, and depending on it directly would re-push a history entry
  // on every re-render instead of once per modal open.
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  const closedViaBackRef = useRef(false)

  useEffect(() => {
    window.history.pushState({ modal: true }, '')

    const onPopState = () => {
      closedViaBackRef.current = true
      onCloseRef.current()
    }
    window.addEventListener('popstate', onPopState)

    return () => {
      window.removeEventListener('popstate', onPopState)
      if (!closedViaBackRef.current) {
        window.history.back()
      }
    }
  }, [])
}
