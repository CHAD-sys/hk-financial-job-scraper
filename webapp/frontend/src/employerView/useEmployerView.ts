import { useContext } from 'react'
import { EmployerViewContext } from './EmployerViewContext'
import type { EmployerViewValue } from './EmployerViewContext'

/**
 * Read whether the Employer view preview is on, and turn it on or off.
 *
 * Throws outside <EmployerViewProvider> rather than handing back a null-ish
 * default, for the same reason useAdminMode and useAuth do: a component that
 * silently decides the preview is off is much harder to diagnose than one that
 * fails at mount.
 */
export function useEmployerView(): EmployerViewValue {
  const value = useContext(EmployerViewContext)
  if (!value) throw new Error('useEmployerView() must be used inside <EmployerViewProvider>')
  return value
}
