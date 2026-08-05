import { useState, useEffect, useCallback, useMemo } from 'react'
import type { Employer, EmployerRegisterPayload } from '../api/client'
import {
  fetchEmployerMe, loginEmployer, logoutEmployer, registerEmployer, addUnauthorizedHandler,
} from '../api/client'
import { EmployerAuthContext } from './EmployerAuthContext'
import type { EmployerAuthValue } from './EmployerAuthContext'

/**
 * The Employer twin of AuthProvider.tsx — same shape, same reasoning (that
 * file's docstring covers both): asks the server once on mount and trusts its
 * own state afterward, `loading` exists only to avoid flashing the wrong nav
 * state at somebody who is in fact signed in.
 *
 * Nested alongside AuthProvider in App.tsx, not inside or instead of it: the
 * two are independent, and Nav needs both — whether to show "Post a role" at
 * all depends on this one, whether to show the Seeker menu depends on the
 * other.
 */
export default function EmployerAuthProvider({ children }: { children: React.ReactNode }) {
  const [employer, setEmployer] = useState<Employer | null>(null)
  const [loading, setLoading] = useState(true)

  // Scoped to /api/employer: a Seeker-endpoint 401 must not sign the Employer
  // out of a session that is still live (client.ts's addUnauthorizedHandler).
  useEffect(() => addUnauthorizedHandler(path => {
    if (path.startsWith('/api/employer')) setEmployer(null)
  }), [])

  useEffect(() => {
    let cancelled = false
    fetchEmployerMe()
      .then(me => { if (!cancelled) setEmployer(me) })
      .catch(() => { if (!cancelled) setEmployer(null) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  const refresh = useCallback(async () => {
    const me = await fetchEmployerMe()
    setEmployer(me)
    return me
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    await loginEmployer(email, password)
    return refresh()
  }, [refresh])

  const register = useCallback(async (payload: EmployerRegisterPayload) => {
    await registerEmployer(payload)
    return refresh()
  }, [refresh])

  const logout = useCallback(async () => {
    try {
      await logoutEmployer()
    } finally {
      setEmployer(null)
    }
  }, [])

  const value = useMemo<EmployerAuthValue>(
    () => ({ employer, loading, login, register, logout, refresh }),
    [employer, loading, login, register, logout, refresh],
  )

  return <EmployerAuthContext.Provider value={value}>{children}</EmployerAuthContext.Provider>
}
