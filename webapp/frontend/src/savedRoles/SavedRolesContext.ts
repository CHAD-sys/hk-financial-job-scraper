import { createContext } from 'react'
import type { Job } from '../api/client'

/**
 * The shape of the Saved Roles context.
 *
 * Split out of the provider file so that file exports a component and nothing
 * else — the repo's oxlint config warns on mixing component and non-component
 * exports (react/only-export-components).
 */
export interface SavedRolesValue {
  /** Keyed by `source__source_id`. */
  saved: Record<string, Job>
  savedList: Job[]
  count: number
  isSaved: (role: { source: string; source_id: string }) => boolean
  toggle: (job: Job) => void
}

export const SavedRolesContext = createContext<SavedRolesValue | null>(null)
