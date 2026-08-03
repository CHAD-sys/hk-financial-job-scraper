import { createContext } from 'react'
import type { RegisterPayload, Seeker } from '../api/client'

/**
 * The shape of the auth context.
 *
 * Split out of AuthProvider.tsx so that file exports a component and nothing
 * else — the repo's oxlint config warns on mixing component and non-component
 * exports (react/only-export-components).
 */
export interface AuthValue {
  /** The signed-in Seeker, or null when browsing anonymously. */
  seeker: Seeker | null
  /** True until the first /api/auth/me call has answered. */
  loading: boolean
  login: (email: string, password: string) => Promise<Seeker | null>
  /**
   * Returns the Seeker if registration signed them straight in, or null if it
   * did not — which is what a duplicate address looks like, since register
   * answers like success either way (PLAN_ACCOUNTS §5).
   */
  register: (payload: RegisterPayload) => Promise<Seeker | null>
  logout: () => Promise<void>
  /** Re-read /api/auth/me and return the result. */
  refresh: () => Promise<Seeker | null>
}

export const AuthContext = createContext<AuthValue | null>(null)
