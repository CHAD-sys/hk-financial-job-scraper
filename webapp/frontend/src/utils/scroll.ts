/**
 * Scroll helpers shared by the nav and the hash-scroll hook.
 *
 * `html { scroll-behavior: smooth }` in index.css handles plain anchor jumps,
 * but programmatic scrolls need the motion preference checked explicitly — and
 * every call site was otherwise going to re-implement the same three lines.
 *
 * ── Why there is a fallback ──────────────────────────────────────────────────
 * Smooth scrolling is silently dropped on /jobs. Measured directly in the
 * browser: window.scrollTo({top:0, behavior:'smooth'}) leaves scrollY unchanged
 * after 1.5s, while behavior:'instant' from the identical state works. The same
 * smooth call works on / and /about, and it is not caused by synthetic input,
 * history churn, or a missing CSS value (scroll-behavior computes to "smooth"
 * there). Something on the board page aborts the animation each time; the root
 * cause is still open.
 *
 * Rather than let a nav control silently do nothing, these helpers ask for a
 * smooth scroll and then verify it actually started, falling back to an instant
 * jump if it did not. Users on pages where smooth works still get smooth; on
 * /jobs they get an instant jump, which is a normal way for "back to top" to
 * behave and is infinitely better than a dead button.
 */

/** How long to wait before deciding a smooth scroll never started. */
const SMOOTH_CHECK_MS = 250

/**
 * Clearance above a scrolled-to section: the sticky nav is 64px (--nav-height)
 * plus 16px of breathing room, matching the `scroll-mt-20` on the sections.
 *
 * Needed explicitly because scroll-margin-top is only honoured by
 * scrollIntoView() and anchor navigation — window.scrollTo ignores it, and the
 * nav would otherwise sit on top of the section heading.
 */
const NAV_CLEARANCE_PX = 80

export function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/**
 * Scroll the window to `top`, preferring a smooth animation but guaranteeing
 * arrival. Returns immediately; the fallback fires on a timer.
 */
function scrollWindowTo(top: number): void {
  if (prefersReducedMotion()) {
    window.scrollTo({ top, left: 0, behavior: 'instant' })
    return
  }

  const start = window.scrollY
  window.scrollTo({ top, left: 0, behavior: 'smooth' })

  // If nothing has moved by now the animation never began — jump instead.
  // A real smooth scroll has always covered some distance within this window.
  window.setTimeout(() => {
    const moved = Math.abs(window.scrollY - start) > 1
    const arrived = Math.abs(window.scrollY - top) <= 1
    if (!moved && !arrived) {
      window.scrollTo({ top, left: 0, behavior: 'instant' })
    }
  }, SMOOTH_CHECK_MS)
}

/** Back to the top of the current page. */
export function scrollToTop(): void {
  scrollWindowTo(0)
}

/**
 * Scroll a fragment (e.g. "#consultation") into view.
 * Returns false when the selector is malformed or matches nothing, so callers
 * can fall back rather than silently doing nothing.
 */
export function scrollToHash(hash: string): boolean {
  if (!hash) return false

  let el: HTMLElement | null = null
  try {
    el = document.querySelector<HTMLElement>(hash)
  } catch {
    return false // e.g. "#123" is not a valid selector
  }
  if (!el) return false

  // Same reliability problem as above, so this goes through scrollWindowTo
  // rather than el.scrollIntoView() — which means compensating for the sticky
  // nav ourselves, since window.scrollTo ignores scroll-margin-top.
  const top = el.getBoundingClientRect().top + window.scrollY - NAV_CLEARANCE_PX
  scrollWindowTo(Math.max(0, top))
  return true
}
