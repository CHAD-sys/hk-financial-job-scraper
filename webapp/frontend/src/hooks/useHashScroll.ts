import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'

/**
 * Scrolls to `location.hash` after a client-side navigation.
 *
 * The browser only honours a URL fragment on a real document load. Arriving at
 * `/#consultation` from `/jobs` is a react-router navigation — no document load,
 * so nothing scrolls and the visitor lands at the top of the portal wondering
 * where the section went. This closes that gap.
 *
 * Runs on every hash change, not just mount, so clicking the same Nav item twice
 * works. Honours prefers-reduced-motion: `html { scroll-behavior: smooth }` in
 * index.css would otherwise animate a long jump for people who asked it not to.
 */
export default function useHashScroll() {
  const { hash } = useLocation()

  useEffect(() => {
    if (!hash) return

    // The target is rendered in the same commit as this effect, but images and
    // fonts above it can still shift layout. A frame's delay lets that settle
    // so we land on the section rather than near it.
    const raf = requestAnimationFrame(() => {
      let el: Element | null = null
      try {
        el = document.querySelector(hash)
      } catch {
        return // malformed fragment, e.g. "#123" — not a valid selector
      }
      if (!el) return

      const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      el.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'start' })
    })

    return () => cancelAnimationFrame(raf)
  }, [hash])
}
