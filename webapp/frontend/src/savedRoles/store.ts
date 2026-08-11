import type { Job } from '../api/client'
import { fetchSavedRoles, mergeSavedRoles, saveRole, unsaveRole } from '../api/client'

/**
 * Where a Seeker's Saved Roles live.
 *
 * There are two real answers — the browser, for someone who has not signed in,
 * and the account, for someone who has — and they differ in substance, not just
 * in plumbing:
 *
 *   the browser stores a COPY of the Role, because there is nothing to resolve
 *   a reference against;
 *   the account stores a REFERENCE, and the server joins the Role's current
 *   fields at read time, which is what lets a Saved Role come back marked
 *   `closed` instead of as a stale snapshot.
 *
 * Two adapters, so the seam is real rather than hypothetical.
 *
 * WHAT THIS SHAPE IS FOR
 * ----------------------
 * Persistence lives INSIDE the adapter. The version this replaced kept the
 * Saved Roles in a hook and persisted them from an effect keyed on the current
 * state, guarded by `if (signedIn) return` — so at the moment of signing out,
 * that effect ran once with the guard already false and the ACCOUNT's Roles
 * still in state, and wrote them into localStorage. They stayed there: on a
 * shared machine, the next visitor inherited them.
 *
 * No effect ordering can reintroduce that here, because nothing outside an
 * adapter ever writes to storage.
 */
export interface SavedRolesStore {
  /** Everything currently saved, newest first. */
  list(): Promise<Job[]>
  save(job: Job): Promise<void>
  unsave(job: Job): Promise<void>
}

// Versioned key: if the saved-role shape ever changes, bump to :v2 and old data
// is simply ignored instead of crashing JSON.parse consumers.
const KEY = 'finex_saved_roles:v1'
// Pre-versioning and pre-rename keys — read as fallbacks so existing saves survive.
const LEGACY_KEYS = ['finex_saved_jobs:v1', 'finex_saved_jobs']

export function roleKey(role: { source: string; source_id: string }): string {
  return `${role.source}__${role.source_id}`
}

function readLocal(): Record<string, Job> {
  for (const key of [KEY, ...LEGACY_KEYS]) {
    try {
      const raw = localStorage.getItem(key)
      if (raw) return JSON.parse(raw) as Record<string, Job>
    } catch {
      // A corrupt or foreign value in one key should not stop us reading the next.
    }
  }
  return {}
}

function writeLocal(roles: Record<string, Job>): void {
  localStorage.setItem(KEY, JSON.stringify(roles))
}

function clearLocal(): void {
  for (const key of [KEY, ...LEGACY_KEYS]) localStorage.removeItem(key)
}

/** What an anonymous visitor has saved. Whole Roles, because there is no server. */
export const localStore: SavedRolesStore = {
  async list() {
    return Object.values(readLocal())
  },
  async save(job) {
    writeLocal({ ...readLocal(), [roleKey(job)]: job })
  },
  async unsave(job) {
    const next = readLocal()
    delete next[roleKey(job)]
    writeLocal(next)
  },
}

/** What a signed-in Seeker has saved. References, resolved server-side. */
export const serverStore: SavedRolesStore = {
  list: fetchSavedRoles,
  save: (job) => saveRole(job.source, job.source_id, job.access_token),
  unsave: (job) => unsaveRole(job.source, job.source_id),
}

/**
 * Move whatever this browser had into the account, then forget it locally.
 *
 * One call, not one per Role: the endpoint is a union and is idempotent, so a
 * retry after a flaky network cannot duplicate or drop anything, and a Seeker
 * signing in on a second device keeps both sets.
 *
 * The local copy is cleared only after the server has confirmed. A migration
 * that wiped the browser first and then failed would silently delete Saved
 * Roles, so on any error we keep the local data and let the next sign-in retry.
 */
export async function liftLocalRolesIntoAccount(): Promise<number> {
  const local = Object.values(readLocal())
  const eligible = local.filter(
    (job): job is Job & { access_token: string } => Boolean(job.access_token),
  )
  let accepted = new Set<string>()
  if (eligible.length > 0) {
    const result = await mergeSavedRoles(eligible.map(job => ({
      source: job.source,
      source_id: job.source_id,
      access_token: job.access_token,
    })))
    accepted = new Set(result.accepted.map(role => `${role.source}__${role.source_id}`))
  }
  const remaining = local.filter(job => !accepted.has(roleKey(job)))
  if (remaining.length > 0) {
    writeLocal(Object.fromEntries(remaining.map(job => [roleKey(job), job])))
  } else {
    clearLocal()
  }
  return accepted.size
}

/** Exposed for the cross-tab listener, which needs to know which key to watch. */
export const LOCAL_STORAGE_KEY = KEY
