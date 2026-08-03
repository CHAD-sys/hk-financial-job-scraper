import { useState, useEffect, useCallback, useMemo } from 'react'
import type { RegisterPayload, Seeker } from '../api/client'
import {
  fetchMe, loginSeeker, logoutSeeker, registerSeeker, setUnauthorizedHandler,
} from '../api/client'
import { AuthContext } from './AuthContext'
import type { AuthValue } from './AuthContext'

/**
 * Holds the one piece of global state this app has: who is signed in.
 *
 * Two things are worth knowing about it.
 *
 * First, it asks the server once on mount and then trusts its own state. The
 * session lives in an httpOnly cookie, so the browser cannot inspect it — there
 * is nothing to read locally and no token to decode. `/api/auth/me` is the only
 * way to find out, and calling it more than once per load buys nothing.
 *
 * Second, `loading` exists so the UI can avoid flashing "Sign in" at somebody
 * who is in fact signed in. It is true only until that first call answers, and
 * it never blocks the board — the board is public (docs/adr/0002) and renders
 * regardless of what this provider is doing.
 */
export default function AuthProvider({ children }: { children: React.ReactNode }) {
  const [seeker, setSeeker] = useState<Seeker | null>(null)
  const [loading, setLoading] = useState(true)

  // Any 401 from any endpoint means the session is gone (expired, revoked, or
  // the account was deleted from another tab). Clear the Seeker and let the
  // visitor carry on anonymously — we never redirect them to a sign-in wall.
  useEffect(() => {
    setUnauthorizedHandler(() => setSeeker(null))
    return () => setUnauthorizedHandler(null)
  }, [])

  useEffect(() => {
    let cancelled = false
    fetchMe()
      .then(me => { if (!cancelled) setSeeker(me) })
      .catch(() => { if (!cancelled) setSeeker(null) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  const refresh = useCallback(async () => {
    const me = await fetchMe()
    setSeeker(me)
    return me
  }, [])

  // login/register both re-read /me rather than trusting their own response
  // body: the contract only promises a status code, and /me is the single
  // definition of "who am I" everywhere else in the app.
  const login = useCallback(async (email: string, password: string) => {
    await loginSeeker(email, password)
    return refresh()
  }, [refresh])

  const register = useCallback(async (payload: RegisterPayload) => {
    await registerSeeker(payload)
    return refresh()
  }, [refresh])

  const logout = useCallback(async () => {
    try {
      await logoutSeeker()
    } finally {
      // Clear locally whatever the server said. If the call failed, the honest
      // outcome for the person who pressed "Sign out" is still signed out here.
      setSeeker(null)
    }
  }, [])

  const value = useMemo<AuthValue>(
    () => ({ seeker, loading, login, register, logout, refresh }),
    [seeker, loading, login, register, logout, refresh],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
