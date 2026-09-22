import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, FileSearch, RefreshCw } from 'lucide-react'
import { fetchResume } from '../api/client'
import { useAuth } from '../auth/useAuth'
import ResumeFlow from './ResumeFlow'

/**
 * The invitation to upload a CV — and nothing else.
 *
 * This used to be `ResumeMatches`, which fetched `/api/me/resume-matches` and
 * handed the result sideways to `RecommendedRoles` so it could render a
 * separate block of CV cards pinned above the feed. There is no second list
 * any more (owner decision, 2026-09-21): a CV changes how "Roles for you" is
 * RANKED — `recommendations.RESUME_WEIGHT` of the relevance, searches take the
 * rest — rather than spawning a list beside it. A Seeker should not have to
 * read two rankings of the same board and work out which one to believe.
 *
 * So this asks the far cheaper question it actually needs answered — "is there
 * a resume on file?" — and once there is one, it gets out of the way. That
 * also drops a full 1,000-Role ranking pass from first paint.
 */
export default function ResumePrompt() {
  const { seeker } = useAuth()
  const seekerId = seeker?.id
  const [hasResume, setHasResume] = useState<boolean | null>(null)
  const [error, setError] = useState(false)
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    if (!seekerId) {
      setHasResume(null)
      return
    }
    let cancelled = false
    setError(false)
    fetchResume()
      .then(value => { if (!cancelled) setHasResume(Boolean(value)) })
      .catch(err => {
        console.error(err)
        if (!cancelled) setError(true)
      })
    return () => { cancelled = true }
  }, [nonce, seekerId])

  if (!seeker) {
    return (
      <section className="resume-match-prompt resume-match-prompt--featured mb-10 sm:mb-14" aria-labelledby="resume-prompt-heading">
        <span className="resume-match-prompt__mark" aria-hidden="true"><FileSearch size={25} strokeWidth={1.9} /></span>
        <div className="min-w-0 flex-1">
          <span className="resume-match-prompt__kicker">Resume intelligence</span>
          <h2 id="resume-prompt-heading">Find Roles that fit you.</h2>
          <ResumeFlow className="resume-match-prompt__flow" />
        </div>
        <div className="resume-match-prompt__actions">
          <Link to="/register" className="resume-match-prompt__primary">Create account <ArrowRight size={14} aria-hidden="true" /></Link>
          <Link to="/signin">Sign in</Link>
        </div>
      </section>
    )
  }

  if (error) {
    return (
      <section className="resume-match-prompt mb-10 sm:mb-14" role="status">
        <FileSearch size={22} aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <p className="font-semibold">We could not check your resume.</p>
          <p>Try again without re-uploading it.</p>
        </div>
        <button type="button" onClick={() => setNonce(value => value + 1)}>
          <RefreshCw size={14} aria-hidden="true" /> Try again
        </button>
      </section>
    )
  }

  // Unknown yet, or already uploaded: say nothing. No skeleton — this is an
  // invitation, and a placeholder for an invitation that may never appear is
  // just a flash of furniture above the feed.
  if (hasResume !== false) return null

  return (
    <section className="resume-match-prompt resume-match-prompt--featured mb-10 sm:mb-14" aria-labelledby="resume-prompt-heading">
      <span className="resume-match-prompt__mark" aria-hidden="true"><FileSearch size={25} strokeWidth={1.9} /></span>
      <div className="min-w-0 flex-1">
        <span className="resume-match-prompt__kicker">Resume intelligence</span>
        <h2 id="resume-prompt-heading">Find Roles that fit you.</h2>
        <ResumeFlow className="resume-match-prompt__flow" />
      </div>
      <div className="resume-match-prompt__actions">
        <Link to="/account" className="resume-match-prompt__primary">Upload your resume <ArrowRight size={14} aria-hidden="true" /></Link>
      </div>
    </section>
  )
}
