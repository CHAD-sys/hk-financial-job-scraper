import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useAuth } from '../auth/useAuth'
import { AdminModeContext } from './AdminModeContext'

/**
 * Admin Mode: whether an admin is currently looking at the product AS an admin.
 *
 * WHY THIS EXISTS
 * ---------------
 * The Admin Mode switch used to be pure navigation — it moved you to /admin and
 * back, and nothing else. That made it decorative, because the admin powers on
 * the board (the pencil on every card, the empty-search browse) were on the
 * whole time regardless of which "mode" the button claimed you were in. A mode
 * that changes nothing is not a mode; it is a link wearing a toggle's clothes.
 *
 * So the flag is real now, and the admin surfaces read it:
 *
 *   Seeker view  — an admin sees precisely what a Seeker sees. No pencils, no
 *                  empty-search browse, no Admin panel entry in the nav.
 *   Admin Mode   — those appear.
 *
 * WHAT THIS IS AND IS NOT
 * -----------------------
 * It is a VIEW preference, not a permission. The permission lives on the server
 * and has not moved: `require_admin` still guards /api/admin/*, and an admin's
 * empty research query is still accepted by /api/jobs whatever this flag says.
 * Turning Admin Mode off does not drop a privilege — it puts the tools away.
 *
 * That distinction matters if this is ever asked to do more than it does.
 * Wiring the flag into the API as a "drop my privileges" header would look like
 * a security control and be none: it is the admin's own client asserting it,
 * and the admin can assert otherwise. The real boundary is, and stays, the
 * session's privilege bits on the server.
 *
 * NON-ADMINS
 * ----------
 * `adminMode` is forced false for anyone without the bits, on every render
 * rather than only at sign-in. A stale `true` in localStorage — left by an
 * admin who used this browser before, or hand-set by a curious visitor — must
 * not survive into a Seeker's session and start drawing controls whose requests
 * would only 403 anyway.
 */

// Versioned key, same convention as savedRoles: bump the suffix rather than
// teaching a reader to cope with an old shape.
const KEY = 'finex_admin_mode:v1'

function readStored(): boolean {
  try {
    return window.localStorage.getItem(KEY) === '1'
  } catch {
    // Safari private mode, or storage disabled entirely. Defaulting to OFF is
    // the safe direction: the worst case is an admin clicking the switch again.
    return false
  }
}

export default function AdminModeProvider({ children }: { children: ReactNode }) {
  const { seeker, loading } = useAuth()

  // Both bits, as everywhere since ADR 0019 — seekers_store.set_super_admin()
  // writes only its own column, so the two are independent in the data model.
  const canUseAdminMode = Boolean(seeker?.is_admin || seeker?.is_super_admin)

  const [stored, setStored] = useState(readStored)

  const setAdminMode = useCallback((on: boolean) => {
    setStored(on)
    try {
      if (on) window.localStorage.setItem(KEY, '1')
      else window.localStorage.removeItem(KEY)
    } catch {
      // Non-fatal: the mode still works for this page's lifetime, it just will
      // not survive a reload. Better than failing the click.
    }
  }, [])

  // Signing out — or signing in as somebody without the bits — puts the tools
  // away and clears the stored flag. Without this, the next person to use this
  // browser inherits an Admin Mode they cannot use, which is the same defect
  // savedRoles/store.ts's docstring describes for Saved Roles.
  useEffect(() => {
    if (!loading && !canUseAdminMode && stored) setAdminMode(false)
  }, [loading, canUseAdminMode, stored, setAdminMode])

  const value = useMemo(
    () => ({ adminMode: canUseAdminMode && stored, canUseAdminMode, setAdminMode }),
    [canUseAdminMode, stored, setAdminMode],
  )

  return <AdminModeContext.Provider value={value}>{children}</AdminModeContext.Provider>
}
