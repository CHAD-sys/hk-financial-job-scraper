import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { Job } from '../api/client'
import { useAuth } from '../auth/useAuth'
import { SavedRolesContext } from './SavedRolesContext'
import type { SavedRolesValue } from './SavedRolesContext'
import {
  LOCAL_STORAGE_KEY,
  liftLocalRolesIntoAccount,
  localStore,
  roleKey,
  serverStore,
} from './store'

/**
 * One record of Saved Roles for the whole app.
 *
 * It is a provider rather than a hook with its own state because four places
 * mount this — the board, the Saved Roles page, the account page and the auth
 * shell — and as a plain hook each got its OWN copy. They shared nothing but a
 * module-global migration promise that any one of them could reset, and the
 * nav badge could disagree with the page underneath it.
 *
 * Which store is in use is decided by one expression. There is no effect that
 * writes state back to storage, so there is no ordering for a sign-out to get
 * wrong — see store.ts for the bug that shape used to produce.
 */
export default function SavedRolesProvider({ children }: { children: ReactNode }) {
  const { seeker, loading: authLoading } = useAuth()
  const signedIn = Boolean(seeker)
  const store = signedIn ? serverStore : localStore

  const [saved, setSaved] = useState<Record<string, Job>>({})

  // Mirrors `saved` for toggle() to read synchronously. A ref, not the `saved`
  // closure, is what lets two rapid presses stay correct without an impure
  // setState updater (see toggle() below) — kept in sync by the effect right
  // after this, so it is never stale by the time any handler reads it.
  const savedRef = useRef(saved)
  useEffect(() => {
    savedRef.current = saved
  }, [saved])

  // Load from whichever store is current. Signing in first lifts the browser's
  // Roles into the account, so the list we then read already contains them.
  useEffect(() => {
    if (authLoading) return

    let cancelled = false
    void (async () => {
      try {
        if (signedIn) await liftLocalRolesIntoAccount()
        const roles = await store.list()
        if (cancelled) return
        setSaved(Object.fromEntries(roles.map(r => [roleKey(r), r])))
      } catch (err) {
        // Keep whatever is on screen rather than blanking the list — a failed
        // sync must never look like "your Saved Roles are gone".
        console.error('Saved Roles sync failed', err)
      }
    })()
    return () => { cancelled = true }
  }, [authLoading, signedIn, store])

  const toggle = useCallback((job: Job) => {
    const key = roleKey(job)

    // Optimistic: the bookmark has to respond on the same tick it is pressed.
    // Read AND write `savedRef` synchronously here, in the event handler —
    // never inside a setState updater, which React may invoke more than once
    // (StrictMode does, on purpose, to catch exactly this class of bug) and
    // whose side effects can then repeat or run out of order. Updating the
    // ref immediately is what keeps two rapid presses correct: the second
    // press reads what the first one just wrote, not a stale snapshot.
    const wasSaved = Boolean(savedRef.current[key])
    const next = { ...savedRef.current }
    if (wasSaved) delete next[key]
    else next[key] = job
    savedRef.current = next
    setSaved(next)

    const request = wasSaved ? store.unsave(job) : store.save(job)
    request.catch((err: unknown) => {
      console.error('Saved Role update failed', err)
      // Put the UI back where the store actually is.
      const reverted = { ...savedRef.current }
      if (wasSaved) reverted[key] = job
      else delete reverted[key]
      savedRef.current = reverted
      setSaved(reverted)
    })
  }, [store])

  // Cross-tab sync, only meaningful for the local store: signed in, the account
  // is the shared record and each tab reads it on load.
  useEffect(() => {
    if (signedIn) return
    const handler = (e: StorageEvent) => {
      if (e.key !== LOCAL_STORAGE_KEY) return
      void localStore.list().then(roles =>
        setSaved(Object.fromEntries(roles.map(r => [roleKey(r), r]))),
      )
    }
    window.addEventListener('storage', handler)
    return () => window.removeEventListener('storage', handler)
  }, [signedIn])

  const value = useMemo<SavedRolesValue>(() => {
    const savedList = Object.values(saved)
    return {
      saved,
      savedList,
      count: savedList.length,
      isSaved: (role) => Boolean(saved[roleKey(role)]),
      toggle,
    }
  }, [saved, toggle])

  return <SavedRolesContext value={value}>{children}</SavedRolesContext>
}
