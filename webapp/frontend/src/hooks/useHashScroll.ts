import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import { scrollToHash } from '../utils/scroll'

/**
 * Scrolls to `location.hash` after a client-side navigation.
 *
 * The browser only honours a URL fragment on a real document load. Arriving at
 * `/#consultation` from `/jobs` is a react-router navigation — no document load,
 * so nothing scrolls and the visitor lands at the top of the portal wondering
 * where the section went. This closes that gap.
 *
 * Runs on every hash change, not just mount, so clicking the same Nav item twice
 * works. Reduced-motion handling lives in scrollToHash.
 */
export default function useHashScroll() {
  const { hash } = useLocation()

  useEffect(() => {
    if (!hash) return

    // The target is rendered in the same commit as this effect, but images and
    // fonts above it can still shift layout. A frame's delay lets that settle
    // so we land on the section rather than near it.
    const raf = requestAnimationFrame(() => scrollToHash(hash))
    return () => cancelAnimationFrame(raf)
  }, [hash])
}
