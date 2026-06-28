import { useState, useCallback, useEffect } from 'react'
import type { Job } from '../api/client'

const KEY = 'finex_saved_jobs'

function load(): Record<string, Job> {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? '{}')
  } catch {
    return {}
  }
}

export function useSavedJobs() {
  const [saved, setSaved] = useState<Record<string, Job>>(load)

  const jobKey = (j: Job) => `${j.source}__${j.source_id}`

  const toggle = useCallback((job: Job) => {
    setSaved(prev => {
      const k = jobKey(job)
      const next = { ...prev }
      if (next[k]) {
        delete next[k]
      } else {
        next[k] = job
      }
      localStorage.setItem(KEY, JSON.stringify(next))
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
