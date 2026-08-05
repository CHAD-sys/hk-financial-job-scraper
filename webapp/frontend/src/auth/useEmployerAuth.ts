import { useContext } from 'react'
import { EmployerAuthContext } from './EmployerAuthContext'
import type { EmployerAuthValue } from './EmployerAuthContext'

/**
 * Read the current Employer and the auth actions. Same contract as useAuth() —
 * see that file for why this throws outside its provider rather than handing
 * back a null-ish default.
 */
export function useEmployerAuth(): EmployerAuthValue {
  const value = useContext(EmployerAuthContext)
  if (!value) throw new Error('useEmployerAuth() must be used inside <EmployerAuthProvider>')
  return value
}
