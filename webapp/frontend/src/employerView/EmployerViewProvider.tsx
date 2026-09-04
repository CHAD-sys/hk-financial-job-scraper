import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useAuth } from '../auth/useAuth'
import { useEmployerAuth } from '../auth/useEmployerAuth'
import { EmployerViewContext } from './EmployerViewContext'

/**
 * Employer view: whether an Ultimate Admin is looking at the product the way an
 * Employer sees it.
 *
 * WHY THIS EXISTS
 * ---------------
 * The Employer surface is small and completely separate from everything an
 * admin normally touches: its own store (ADR 0001), its own session cookie, its
 * own sign-in pages, and exactly one thing to do once you are in (Post a role).
 * Nobody on the team has an Employer account, so nobody had ever seen it — the
 * only way to look was to register a throwaway company, which puts a fake
 * Employer in employers.db permanently. This is the way to look without doing
 * that.
 *
 * A PREVIEW, NOT AN IMPERSONATION — the line this must never cross
 * ---------------------------------------------------------------
 * Admin Mode's flag is a view preference over surfaces the admin's OWN session
 * already has the right to use; the server would let those requests through
 * with the flag off. This flag is different in kind, and the difference is the
 * whole safety story: there is no Employer session here and this must never
 * manufacture one.
 *
 *   - It turns on employer-shaped CHROME (the Post a role entry, the employer
 *     menu, the banner) so an admin can see the shape of the product.
 *   - It never sends an employer-authenticated request, because it cannot:
 *     `finex_employer_session` is httpOnly and issued only by
 *     /api/employer/login. Nothing in the client can forge one.
 *   - It never lets a WRITE go out under a borrowed identity. /post-a-role
 *     renders in preview with submission disabled (PostRolePage.tsx), so an
 *     admin looking around cannot drop a test row into the moderation queue
 *     wearing some company's name.
 *
 * If this is ever asked to do more — "let me post as them", "let me see their
 * drafts" — that is a real impersonation feature and needs a server-side grant
 * with an audit trail, the same shape as the resume-download route in admin.py.
 * It must not be built by widening this flag, which is only ever the admin's
 * own browser asserting something about itself.
 *
 * WHY A REAL EMPLOYER SESSION DISABLES IT
 * ---------------------------------------
 * Both accounts can be held in one browser at once (main.py), so an admin who
 * also has an Employer account could have both. Previewing "what an Employer
 * sees" while actually BEING one is not a preview — the nav would carry two
 * competing employer identities and neither would be trustworthy. The real
 * session wins; the preview is unavailable while it lasts.
 */

// Versioned key, same convention as adminMode and savedRoles.
const KEY = 'finex_employer_view:v1'

function readStored(): boolean {
  try {
    return window.localStorage.getItem(KEY) === '1'
  } catch {
    // Safari private mode, or storage disabled. OFF is the safe direction: the
    // worst case is the admin clicking the switch again.
    return false
  }
}

export default function EmployerViewProvider({ children }: { children: ReactNode }) {
  const { seeker, loading } = useAuth()
  const { employer, loading: employerLoading } = useEmployerAuth()

  // Ultimate Admin only — the same bit that gates the account directory and the
  // Employer view panel this is launched from. NOT `is_admin`: the other four
  // admins have no reason to be inside another product's shell.
  const canUseEmployerView = Boolean(seeker?.is_super_admin) && !employer

  const [stored, setStored] = useState(readStored)

  const setEmployerView = useCallback((on: boolean) => {
    setStored(on)
    try {
      if (on) window.localStorage.setItem(KEY, '1')
      else window.localStorage.removeItem(KEY)
    } catch {
      // Non-fatal: the preview still works for this page's lifetime, it just
      // will not survive a reload. Better than failing the click.
    }
  }, [])

  // Signing out, losing the bit, or signing IN as a real Employer all end the
  // preview and clear the stored flag. Without this the next person to use the
  // browser inherits an Employer view they cannot use — and, worse, a real
  // Employer signing in here would be shown a preview banner about their own
  // genuine session.
  useEffect(() => {
    if (!loading && !employerLoading && !canUseEmployerView && stored) setEmployerView(false)
  }, [loading, employerLoading, canUseEmployerView, stored, setEmployerView])

  const value = useMemo(
    () => ({
      employerView: canUseEmployerView && stored,
      canUseEmployerView,
      setEmployerView,
    }),
    [canUseEmployerView, stored, setEmployerView],
  )

  return <EmployerViewContext.Provider value={value}>{children}</EmployerViewContext.Provider>
}
