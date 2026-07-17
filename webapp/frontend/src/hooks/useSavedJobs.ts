import { useState, useCallback, useEffect } from 'react'
import type { Job } from '../api/client'

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

function jobKey(j: Job): string {
  return `${j.source}__${j.source_id}`
}

export function useSavedJobs() {
  const [saved, setSaved] = useState<Record<string, Job>>(load)

  // Persist outside the state updater: React may invoke updaters more than
  // once (e.g. in StrictMode), so side effects like setItem don't belong there.
  useEffect(() => {
    localStorage.setItem(KEY, JSON.stringify(saved))
  }, [saved])

  const toggle = useCallback((job: Job) => {
    setSaved(prev => {
      const k = jobKey(job)
      const next = { ...prev }
      if (next[k]) {
        delete next[k]
      } else {
        next[k] = job
      }
      return next
    })
  }, [])

  const isSaved = useCallback(
    (job: Job) => Boolean(saved[jobKey(job)]),
    [saved],
  )

  const savedList = Object.values(saved)

  // Sync across tabs
  useEffect(() => {
    const handler = (e: StorageEvent) => {
      if (e.key === KEY) setSaved(load())
    }
    window.addEventListener('storage', handler)
    return () => window.removeEventListener('storage', handler)
  }, [])

  return { saved, savedList, toggle, isSaved, count: savedList.length }
}
