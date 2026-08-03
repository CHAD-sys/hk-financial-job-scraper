import { useContext } from 'react'
import { SavedRolesContext } from './SavedRolesContext'
import type { SavedRolesValue } from './SavedRolesContext'

/**
 * Read the Seeker's Saved Roles.
 *
 * Named for the domain term (CONTEXT.md): a Role is what the board presents, a
 * job is the stored row. The old name was `useSavedJobs`.
 *
 * Throws outside <SavedRolesProvider> rather than handing back an empty default,
 * for the same reason useAuth does: a component that silently believes nothing
 * is saved is much harder to diagnose than one that fails at mount. That is not
 * hypothetical here — four pages rendered a bare <Nav /> and so showed a
 * signed-in Seeker a Saved count of zero.
 */
export function useSavedRoles(): SavedRolesValue {
  const value = useContext(SavedRolesContext)
  if (!value) throw new Error('useSavedRoles() must be used inside <SavedRolesProvider>')
  return value
}
