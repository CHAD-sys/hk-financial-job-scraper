import { useContext } from 'react'
import { AuthContext } from './AuthContext'
import type { AuthValue } from './AuthContext'

/**
 * Read the current Seeker and the auth actions.
 *
 * Throws outside <AuthProvider> rather than handing back a null-ish default:
 * a component that silently thinks nobody is signed in is much harder to
 * diagnose than one that fails at mount.
 */
export function useAuth(): AuthValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth() must be used inside <AuthProvider>')
  return value
}
