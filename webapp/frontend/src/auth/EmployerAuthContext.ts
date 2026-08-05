import { createContext } from 'react'
import type { Employer, EmployerRegisterPayload } from '../api/client'

/**
 * The Employer twin of AuthContext.ts — a separate context, not a generic
 * "account" one, because Seeker and Employer are a separate identity system
 * end to end (docs/adr/0001): separate cookie, separate store, and a browser
 * can hold both signed in at once. Merging them into one context would mean
 * inventing a shared shape neither side actually has.
 */
export interface EmployerAuthValue {
  /** The signed-in Employer, or null when nobody is signed in as one. */
  employer: Employer | null
  /** True until the first /api/employer/me call has answered. */
  loading: boolean
  login: (email: string, password: string) => Promise<Employer | null>
  register: (payload: EmployerRegisterPayload) => Promise<Employer | null>
  logout: () => Promise<void>
  /** Re-read /api/employer/me and return the result. */
  refresh: () => Promise<Employer | null>
}

export const EmployerAuthContext = createContext<EmployerAuthValue | null>(null)
