import { useState, useCallback, useEffect } from 'react'
import type { Job } from '../api/client'
import { fetchSavedRoles, saveRole, unsaveRole } from '../api/client'
import { useAuth } from '../auth/useAuth'

// Versioned key: if the saved-job shape ever changes, bump to :v2 and old data
// is simply ignored instead of crashing JSON.parse consumers.
const KEY = 'finex_saved_jobs:v1'
// Pre-versioning key — read once as a fallback so existing saves migrate.
const LEGACY_KEY = 'finex_saved_jobs'

function load(): Record<string, Job> {
  try {
    const raw = localStorage.getItem(KEY) ?? localStorage.getItem(LEGACY_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch {
    return {}
  }
}

function jobKey(j: { source: string; source_id: string }): string {
  return `${j.source}__${j.source_id}`
}

/**
 * The first-sign-in migration, held at module scope so it runs at most once per
 * page load even if two components mount this hook at the same moment.
 *
 * Reset to null when it fails so a later mount can retry — a browser full of
 * Saved Roles that never reached the account is the one outcome worth going out
 * of our way to avoid.
 */
let migration: Promise<void> | null = null

/**
 * Move any localStorage saves into the account, then clear the local key.
 *
 * It is a *union*, not a replace: the server keeps what it already had and gains
 * whatever this browser had. So it is safe to run against an account that
 * already has Saved Roles, and safe to run twice — a second POST of the same
 * (source, source_id) is a no-op server-side.
 *
 * The local key is cleared only after every write has succeeded. A partial
 * migration that wiped the browser copy would silently delete Saved Roles, so
 * on any failure we keep the local data and try again next time.
 */
async function migrateLocalSaves(): Promise<void> {
  const local = Object.values(load())

  if (local.length > 0) {
    const results = await Promise.allSettled(
      local.map(job => saveRole(job.source, job.source_id)),
    )
    if (results.some(r => r.status === 'rejected')) {
      throw new Error('Some Saved Roles could not be moved to the account')
    }
  }

  localStorage.removeItem(KEY)
  localStorage.removeItem(LEGACY_KEY)
}

function ensureMigrated(): Promise<void> {
  migration ??= migrateLocalSaves().catch(err => {
    migration = null // let the next mount try again
    throw err
  })
  return migration
}

/**
 * Saved Roles, in whichever of the two modes applies.
 *
 * Signed out → localStorage, exactly as before accounts existed.
 * Signed in  → the account, via /api/me/saved.
 *
 * The shapes differ underneath: localStorage holds whole Job objects (a frozen
 * snapshot, which is why a closed Role still looks live there), while the server
 * stores only (source, source_id) and joins the Role's current fields at read
 * time. Callers see the same `Record<string, Job>` either way.
 */
export function useSavedJobs() {
  const { seeker, loading: authLoading } = useAuth()
  const signedIn = Boolean(seeker)

  // Start from localStorage in both modes. For a signed-in Seeker it is a
  // stand-in for the half-second before the server answers, and it is the right
  // stand-in: those are the Roles the migration is about to upload anyway.
  const [saved, setSaved] = useState<Record<string, Job>>(load)

  // Persist outside the state updater: React may invoke updaters more than
  // once (e.g. in StrictMode), so side effects like setItem don't belong there.
  // Signed in, the account is the record — writing the server's list back into
  // localStorage would resurrect the local copy the migration just cleared.
  useEffect(() => {
    if (signedIn) return
    localStorage.setItem(KEY, JSON.stringify(saved))
  }, [saved, signedIn])

  // Load the right source whenever the signed-in state settles or changes.
  useEffect(() => {
    if (authLoading) return

    if (!signedIn) {
      // Signed out (including just after signing out): the browser is the
      // record again, and the migration emptied it.
      //
      // Arm the migration again too. Without this, someone who signs out, saves
      // a few Roles, and signs back in within the same page load would find
      // those saves stranded in localStorage, because the one-shot promise had
      // already resolved.
      migration = null
      setSaved(load())
      return
    }

    let cancelled = false
    void (async () => {
      try {
        await ensureMigrated()
        const roles = await fetchSavedRoles()
        if (cancelled) return
        const next: Record<string, Job> = {}
        for (const role of roles) next[jobKey(role)] = role
        setSaved(next)
      } catch (err) {
        // Keep whatever is on screen rather than blanking the list — a failed
        // sync must never look like "your Saved Roles are gone".
        console.error('Saved Roles sync failed', err)
      }
    })()
    return () => { cancelled = true }
  }, [authLoading, signedIn])

  const toggle = useCallback((job: Job) => {
    const k = jobKey(job)
    const wasSaved = Boolean(saved[k])

    // Optimistic: the bookmark has to respond on the same tick it is pressed.
    const next = { ...saved }
    if (wasSaved) delete next[k]
    else next[k] = job
    setSaved(next)

    if (!signedIn) return

    const request = wasSaved
      ? unsaveRole(job.source, job.source_id)
      : saveRole(job.source, job.source_id)

    request.catch(err => {
      console.error('Saved Role update failed', err)
      // Put the UI back where the server actually is.
      setSaved(prev => {
        const reverted = { ...prev }
        if (wasSaved) reverted[k] = job
        else delete reverted[k]
        return reverted
      })
    })
  }, [saved, signedIn])

  const isSaved = useCallback(
    (job: Job) => Boolean(saved[jobKey(job)]),
    [saved],
  )

  const savedList = Object.values(saved)

  // Sync across tabs — only meaningful in localStorage mode; signed in, the
  // account is shared and each tab reads it on load.
  useEffect(() => {
    if (signedIn) return
    const handler = (e: StorageEvent) => {
      if (e.key === KEY) setSaved(load())
    }
    window.addEventListener('storage', handler)
    return () => window.removeEventListener('storage', handler)
  }, [signedIn])

  return { saved, savedList, toggle, isSaved, count: savedList.length }
}
