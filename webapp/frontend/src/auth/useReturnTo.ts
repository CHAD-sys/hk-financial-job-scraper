import { useLocation } from 'react-router-dom'

/**
 * Where to land after signing in or registering: back where the visitor came
 * from, otherwise the board.
 *
 * Nav passes the current path through router state when it sends someone to
 * /signin, so pressing "Sign in" from halfway down the job board returns you to
 * the job board rather than dumping you on a landing page.
 *
 * Only an in-app path is ever trusted. An absolute URL arriving through history
 * state would turn this into an open redirect.
 */
export function useReturnTo(fallback = '/jobs'): string {
  const { state } = useLocation()
  const from = (state as { from?: unknown } | null)?.from
  return typeof from === 'string' && from.startsWith('/') && !from.startsWith('//')
    ? from
    : fallback
}
