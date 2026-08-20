import { createContext } from 'react'

/**
 * The shape of the Admin Mode context.
 *
 * Split out of the provider file so that file exports a component and nothing
 * else — same reason as SavedRolesContext (react/only-export-components).
 */
export interface AdminModeValue {
  /**
   * Whether the admin is currently LOOKING at the product as an admin.
   *
   * False for everyone who is not an admin, always. For an admin it is a
   * deliberate choice they make with the Admin Mode switch, and it survives a
   * reload so the choice does not silently reset under them mid-task.
   */
  adminMode: boolean
  /** True if this account could turn it on at all. */
  canUseAdminMode: boolean
  setAdminMode: (on: boolean) => void
}

export const AdminModeContext = createContext<AdminModeValue | null>(null)
