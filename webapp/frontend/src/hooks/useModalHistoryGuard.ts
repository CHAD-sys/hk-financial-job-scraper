import { useEffect, useRef } from 'react'

/**
 * Makes a modal closeable via the phone/browser back gesture. Without this,
 * opening the job detail modal never touches the URL, so a phone's back
 * gesture navigates away from /jobs entirely instead of just closing it.
 *
 * Pushes one history entry on mount, closes on 'popstate' (back), and pops
 * that entry on unmount if the modal was instead closed via the X button,
 * Escape, or the backdrop — so the history stack never grows unbounded.
 *
 * The pushState is deferred one tick (setTimeout 0) specifically to defeat
 * React StrictMode (dev only): StrictMode double-invokes this effect on
 * every mount — mount -> cleanup -> mount again, synchronously, before
 * yielding to the browser — to surface exactly this class of bug. An
 * earlier version of this hook called history.back() directly in the
 * cleanup, which meant the FIRST (throwaway) mount's cleanup queued an
 * async history.back() while the SECOND (real) mount's pushState had
 * already run, moving the pointer forward again first. When that queued
 * back() finally resolved, it moved the pointer back from wherever it
 * CURRENTLY was — landing one entry BEHIND where the live component
 * thought it was, a desync invisible in a single open/close cycle but
 * that silently drifted the browser's real history pointer one step
 * further behind the app's mental model on every single modal open —
 * StrictMode re-mounts on every fresh <JobDetailModal> instance, so this
 * compounded across a session. After opening a few different job cards,
 * closing (a single history.back() call) would overshoot straight past
 * /jobs to Home, since the pointer was already sitting further back than
 * expected. Deferring the push means the throwaway mount's cleanup runs
 * BEFORE the timer ever fires, so it cancels the timer and calls
 * history.back() zero times — it never touches the History API at all.
 * Only the surviving (real) mount ever pushes, and later pops, exactly
 * one entry — no drift possible, regardless of how many modals open and
 * close in one session.
 */
export function useModalHistoryGuard(onClose: () => void) {
  // Ref so the effect below can stay mount-once (empty deps) while still
  // calling the latest onClose — the parent passes a fresh arrow every
  // render, and depending on it directly would re-push a history entry
  // on every re-render instead of once per modal open.
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => {
    let cancelled = false
    let pushed = false
    let consumedViaBack = false

    const timer = window.setTimeout(() => {
      if (cancelled) return
      window.history.pushState({ modal: true }, '')
      pushed = true
    }, 0)

    const onPopState = () => {
      consumedViaBack = true
      onCloseRef.current()
    }
    window.addEventListener('popstate', onPopState)

    return () => {
      cancelled = true
      window.clearTimeout(timer)
      window.removeEventListener('popstate', onPopState)
      // Only pop if we actually pushed (the deferred push fired) AND the
      // entry wasn't already consumed by a real back-press (consumedViaBack)
      // — popping again in that case would remove ANOTHER entry beyond the
      // one the user's own back gesture already took care of.
      if (pushed && !consumedViaBack) {
        window.history.back()
      }
    }
  }, [])
}
