import { useContext } from 'react'
import { AdminModeContext } from './AdminModeContext'
import type { AdminModeValue } from './AdminModeContext'

/**
 * Read whether Admin Mode is on, and turn it on or off.
 *
 * Throws outside <AdminModeProvider> rather than handing back a null-ish
 * default, for the same reason useAuth does: a component that silently decides
 * nobody is an admin is much harder to diagnose than one that fails at mount.
 */
export function useAdminMode(): AdminModeValue {
  const value = useContext(AdminModeContext)
  if (!value) throw new Error('useAdminMode() must be used inside <AdminModeProvider>')
  return value
}
