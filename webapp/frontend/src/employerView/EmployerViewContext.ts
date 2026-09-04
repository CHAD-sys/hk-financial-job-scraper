import { createContext } from 'react'

/**
 * The shape of the Employer view context.
 *
 * Split out of the provider file so that file exports a component and nothing
 * else — same reason as AdminModeContext and SavedRolesContext
 * (react/only-export-components).
 */
export interface EmployerViewValue {
  /**
   * Whether the Ultimate Admin is currently PREVIEWING the product as an
   * Employer sees it.
   *
   * False for everyone else, always. It is a view preference that survives a
   * reload, exactly like Admin Mode — but unlike Admin Mode it is a preview of
   * somebody else's product, never a session, so nothing it turns on may act
   * on an Employer's behalf. See the provider for the whole posture.
   */
  employerView: boolean
  /** True if this account could turn it on at all. Ultimate Admin, and only
   *  when no real Employer session is already in this browser. */
  canUseEmployerView: boolean
  setEmployerView: (on: boolean) => void
}

export const EmployerViewContext = createContext<EmployerViewValue | null>(null)
